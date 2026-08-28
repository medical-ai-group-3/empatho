"""
sTIL 계산 데모 파이프라인.

확정_사양서 정의: stil_percent = 면역세포 ÷ (면역세포 + 사이조직)

이 스크립트는:
  1. 조직분할 모델(Virchow2+Linear, 가중치판)로 이미지의 간질(사이조직) 영역을 예측
  2. 이미 만들어둔 TIL 좌표 라벨(0/1)에서 TIL(면역세포) 개수를 집계
  3. 위 공식으로 이미지별 sTIL%를 계산

주의(⚑, 팀 확인 필요):
  - 분모의 "사이조직"이 면적(픽셀 수) 기준인지 개수 기준인지 확정_사양서에
    명시되어 있지 않음(검토보고서 S1 항목). 이 스크립트는 우선 픽셀 수를
    사용하고 있으며, 개수 기준이 맞다면 별도 세포 밀도 추정이 필요함.
  - 세포검출 모델의 실제 추론(inference)은 이 스크립트에서 재실행하지 않고,
    이미 생성해둔 TIL/nonTIL 라벨(build_binary_labels.py 결과물)을 정답처럼
    사용함. 신규 이미지에 대한 실시간 추론은 별도 구현 필요.
"""
import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn as nn
from PIL import Image

NUM_CLASSES = 3
PATCH_GRID = 16
NUM_REGISTER_TOKENS = 4
STROMA_CLASS_IDX = 2  # 간질 (기타=0, 종양=1, 간질=2)


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


def predict_tissue_mask(model, img_path, mean, std, image_size, device):
    img = Image.open(img_path).convert("RGB")
    img_resized = img.resize((image_size, image_size), Image.BILINEAR)
    img_t = torch.from_numpy(np.array(img_resized)).permute(2, 0, 1).float() / 255.0
    mean_t = torch.tensor(mean).view(3, 1, 1)
    std_t = torch.tensor(std).view(3, 1, 1)
    img_t = ((img_t - mean_t) / std_t).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(img_t)
        pred = logits.argmax(dim=1).squeeze(0).cpu().numpy()  # (16, 16)
    return pred


def count_til_cells(label_csv_path):
    til_count = 0
    total_count = 0
    if not label_csv_path.exists():
        return 0, 0
    with open(label_csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            total_count += 1
            if row[2].strip() == "1":
                til_count += 1
    return til_count, total_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tissue_checkpoint",
        type=str,
        default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand_weighted/best_head.pth"),
    )
    parser.add_argument(
        "--images_dir",
        type=str,
        default=os.path.expanduser("~/data/tiger/tissue_segmentation_v2/val/images"),
    )
    parser.add_argument(
        "--cell_labels_dir",
        type=str,
        default=os.path.expanduser("~/data/tiger/cellvit_detection_v2/train/labels"),
        help="TIL/nonTIL 라벨 CSV가 있는 폴더 (build_binary_labels.py 결과물)",
    )
    parser.add_argument("--outdir", type=str, default=os.path.expanduser("~/workspace/breast/pathology/code/stil_results"))
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20, help="처리할 이미지 수 (데모용, 0이면 전체)")
    args = parser.parse_args()

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    os.makedirs(args.outdir, exist_ok=True)

    print("조직분할 모델 로딩 중...")
    model, mean, std, image_size = load_tissue_model(args.tissue_checkpoint, device)

    images_dir = Path(args.images_dir)
    cell_labels_dir = Path(args.cell_labels_dir)
    image_files = sorted(images_dir.glob("*.png"))
    if args.limit > 0:
        image_files = image_files[: args.limit]

    results = []
    for img_path in image_files:
        stem = img_path.stem

        tissue_pred = predict_tissue_mask(model, img_path, mean, std, image_size, device)
        stroma_pixels = int((tissue_pred == STROMA_CLASS_IDX).sum())

        label_csv = cell_labels_dir / f"{stem}.csv"
        til_count, total_count = count_til_cells(label_csv)

        denom = til_count + stroma_pixels
        stil_percent = (til_count / denom * 100) if denom > 0 else None

        results.append(
            {
                "stem": stem,
                "til_count": til_count,
                "total_cells": total_count,
                "stroma_pixels_16x16grid": stroma_pixels,
                "stil_percent": round(stil_percent, 2) if stil_percent is not None else None,
            }
        )
        print(
            f"{stem[:40]:40s} TIL={til_count:3d} 간질픽셀(16x16기준)={stroma_pixels:3d} "
            f"sTIL%={results[-1]['stil_percent']}"
        )

    out_path = Path(args.outdir) / "stil_demo_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")
    print(f"처리된 이미지 수: {len(results)}")


if __name__ == "__main__":
    main()
