#!/usr/bin/env python3
"""
MRI LoRA 학습 결과 평가 v3 - Dice 버그 수정 + 분할 클래스 오탐율 추가

v2 대비 변경점:
  1. [버그수정] Dice 계산 시 정답(gts)이 실제로 있는 이미지에서만 채점하도록 함.
     기존엔 정답 없는 이미지에서 모델이 헛짚으면 Dice=0으로 강제 기록되어
     breast/dense tissue 평균을 심하게 깎아먹고 있었음.
  2. [추가] 정답 없는 이미지에서 분할 클래스가 얼마나 헛짚는지(오탐율) 별도 카운터로 기록.

사용법:
    python eval_mri_lora_v3.py --config configs/mri_lora.yaml --weights train/ckpt/mri_lora_best.pt \
        --score-threshold 0.5 --iou-threshold 0.5 --max-images 150
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import yaml
from PIL import Image as PILImage
from scipy.ndimage import zoom
from torchvision.transforms import v2
from torchvision.ops import nms

import pycocotools.mask as mask_utils


SEG_CLASSES = {"tumor", "breast", "dense tissue"}
DET_CLASSES = {"benign lesion", "malignant lesion"}


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def import_medsam3(repo_root):
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
    print("병합본 로드:", ckpt)
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
    print("학습된 MRI LoRA 가중치 로드:", weights_path)
    M["load_lora_weights"](model, weights_path)

    model.to(device).eval()
    return model


def dice_score(pred_mask, gt_mask):
    pred = pred_mask.astype(bool)
    gt = gt_mask.astype(bool)
    inter = (pred & gt).sum()
    denom = pred.sum() + gt.sum()
    if denom == 0:
        return 1.0 if not pred.any() and not gt.any() else 0.0
    return 2.0 * inter / denom


def box_iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def cxcywh_to_xyxy_pixel(box, w, h):
    cx, cy, bw, bh = box
    x1 = (cx - bw / 2) * w
    y1 = (cy - bh / 2) * h
    x2 = (cx + bw / 2) * w
    y2 = (cy + bh / 2) * h
    return x1, y1, x2, y2


def apply_nms(boxes, scores, iou_threshold=0.5):
    if len(boxes) == 0:
        return np.array([], dtype=np.int64)
    boxes_xyxy = np.stack([
        boxes[:, 0] - boxes[:, 2] / 2,
        boxes[:, 1] - boxes[:, 3] / 2,
        boxes[:, 0] + boxes[:, 2] / 2,
        boxes[:, 1] + boxes[:, 3] / 2,
    ], axis=1)
    boxes_t = torch.as_tensor(boxes_xyxy, dtype=torch.float32)
    scores_t = torch.as_tensor(scores, dtype=torch.float32)
    keep = nms(boxes_t, scores_t, iou_threshold)
    return keep.cpu().numpy()


def sigmoid_np(x):
    x = np.asarray(x, dtype=np.float32)
    out = np.empty_like(x)
    pos = x >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    exp_x = np.exp(x[~pos])
    out[~pos] = exp_x / (1.0 + exp_x)
    return out


def resize_mask(mask, h, w):
    if mask.shape == (h, w):
        return mask.astype(bool)
    return zoom(mask.astype(np.uint8), (h / mask.shape[0], w / mask.shape[1]), order=0).astype(bool)


def resize_logits_then_binarize(raw_logits, target_h, target_w, threshold=0.5):
    """[버그수정] 이진화 먼저 -> nearest 확대(경계 뭉개짐) 대신,
    연속값(logit) 상태에서 bilinear로 먼저 확대 -> sigmoid -> 이진화 순서로 처리.
    작은 288x288 model-space 마스크를 원본(수백~수천 px) 크기로 키울 때
    특히 이 순서 차이가 크다 - 병변이 작을수록(dense tissue, malignant lesion 등)
    영향이 커진다."""
    raw_t = torch.from_numpy(raw_logits).float()[None, None]  # (1,1,h,w)
    raw_up = torch.nn.functional.interpolate(
        raw_t, size=(target_h, target_w), mode="bilinear", align_corners=False
    )
    prob_up = torch.sigmoid(raw_up)
    return (prob_up[0, 0] > threshold).numpy()


def build_gt_union(gts, h, w, target_h=None, target_w=None):
    target_h = target_h or h
    target_w = target_w or w
    union = np.zeros((target_h, target_w), dtype=bool)
    for ann in gts:
        gm = decode_gt_mask(ann, h, w)
        if gm is None:
            continue
        if gm.shape != (target_h, target_w):
            gm = resize_mask(gm, target_h, target_w)
        union |= gm.astype(bool)
    return union


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


def evaluate(cfg, model, M, device, split="val", score_threshold=0.5, iou_threshold=0.5, max_images=None, debug_shapes=True, load_sample_list=None):
    root = Path(cfg["data"]["root"])
    split_key = split + "_split"
    split_dir = root / cfg["data"][split_key] if split_key in cfg["data"] else root / split
    with open(split_dir / "_annotations.coco.json") as f:
        coco = json.load(f)

    images = {im["id"]: im for im in coco["images"]}
    cat_id_to_name = {c["id"]: c["name"] for c in coco["categories"]}
    img_to_anns = defaultdict(list)
    for a in coco["annotations"]:
        img_to_anns[a["image_id"]].append(a)

    class_names = list(cat_id_to_name.values())
    resolution = cfg["data"]["resolution"]
    transform = v2.Compose([
        v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
        v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
    ])

    dice_scores = defaultdict(list)
    det_tp = defaultdict(int)
    det_fp = defaultdict(int)
    det_fn = defaultdict(int)
    seg_fp_on_negative = defaultdict(int)
    seg_total_negative = defaultdict(int)

    image_ids = list(images.keys())

    if load_sample_list:
        # [신규] 저장해둔 목록을 그대로 불러와서 완전히 동일한 표본으로 재평가
        with open(load_sample_list) as f:
            record = json.load(f)
        fname_to_id = {v["file_name"]: k for k, v in images.items()}
        image_ids = [fname_to_id[fn] for fn in record["file_names"] if fn in fname_to_id]
        missing = len(record["file_names"]) - len(image_ids)
        print(f"\n[샘플 재사용] {load_sample_list} 에서 {len(image_ids)}장 로드"
              + (f" ({missing}장은 현재 split에 없어 제외)" if missing else ""))
        max_images = None  # 이미 확정된 목록이니 아래 그룹 샘플링 로직 건너뜀

    elif max_images and max_images >= 3:
        groups = {"MAMA-MIA": [], "Duke": [], "AMBL": [], "unknown": []}
        for iid in image_ids:
            fname = str(images[iid].get("file_name", "")).lower()
            if "mamamia" in fname or "mama-mia" in fname or "mama_mia" in fname:
                groups["MAMA-MIA"].append(iid)
            elif "duke" in fname:
                groups["Duke"].append(iid)
            elif "ambl" in fname:
                groups["AMBL"].append(iid)
            else:
                groups["unknown"].append(iid)

        # [수정①] 파일 저장 순서 그대로 앞에서부터 자르면 같은 환자 슬라이스가 연달아 붙어있어
        # 소수 환자로 쏠릴 위험이 있음 -> 소스별로 고정 시드(42)로 섞은 뒤 자름 (결정적 + 대표성 확보)
        rng = __import__("random").Random(42)
        for s in groups:
            groups[s] = sorted(groups[s])  # dict 순서 변동 방지용으로 먼저 정렬
            rng.shuffle(groups[s])

        per_source = max_images // 3
        selected = []
        for s in ("MAMA-MIA", "Duke", "AMBL"):
            selected.extend(groups[s][:per_source])

        used = set(selected)
        for iid in groups["unknown"] + image_ids:
            if len(selected) >= max_images:
                break
            if iid not in used:
                selected.append(iid)
                used.add(iid)
        image_ids = selected[:max_images]

        # [수정②] 이번에 실제로 뽑힌 이미지 목록을 파일로 남김
        # -> 2차 학습 후 재평가할 때 --load-sample-list로 똑같은 150장을 그대로 재사용 가능
        sample_record = {
            "seed": 42,
            "max_images": max_images,
            "file_names": [images[iid]["file_name"] for iid in image_ids],
        }
        sample_log_path = Path("eval_sample_list.json")
        with open(sample_log_path, "w") as f:
            json.dump(sample_record, f, indent=1)
        print(f"\n[샘플 기록] 이번 평가에 쓰인 150장 목록을 저장함: {sample_log_path.resolve()}")
        print("           2차 학습 후 --load-sample-list 로 이 파일을 넘기면 완전히 같은 150장으로 재평가됨")

        print()
        print("=" * 60)
        print("[평가 샘플]")
        print("=" * 60)
        for s in ("MAMA-MIA", "Duke", "AMBL", "unknown"):
            cnt = 0
            for iid in image_ids:
                fn = str(images[iid].get("file_name", "")).lower()
                if s == "unknown":
                    cnt += 1
                elif s == "MAMA-MIA" and ("mamamia" in fn or "mama-mia" in fn or "mama_mia" in fn):
                    cnt += 1
                elif s == "Duke" and "duke" in fn:
                    cnt += 1
                elif s == "AMBL" and "ambl" in fn:
                    cnt += 1
            print(f"  {s:10s}: {cnt}")
    elif max_images:
        image_ids = image_ids[:max_images]

    for n, img_id in enumerate(image_ids):
        info = images[img_id]
        img_path = split_dir / info["file_name"]

        pil = PILImage.open(img_path).convert("RGB")
        orig_w, orig_h = pil.size
        pil_r = pil.resize((resolution, resolution), PILImage.BILINEAR)
        image_tensor = transform(pil_r)

        gt_anns = img_to_anns.get(img_id, [])
        gt_by_class = defaultdict(list)
        for ann in gt_anns:
            gt_by_class[cat_id_to_name[ann["category_id"]]].append(ann)

        for cname in class_names:
            if cname not in SEG_CLASSES and cname not in DET_CLASSES:
                continue

            outputs = run_one_query(model, M, image_tensor, resolution, (orig_w, orig_h), cname, device)

            if debug_shapes and n == 0:
                print()
                print(f"[진단] 첫 이미지, 쿼리='{cname}' 출력 shape")
                for k in ("pred_logits", "pred_boxes", "pred_masks"):
                    if k in outputs:
                        print(f"  {k}: {tuple(outputs[k].shape)}")

            pred_logits = outputs["pred_logits"][0]
            pred_boxes = outputs["pred_boxes"][0]
            pred_masks = outputs.get("pred_masks", None)
            pred_masks = pred_masks[0] if pred_masks is not None else None

            scores = pred_logits.sigmoid().amax(dim=-1).cpu().numpy()
            boxes = pred_boxes.cpu().numpy()
            masks = pred_masks.cpu().numpy() if pred_masks is not None else None

            if debug_shapes and n < 3:
                sweep = " ".join(f">={t:.2f}:{int((scores >= t).sum())}" for t in (0.10, 0.20, 0.30, 0.40, 0.50))
                print(f"  [SCORE] {cname:16s} {sweep}")

            keep = np.where(scores >= score_threshold)[0]
            gts = gt_by_class.get(cname, [])

            if cname in SEG_CLASSES:
                has_pred = masks is not None and keep.size > 0

                if not gts:
                    seg_total_negative[cname] += 1
                    if has_pred:
                        seg_fp_on_negative[cname] += 1

                if has_pred:
                    raw_union_orig = np.zeros((orig_h, orig_w), dtype=bool)
                    for qi in keep:
                        # [버그수정] raw>0 이진화 후 nearest 확대 -> bilinear 확대 후 sigmoid+이진화
                        mask_up = resize_logits_then_binarize(masks[qi], orig_h, orig_w)
                        raw_union_orig |= mask_up

                    if gts:
                        gt_union_orig = build_gt_union(gts, orig_h, orig_w, orig_h, orig_w)
                        raw_orig_dice = dice_score(raw_union_orig, gt_union_orig)
                        dice_scores[cname].append(raw_orig_dice)
                        if debug_shapes and n < 3:
                            print(f"  [DICE] {cname:16s} {raw_orig_dice:.4f}")
                elif gts:
                    dice_scores[cname].append(0.0)

            else:
                if keep.size > 0:
                    nms_local = apply_nms(boxes[keep], scores[keep], iou_threshold=iou_threshold)
                    keep = keep[nms_local]

                gt_boxes_xyxy = []
                for ann in gts:
                    x, y, w, h = ann["bbox"]
                    gt_boxes_xyxy.append((x, y, x + w, y + h))
                matched_gt = set()
                for qi in keep:
                    pbox = cxcywh_to_xyxy_pixel(boxes[qi], orig_w, orig_h)
                    best_iou, best_j = 0.0, -1
                    for j, gbox in enumerate(gt_boxes_xyxy):
                        if j in matched_gt:
                            continue
                        iou = box_iou_xyxy(pbox, gbox)
                        if iou > best_iou:
                            best_iou, best_j = iou, j
                    if best_iou >= iou_threshold:
                        det_tp[cname] += 1
                        matched_gt.add(best_j)
                    else:
                        det_fp[cname] += 1
                det_fn[cname] += len(gt_boxes_xyxy) - len(matched_gt)

        if (n + 1) % 200 == 0:
            print(f"  {n+1}/{len(image_ids)} 이미지 평가 완료")

    print()
    print("=" * 60)
    print("Dice (분할 클래스, 정답 있는 이미지만)")
    print("=" * 60)
    for cname in SEG_CLASSES:
        vals = dice_scores[cname]
        if vals:
            print(f"  {cname:20s}  mean Dice = {np.mean(vals):.4f}  (n={len(vals)})")
        else:
            print(f"  {cname:20s}  평가 대상 없음")

    print()
    print("=" * 60)
    print("분할 클래스 - 정답 없는 이미지에서의 오탐율 (v3 신규)")
    print("=" * 60)
    for cname in SEG_CLASSES:
        neg = seg_total_negative[cname]
        fp = seg_fp_on_negative[cname]
        rate = fp / neg if neg else 0.0
        print(f"  {cname:20s}  {fp}/{neg}  ({rate:.1%})")

    print()
    print("=" * 60)
    print("F1 (검출 클래스, box IoU>=" + f"{iou_threshold:.2f}" + " 기준)")
    print("=" * 60)
    for cname in DET_CLASSES:
        tp, fp, fn = det_tp[cname], det_fp[cname], det_fn[cname]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        print(f"  {cname:20s}  P={precision:.3f} R={recall:.3f} F1={f1:.4f}  (TP={tp} FP={fp} FN={fn})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--score-threshold", type=float, default=0.5)
    ap.add_argument("--iou-threshold", type=float, default=0.5)
    ap.add_argument("--max-images", type=int, default=None)
    ap.add_argument("--load-sample-list", default=None,
                     help="이전 실행에서 저장된 eval_sample_list.json 경로 - 동일 150장으로 재평가")
    args = ap.parse_args()

    cfg = load_config(args.config)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, args.weights, M, device)

    evaluate(
        cfg, model, M, device,
        split=args.split,
        score_threshold=args.score_threshold,
        iou_threshold=args.iou_threshold,
        max_images=args.max_images,
        load_sample_list=args.load_sample_list,
    )


if __name__ == "__main__":
    main()