#!/usr/bin/env python3
"""조직분할 후보 원본 해상도 비교 — (0) 기존 고해상도 후보 / (1) 현재 / (2a) 타일링. 학습 없음.

방식 (모두 crop_gt_eval 분석1 과 같은 val 281장, GT = 7-class -> REMAP 3-class 원본 해상도):
  lin_nearest   (1) 현재 서빙: linear_tand, 크롭 전체 224 축소 -> 16x16 argmax -> nearest
  lin_bilinear  (1) linear_tand, softmax -> bilinear -> argmax
  lin_tiled     (2a) linear_tand 를 원본 배율 224 조각(stride 160, 겹침 64)에 그대로 적용.
                224 보다 작은 변은 흰색(255)으로 가운데 패딩. 조각마다 softmax 16x16 -> 224 bilinear,
                겹침은 확률 평균, 패딩 영역은 버림.
  dpt / effunet / ptc  (0) candidates/socket1 체크포인트. 크롭 전체 224 축소 -> 224x224 출력 ->
                softmax -> 원본 크기 bilinear -> argmax.

인코더(Virchow2)는 fp16, 헤드/디코더는 fp32. 원래 클래스의 forward 는 인코더 출력 dtype 이
헤드와 맞지 않아 쓰지 못하므로, 같은 계산을 인코더 출력만 float 으로 바꿔 재현한다.
시작 시 fp32 원래 forward 와 argmax 일치율을 대조한다 (sanity).
크롭 전체 입력이 같은 lin/dpt/effunet/ptc 는 인코더 1회를 공유 — 크롭당 시간 = 인코더 + 해당 헤드.

선정 당시 기준 Dice (evaluate_socket1_dice.py 방식 재현): linear = 16x16, 나머지 = 224x224 (GT NEAREST 축소).
16x16 공통 기준: 모든 방식의 확률을 16x16 으로 면적 평균 -> argmax, GT 16x16 NEAREST.

GPU: 시작 전 nvidia-smi 사용률 < 10% 확인(아니면 중단), set_per_process_memory_fraction(0.25).
출력: results/cand_crop.csv (크롭 x 방식 wide), results/cand_selection.json, results/cand_masks/{method}/{id}.png

실행: HF_HUB_OFFLINE=1 ~/miniconda3/envs/cellvitpp/bin/python code/crop_gt_eval/eval_socket1_candidates.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from PIL import Image

import common as C
import stil_inference_pipeline as sip  # noqa: E402
from train_virchow2_dpt import VirchowDPT  # noqa: E402
from train_efficientnet_unet_virchow_fusion import VirchowFusionUNet  # noqa: E402
from train_ptc_efficientunet_virchow2 import EfficientUNetWithPTC  # noqa: E402

CAND = C.CODE_DIR.parent / "candidates/socket1"
METHODS = ["lin_nearest", "lin_bilinear", "lin_tiled", "dpt", "effunet", "ptc"]
TILE, STRIDE = 224, 160
N_REG = sip.NUM_REGISTER_TOKENS
MEM_FRACTION = 0.25
N_SANITY = 3


def gpu_util_ok(samples: int = 5, thr: int = 10) -> bool:
    vals = []
    for _ in range(samples):
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.free",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
        u, used, free = (int(x) for x in out.strip().splitlines()[0].split(","))
        vals.append(u)
        time.sleep(1)
    print(f"[GPU] 사용률 샘플 {vals} %, used {used} MiB, free {free} MiB (기준 < {thr}%)")
    return max(vals) < thr


class Models:
    """Virchow2 1개를 공유하는 4개 후보. 체크포인트는 읽기만."""

    def __init__(self, device):
        self.device = device
        enc, self.mean, self.std, size = sip.build_virchow2()
        assert size == TILE
        enc = enc.to(device).eval()
        self.enc = enc
        self.lin = sip.VirchowLinearHeadTAND(enc).to(device).eval()
        ck = torch.load(CAND / "linear_tand.pth", map_location=device, weights_only=False)
        self.lin.head.load_state_dict(ck["head_state_dict"])
        self.lin.log_temperature.data = ck["log_temperature"].data.to(device)

        self.dpt = VirchowDPT(enc, TILE).to(device).eval()      # blocks 8/16/24/32 에 hook 등록
        ck = torch.load(CAND / "dpt.pth", map_location=device, weights_only=False)
        self.dpt.dpt_head.load_state_dict(ck["dpt_head_state_dict"])

        self.eff = VirchowFusionUNet(enc, TILE).to(device).eval()
        ck = torch.load(CAND / "efficientnet_unet.pth", map_location=device, weights_only=False)
        self.eff.virchow_proj.load_state_dict(ck["virchow_proj_state_dict"])
        self.eff.unet.load_state_dict(ck["unet_state_dict"])

        self.ptc = EfficientUNetWithPTC(enc).to(device).eval()
        ck = torch.load(CAND / "ptc_efficientunet.pth", map_location=device, weights_only=False)
        self.ptc.ptc.load_state_dict(ck["ptc_state_dict"])
        self.ptc.unet.load_state_dict(ck["unet_state_dict"])
        self.m = torch.tensor(self.mean, device=device).view(1, 3, 1, 1)
        self.s = torch.tensor(self.std, device=device).view(1, 3, 1, 1)

    # ---- 전처리: 학습 Dataset / sip.tissue_stroma_mask 와 동일 (PIL BILINEAR 224 축소) ----
    def whole_input(self, img: Image.Image):
        raw = torch.from_numpy(np.array(img.resize((TILE, TILE), Image.BILINEAR))).permute(2, 0, 1)
        raw = raw.float().div(255).unsqueeze(0).to(self.device)
        return raw, (raw - self.m) / self.s

    # ---- fp16 인코더 + fp32 헤드 (원래 forward 와 같은 계산) ----
    @torch.inference_mode()
    def encode(self, x_norm):
        self.dpt._hooked_outputs = {}
        tok = self.enc.forward_features(x_norm.to(next(self.enc.parameters()).dtype))
        return tok[:, 1 + N_REG:, :].float()

    def dpt_layers(self):
        return [self.dpt._hooked_outputs[i][:, 1 + N_REG:, :].float() for i in (8, 16, 24, 32)]

    @torch.inference_mode()
    def head_lin(self, pt):
        B = pt.shape[0]
        lg = self.lin.head(pt).permute(0, 2, 1).reshape(B, 3, sip.PATCH_GRID, sip.PATCH_GRID)
        return lg / torch.exp(self.lin.log_temperature)

    @torch.inference_mode()
    def head_dpt(self):
        return self.dpt.dpt_head(self.dpt_layers())

    @torch.inference_mode()
    def head_eff(self, pt, x_norm):
        B = pt.shape[0]
        proj = self.eff.virchow_proj(pt).permute(0, 2, 1).reshape(B, -1, sip.PATCH_GRID, sip.PATCH_GRID)
        proj = F.interpolate(proj, size=(TILE, TILE), mode="bilinear", align_corners=False)
        return self.eff.unet(torch.cat([x_norm, proj], 1))

    @torch.inference_mode()
    def head_ptc(self, pt, x_raw):
        B = pt.shape[0]
        grid = pt.permute(0, 2, 1).reshape(B, 1280, sip.PATCH_GRID, sip.PATCH_GRID)
        return self.ptc.unet(torch.cat([x_raw, self.ptc.ptc(grid)], 1))

    # ---- (2a) 원본 배율 224 조각 ----
    @torch.inference_mode()
    def tiled_prob(self, img_np: np.ndarray, batch: int = 16) -> torch.Tensor:
        H, W = img_np.shape[:2]
        Hp, Wp = max(H, TILE), max(W, TILE)
        oy, ox = (Hp - H) // 2, (Wp - W) // 2
        pad = np.full((Hp, Wp, 3), 255, np.uint8)
        pad[oy:oy + H, ox:ox + W] = img_np

        def starts(n):
            s = list(range(0, n - TILE, STRIDE)) + [n - TILE]
            return sorted(set(s))

        boxes = [(y, x) for y in starts(Hp) for x in starts(Wp)]
        acc = torch.zeros(3, Hp, Wp, device=self.device)
        cnt = torch.zeros(1, Hp, Wp, device=self.device)
        t = torch.from_numpy(pad).to(self.device).permute(2, 0, 1).float().div(255)
        for i in range(0, len(boxes), batch):
            bb = boxes[i:i + batch]
            x = torch.stack([t[:, y:y + TILE, x0:x0 + TILE] for y, x0 in bb])
            p = torch.softmax(self.head_lin(self.encode((x - self.m) / self.s)), 1)
            p = F.interpolate(p, size=(TILE, TILE), mode="bilinear", align_corners=False)
            for k, (y, x0) in enumerate(bb):
                acc[:, y:y + TILE, x0:x0 + TILE] += p[k]
                cnt[:, y:y + TILE, x0:x0 + TILE] += 1
        prob = (acc / cnt)[:, oy:oy + H, ox:ox + W]
        self.last_n_tiles = len(boxes)
        return prob.unsqueeze(0)                                    # (1,3,H,W)


def up_argmax(prob: torch.Tensor, H: int, W: int) -> np.ndarray:
    if prob.shape[-2:] != (H, W):
        prob = F.interpolate(prob, size=(H, W), mode="bilinear", align_corners=False)
    return prob.argmax(1)[0].byte().cpu().numpy()


def grid16(prob: torch.Tensor) -> np.ndarray:
    return F.adaptive_avg_pool2d(prob, 16).argmax(1)[0].byte().cpu().numpy()


def sync():
    torch.cuda.synchronize()
    return time.perf_counter()


@torch.inference_mode()
def sanity(M: Models, val: list[str]):
    """fp32 인코더로 원래 클래스 forward 를 돌려, fp16 래퍼와 224/16 격자 argmax 일치율 비교."""
    M.enc.float()
    ref = []
    for stem in val[:N_SANITY]:
        raw, xn = M.whole_input(C.load_image(stem))
        ref.append({"lin": M.lin(xn).argmax(1), "dpt": M.dpt(xn).argmax(1),
                    "eff": M.eff(xn).argmax(1), "ptc": M.ptc(raw, xn)[1].argmax(1)})
    M.enc.half()
    agree = {k: [] for k in ref[0]}
    for stem, r in zip(val[:N_SANITY], ref):
        raw, xn = M.whole_input(C.load_image(stem))
        pt = M.encode(xn)
        out = {"lin": M.head_lin(pt), "dpt": M.head_dpt(), "eff": M.head_eff(pt, xn), "ptc": M.head_ptc(pt, raw)}
        for k in agree:
            agree[k].append(float((out[k].argmax(1) == r[k]).float().mean()))
    print("[sanity] fp16 래퍼 vs fp32 원래 forward argmax 일치율:",
          {k: f"{np.mean(v) * 100:.2f}%" for k, v in agree.items()})
    bad = {k: v for k, v in agree.items() if np.mean(v) < 0.98}
    if bad:
        sys.exit(f"[sanity] 일치율 98% 미만 — 래퍼 구현 확인 필요: {bad}")
    # 기존 분석1(fp32) linear nearest 마스크와도 대조
    ids = C.crop_ids(val)
    for stem in val[:N_SANITY]:
        img = C.load_image(stem)
        W, H = img.size
        _, xn = M.whole_input(img)
        p16 = M.head_lin(M.encode(xn)).argmax(1)[0].byte().cpu().numpy()
        near = cv2.resize(p16, (W, H), interpolation=cv2.INTER_NEAREST)
        old = np.array(Image.open(C.RESULTS / "socket1_masks" / f"{ids[stem]}_nearest.png"))
        print(f"[sanity] {ids[stem]} lin_nearest fp16 vs 분석1 fp32 픽셀 일치 {np.mean(near == old) * 100:.2f}%")


def main():
    val, s2 = C.check_split()
    ids = C.crop_ids(val)
    if not gpu_util_ok():
        sys.exit("[GPU] 사용률 10% 이상 — 팀 추론 서버 사용 중. 실행 중단")
    device = "cuda:0"
    torch.cuda.set_per_process_memory_fraction(MEM_FRACTION, 0)
    print(f"[GPU] per-process 메모리 상한 {MEM_FRACTION} x "
          f"{torch.cuda.get_device_properties(0).total_memory / 2**30:.1f} GiB")

    t0 = time.time()
    M = Models(device)
    print(f"[load] {time.time() - t0:.1f}s")
    sanity(M, val)                               # 끝나면 인코더는 fp16
    assert next(M.enc.parameters()).dtype == torch.float16

    out_masks = C.RESULTS / "cand_masks"
    for m in METHODS:
        (out_masks / m).mkdir(parents=True, exist_ok=True)

    # 워밍업 (커널 초기화 시간 제외)
    img0 = C.load_image(val[0])
    raw, xn = M.whole_input(img0)
    pt = M.encode(xn); M.head_lin(pt); M.head_dpt(); M.head_eff(pt, xn); M.head_ptc(pt, raw)
    M.tiled_prob(np.array(img0))

    sel = {k: C.PooledDice() for k in ("lin@16", "dpt@224", "effunet@224", "ptc@224")}
    rows = []
    t_all = time.time()
    for n, stem in enumerate(val):
        cid = ids[stem]
        img = C.load_image(stem)
        W, H = img.size
        gt = C.load_gt_mask(stem)
        g16 = C.gt16(gt)
        g224 = np.array(Image.fromarray(gt).resize((TILE, TILE), Image.NEAREST))

        preds, p16, tms = {}, {}, {}
        ta = sync()
        raw, xn = M.whole_input(img)
        pt = M.encode(xn)
        tb = sync()
        t_enc = tb - ta

        lg = M.head_lin(pt)
        prob = torch.softmax(lg, 1)
        a16 = lg.argmax(1)[0].byte().cpu().numpy()
        preds["lin_nearest"] = cv2.resize(a16, (W, H), interpolation=cv2.INTER_NEAREST)
        tc = sync()
        tms["lin_nearest"] = t_enc + (tc - tb)
        preds["lin_bilinear"] = up_argmax(prob, H, W)
        td = sync()
        tms["lin_bilinear"] = t_enc + (tc - tb) + (td - tc)
        p16["lin_nearest"] = p16["lin_bilinear"] = a16
        sel["lin@16"].update(a16, g16)

        for name, fn in (("dpt", lambda: M.head_dpt()), ("effunet", lambda: M.head_eff(pt, xn)),
                         ("ptc", lambda: M.head_ptc(pt, raw))):
            t1 = sync()
            pr = torch.softmax(fn().float(), 1)                    # (1,3,224,224)
            preds[name] = up_argmax(pr, H, W)
            tms[name] = t_enc + (sync() - t1)
            p16[name] = grid16(pr)
            sel[f"{name}@224"].update(pr.argmax(1)[0].byte().cpu().numpy(), g224)

        t1 = sync()
        prt = M.tiled_prob(np.array(img))
        preds["lin_tiled"] = up_argmax(prt, H, W)
        tms["lin_tiled"] = sync() - t1
        p16["lin_tiled"] = grid16(prt)

        r = {"crop_id": cid, "stem": stem, "W": W, "H": H, "in_socket2_train": stem in s2,
             "big": max(W, H) > 512, "n_tiles": M.last_n_tiles,
             "gt_stroma_px": int((gt == 2).sum()), "gt_tumor_px": int((gt == 1).sum())}
        for m in METHODS:
            pm = preds[m]
            for c in range(3):
                pc, tcm = pm == c, gt == c
                r[f"{m}_I{c}"] = int((pc & tcm).sum()); r[f"{m}_P{c}"] = int(pc.sum()); r[f"{m}_T{c}"] = int(tcm.sum())
                q, g = p16[m] == c, g16 == c
                r[f"{m}_g16I{c}"] = int((q & g).sum()); r[f"{m}_g16P{c}"] = int(q.sum()); r[f"{m}_g16T{c}"] = int(g.sum())
            r[f"{m}_stroma_dice"] = C.dice(pm, gt, 2)
            r[f"{m}_tumor_dice"] = C.dice(pm, gt, 1)
            r[f"{m}_ms"] = tms[m] * 1000
            Image.fromarray(pm).save(out_masks / m / f"{cid}.png")
        rows.append(r)
        if (n + 1) % 50 == 0 or n + 1 == len(val):
            print(f"  {n + 1}/{len(val)}  {time.time() - t_all:.0f}s  "
                  f"peak {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB", flush=True)

    pd.DataFrame(rows).to_csv(C.RESULTS / "cand_crop.csv", index=False)
    selj = {k: dict(zip(C.CLASS_NAMES, map(float, v.dice()))) for k, v in sel.items()}
    selj["_note"] = "선정 당시 기준 재현: linear=16x16, 나머지=224x224 (크롭 전체 축소, GT NEAREST). fp16 인코더."
    (C.RESULTS / "cand_selection.json").write_text(json.dumps(selj, indent=2, ensure_ascii=False))
    print(json.dumps(selj, indent=2, ensure_ascii=False))
    print("saved ->", C.RESULTS / "cand_crop.csv")


if __name__ == "__main__":
    main()
