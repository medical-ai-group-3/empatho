#!/usr/bin/env python3
"""
[v7 - 위치(사분면/유두거리) 재설계]
v6 대비 변경점:
  어제 위치 지표(사분면/유두거리)가 실패한 이유: 서로 다른 두 프로젝트(MAMA-MIA tumor
  라벨 vs Duke breast 라벨)의 파일을 환자번호로 "빌려와서" 섞어 썼더니 좌표계가 어긋남.

  해결: 다른 파일을 안 빌려온다. MAMA-MIA 환자 볼륨 자체에 "breast" 쿼리도 같이 던져서,
  그 환자 자신의 유방 윤곽을 그 자리에서 예측한다. tumor와 breast가 "같은 볼륨, 같은
  좌표계"에서 나오므로 어제 같은 좌표계 불일치가 구조적으로 생길 수 없다.

  단, 이게 좌표축(어느 축이 상하/전후인지) 가정 자체를 검증해주진 않는다 - 그건 별도로
  MAMA-MIA 소스 환자 한 명을 Slicer로 다시 확인해야 함(어제는 Duke 소스로 시도했다가
  교차 데이터셋 문제로 실패해서 축 가정 자체는 여전히 미검증 상태).
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image as PILImage
from scipy import ndimage
from torchvision.transforms import v2

# build_coco_from_npy.py가 이 파일과 같은 폴더(postprocess_3d/code/)에 있으므로
# 별도 sys.path 조작 없이 바로 import 가능 (2026-08-31 폴더 재정리 후 확인)
from build_coco_from_npy import build_rgb_2phase, build_rgb_1phase  # noqa: E402

from eval_mri_lora_v3 import (
    load_config,
    import_medsam3,
    build_model,
    run_one_query,
    resize_logits_then_binarize,
    SEG_CLASSES,
)
from compute_stage1_metrics import summarize_lesions, find_body_silhouette_mask

MASK_PIXEL_THRESHOLD = 0.5
MIN_VOXELS = 30
MIN_CONTIGUOUS_SLICES = 2
CLASSES_TODAY = sorted(SEG_CLASSES)

# [2026-08-31 추가] 납작한 시트형 오탐 필터 기준값.
# ISPY2_242370 tumor 메시를 Slicer로 육안 확인 -> JSON 메시 connected component 분석 결과,
# 실제 병변(둥근 덩어리, bbox 17x19x15mm, min/max=0.79)과 시트형 오탐 6개(min/max=0.02~0.28)
# 사이에 격차가 커서 이 값으로 일단 구분 가능. 단 환자 1명 실측이므로 여러 건 더 검증 후 확정할 것.
# ★ tumor(및 향후 benign/malignant lesion)에만 적용한다 - breast/dense tissue는 원래
#   흉벽 방향으로 눌린 납작한 해부학적 구조라 이 기준을 적용하면 정상 조직이 잘려나간다.
MIN_ASPECT_RATIO = 0.3
MIN_THIN_AXIS_MM = 4.0
FLAT_FILTER_ELIGIBLE_CLASSES = {"tumor", "malignant lesion", "benign lesion"}

TRANSFORM = v2.Compose([
    v2.ToImage(),
    v2.ToDtype(torch.float32, scale=True),
    v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
])


def check_val_membership(coco_root: Path, pid: str) -> str:
    needle = f"{pid.lower()}_z"
    for split in ("val", "train"):
        json_path = coco_root / split / "_annotations.coco.json"
        if not json_path.exists():
            continue
        with open(json_path) as f:
            coco = json.load(f)
        if any(needle in im["file_name"].lower() for im in coco["images"]):
            return split
    return "unknown"


def find_patient_volume(mama_mia_dir: Path, duke_dir: Path, pid: str):
    mama_path = mama_mia_dir / "images" / f"{pid}.npy"
    duke_path = duke_dir / "images" / f"{pid}.npy"
    if mama_path.exists():
        return np.load(mama_path), "mamamia"
    if duke_path.exists():
        return np.load(duke_path), "duke"
    raise FileNotFoundError(
        f"'{pid}.npy'를 mama-mia-dir, duke-dir 어느 쪽에서도 못 찾음."
    )


def volume_to_rgb_slices(img: np.ndarray, dataset_tag: str):
    n_z = img.shape[1]
    slices = []
    for z in range(n_z):
        if dataset_tag == "mamamia":
            rgb = build_rgb_2phase(img[0, z], img[1, z])
        elif dataset_tag == "duke":
            rgb = build_rgb_1phase(img[0, z])
        else:
            raise ValueError(f"알 수 없는 dataset_tag: {dataset_tag}")
        slices.append(rgb)
    return slices


def rgb_array_to_tensor(rgb: np.ndarray, resolution: int):
    pil = PILImage.fromarray(rgb).convert("RGB")
    orig_w, orig_h = pil.size
    pil_r = pil.resize((resolution, resolution), PILImage.BILINEAR)
    image_tensor = TRANSFORM(pil_r)
    return image_tensor, (orig_w, orig_h)


def infer_slice_mask(model, M, image_tensor, resolution, orig_size, class_name, device, score_threshold,
                     mask_pixel_threshold=MASK_PIXEL_THRESHOLD, return_score_map=False):
    """[2026-09-29] mask_pixel_threshold / return_score_map 인자 추가 — 기본값이면 기존과 동일.
    return_score_map=True면 (mask_2d, score_map)을 반환한다. score_map은 각 픽셀을 덮는
    쿼리들(score_threshold 통과분) 중 최대 쿼리 점수(float32, 안 덮인 픽셀은 0). 병변별
    점수 요약(serving predict의 score_max/score_mean)에 쓴다 — 기존엔 OR로 합치면서 버려졌다."""
    orig_w, orig_h = orig_size
    outputs = run_one_query(model, M, image_tensor, resolution, orig_size, class_name, device)
    pred_logits = outputs["pred_logits"][0]
    pred_masks = outputs.get("pred_masks", None)
    pred_masks = pred_masks[0] if pred_masks is not None else None
    scores = pred_logits.sigmoid().amax(dim=-1).cpu().numpy()
    masks = pred_masks.cpu().numpy() if pred_masks is not None else None
    keep = np.where(scores >= score_threshold)[0]
    mask_2d = np.zeros((orig_h, orig_w), dtype=bool)
    score_map = np.zeros((orig_h, orig_w), dtype=np.float32) if return_score_map else None
    if masks is not None and keep.size > 0:
        for qi in keep:
            mask_up = resize_logits_then_binarize(
                masks[qi], orig_h, orig_w, threshold=mask_pixel_threshold
            )
            mask_2d |= mask_up
            if score_map is not None:
                score_map[mask_up] = np.maximum(score_map[mask_up], float(scores[qi]))
    if return_score_map:
        return mask_2d, score_map
    return mask_2d


def run_inference_for_patient(model, M, device, resolution, rgb_slices, classes, thresholds: dict):
    volumes = {cname: [] for cname in classes}
    with torch.no_grad():
        for rgb in rgb_slices:
            image_tensor, orig_size = rgb_array_to_tensor(rgb, resolution)
            for cname in classes:
                mask_2d = infer_slice_mask(model, M, image_tensor, resolution, orig_size, cname, device, thresholds[cname])
                volumes[cname].append(mask_2d)
    return {cname: np.stack(slices, axis=0).astype(np.uint8) for cname, slices in volumes.items()}


def filter_false_positives(mask_3d, min_voxels=MIN_VOXELS, min_contiguous_slices=MIN_CONTIGUOUS_SLICES,
                           return_stats=False):
    """[2026-09-29] return_stats=True면 (filtered, stats)를 반환 — 기존엔 print로만 남던
    제거 개수를 서빙 응답(filter_stats)에 싣기 위해. 기본값이면 기존과 동일."""
    structure = np.ones((3, 3, 3), dtype=int)  # 26-connectivity, compute_stage1_metrics.py와 통일
    labeled, n_components = ndimage.label(mask_3d, structure=structure)
    filtered = np.zeros_like(mask_3d)
    kept, dropped_size, dropped_span = 0, 0, 0
    for comp_id in range(1, n_components + 1):
        coords = np.argwhere(labeled == comp_id)
        n_voxels = coords.shape[0]
        if n_voxels < min_voxels:
            dropped_size += 1
            continue
        z_indices = coords[:, 0]
        slice_span = z_indices.max() - z_indices.min() + 1
        if slice_span < min_contiguous_slices:
            dropped_span += 1
            continue
        filtered[labeled == comp_id] = 1
        kept += 1
    print(f"  [오탐필터] 전체 {n_components}개 -> 통과 {kept}개 "
          f"(크기미달 제거 {dropped_size}, 슬라이스연속미달 제거 {dropped_span})")
    if return_stats:
        return filtered, {"candidates": int(n_components), "dropped_small": dropped_size,
                          "dropped_short_span": dropped_span}
    return filtered


def filter_flat_artifacts(mask_3d, voxel_spacing=(1.0, 1.0, 1.0),
                           min_aspect_ratio=MIN_ASPECT_RATIO,
                           min_thin_axis_mm=MIN_THIN_AXIS_MM, return_stats=False):
    """
    [2026-09-29] return_stats=True면 (cleaned, {"dropped_flat": n})을 반환. 기본값이면 기존과 동일.

    filter_false_positives(복셀 수 + 슬라이스 연속성)를 통과한 뒤에도 남는,
    Z축으로 안 이어지고 납작한 시트 모양인 오탐을 제거한다.

    2D 슬라이스 단위로 예측한 마스크가 인접 슬라이스와 일관성 없이 쌓이면
    "한 축만 얇고 나머지 두 축으로 넓게 퍼진" 성분이 생긴다. 실제 병변은
    대체로 등방형(구형/타원체)에 가까우므로 bbox 세 축 비율로 구분한다.

    ★ 호출하는 쪽에서 반드시 FLAT_FILTER_ELIGIBLE_CLASSES에 해당하는 클래스에만
      적용할 것 - breast/dense tissue는 원래 납작한 구조라 여기 걸면 안 됨.
    """
    if mask_3d.sum() == 0:
        return (mask_3d, {"dropped_flat": 0}) if return_stats else mask_3d

    structure = np.ones((3, 3, 3), dtype=int)  # filter_false_positives와 동일 26-connectivity
    labeled, n_components = ndimage.label(mask_3d, structure=structure)
    if n_components == 0:
        return (mask_3d, {"dropped_flat": 0}) if return_stats else mask_3d

    cleaned = np.zeros_like(mask_3d)
    kept, dropped = 0, 0
    for comp_id, slc in enumerate(ndimage.find_objects(labeled), start=1):
        if slc is None:
            continue
        comp = (labeled[slc] == comp_id)
        dims_mm = np.array([
            comp.shape[0] * voxel_spacing[0],
            comp.shape[1] * voxel_spacing[1],
            comp.shape[2] * voxel_spacing[2],
        ])
        min_dim, max_dim = dims_mm.min(), dims_mm.max()
        aspect_ratio = (min_dim / max_dim) if max_dim > 0 else 0.0

        if min_dim < min_thin_axis_mm or aspect_ratio < min_aspect_ratio:
            dropped += 1
            continue

        cleaned[slc][comp] = 1
        kept += 1

    print(f"  [납작형오탐필터] 성분 {n_components}개 -> 통과 {kept}개 (시트형 제거 {dropped})")
    if return_stats:
        return cleaned.astype(mask_3d.dtype), {"dropped_flat": dropped}
    return cleaned.astype(mask_3d.dtype)


def run_pipeline_for_patient(model, M, device, resolution, rgb_slices, pid, dataset_tag,
                              tumor_threshold, seg_threshold, raw_img=None,
                              apply_flat_filter=True):
    # [v9] mamamia는 더 이상 breast 쿼리를 안 던진다 - breast 모델이 MAMA-MIA에서
    # 불안정(22조각)했던 문제를 근본적으로 피하기 위해, 명암 기반 몸통 윤곽(모델 불필요)으로 대체.
    classes = ["tumor"] if dataset_tag == "mamamia" else ["breast", "dense tissue"]
    thresholds = {}
    if "tumor" in classes:
        thresholds["tumor"] = tumor_threshold
    if "breast" in classes:
        thresholds["breast"] = seg_threshold
    if "dense tissue" in classes:
        thresholds["dense tissue"] = seg_threshold

    print(f"[{pid}] ({dataset_tag}) 전체 슬라이스 {len(rgb_slices)}장, 클래스 {classes} 추론 중 "
          f"(threshold: {thresholds})...")
    class_volumes = run_inference_for_patient(model, M, device, resolution, rgb_slices, classes, thresholds)

    lesion_rows = []
    density_row = None

    if dataset_tag == "mamamia":
        mask_3d = class_volumes["tumor"]
        print(f"[{pid}/tumor] 오탐 필터링 (복셀 수 + 슬라이스 연속성)...")
        filtered_tumor = filter_false_positives(mask_3d)

        if apply_flat_filter:
            print(f"[{pid}/tumor] 오탐 필터링 (납작한 시트형 성분 추가 제거)...")
            filtered_tumor = filter_flat_artifacts(filtered_tumor)

        print(f"[{pid}] 명암 기반 몸통 윤곽 추출 중 (breast 모델 대신, 소스 무관하게 항상 작동)...")
        body_mask_bool = None
        if raw_img is not None:
            body_mask_bool = find_body_silhouette_mask(raw_img[0])  # raw_img[0] = pre-contrast 채널
            if body_mask_bool is None:
                print(f"[{pid}] 몸통 윤곽 추출 실패(임계값 미달) - 위치 계산 생략")
        else:
            print(f"[{pid}] raw_img 없음 - 위치 계산 생략")

        rows, n = summarize_lesions(filtered_tumor, pid, "tumor", breast_mask=body_mask_bool)
        n_with_location = sum(1 for r in rows if r.get("nipple_distance_mm") is not None)
        print(f"[{pid}/tumor] 병변 {n}개 검출, 위치(사분면/유두거리) 계산됨 {n_with_location}개")
        print(f"  ⚠ 주의: 축 방향(상하/전후) 가정 자체는 여전히 별도 실측 검증 안 됨. "
              f"몸통윤곽 방식은 breast 모델 불안정 문제만 해결한 것 - 발표/보고 전 Slicer 1건 재확인 권장.")
        lesion_rows.extend(rows)

    else:  # duke
        # [진단 추가] MAMA-MIA에서 breast가 22조각으로 쪼개진 것과 비교하기 위해
        # Duke(breast 학습에 실제 쓰인 소스)에서는 몇 조각인지 확인
        structure = np.ones((3, 3, 3), dtype=int)
        _, n_breast_components = ndimage.label(class_volumes["breast"], structure=structure)
        print(f"[{pid}/breast] connected component 개수(필터 전): {n_breast_components}개 "
              f"(정상이면 좌우 2개 근처, MAMA-MIA에서는 22개였음 - 비교용)")

        breast_vox = int(class_volumes["breast"].sum())
        dense_vox = int(class_volumes["dense tissue"].sum())
        if breast_vox > 0:
            density_row = {
                "patient_id": pid,
                "breast_voxels": breast_vox,
                "dense_voxels": dense_vox,
                "dense_density_pct": round(dense_vox / breast_vox * 100, 2),
                "breast_components_unfiltered": n_breast_components,
            }
            print(f"[{pid}] 밀도비율(예측 기반): {density_row['dense_density_pct']}%")
        else:
            print(f"[{pid}] breast mask가 비어있어 밀도비율 계산 불가")

    return lesion_rows, density_row


def save_results(lesion_rows, density_row, out_path: Path):
    out_root = out_path.parent
    out_root.mkdir(parents=True, exist_ok=True)
    base = out_path.stem
    if lesion_rows:
        df_lesions = pd.DataFrame(lesion_rows)
        df_lesions.to_csv(out_root / f"{base}_lesions.csv", index=False)
        print(f"\n병변별 상세: {out_root / (base + '_lesions.csv')} ({len(df_lesions)}행)")
    if density_row:
        df_density = pd.DataFrame([density_row])
        df_density.to_csv(out_root / f"{base}_density.csv", index=False)
        print(f"밀도비율: {out_root / (base + '_density.csv')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--mama-mia-dir", required=True, type=Path)
    ap.add_argument("--duke-dir", required=True, type=Path)
    ap.add_argument("--coco-root", required=True, type=Path)
    ap.add_argument("--pid", required=True)
    ap.add_argument("--out", default="stage3d_test.csv", type=Path)
    ap.add_argument("--score-threshold", type=float, default=0.7,
                     help="tumor(검출류)용. 높일수록 오탐 감소(대신 진짜 병변도 놓칠 위험)")
    ap.add_argument("--seg-score-threshold", type=float, default=0.5,
                     help="breast/dense tissue(분할류)용. tumor보다 낮게 - 큰 구조물은 threshold를 "
                          "tumor와 같이 높게 잡으면 좌우 유방 중 한쪽이 통째로 걸러지는 문제 확인됨")
    ap.add_argument("--skip-flat-filter", action="store_true",
                     help="디버깅용 - tumor 경로의 시트형 오탐 필터를 끄고 원본 그대로 지표 계산")
    args = ap.parse_args()

    args.mama_mia_dir = args.mama_mia_dir.resolve()
    args.duke_dir = args.duke_dir.resolve()
    args.coco_root = args.coco_root.resolve()
    args.out = args.out.resolve()
    args.config = str(Path(args.config).resolve())
    args.weights = str(Path(args.weights).resolve())

    split = check_val_membership(args.coco_root, args.pid)
    if split == "train":
        print(f"[WARN] '{args.pid}'는 train split 환자입니다. Enter로 계속, Ctrl+C로 취소")
        input()
    elif split == "unknown":
        print(f"[WARN] '{args.pid}'가 COCO train/val 어디에도 안 잡힘 - 오탐 검증용으로는 적합할 수 있음")
    else:
        print(f"[확인] '{args.pid}' -> {split} split 환자")

    cfg = load_config(args.config)
    resolution = cfg["data"]["resolution"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, args.weights, M, device)

    img, dataset_tag = find_patient_volume(args.mama_mia_dir, args.duke_dir, args.pid)
    rgb_slices = volume_to_rgb_slices(img, dataset_tag)

    lesion_rows, density_row = run_pipeline_for_patient(
        model, M, device, resolution, rgb_slices, args.pid, dataset_tag,
        args.score_threshold, args.seg_score_threshold, raw_img=img,
        apply_flat_filter=not args.skip_flat_filter,
    )

    save_results(lesion_rows, density_row, args.out)


if __name__ == "__main__":
    main()