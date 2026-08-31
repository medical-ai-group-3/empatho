"""
sTIL 계산 데모 파이프라인.

확정_사양서 정의: stil_percent = 면역세포 ÷ (면역세포 + 사이조직)

이 스크립트는:
  1. 조직분할 모델(Virchow2+Linear, TAND 논문 사양 = 온도 스케일링 + CE/Dice/BCE)로
     이미지의 간질(사이조직) 영역을 예측 (16x16 격자, 확정: linear_tand)
  2. 세포검출·분류 모델(CellViT-SAM-H 검출 + weighted LinearClassifier 헤드)로
     이미지의 모든 세포를 검출하고 각 세포를 TIL/nonTIL 로 분류, P(TIL) >= 임계값
     인 세포를 면역세포로 카운트
     (2026-08-31 확정: 큰 이미지 타일링 재추출 + 가중 CE 재학습 모델.
      candidates/socket2/model_best.pth, val AUROC 0.9656)
  3. 아래 공식으로 이미지별 sTIL% 계산

주의(⚑):
  - 현재 공식은 "면역세포 개수 ÷ (면역세포 개수 + 간질 격자칸 수)" 로, 분자·분모의
    단위(개수 vs 16x16 격자칸)가 불일치. 표준(면역세포 면적 ÷ 간질 면적 × 100)으로
    고치는 작업이 별도 예정. 이 버전은 검출/분류 개선 효과만 보기 위한 것.
  - 큰 이미지(>512px)는 타일링으로 검출. 작은 이미지는 512 pad+centercrop 단일 추론.
"""
import argparse
import json
import os
import sys
from pathlib import Path

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
        temperature = torch.exp(self.log_temperature)
        return logits / temperature


def build_virchow2():
    model = timm.create_model(
        "hf_hub:paige-ai/Virchow2", pretrained=True,
        mlp_layer=timm.layers.SwiGLUPacked, act_layer=torch.nn.SiLU,
    )
    model.eval()
    data_cfg = timm.data.resolve_model_data_config(model)
    return model, data_cfg["mean"], data_cfg["std"], data_cfg["input_size"][-1]


def load_tissue_model(checkpoint_path, device):
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowLinearHeadTAND(virchow_model).to(device)
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    model.log_temperature.data = ckpt["log_temperature"].data.to(device)
    model.eval()
    return model, mean, std, image_size


def load_cell_classifier(head_path, device):
    head = LinearClassifier(embed_dim=TOKEN_DIM, hidden_dim=HIDDEN_DIM, num_classes=2, drop_rate=0)
    ckpt = torch.load(head_path, map_location=device, weights_only=False)
    head.load_state_dict(ckpt["model_state_dict"] if "model_state_dict" in ckpt else ckpt)
    head.eval().to(device)
    return head


def predict_tissue_mask(model, img, mean, std, image_size, device):
    img_resized = img.resize((image_size, image_size), Image.BILINEAR)
    img_t = torch.from_numpy(np.array(img_resized)).permute(2, 0, 1).float() / 255.0
    mean_t = torch.tensor(mean).view(3, 1, 1)
    std_t = torch.tensor(std).view(3, 1, 1)
    img_t = ((img_t - mean_t) / std_t).unsqueeze(0).to(device)
    with torch.no_grad():
        logits = model(img_t)
        pred = logits.argmax(dim=1).squeeze(0).cpu().numpy()  # (16, 16)
    return pred


@torch.inference_mode()
def classify_til_cells(img_np, cellvit, postproc, head, device, threshold, batch_size):
    """모든 세포 검출 -> 토큰 -> 헤드 분류. P(TIL) >= threshold 인 세포 수 반환."""
    H, W = img_np.shape[:2]
    if max(H, W) <= INPUT_SHAPE:
        _, tokens = detect_cells_small(img_np, cellvit, postproc, device)
    else:
        _, tokens = detect_cells_large(img_np, cellvit, postproc, device, batch_size)
    if len(tokens) == 0:
        return 0, 0
    T = torch.tensor(np.stack(tokens), dtype=torch.float32, device=device)
    p_til = torch.softmax(head(T), dim=1)[:, 1].cpu().numpy()
    return int((p_til >= threshold).sum()), len(tokens)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tissue_checkpoint", type=str,
        default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand/best_head.pth"),
    )
    parser.add_argument(
        "--cell_head", type=str,
        default=os.path.expanduser("~/pathology-eval/candidates/socket2/model_best.pth"),
        help="weighted LinearClassifier 헤드 체크포인트",
    )
    parser.add_argument(
        "--cellvit_path", type=str,
        default=os.path.join(REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"),
    )
    parser.add_argument(
        "--images_dir", type=str,
        default=os.path.expanduser("~/data/tiger/tissue_segmentation/val/images"),
    )
    parser.add_argument("--til_threshold", type=float, default=0.5)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument(
        "--outdir", type=str,
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "stil_results"),
    )
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="처리할 이미지 수 (0이면 전체)")
    args = parser.parse_args()

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    os.makedirs(args.outdir, exist_ok=True)

    print("조직분할 모델 로딩...")
    tissue_model, mean, std, image_size = load_tissue_model(args.tissue_checkpoint, device)
    print("세포검출(CellViT-SAM-H) + 분류 헤드 로딩...")
    cellvit, _ = load_cellvit_sam(args.cellvit_path, args.gpu)
    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=NR_TYPES)
    head = load_cell_classifier(args.cell_head, device)

    image_files = sorted(Path(args.images_dir).glob("*.png"))
    if args.limit > 0:
        image_files = image_files[: args.limit]
    print(f"이미지 {len(image_files)}장, TIL 임계값 {args.til_threshold}")

    results = []
    for i, img_path in enumerate(image_files):
        img = Image.open(img_path).convert("RGB")
        img_np = np.array(img).astype(np.uint8)

        tissue_pred = predict_tissue_mask(tissue_model, img, mean, std, image_size, device)
        stroma_pixels = int((tissue_pred == STROMA_CLASS_IDX).sum())

        til_count, total_cells = classify_til_cells(
            img_np, cellvit, postproc, head, device, args.til_threshold, args.batch_size
        )

        denom = til_count + stroma_pixels
        stil_percent = (til_count / denom * 100) if denom > 0 else None

        results.append({
            "stem": img_path.stem,
            "til_count": til_count,
            "total_cells": total_cells,
            "stroma_pixels_16x16grid": stroma_pixels,
            "stil_percent": round(stil_percent, 2) if stil_percent is not None else None,
        })
        if (i + 1) % 25 == 0 or i == 0:
            print(f"  [{i+1}/{len(image_files)}] {img_path.stem[:36]:36s} "
                  f"TIL={til_count}/{total_cells}  간질칸={stroma_pixels}  sTIL%={results[-1]['stil_percent']}")

    out_path = Path(args.outdir) / "stil_demo_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    vals = [r["stil_percent"] for r in results if r["stil_percent"] is not None]
    print(f"\n결과 저장: {out_path}  (처리 {len(results)}장, sTIL 유효 {len(vals)}장)")
    if vals:
        v = np.array(vals)
        print(f"sTIL% 분포: min={v.min():.2f}  mean={v.mean():.2f}  median={np.median(v):.2f}  max={v.max():.2f}")
        edges = [0, 1, 2, 5, 10, 20, 30, 50, 100.01]
        hist, _ = np.histogram(v, bins=edges)
        for lo, hi, c in zip(edges[:-1], edges[1:], hist):
            bar = "#" * int(c / max(hist.max(), 1) * 40)
            print(f"  [{lo:5.0f}, {hi:5.0f}) {c:4d}  {bar}")


if __name__ == "__main__":
    main()
