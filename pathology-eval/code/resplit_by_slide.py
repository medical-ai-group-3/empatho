"""
기존 TIGER tissue-cells 데이터를 슬라이드(환자) 단위로 train/val 재분할.

문제: 기존 방식은 이미지 파일 하나하나를 랜덤 셔플해서 나눴기 때문에,
같은 슬라이드(환자)에서 나온 여러 조각(patch)이 train과 val에 동시에 섞여
들어갈 수 있었음 -> 사실상 "정답을 미리 본 것"과 비슷한 데이터 누수 발생 가능.

해결: 슬라이드 ID를 먼저 추출해서 슬라이드 단위로 셔플 후 분할.
같은 슬라이드에서 나온 이미지는 항상 같은 split(train 또는 val)에만 속하게 됨.

출력 대상: 세포검출(cellvit_detection), 조직분할(tissue_segmentation) 둘 다
동일한 슬라이드 단위 split을 공유하도록 재생성.
"""
import csv
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

VAL_RATIO = 0.15
SEED = 42

TIGER_ROOT = Path.home() / "data/tiger/tissue-cells"
CELLVIT_DST = Path.home() / "data/tiger/cellvit_detection_v2"
TISSUE_SEG_DST = Path.home() / "data/tiger/tissue_segmentation_v2"

REMAP_TISSUE = {0: 0, 1: 1, 2: 2, 3: 1, 4: 0, 5: 0, 6: 2, 7: 0}


def get_slide_id(filename: str) -> str:
    if filename.startswith("TCGA-"):
        parts = filename.split("-")
        return "-".join(parts[:3])
    return filename.split("_[")[0]


def main():
    image_dir = TIGER_ROOT / "images"
    files = list(image_dir.glob("*.png"))
    stems = [f.stem for f in files]

    slide_to_stems = {}
    for stem in stems:
        sid = get_slide_id(stem + ".png")
        slide_to_stems.setdefault(sid, []).append(stem)

    slide_ids = list(slide_to_stems.keys())
    random.Random(SEED).shuffle(slide_ids)
    n_val_slides = max(1, int(len(slide_ids) * VAL_RATIO))
    val_slide_ids = set(slide_ids[:n_val_slides])
    train_slide_ids = slide_ids[n_val_slides:]

    train_stems = [s for sid in train_slide_ids for s in slide_to_stems[sid]]
    val_stems = [s for sid in val_slide_ids for s in slide_to_stems[sid]]

    print(f"전체 슬라이드: {len(slide_ids)}, train 슬라이드: {len(train_slide_ids)}, val 슬라이드: {len(val_slide_ids)}")
    print(f"전체 이미지: {len(stems)}, train 이미지: {len(train_stems)}, val 이미지: {len(val_stems)}")

    overlap = set(get_slide_id(s + ".png") for s in train_stems) & set(get_slide_id(s + ".png") for s in val_stems)
    assert len(overlap) == 0, f"슬라이드 겹침 발견: {overlap}"
    print("슬라이드 겹침 없음 확인됨")

    coco_labels_dir_train = TIGER_ROOT.parent / "cellvit_detection" / "train" / "labels_til_only_backup"
    if not coco_labels_dir_train.exists():
        print("경고: 기존 TIL 원본 라벨 백업을 못 찾음. 세포검출 재구성은 생략합니다.")
    else:
        for split, split_stems in (("train", train_stems), ("test", val_stems)):
            (CELLVIT_DST / split / "images").mkdir(parents=True, exist_ok=True)
            (CELLVIT_DST / split / "labels").mkdir(parents=True, exist_ok=True)
            for stem in split_stems:
                src_img = image_dir / f"{stem}.png"
                dst_img = CELLVIT_DST / split / "images" / f"{stem}.png"
                if src_img.exists():
                    shutil.copyfile(src_img, dst_img)
                src_label = coco_labels_dir_train / f"{stem}.csv"
                if not src_label.exists():
                    src_label = TIGER_ROOT.parent / "cellvit_detection" / "test" / "labels_til_only_backup" / f"{stem}.csv"
                dst_label = CELLVIT_DST / split / "labels" / f"{stem}.csv"
                if src_label.exists():
                    shutil.copyfile(src_label, dst_label)

        (CELLVIT_DST / "splits" / "fold_0").mkdir(parents=True, exist_ok=True)
        with open(CELLVIT_DST / "splits" / "fold_0" / "train.csv", "w", newline="") as f:
            writer = csv.writer(f)
            for s in train_stems:
                writer.writerow([s])
        with open(CELLVIT_DST / "splits" / "fold_0" / "val.csv", "w", newline="") as f:
            writer = csv.writer(f)
            for s in val_stems:
                writer.writerow([s])
        print(f"세포검출용 재구성 완료: {CELLVIT_DST}")

    mask_dir = TIGER_ROOT / "masks"
    for split, split_stems in (("train", train_stems), ("val", val_stems)):
        (TISSUE_SEG_DST / split / "images").mkdir(parents=True, exist_ok=True)
        (TISSUE_SEG_DST / split / "masks").mkdir(parents=True, exist_ok=True)
        for stem in split_stems:
            src_img = image_dir / f"{stem}.png"
            src_mask = mask_dir / f"{stem}.png"
            if not src_img.exists() or not src_mask.exists():
                continue
            shutil.copyfile(src_img, TISSUE_SEG_DST / split / "images" / f"{stem}.png")
            mask = np.array(Image.open(src_mask))
            out = np.zeros_like(mask, dtype=np.uint8)
            for orig_val, new_val in REMAP_TISSUE.items():
                out[mask == orig_val] = new_val
            Image.fromarray(out).save(TISSUE_SEG_DST / split / "masks" / f"{stem}.png")

    print(f"조직분할용 재구성 완료: {TISSUE_SEG_DST}")


if __name__ == "__main__":
    main()
