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


def load_cell_classifier(head_path, device):
    head = LinearClassifier(embed_dim=TOKEN_DIM, hidden_dim=HIDDEN_DIM, num_classes=2, drop_rate=0)
    ckpt = torch.load(head_path, map_location=device, weights_only=False)
    head.load_state_dict(ckpt["model_state_dict"] if "model_state_dict" in ckpt else ckpt)
    head.eval().to(device)
    return head


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
def detect_and_classify(img_np, cellvit, postproc, head, device, batch_size):
    """반환: list[{cx, cy (원본좌표), p_til, area_px (원본 픽셀^2)}]  (이미지 밖 세포는 제외)"""
    H, W = img_np.shape[:2]
    if max(H, W) <= INPUT_SHAPE:
        coords, tokens, contours = detect_cells_small(img_np, cellvit, postproc, device)
        dx, dy = (INPUT_SHAPE - W) // 2, (INPUT_SHAPE - H) // 2  # PadIfNeeded(center) 오프셋
        coords = coords - np.array([dx, dy])
        contours = [c - np.array([dx, dy]) for c in contours]
    else:
        coords, tokens, contours = detect_cells_large(img_np, cellvit, postproc, device, batch_size)

    if len(tokens) == 0:
        return []
    T = torch.tensor(np.stack(tokens), dtype=torch.float32, device=device)
    p_til = torch.softmax(head(T), dim=1)[:, 1].cpu().numpy()

    cells = []
    for (cx, cy), p, cont in zip(coords, p_til, contours):
        if not (0 <= cx < W and 0 <= cy < H):
            continue
        cells.append({"cx": float(cx), "cy": float(cy), "p_til": float(p), "area_px": _contour_area(cont)})
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
    args = ap.parse_args()

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    os.makedirs(args.outdir, exist_ok=True)

    print("조직분할 모델 로딩...")
    tissue_model, mean, std, image_size = load_tissue_model(args.tissue_checkpoint, device)
    print("세포검출(CellViT-SAM-H) + 분류 헤드 로딩...")
    cellvit, _ = load_cellvit_sam(args.cellvit_path, args.gpu)
    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=NR_TYPES)
    head = load_cell_classifier(args.cell_head, device)

    files = sorted(Path(args.images_dir).glob("*.png"))
    if args.limit > 0:
        files = files[: args.limit]
    print(f"이미지 {len(files)}장, TIL 임계값 {args.til_threshold}, mpp {args.mpp} µm/px")

    results = []
    all_areas_px = []       # 검출된 모든 세포
    all_areas_px_til = []    # P(TIL)>=임계값 세포
    for i, fp in enumerate(files):
        img = Image.open(fp).convert("RGB")
        img_np = np.array(img).astype(np.uint8)
        H, W = img_np.shape[:2]

        mask, pred16 = tissue_stroma_mask(tissue_model, img, mean, std, image_size, device, W, H)
        stroma_area_px = int((mask == STROMA_CLASS_IDX).sum())
        stroma_16grid = int((pred16 == STROMA_CLASS_IDX).sum())

        cells = detect_and_classify(img_np, cellvit, postproc, head, device, args.batch_size)
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

        results.append({
            "stem": fp.stem,
            "img_w": W, "img_h": H,
            "n_cells": len(cells),
            "til_count": len(immune),
            "til_count_stromal": len(intra),
            "stroma_status": "ok" if stroma_ok else "absent",
            "stroma_area_px": stroma_area_px,
            "stroma_area_um2": round(stroma_area_px * args.mpp ** 2, 1),
            "immune_nucleus_area_px": round(immune_nuc_px, 1),
            "immune_cell_area_px": round(immune_cell_px, 1),
            "immune_cell_area_um2": round(immune_cell_px * args.mpp ** 2, 1),
            "nc_ratio": args.nc_ratio,
            "stil_percent": round(stil_std, 2) if stil_std is not None else None,
            "legacy_stil_percent": round(legacy, 2) if legacy is not None else None,
        })
        if (i + 1) % 25 == 0 or i == 0:
            r = results[-1]
            print(f"  [{i+1}/{len(files)}] {fp.stem[:32]:32s} {W}x{H}  "
                  f"면역세포 {r['til_count_stromal']}/{r['til_count']}(간질내/전체)  "
                  f"stil={r['stil_percent']}  legacy={r['legacy_stil_percent']}")

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

    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
