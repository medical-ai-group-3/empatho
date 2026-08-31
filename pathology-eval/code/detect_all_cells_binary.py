"""
1단계: SAM-H 사전학습 CellViT로 TIGER 이미지 안의 모든 세포 위치(좌표)를 binary 검출.
타입 분류 없이 "여기 세포가 있다"만 찾아냄. 결과는 나중에 TIGER TIL 라벨과 매칭해서
label 0(non-TIL)/1(TIL) 이진분류 학습 데이터를 만드는 데 쓰임.

--- v2 수정 (2026-08-31): 큰 이미지 타일링 ---
기존 build_transform 의 LongestMaxSize(max_size=256) 이 큰 이미지(>256px)를 최대 5.3배
축소해 세포핵이 뭉개지고 watershed 후처리가 붕괴 -> >600px 이미지의 TIL 매칭 recall 0.7%.
(진단: 작은 이미지 95.6% vs 큰 이미지 4% / det/GT 비 0.25)

수정:
  - 최장변 <= target_size(256) 이미지: 기존과 완전히 동일 (LongestMaxSize+Pad, 단일 추론)
  - 최장변 >  target_size 이미지: 256x256 타일로 분할(overlap 64px)해 원본 해상도 그대로
    타일별 추론 -> 좌표를 원본 기준으로 합침 -> 타일 경계 중복 검출은 greedy NMS 제거
출력 포맷/파일명은 기존과 동일: {stem: [{"x":.., "y":..}, ...]} -> {split}_all_cells.json

사용법:
  python3 detect_all_cells_binary.py --split train
  python3 detect_all_cells_binary.py --split test
  # VRAM 부족 시 (예: RTX 2060 6GB): --batch_size 2  또는 1
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import albumentations as A
import numpy as np
import torch
import torch.nn.functional as F
from albumentations.pytorch import ToTensorV2
from PIL import Image

# 레포 루트를 path에 추가
REPO_ROOT = os.path.expanduser("~/models/cellvitpp")
sys.path.insert(0, REPO_ROOT)

from cellvit.models.cell_segmentation.cellvit_sam import CellViTSAM
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy
from cellvit.utils.tools import unflatten_dict

TILE_SIZE = 256
TILE_OVERLAP = 64  # 타일 간 겹침(px). 경계에 걸친 세포가 최소 한 타일 안에 온전히 들어오도록.


def load_model(model_path: str, gpu: int = 0):
    device = f"cuda:{gpu}"
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    run_conf = unflatten_dict(checkpoint["config"], ".")

    model = CellViTSAM(
        model_path=None,
        num_nuclei_classes=run_conf["data"]["num_nuclei_classes"],
        num_tissue_classes=run_conf["data"]["num_tissue_classes"],
        vit_structure=run_conf["model"]["backbone"],
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    model.to(device)
    return model, run_conf, device


def build_transform(target_size: int = 256):
    """<=target_size 이미지용 (기존 동작 그대로): 최장변 리사이즈 + 가운데 패딩."""
    return A.Compose(
        [
            A.LongestMaxSize(max_size=target_size),
            A.PadIfNeeded(
                min_height=target_size,
                min_width=target_size,
                border_mode=0,
                value=(255, 255, 255),
            ),
            A.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
            ToTensorV2(),
        ]
    )


def build_tile_transform():
    """타일용: 리사이즈 없음. 가장자리 타일만 오른쪽/아래로 패딩(좌상단 정렬)해서
    타일 로컬 좌표 = (원본좌표 - 타일오프셋) 이 되도록 한다."""
    return A.Compose(
        [
            A.PadIfNeeded(
                min_height=TILE_SIZE,
                min_width=TILE_SIZE,
                position="top_left",
                border_mode=0,
                value=(255, 255, 255),
            ),
            A.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
            ToTensorV2(),
        ]
    )


def tile_starts(length: int, tile: int, overlap: int):
    """축 하나에 대한 타일 시작 좌표들. 마지막 타일은 이미지 끝에 딱 맞춘다."""
    if length <= tile:
        return [0]
    step = tile - overlap
    starts = list(range(0, length - tile + 1, step))
    if starts[-1] != length - tile:
        starts.append(length - tile)
    return starts


@torch.inference_mode()
def detect_batch(model, postprocessor, tensor_batch):
    """(B,3,256,256) -> 배치 내 각 이미지의 cell dict 리스트. 좌표는 256px 입력 공간 기준."""
    predictions = model.forward(tensor_batch, retrieve_tokens=True)
    predictions_binary = {
        "nuclei_binary_map": predictions["nuclei_binary_map"].permute(0, 2, 3, 1),
        "nuclei_type_map": predictions["nuclei_binary_map"].permute(0, 2, 3, 1),
        "hv_map": predictions["hv_map"].permute(0, 2, 3, 1),
    }
    predictions_binary["nuclei_binary_map"] = F.softmax(
        predictions_binary["nuclei_binary_map"], dim=-1
    )
    predictions_binary["nuclei_type_map"] = predictions_binary["nuclei_binary_map"]
    _, cell_dicts = postprocessor.post_process_batch(predictions_binary)
    return cell_dicts


def detect_batch_safe(model, postprocessor, tensors, device, batch_size):
    """OOM 시 배치 크기를 반씩 줄여 재시도. tensors: list[(3,256,256)] (CPU)."""
    out = []
    i = 0
    bs = max(1, batch_size)
    while i < len(tensors):
        chunk = tensors[i : i + bs]
        try:
            batch = torch.stack(chunk).to(device)
            out.extend(detect_batch(model, postprocessor, batch))
            del batch
            i += len(chunk)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if bs == 1:
                raise
            bs = max(1, bs // 2)
            print(f"    [OOM] 배치 크기를 {bs}로 축소 후 재시도")
    return out


def merge_tile_detections(dets, dedup_radius: float):
    """타일 경계 중복 제거. dets: list[(x, y, edge_margin)].
    edge_margin(타일 내부 경계까지 거리)이 큰 것 = 더 신뢰 -> 먼저 채택."""
    dets = sorted(dets, key=lambda d: -d[2])
    kept = []
    for x, y, _ in dets:
        if all(math.hypot(x - kx, y - ky) > dedup_radius for kx, ky in kept):
            kept.append((x, y))
    return kept


def process_small_image(img_np, orig_w, orig_h, transform, target_size, model, postprocessor, device):
    """<=target_size 경로 (기존 로직 그대로)."""
    tensor = transform(image=img_np)["image"]
    cell_dicts = detect_batch_safe(model, postprocessor, [tensor], device, 1)
    scale = target_size / max(orig_w, orig_h)
    pad_x = (target_size - orig_w * scale) / 2
    pad_y = (target_size - orig_h * scale) / 2

    cells_out = []
    for _, cell in cell_dicts[0].items():
        cx, cy = cell["centroid"]
        orig_x = (cx - pad_x) / scale
        orig_y = (cy - pad_y) / scale
        if 0 <= orig_x <= orig_w and 0 <= orig_y <= orig_h:
            cells_out.append({"x": round(float(orig_x), 2), "y": round(float(orig_y), 2)})
    return cells_out


def process_large_image(img_np, orig_w, orig_h, tile_transform, model, postprocessor, device, batch_size, dedup_radius):
    """>target_size 경로: 원본 해상도 타일링."""
    xs = tile_starts(orig_w, TILE_SIZE, TILE_OVERLAP)
    ys = tile_starts(orig_h, TILE_SIZE, TILE_OVERLAP)

    tensors, metas = [], []
    for y0 in ys:
        for x0 in xs:
            crop = img_np[y0 : y0 + TILE_SIZE, x0 : x0 + TILE_SIZE]
            crop_h, crop_w = crop.shape[:2]
            tensors.append(tile_transform(image=crop)["image"])
            metas.append((x0, y0, crop_w, crop_h))

    cell_dicts = detect_batch_safe(model, postprocessor, tensors, device, batch_size)

    raw = []
    for (x0, y0, crop_w, crop_h), cells in zip(metas, cell_dicts):
        left_internal = x0 > 0
        top_internal = y0 > 0
        right_internal = x0 + TILE_SIZE < orig_w
        bottom_internal = y0 + TILE_SIZE < orig_h
        for _, cell in cells.items():
            cx, cy = cell["centroid"]
            # 패딩 영역(유효 crop 밖) 검출은 버림
            if cx > crop_w or cy > crop_h:
                continue
            gx, gy = x0 + cx, y0 + cy
            if not (0 <= gx <= orig_w and 0 <= gy <= orig_h):
                continue
            margins = [1e9]
            if left_internal:
                margins.append(cx)
            if top_internal:
                margins.append(cy)
            if right_internal:
                margins.append(crop_w - cx)
            if bottom_internal:
                margins.append(crop_h - cy)
            raw.append((gx, gy, min(margins)))

    merged = merge_tile_detections(raw, dedup_radius)
    return [{"x": round(float(x), 2), "y": round(float(y), 2)} for x, y in merged]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", type=str, required=True, choices=["train", "test"])
    parser.add_argument(
        "--dataset_path",
        type=str,
        default=os.path.expanduser("~/data/tiger/cellvit_detection"),
    )
    parser.add_argument(
        "--model_path",
        type=str,
        default=os.path.join(REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"),
    )
    parser.add_argument("--outdir", type=str, default=os.path.expanduser("~/data/tiger/binary_detection"))
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--target_size", type=int, default=256)
    parser.add_argument("--batch_size", type=int, default=4, help="타일 추론 배치 크기 (VRAM 부족 시 낮출 것)")
    parser.add_argument("--dedup_radius", type=float, default=10.0, help="타일 경계 중복 검출 병합 반경(px)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    model, run_conf, device = load_model(args.model_path, args.gpu)
    transform = build_transform(args.target_size)
    tile_transform = build_tile_transform()

    postprocessor = DetectionCellPostProcessorCupy(
        wsi=None,
        nr_types=2,  # background + cell (binary)
        resolution=0.25,
        binary=True,
    )

    image_dir = Path(args.dataset_path) / args.split / "images"
    image_files = sorted(
        [f for f in image_dir.glob("*") if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]
    )
    print(f"Found {len(image_files)} images in {image_dir}")

    n_small = n_large = 0
    results = {}
    for i, img_path in enumerate(image_files):
        img = Image.open(img_path).convert("RGB")
        orig_w, orig_h = img.size
        img_np = np.array(img).astype(np.uint8)

        if max(orig_w, orig_h) <= args.target_size:
            cells_out = process_small_image(
                img_np, orig_w, orig_h, transform, args.target_size, model, postprocessor, device
            )
            n_small += 1
        else:
            cells_out = process_large_image(
                img_np, orig_w, orig_h, tile_transform, model, postprocessor, device,
                args.batch_size, args.dedup_radius,
            )
            n_large += 1

        results[img_path.stem] = cells_out
        if (i + 1) % 50 == 0:
            print(f"{i + 1}/{len(image_files)} processed  (small={n_small}, tiled={n_large})")

    out_path = Path(args.outdir) / f"{args.split}_all_cells.json"
    with open(out_path, "w") as f:
        json.dump(results, f)
    print(f"Saved: {out_path}")
    print(f"단일추론(<= {args.target_size}px): {n_small}장,  타일링(> {args.target_size}px): {n_large}장")


if __name__ == "__main__":
    main()
