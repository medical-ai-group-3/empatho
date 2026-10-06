"""
3D npy(전처리 완료) -> 2D COCO 포맷 변환 스크립트
초음파 학습 코드(train_us_lora.py)의 USCocoDataset이 그대로 읽을 수 있는 구조로 저장한다.

이미지 채널 구성 (RGB 3채널):
  - MAMA-MIA(종양), AMBL(양성/악성): R=조영전, G=조영후, B=조영후-조영전(차분)
  - Duke(밀도): pre-contrast 단일 채널만 있으므로 R=G=B=그 채널(그레이스케일)

라벨 -> 텍스트 쿼리 매핑:
  - MAMA-MIA: {1} -> "tumor"
  - Duke:     채널0(breast)=1 -> "breast", 채널1(dense_vessels)=2 -> "dense tissue"
  - AMBL:     {1} -> "benign lesion", {2} -> "malignant lesion"

출력 구조 (train_us_lora.py의 USCocoDataset이 기대하는 형식):
  <out>/train/_annotations.coco.json + *.png
  <out>/val/_annotations.coco.json + *.png

실행 전 설치: pip install numpy opencv-python-headless pillow --break-system-packages

사용법:
    python build_coco_from_npy.py \
        --mama-mia-dir data/mri/mama_mia_processed \
        --duke-dir data/mri/duke_density_processed \
        --ambl-dir data/mri/ambl_processed \
        --out data/mri/coco_2d \
        --val-ratio 0.15
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


CLIP_RANGE = (-3.0, 3.0)  # z-score 클리핑 범위 (전 데이터셋 공통 - 대비 일관성 유지)
DIFF_CLIP_RANGE = (-2.0, 2.0)


def to_uint8(arr, clip_range):
    lo, hi = clip_range
    arr = np.clip(arr, lo, hi)
    arr = (arr - lo) / (hi - lo) * 255.0
    return arr.astype(np.uint8)


def mask_to_coco_annotations(mask: np.ndarray, category_id: int, ann_id_start: int, image_id: int, min_area: int = 20):
    """이진 마스크 -> COCO annotation 리스트(폴리곤 기반). connected component별로 분리."""
    anns = []
    ann_id = ann_id_start
    num_labels, labels = cv2.connectedComponents(mask.astype(np.uint8))
    for lbl in range(1, num_labels):
        comp = (labels == lbl).astype(np.uint8)
        if comp.sum() < min_area:  # 너무 작은 잡음/파편 성분 제외 (Duke dense tissue 파편화 방지)
            continue
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        if len(contour) < 3:
            continue
        segmentation = contour.flatten().tolist()
        x, y, w, h = cv2.boundingRect(contour)
        anns.append({
            "id": ann_id,
            "image_id": image_id,
            "category_id": category_id,
            "segmentation": [segmentation],
            "bbox": [x, y, w, h],
            "area": float(comp.sum()),
            "iscrowd": 0,
        })
        ann_id += 1
    return anns, ann_id


def build_rgb_2phase(pre_slice, post_slice):
    diff = post_slice - pre_slice
    r = to_uint8(pre_slice, CLIP_RANGE)
    g = to_uint8(post_slice, CLIP_RANGE)
    b = to_uint8(diff, DIFF_CLIP_RANGE)
    return np.stack([r, g, b], axis=-1)


def build_rgb_1phase(slice_arr):
    gray = to_uint8(slice_arr, CLIP_RANGE)
    return np.stack([gray, gray, gray], axis=-1)


def process_mamamia(mama_dir: Path, out_dir: Path, categories: dict, state: dict, val_ratio: float, rng: random.Random):
    images_dir = mama_dir / "images"
    labels_dir = mama_dir / "labels"
    patient_files = sorted(images_dir.glob("*.npy"))
    patients = [p.stem for p in patient_files if (labels_dir / f"{p.stem}.npy").exists()]
    rng.shuffle(patients)
    n_val = int(len(patients) * val_ratio)
    val_set = set(patients[:n_val])

    cat_id = categories["tumor"]

    for pid in patients:
        split = "val" if pid in val_set else "train"
        img = np.load(images_dir / f"{pid}.npy")  # (2,Z,Y,X)
        lbl = np.load(labels_dir / f"{pid}.npy")  # (Z,Y,X)
        n_z = img.shape[1]
        for z in range(n_z):
            mask = (lbl[z] == 1).astype(np.uint8)
            if mask.sum() < 5:
                continue
            rgb = build_rgb_2phase(img[0, z], img[1, z])
            _save_slice(out_dir, split, "mamamia", pid, z, rgb, [(mask, cat_id)], state)


def process_duke(duke_dir: Path, out_dir: Path, categories: dict, state: dict, val_ratio: float, rng: random.Random):
    images_dir = duke_dir / "images"
    labels_dir = duke_dir / "labels"
    patient_files = sorted(images_dir.glob("*.npy"))
    patients = [p.stem for p in patient_files if (labels_dir / f"{p.stem}.npy").exists()]
    skipped_no_label = [p.stem for p in patient_files if not (labels_dir / f"{p.stem}.npy").exists()]
    if skipped_no_label:
        print(f"      경고: images엔 있는데 labels 없는 환자 {len(skipped_no_label)}명 스킵 - {skipped_no_label}")
    rng.shuffle(patients)
    n_val = int(len(patients) * val_ratio)
    val_set = set(patients[:n_val])

    breast_cat = categories["breast"]
    dense_cat = categories["dense tissue"]

    for pid in patients:
        split = "val" if pid in val_set else "train"
        img = np.load(images_dir / f"{pid}.npy")  # (1,Z,Y,X)
        lbl = np.load(labels_dir / f"{pid}.npy")  # (2,Z,Y,X): ch0=breast(0/1), ch1=dense_vessels(0/1/2)
        n_z = img.shape[1]
        for z in range(n_z):
            breast_mask = (lbl[0, z] == 1).astype(np.uint8)
            dense_mask = (lbl[1, z] == 2).astype(np.uint8)
            if breast_mask.sum() < 5 and dense_mask.sum() < 5:
                continue
            rgb = build_rgb_1phase(img[0, z])
            masks = []
            if breast_mask.sum() >= 5:
                masks.append((breast_mask, breast_cat))
            if dense_mask.sum() >= 5:
                masks.append((dense_mask, dense_cat))
            _save_slice(out_dir, split, "duke", pid, z, rgb, masks, state)


def process_ambl(ambl_dir: Path, out_dir: Path, categories: dict, state: dict, val_ratio: float, rng: random.Random):
    images_dir = ambl_dir / "images"
    labels_dir = ambl_dir / "labels"
    patient_files = sorted(images_dir.glob("*.npy"))
    patients = [p.stem for p in patient_files if (labels_dir / f"{p.stem}.npy").exists()]
    rng.shuffle(patients)
    n_val = int(len(patients) * val_ratio)
    val_set = set(patients[:n_val])

    benign_cat = categories["benign lesion"]
    malignant_cat = categories["malignant lesion"]

    for pid in patients:
        split = "val" if pid in val_set else "train"
        img = np.load(images_dir / f"{pid}.npy")  # (2,Z,Y,X) - AMBL은 Z가 axis1이지만 크기만 다를 뿐 위치는 동일
        lbl = np.load(labels_dir / f"{pid}.npy")  # (Z,Y,X): 0=bg,1=benign,2=malignant
        n_z = img.shape[1]
        for z in range(n_z):
            benign_mask = (lbl[z] == 1).astype(np.uint8)
            malignant_mask = (lbl[z] == 2).astype(np.uint8)
            if benign_mask.sum() < 5 and malignant_mask.sum() < 5:
                continue
            rgb = build_rgb_2phase(img[0, z], img[1, z])
            masks = []
            if benign_mask.sum() >= 5:
                masks.append((benign_mask, benign_cat))
            if malignant_mask.sum() >= 5:
                masks.append((malignant_mask, malignant_cat))
            _save_slice(out_dir, split, "ambl", pid, z, rgb, masks, state)


def _save_slice(out_dir, split, dataset_tag, pid, z, rgb, mask_cat_pairs, state):
    coco = state[split]
    img_id = state["next_image_id"]
    state["next_image_id"] += 1

    fname = f"{dataset_tag}_{pid}_z{z:04d}.png"
    split_dir = out_dir / split
    split_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(split_dir / fname)

    h, w = rgb.shape[0], rgb.shape[1]
    coco["images"].append({"id": img_id, "file_name": fname, "width": w, "height": h})

    for mask, cat_id in mask_cat_pairs:
        anns, state["next_ann_id"] = mask_to_coco_annotations(mask, cat_id, state["next_ann_id"], img_id)
        coco["annotations"].extend(anns)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mama-mia-dir", required=True)
    ap.add_argument("--duke-dir", required=True)
    ap.add_argument("--ambl-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-ratio", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    category_names = ["tumor", "breast", "dense tissue", "benign lesion", "malignant lesion"]
    categories = {name: i + 1 for i, name in enumerate(category_names)}
    coco_categories = [{"id": cid, "name": name} for name, cid in categories.items()]

    state = {
        "train": {"images": [], "annotations": [], "categories": coco_categories},
        "val": {"images": [], "annotations": [], "categories": coco_categories},
        "next_image_id": 0,
        "next_ann_id": 0,
    }

    print("[1/3] MAMA-MIA 처리 중...")
    process_mamamia(Path(args.mama_mia_dir), out_dir, categories, state, args.val_ratio, rng)
    print(f"      누적 이미지 {state['next_image_id']}장")

    print("[2/3] Duke 밀도 처리 중...")
    process_duke(Path(args.duke_dir), out_dir, categories, state, args.val_ratio, rng)
    print(f"      누적 이미지 {state['next_image_id']}장")

    print("[3/3] AMBL 처리 중...")
    process_ambl(Path(args.ambl_dir), out_dir, categories, state, args.val_ratio, rng)
    print(f"      누적 이미지 {state['next_image_id']}장")

    for split in ["train", "val"]:
        with open(out_dir / split / "_annotations.coco.json", "w") as f:
            json.dump(state[split], f)
        print(f"{split}: 이미지 {len(state[split]['images'])}장, "
              f"어노테이션 {len(state[split]['annotations'])}개")

    print(f"\n출력 위치: {out_dir}")


if __name__ == "__main__":
    main()