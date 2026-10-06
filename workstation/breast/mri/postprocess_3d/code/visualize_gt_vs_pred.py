#!/usr/bin/env python3
"""
정답 마스크 vs 모델이 예측한 마스크를 눈으로 비교하는 스크립트.
숫자(Dice/F1) 대신 사진으로 확인용.

한 이미지당 3장을 나란히 붙인 그림 하나로 저장한다:
  [원본]  [정답 마스크(초록)]  [모델 예측 마스크(빨강)]

사용법:
    python visualize_gt_vs_pred.py \
        --config configs/mri_lora.yaml \
        --weights train/ckpt/mri_lora_best.pt \
        --class-name tumor \
        --n 8 \
        --out compare_out
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import yaml
from PIL import Image as PILImage, ImageDraw
from scipy.ndimage import zoom
from torchvision.ops import nms
from torchvision.transforms import v2

import pycocotools.mask as mask_utils


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def import_medsam3(repo_root: str):
    repo = str(Path(repo_root).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    os.chdir(repo)

    from merge_medsam3 import load_merged_model
    from lora_layers import LoRAConfig, apply_lora_to_model, load_lora_weights
    from sam3.train.data.collator import collate_fn_api
    from sam3.train.data.sam3_image_dataset import (
        Datapoint, FindQueryLoaded, Image, InferenceMetadata, Object,
    )

    return dict(
        load_merged_model=load_merged_model, LoRAConfig=LoRAConfig,
        apply_lora_to_model=apply_lora_to_model, load_lora_weights=load_lora_weights,
        collate_fn_api=collate_fn_api, Datapoint=Datapoint, FindQueryLoaded=FindQueryLoaded,
        Image=Image, InferenceMetadata=InferenceMetadata, Object=Object,
    )


def move_to_device(obj, device):
    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, list):
        return [move_to_device(x, device) for x in obj]
    if isinstance(obj, tuple):
        return tuple(move_to_device(x, device) for x in obj)
    if isinstance(obj, dict):
        return {k: move_to_device(v, device) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        for f in obj.__dataclass_fields__:
            setattr(obj, f, move_to_device(getattr(obj, f), device))
        return obj
    return obj


def build_model(cfg, weights_path, M, device):
    ckpt = Path(cfg["model"]["checkpoint"]).resolve()
    merge_cfg = Path(cfg["model"]["merge_lora_config"]).resolve()
    model = M["load_merged_model"](str(ckpt), str(merge_cfg), device=device)

    if getattr(model, "matcher", None) is None:
        from sam3.train.matcher import BinaryHungarianMatcherV2
        model.matcher = BinaryHungarianMatcherV2(
            focal=True, cost_class=2.0, cost_bbox=5.0, cost_giou=2.0,
            alpha=0.25, gamma=2, stable=False,
        )

    lc = cfg["lora"]
    model = M["apply_lora_to_model"](model, M["LoRAConfig"](
        rank=lc["rank"], alpha=lc["alpha"], dropout=0.0,
        target_modules=lc["target_modules"],
        apply_to_vision_encoder=lc["apply_to_vision_encoder"],
        apply_to_text_encoder=lc["apply_to_text_encoder"],
        apply_to_geometry_encoder=lc["apply_to_geometry_encoder"],
        apply_to_detr_encoder=lc["apply_to_detr_encoder"],
        apply_to_detr_decoder=lc["apply_to_detr_decoder"],
        apply_to_mask_decoder=lc["apply_to_mask_decoder"],
    ))
    M["load_lora_weights"](model, weights_path)
    model.to(device).eval()
    return model


def resize_logits_then_binarize(raw_logits, target_h, target_w, threshold=0.5):
    """[버그수정] 이진화 먼저 -> nearest 확대(경계 뭉개짐) 대신,
    연속값(logit) 상태에서 bilinear로 먼저 확대 -> sigmoid -> 이진화 순서로 처리.
    eval_mri_lora_v3.py와 동일한 수정 (숫자엔 영향 없지만 시각 비교 정확도를 위해 통일)."""
    raw_t = torch.from_numpy(raw_logits).float()[None, None]
    raw_up = torch.nn.functional.interpolate(
        raw_t, size=(target_h, target_w), mode="bilinear", align_corners=False
    )
    prob_up = torch.sigmoid(raw_up)
    return (prob_up[0, 0] > threshold).numpy()


def decode_gt_mask(ann, h, w):
    seg = ann.get("segmentation")
    if not seg:
        return None
    if isinstance(seg, dict):
        m = mask_utils.decode(seg)
    else:
        rles = mask_utils.frPyObjects(seg, h, w)
        m = mask_utils.decode(mask_utils.merge(rles))
    return m.astype(np.uint8)


@torch.no_grad()
def run_one_query(model, M, image_tensor, resolution, orig_size, class_name, device):
    orig_w, orig_h = orig_size
    image_obj = M["Image"](data=image_tensor, objects=[], size=(resolution, resolution))
    meta = M["InferenceMetadata"](
        coco_image_id=0, original_image_id=0, original_category_id=0,
        original_size=(orig_h, orig_w), object_id=-1, frame_index=-1,
    )
    query = M["FindQueryLoaded"](
        query_text=class_name, image_id=0, object_ids_output=[],
        is_exhaustive=True, query_processing_order=0, inference_metadata=meta,
    )
    dp = M["Datapoint"](find_queries=[query], images=[image_obj], raw_images=[None])
    batch_dict = M["collate_fn_api"]([dp], dict_key="input", with_seg_masks=True)
    input_batch = move_to_device(batch_dict["input"], device)
    outputs_list = model(input_batch)
    return outputs_list[-1]


def overlay_mask(base_img: PILImage.Image, mask: np.ndarray, color) -> PILImage.Image:
    """base_img(RGB) 위에 mask(bool)를 반투명 색으로 얹는다."""
    overlay = PILImage.new("RGBA", base_img.size, (0, 0, 0, 0))
    mask_img = PILImage.fromarray((mask * 255).astype(np.uint8)).convert("L")
    solid = PILImage.new("RGBA", base_img.size, color + (110,))
    overlay.paste(solid, (0, 0), mask_img)
    base_rgba = base_img.convert("RGBA")
    return PILImage.alpha_composite(base_rgba, overlay).convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--class-name", required=True,
                     help="tumor / breast / dense tissue / benign lesion / malignant lesion")
    ap.add_argument("--n", type=int, default=8, help="비교할 이미지 개수")
    ap.add_argument("--score-threshold", type=float, default=0.5)
    ap.add_argument("--out", default="compare_out")
    ap.add_argument("--subset", default=None,
                     help="파일명에 이 문자열이 포함된 이미지만 (예: ISPY2, DUKE, NACT, ISPY1, duke_density, ambl)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, args.weights, M, device)

    root = Path(cfg["data"]["root"])
    split_key = f"{args.split}_split"
    split_dir = root / cfg["data"][split_key] if split_key in cfg["data"] else root / args.split
    with open(split_dir / "_annotations.coco.json") as f:
        coco = json.load(f)

    images = {im["id"]: im for im in coco["images"]}
    cat_id_to_name = {c["id"]: c["name"] for c in coco["categories"]}
    cat_name_to_id = {v: k for k, v in cat_id_to_name.items()}
    target_cat_id = cat_name_to_id.get(args.class_name)
    if target_cat_id is None:
        sys.exit(f"클래스 '{args.class_name}' 를 COCO categories에서 못 찾음. 목록: {list(cat_name_to_id)}")

    # 해당 클래스의 정답이 실제로 있는 이미지만 골라서 비교(빈 이미지 비교는 의미 없음)
    target_images = []
    for a in coco["annotations"]:
        if a["category_id"] == target_cat_id:
            target_images.append(a["image_id"])
    target_images = list(dict.fromkeys(target_images))  # 순서 유지 중복 제거

    if args.subset:
        before = len(target_images)
        target_images = [iid for iid in target_images if args.subset.lower() in images[iid]["file_name"].lower()]
        print(f"--subset '{args.subset}' 필터: {before}장 -> {len(target_images)}장")

    if not target_images:
        sys.exit(f"'{args.class_name}' 정답이 있는 이미지가 {args.split}에 없음 (subset='{args.subset}')")

    import random
    random.Random(42).shuffle(target_images)
    target_images = target_images[: args.n]

    resolution = cfg["data"]["resolution"]
    transform = v2.Compose([
        v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
        v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
    ])

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, img_id in enumerate(target_images):
        info = images[img_id]
        img_path = split_dir / info["file_name"]
        pil = PILImage.open(img_path).convert("RGB")
        orig_w, orig_h = pil.size
        pil_r = pil.resize((resolution, resolution), PILImage.BILINEAR)
        image_tensor = transform(pil_r)

        # 정답 마스크 (해당 클래스 전부 합집합)
        gt_union = np.zeros((orig_h, orig_w), dtype=bool)
        for a in coco["annotations"]:
            if a["image_id"] == img_id and a["category_id"] == target_cat_id:
                gm = decode_gt_mask(a, orig_h, orig_w)
                if gm is not None:
                    gt_union |= gm.astype(bool)

        # 모델 예측
        outputs = run_one_query(model, M, image_tensor, resolution, (orig_w, orig_h), args.class_name, device)
        pred_logits = outputs["pred_logits"][0]
        pred_boxes = outputs["pred_boxes"][0]
        pred_masks = outputs.get("pred_masks", None)
        pred_masks = pred_masks[0] if pred_masks is not None else None

        scores = pred_logits.sigmoid().amax(dim=-1).cpu().numpy()
        boxes = pred_boxes.cpu().numpy()
        masks = pred_masks.cpu().numpy() if pred_masks is not None else None

        keep = np.where(scores > args.score_threshold)[0]
        if keep.size > 1:
            kb = boxes[keep]
            cx, cy, bw, bh = kb[:, 0], kb[:, 1], kb[:, 2], kb[:, 3]
            x1 = (cx - bw / 2) * orig_w
            y1 = (cy - bh / 2) * orig_h
            x2 = (cx + bw / 2) * orig_w
            y2 = (cy + bh / 2) * orig_h
            boxes_xyxy_t = torch.from_numpy(np.stack([x1, y1, x2, y2], axis=1)).float()
            scores_t = torch.from_numpy(scores[keep]).float()
            nms_keep = nms(boxes_xyxy_t, scores_t, iou_threshold=0.5).numpy()
            keep = keep[nms_keep]

        pred_union = np.zeros((orig_h, orig_w), dtype=bool)
        for qi in keep:
            if masks is None:
                break
            m = resize_logits_then_binarize(masks[qi], orig_h, orig_w)
            pred_union |= m

        gt_overlay = overlay_mask(pil, gt_union, (46, 204, 113))     # 초록 = 정답
        pred_overlay = overlay_mask(pil, pred_union, (231, 76, 60))  # 빨강 = 예측

        # 세 장 나란히 붙이기
        gap = 8
        combo = PILImage.new("RGB", (orig_w * 3 + gap * 2, orig_h + 30), (255, 255, 255))
        combo.paste(pil, (0, 30))
        combo.paste(gt_overlay, (orig_w + gap, 30))
        combo.paste(pred_overlay, (orig_w * 2 + gap * 2, 30))
        draw = ImageDraw.Draw(combo)
        draw.text((10, 6), "원본", fill=(0, 0, 0))
        draw.text((orig_w + gap + 10, 6), "정답(초록)", fill=(0, 0, 0))
        draw.text((orig_w * 2 + gap * 2 + 10, 6), "모델 예측(빨강)", fill=(0, 0, 0))

        n_pred = len(keep)
        tag = args.class_name.replace(" ", "_")
        if args.subset:
            tag += f"_{args.subset}"
        out_path = out_dir / f"{tag}_{i:02d}_{info['file_name']}"
        combo.save(out_path)
        print(f"[{i+1}/{len(target_images)}] {out_path.name}  (예측 마스크 {n_pred}개, score>{args.score_threshold})")

    print(f"\n비교 이미지 {len(target_images)}장 저장 완료: {out_dir}")
    print("로컬로 받기:")
    print(f"  scp -P 22 -r wsuser@lan-host:{out_dir.resolve()} .")


if __name__ == "__main__":
    main()
