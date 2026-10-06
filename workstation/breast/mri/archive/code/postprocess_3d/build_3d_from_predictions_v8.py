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

_BREAST_ROOT = Path(__file__).resolve().parents[2]
if str(_BREAST_ROOT) not in sys.path:
    sys.path.insert(0, str(_BREAST_ROOT))
from breast.mri.postprocess_3d.build_coco_from_npy import build_rgb_2phase, build_rgb_1phase  # noqa: E402

from eval_mri_lora_v3 import (
    load_config,
    import_medsam3,
    build_model,
    run_one_query,
    resize_logits_then_binarize,
    SEG_CLASSES,
)
from compute_stage1_metrics import summarize_lesions

MASK_PIXEL_THRESHOLD = 0.5
MIN_VOXELS = 30
MIN_CONTIGUOUS_SLICES = 2
CLASSES_TODAY = sorted(SEG_CLASSES)

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


def infer_slice_mask(model, M, image_tensor, resolution, orig_size, class_name, device, score_threshold):
    orig_w, orig_h = orig_size
    outputs = run_one_query(model, M, image_tensor, resolution, orig_size, class_name, device)
    pred_logits = outputs["pred_logits"][0]
    pred_masks = outputs.get("pred_masks", None)
    pred_masks = pred_masks[0] if pred_masks is not None else None
    scores = pred_logits.sigmoid().amax(dim=-1).cpu().numpy()
    masks = pred_masks.cpu().numpy() if pred_masks is not None else None
    keep = np.where(scores >= score_threshold)[0]
    mask_2d = np.zeros((orig_h, orig_w), dtype=bool)
    if masks is not None and keep.size > 0:
        for qi in keep:
            mask_up = resize_logits_then_binarize(
                masks[qi], orig_h, orig_w, threshold=MASK_PIXEL_THRESHOLD
            )
            mask_2d |= mask_up
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


def filter_false_positives(mask_3d, min_voxels=MIN_VOXELS, min_contiguous_slices=MIN_CONTIGUOUS_SLICES):
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
    return filtered


def run_pipeline_for_patient(model, M, device, resolution, rgb_slices, pid, dataset_tag,
                              tumor_threshold, seg_threshold):
    classes = ["tumor", "breast"] if dataset_tag == "mamamia" else ["breast", "dense tissue"]
    # [v8] tumor(검출류)와 breast/dense tissue(분할류)를 다른 threshold로 분리.
    # breast가 tumor와 같은 0.7을 쓰면 좌우 유방 중 한쪽이 통째로 오탐필터에 걸려
    # 사라지는 문제를 확인함(20개->1개) - breast/dense tissue는 더 낮은 threshold 사용.
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
        print(f"[{pid}/tumor] 오탐 필터링...")
        filtered_tumor = filter_false_positives(mask_3d)

        print(f"[{pid}/breast] 오탐 필터링 (유두 근사용 - 작은 노이즈가 '가장 전방' 판정을 왜곡할 수 있음)...")
        filtered_breast = filter_false_positives(class_volumes["breast"], min_voxels=MIN_VOXELS, min_contiguous_slices=1)
        breast_mask_bool = filtered_breast.astype(bool)
        if breast_mask_bool.sum() == 0:
            print(f"[{pid}] breast 예측이 비어있어 위치(사분면/유두거리) 계산 생략")
            breast_mask_bool = None

        rows, n = summarize_lesions(filtered_tumor, pid, "tumor", breast_mask=breast_mask_bool)
        n_with_location = sum(1 for r in rows if r.get("nipple_distance_mm") is not None)
        print(f"[{pid}/tumor] 병변 {n}개 검출, 위치(사분면/유두거리) 계산됨 {n_with_location}개")
        print(f"  ⚠ 주의: 축 방향(상하/전후) 가정은 MAMA-MIA 소스에서 별도 실측 검증 안 됨. "
              f"발표/보고 전 Slicer로 1건은 눈으로 재확인 권장.")
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
        args.score_threshold, args.seg_score_threshold
    )

    save_results(lesion_rows, density_row, args.out)


if __name__ == "__main__":
    main()
