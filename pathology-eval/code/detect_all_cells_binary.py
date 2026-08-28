"""
1단계: SAM-H 사전학습 CellViT로 TIGER 이미지 안의 모든 세포 위치(좌표)를 binary 검출.
타입 분류 없이 "여기 세포가 있다"만 찾아냄. 결과는 나중에 TIGER TIL 라벨과 매칭해서
label 0(non-TIL)/1(TIL) 이진분류 학습 데이터를 만드는 데 쓰임.

사용법:
  python3 detect_all_cells_binary.py --split train
  python3 detect_all_cells_binary.py --split test
"""
import argparse
import json
import os
import sys
from pathlib import Path

import albumentations as A
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from PIL import Image

# 레포 루트를 path에 추가
REPO_ROOT = os.path.expanduser("~/models/cellvitpp")
sys.path.insert(0, REPO_ROOT)

from cellvit.models.cell_segmentation.cellvit_sam import CellViTSAM
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy
from cellvit.utils.tools import unflatten_dict


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
        default=os.path.join(
            REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"
        ),
    )
    parser.add_argument("--outdir", type=str, default=os.path.expanduser("~/data/tiger/binary_detection"))
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--target_size", type=int, default=256)
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    model, run_conf, device = load_model(args.model_path, args.gpu)
    transform = build_transform(args.target_size)

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

    results = {}
    with torch.no_grad():
        for i, img_path in enumerate(image_files):
            img = Image.open(img_path).convert("RGB")
            orig_w, orig_h = img.size
            img_np = np.array(img).astype(np.uint8)

            transformed = transform(image=img_np)
            tensor = transformed["image"].unsqueeze(0).to(device)

            predictions = model.forward(tensor, retrieve_tokens=True)
            # binary segmentation head still outputs full nuclei_type_map; reduce to 2 classes for binary postproc
            predictions_binary = {
                "nuclei_binary_map": predictions["nuclei_binary_map"].permute(0, 2, 3, 1),
                "nuclei_type_map": predictions["nuclei_binary_map"].permute(0, 2, 3, 1),
                "hv_map": predictions["hv_map"].permute(0, 2, 3, 1),
            }
            import torch.nn.functional as F
            predictions_binary["nuclei_binary_map"] = F.softmax(predictions_binary["nuclei_binary_map"], dim=-1)
            predictions_binary["nuclei_type_map"] = predictions_binary["nuclei_binary_map"]

            _, cell_dicts = postprocessor.post_process_batch(predictions_binary)

            # scale detected coordinates back to original image size
            scale = args.target_size / max(orig_w, orig_h)
            pad_x = (args.target_size - orig_w * scale) / 2
            pad_y = (args.target_size - orig_h * scale) / 2

            cells_out = []
            for cell_id, cell in cell_dicts[0].items():
                cx, cy = cell["centroid"]
                orig_x = (cx - pad_x) / scale
                orig_y = (cy - pad_y) / scale
                if 0 <= orig_x <= orig_w and 0 <= orig_y <= orig_h:
                    cells_out.append({"x": round(float(orig_x), 2), "y": round(float(orig_y), 2)})

            results[img_path.stem] = cells_out
            if (i + 1) % 50 == 0:
                print(f"{i + 1}/{len(image_files)} processed")

    out_path = Path(args.outdir) / f"{args.split}_all_cells.json"
    with open(out_path, "w") as f:
        json.dump(results, f)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
