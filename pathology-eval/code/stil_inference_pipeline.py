"""
sTIL 계산 파이프라인 (표준 정의).

국제 TIL Working Group 표준:
    stil_percent = (간질 내 면역세포 면적) / (전체 간질 면적) * 100

구현:
  1. 조직분할 모델(Virchow2+Linear TAND, linear_tand 확정)로 16x16 격자 예측
     -> 원본 해상도로 nearest 업샘플 -> 간질(class 2) 이진 마스크 (H,W)
  2. 세포검출·분류 모델(CellViT-SAM-H 검출 + weighted LinearClassifier 헤드,
     candidates/socket2/model_best.pth)로 모든 세포 검출:
       - 큰 이미지(>512px): 원본 해상도 512 타일링
       - 작은 이미지(<=512px): 512 pad+centercrop 단일 추론 (좌표는 원본으로 역변환)
     각 세포: centroid(원본좌표), P(TIL), contour 면적(원본 픽셀^2)
  3. 공간 게이팅: centroid 가 간질 마스크 안에 있는 P(TIL)>=임계값 세포만 분자에 포함
  4. stil% = sum(간질내 면역세포 contour 면적) / (간질 마스크 픽셀 수) * 100
     -> 분자·분모 모두 "원본 이미지 픽셀^2" 단위이므로 비율은 mpp 무관.
        mpp 는 면적을 µm^2 로 환산해 보고/검증할 때만 사용 (--mpp, TIGER 기본 0.5).

레거시(차원 불일치) 값도 함께 기록: legacy_stil = til / (til + stroma_16x16칸) * 100
"""
import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import timm
import torch
import torch.nn as nn
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.expanduser("~/models/cellvitpp")
sys.path.insert(0, REPO_ROOT)

from extract_socket2_tokens import (
    load_model as load_cellvit_sam,
    detect_cells_small,
    detect_cells_large,
    INPUT_SHAPE,
    NR_TYPES,
)
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy
from cellvit.models.classifier.linear_classifier import LinearClassifier

NUM_CLASSES = 3
PATCH_GRID = 16
NUM_REGISTER_TOKENS = 4
TUMOR_CLASS_IDX = 1   # 종양 (기타=0, 종양=1, 간질=2)
STROMA_CLASS_IDX = 2  # 간질 (기타=0, 종양=1, 간질=2)
TOKEN_DIM = 1280
HIDDEN_DIM = 256


class VirchowLinearHeadTAND(nn.Module):
    def __init__(self, virchow_model):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.head = nn.Linear(1280, NUM_CLASSES)
        self.log_temperature = nn.Parameter(torch.zeros(1))

    def forward(self, x):
        with torch.no_grad():
            tokens = self.encoder.forward_features(x)
        patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]
        logits = self.head(patch_tokens)
        B = logits.shape[0]
        logits = logits.permute(0, 2, 1).reshape(B, NUM_CLASSES, PATCH_GRID, PATCH_GRID)
        return logits / torch.exp(self.log_temperature)


def build_virchow2():
    model = timm.create_model(
        "hf_hub:paige-ai/Virchow2", pretrained=True,
        mlp_layer=timm.layers.SwiGLUPacked, act_layer=torch.nn.SiLU,
    )
    model.eval()
    cfg = timm.data.resolve_model_data_config(model)
    return model, cfg["mean"], cfg["std"], cfg["input_size"][-1]


def load_tissue_model(checkpoint_path, device, fp16=False):
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowLinearHeadTAND(virchow_model).to(device)
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    model.log_temperature.data = ckpt["log_temperature"].data.to(device)
    model.eval()
    if fp16:
        model.half()  # 저VRAM 모드 (공유 GPU)
    return model, mean, std, image_size


def load_cell_classifier(head_path, device, mc_dropout=False, drop_rate=0.5):
    """소켓2 셀 분류 헤드. mc_dropout=True 면 dropout 모듈만 train 모드로 두어
    MC Dropout(추론 시 확률적 forward) 활성화 — 나머지 레이어는 eval 유지.
    학습이 drop_rate=0.5 로 됐으므로(체크포인트 config) 동일 값이 기본."""
    dr = drop_rate if mc_dropout else 0
    head = LinearClassifier(embed_dim=TOKEN_DIM, hidden_dim=HIDDEN_DIM, num_classes=2, drop_rate=dr)
    ckpt = torch.load(head_path, map_location=device, weights_only=False)
    head.load_state_dict(ckpt["model_state_dict"] if "model_state_dict" in ckpt else ckpt)
    head.eval().to(device)  # dropout 은 파라미터가 없어 가중치 로드에 영향 없음
    if mc_dropout:
        head.dropout.train()  # dropout 모듈만 확률적으로
    return head


@torch.inference_mode()
def mc_ptil_samples(head, T, n_samples):
    """dropout train 모드인 head 로 T(셀 토큰, (N,D))에 대해 P(TIL) 을 n_samples 회 샘플.
    반환: (n_samples, N) float32.  토큰은 재사용, MLP 만 반복 -> 비용 거의 없음."""
    out = np.empty((n_samples, T.shape[0]), dtype=np.float32)
    for s in range(n_samples):
        out[s] = torch.softmax(head(T), dim=1)[:, 1].float().cpu().numpy()
    return out


@torch.inference_mode()
def tissue_stroma_mask(model, img, mean, std, image_size, device, W, H):
    """16x16 예측 -> 원본 해상도(H,W) nearest 업샘플. 반환: (H,W) uint8, 값 0/1/2."""
    img_resized = img.resize((image_size, image_size), Image.BILINEAR)
    t = torch.from_numpy(np.array(img_resized)).permute(2, 0, 1).float() / 255.0
    t = ((t - torch.tensor(mean).view(3, 1, 1)) / torch.tensor(std).view(3, 1, 1)).unsqueeze(0).to(device)
    t = t.to(next(model.parameters()).dtype)
    pred16 = model(t).argmax(dim=1).squeeze(0).cpu().numpy().astype(np.uint8)  # (16,16)
    mask = cv2.resize(pred16, (W, H), interpolation=cv2.INTER_NEAREST)  # (H,W)
    return mask, pred16


def _contour_area(cont):
    c = np.asarray(cont, dtype=np.float32).reshape(-1, 2)
    return float(cv2.contourArea(c)) if c.shape[0] >= 3 else 0.0


@torch.inference_mode()
def detect_and_classify(img_np, cellvit, postproc, head, device, batch_size, return_tokens=False):
    """반환: list[{cx, cy (원본좌표), p_til, area_px (원본 픽셀^2)}]  (이미지 밖 세포는 제외)
    return_tokens=True 면 (cells, T_kept) 반환 — T_kept 은 cells 와 순서가 맞는 셀 토큰 (N,D).
    MC Dropout 시 이 토큰을 재사용해 MLP 만 반복한다."""
    H, W = img_np.shape[:2]
    if max(H, W) <= INPUT_SHAPE:
        coords, tokens, contours = detect_cells_small(img_np, cellvit, postproc, device)
        dx, dy = (INPUT_SHAPE - W) // 2, (INPUT_SHAPE - H) // 2  # PadIfNeeded(center) 오프셋
        coords = coords - np.array([dx, dy])
        contours = [c - np.array([dx, dy]) for c in contours]
    else:
        coords, tokens, contours = detect_cells_large(img_np, cellvit, postproc, device, batch_size)

    if len(tokens) == 0:
        return ([], None) if return_tokens else []
    T = torch.tensor(np.stack(tokens), dtype=torch.float32, device=device)
    p_til = torch.softmax(head(T), dim=1)[:, 1].cpu().numpy()

    cells, keep_idx = [], []
    for i, ((cx, cy), p, cont) in enumerate(zip(coords, p_til, contours)):
        if not (0 <= cx < W and 0 <= cy < H):
            continue
        cells.append({"cx": float(cx), "cy": float(cy), "p_til": float(p), "area_px": _contour_area(cont)})
        keep_idx.append(i)
    if return_tokens:
        T_kept = T[keep_idx] if keep_idx else None
        return cells, T_kept
    return cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tissue_checkpoint", type=str,
                    default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand/best_head.pth"))
    ap.add_argument("--cell_head", type=str,
                    default=os.path.expanduser("~/pathology-eval/candidates/socket2/model_best.pth"))
    ap.add_argument("--cellvit_path", type=str,
                    default=os.path.join(REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"))
    ap.add_argument("--images_dir", type=str,
                    default=os.path.expanduser("~/data/tiger/tissue_segmentation/val/images"))
    ap.add_argument("--til_threshold", type=float, default=0.5)
    ap.add_argument("--mpp", type=float, default=0.5, help="µm/px (TIGER tissue-cells crop ≈ 0.5)")
    ap.add_argument("--nc_ratio", type=float, default=1.5,
                    help="핵→세포 면적 보정계수 (세포면적 / 핵면적). CellViT 는 핵을 분할하지만 "
                         "WG sTIL 은 세포가 차지하는 면적 기준. 소림프구 세포지름≈8µm / 핵지름≈6.5µm "
                         "(표준 조직학 참고치) -> (8/6.5)^2 ≈ 1.5. 형질세포 비중이 크면 상향(~2.0).")
    ap.add_argument("--batch_size", type=int, default=4)
    ap.add_argument("--outdir", type=str,
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "stil_results"))
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mc_samples", type=int, default=50,
                    help="MC Dropout 반복 횟수 (소켓2 셀 분류 헤드). 0 이면 비활성. "
                         "토큰 재사용·MLP만 반복이라 비용 거의 없음 -> 50~100 무방.")
    ap.add_argument("--mc_drop_rate", type=float, default=0.5,
                    help="MC Dropout rate. 소켓2 헤드가 drop_rate=0.5 로 학습됨(체크포인트 config).")
    ap.add_argument("--mc_ci", type=float, default=95.0,
                    help="신뢰구간 % (기본 95 -> 2.5/97.5 백분위수).")
    args = ap.parse_args()
    do_mc = args.mc_samples > 0
    ci_lo, ci_hi = (100 - args.mc_ci) / 2, 100 - (100 - args.mc_ci) / 2

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    os.makedirs(args.outdir, exist_ok=True)

    print("조직분할 모델 로딩...")
    tissue_model, mean, std, image_size = load_tissue_model(args.tissue_checkpoint, device)
    print("세포검출(CellViT-SAM-H) + 분류 헤드 로딩...")
    cellvit, _ = load_cellvit_sam(args.cellvit_path, args.gpu)
    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=NR_TYPES)
    head = load_cell_classifier(args.cell_head, device, mc_dropout=do_mc, drop_rate=args.mc_drop_rate)

    files = sorted(Path(args.images_dir).glob("*.png"))
    if args.limit > 0:
        files = files[: args.limit]
    print(f"이미지 {len(files)}장, TIL 임계값 {args.til_threshold}, mpp {args.mpp} µm/px")
    if do_mc:
        print(f"MC Dropout: 소켓2 헤드 dropout={args.mc_drop_rate}, {args.mc_samples}회 샘플 "
              f"-> stil_interval [{ci_lo:.1f}, {ci_hi:.1f}] 백분위수 "
              f"(주의: TIL 분류 불확실성만; 조직분할 불확실성 제외)")

    results = []
    all_areas_px = []       # 검출된 모든 세포
    all_areas_px_til = []    # P(TIL)>=임계값 세포
    for i, fp in enumerate(files):
        img = Image.open(fp).convert("RGB")
        img_np = np.array(img).astype(np.uint8)
        H, W = img_np.shape[:2]

        mask, pred16 = tissue_stroma_mask(tissue_model, img, mean, std, image_size, device, W, H)
        stroma_area_px = int((mask == STROMA_CLASS_IDX).sum())
        tumor_area_px = int((mask == TUMOR_CLASS_IDX).sum())
        stroma_16grid = int((pred16 == STROMA_CLASS_IDX).sum())

        # TSR (Tumor-Stroma Ratio): 종양+간질 픽셀 중 각 비율. 사양서 Q6 미확정이라
        # tumor/stroma 두 관점 다 반환 -> 팀이 나중에 선택. 분모 0 이면 None.
        tsr_denom = tumor_area_px + stroma_area_px
        tsr_tumor_percent = (tumor_area_px / tsr_denom * 100) if tsr_denom > 0 else None
        tsr_stroma_percent = (stroma_area_px / tsr_denom * 100) if tsr_denom > 0 else None

        if do_mc:
            head.dropout.eval()  # 점추정(stil_percent)은 결정론적으로
        cells, T_kept = detect_and_classify(img_np, cellvit, postproc, head, device,
                                            args.batch_size, return_tokens=True)
        immune = [c for c in cells if c["p_til"] >= args.til_threshold]
        intra = [c for c in immune
                 if mask[min(int(c["cy"]), H - 1), min(int(c["cx"]), W - 1)] == STROMA_CLASS_IDX]
        immune_nuc_px = float(sum(c["area_px"] for c in intra))   # 핵 면적 합
        immune_cell_px = immune_nuc_px * args.nc_ratio            # 세포 면적 보정

        all_areas_px += [c["area_px"] for c in cells]
        all_areas_px_til += [c["area_px"] for c in immune]

        stroma_ok = stroma_area_px > 0
        stil_std = (immune_cell_px / stroma_area_px * 100) if stroma_ok else None
        legacy = (len(immune) / (len(immune) + stroma_16grid) * 100) if (len(immune) + stroma_16grid) > 0 else None

        # ---- MC Dropout v1: 소켓2 셀 분류 불확실성 -> stil 구간 ----
        stil_lo = stil_hi = stil_mc_mean = stil_mc_std = None
        if do_mc and stroma_ok and T_kept is not None and len(cells) > 0:
            head.dropout.train()
            mc_p = mc_ptil_samples(head, T_kept, args.mc_samples)       # (S, N)
            areas = np.array([c["area_px"] for c in cells], dtype=np.float64)
            yy = np.clip([int(c["cy"]) for c in cells], 0, H - 1)
            xx = np.clip([int(c["cx"]) for c in cells], 0, W - 1)
            in_stroma = (mask[yy, xx] == STROMA_CLASS_IDX)             # (N,)
            is_immune = mc_p >= args.til_threshold                     # (S, N)
            num_px = (areas[None, :] * is_immune * in_stroma[None, :]).sum(axis=1)
            stil_s = num_px * args.nc_ratio / stroma_area_px * 100     # (S,)
            stil_lo, stil_hi = (float(x) for x in np.percentile(stil_s, [ci_lo, ci_hi]))
            stil_mc_mean, stil_mc_std = float(stil_s.mean()), float(stil_s.std())

        results.append({
            "stem": fp.stem,
            "img_w": W, "img_h": H,
            "n_cells": len(cells),
            "til_count": len(immune),
            "til_count_stromal": len(intra),
            "stroma_status": "ok" if stroma_ok else "absent",
            "stroma_area_px": stroma_area_px,
            "tumor_area_px": tumor_area_px,
            "stroma_area_um2": round(stroma_area_px * args.mpp ** 2, 1),
            "tsr_tumor_percent": round(tsr_tumor_percent, 2) if tsr_tumor_percent is not None else None,
            "tsr_stroma_percent": round(tsr_stroma_percent, 2) if tsr_stroma_percent is not None else None,
            "immune_nucleus_area_px": round(immune_nuc_px, 1),
            "immune_cell_area_px": round(immune_cell_px, 1),
            "immune_cell_area_um2": round(immune_cell_px * args.mpp ** 2, 1),
            "nc_ratio": args.nc_ratio,
            "stil_percent": round(stil_std, 2) if stil_std is not None else None,
            "legacy_stil_percent": round(legacy, 2) if legacy is not None else None,
            # MC Dropout v1 (소켓2 TIL 분류 불확실성만; 조직분할 불확실성 제외)
            "mc_samples": args.mc_samples if do_mc else 0,
            "stil_interval_low": round(stil_lo, 2) if stil_lo is not None else None,
            "stil_interval_high": round(stil_hi, 2) if stil_hi is not None else None,
            "stil_mc_mean": round(stil_mc_mean, 2) if stil_mc_mean is not None else None,
            "stil_mc_std": round(stil_mc_std, 3) if stil_mc_std is not None else None,
        })
        if (i + 1) % 25 == 0 or i == 0:
            r = results[-1]
            ci = (f"  CI[{r['stil_interval_low']}, {r['stil_interval_high']}]"
                  if r['stil_interval_low'] is not None else "")
            print(f"  [{i+1}/{len(files)}] {fp.stem[:32]:32s} {W}x{H}  "
                  f"면역세포 {r['til_count_stromal']}/{r['til_count']}(간질내/전체)  "
                  f"stil={r['stil_percent']}{ci}  legacy={r['legacy_stil_percent']}")

    out_path = Path(args.outdir) / "stil_demo_results.json"
    json.dump(results, open(out_path, "w"), ensure_ascii=False, indent=2)

    n_absent = sum(1 for r in results if r["stroma_status"] == "absent")
    print(f"\n간질 미검출(stroma_status=absent, sTIL 산출 불가): {n_absent}/{len(results)} "
          f"({n_absent / len(results) * 100:.0f}%)  -- 슬라이드 단위 집계 시 분자·분모 모두에서 제외")
    print(f"보정계수 nc_ratio = {args.nc_ratio} (핵면적 -> 세포면적)")

    # ---- contour 면적 sanity check ----
    a = np.array([x for x in all_areas_px if x > 0])
    mpp2 = args.mpp ** 2
    print(f"\n=== contour 면적 sanity (검출 세포 {len(a)}개) ===")
    for lab, arr in [("전체 세포", a), ("P(TIL)>=임계값 세포", np.array([x for x in all_areas_px_til if x > 0]))]:
        if len(arr) == 0:
            continue
        um2 = arr * mpp2
        dia_um = 2 * np.sqrt(um2 / np.pi)
        print(f"  {lab}: n={len(arr)}")
        print(f"    면적 px^2   p10/median/p90 = {np.percentile(arr,10):.0f} / {np.median(arr):.0f} / {np.percentile(arr,90):.0f}")
        print(f"    면적 µm^2   p10/median/p90 = {np.percentile(um2,10):.1f} / {np.median(um2):.1f} / {np.percentile(um2,90):.1f}")
        print(f"    등가지름 µm p10/median/p90 = {np.percentile(dia_um,10):.1f} / {np.median(dia_um):.1f} / {np.percentile(dia_um,90):.1f}")
    print("  (림프구 핵 ≈ 5~7µm, 상피/종양 핵 ≈ 10~15µm 예상)")

    # ---- sTIL 분포 ----
    for key, name in [("stil_percent", "표준 sTIL%"), ("legacy_stil_percent", "레거시 sTIL%")]:
        v = np.array([r[key] for r in results if r[key] is not None])
        big = np.array([r[key] for r in results if r[key] is not None and max(r["img_w"], r["img_h"]) > 512])
        small = np.array([r[key] for r in results if r[key] is not None and max(r["img_w"], r["img_h"]) <= 512])
        print(f"\n=== {name}  (유효 {len(v)}/{len(results)}) ===")
        print(f"  전체       min/mean/median/max = {v.min():.2f} / {v.mean():.2f} / {np.median(v):.2f} / {v.max():.2f}")
        if len(small):
            print(f"  작은(<=512) mean/median = {small.mean():.2f} / {np.median(small):.2f}  (n={len(small)})")
        if len(big):
            print(f"  큰(>512)    mean/median = {big.mean():.2f} / {np.median(big):.2f}  (n={len(big)})")
        edges = [0, 5, 10, 20, 30, 40, 50, 60, 100.01]
        hist, _ = np.histogram(v, bins=edges)
        for lo, hi, c in zip(edges[:-1], edges[1:], hist):
            print(f"    [{lo:5.0f}, {hi:5.0f}) {c:4d}  {'#' * int(c / max(hist.max(), 1) * 40)}")

    # ---- MC Dropout 구간 폭 ----
    if do_mc:
        w = np.array([r["stil_interval_high"] - r["stil_interval_low"]
                      for r in results if r["stil_interval_low"] is not None])
        rel = np.array([(r["stil_interval_high"] - r["stil_interval_low"]) / r["stil_percent"] * 100
                        for r in results
                        if r["stil_interval_low"] is not None and r["stil_percent"]])
        bias = np.array([r["stil_mc_mean"] - r["stil_percent"]
                         for r in results if r["stil_mc_mean"] is not None])
        print(f"\n=== MC Dropout {args.mc_samples}회 (소켓2 헤드 dropout={args.mc_drop_rate}) — {args.mc_ci:.0f}% 구간 ===")
        print(f"  유효 {len(w)}/{len(results)} 장")
        if len(w):
            print(f"  절대 폭(%TIL point)  min/median/mean/max = "
                  f"{w.min():.2f} / {np.median(w):.2f} / {w.mean():.2f} / {w.max():.2f}")
            print(f"  상대 폭(폭/stil*100) min/median/mean/max = "
                  f"{rel.min():.0f}% / {np.median(rel):.0f}% / {rel.mean():.0f}% / {rel.max():.0f}%")
            print(f"  MC평균 - 점추정      median/mean = {np.median(bias):+.2f} / {bias.mean():+.2f}  "
                  f"(0 에 가까우면 dropout 이 점추정을 편향 안 시킴)")
            print("  주의: 이 구간은 소켓2 TIL 분류 불확실성만 반영. 조직분할(소켓1) 불확실성 제외 -> v2 후보.")

    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
