"""
TIGER tissue-cells masks (7클래스: 0=배경, 1=침습성종양, 2=종양연관간질, 3=상피내암,
4=정상선조직, 5=괴사, 6=염증성간질, 7=나머지)를
3클래스(0=기타, 1=종양, 2=간질)로 리매핑.

종양 = {1, 3}
간질 = {2, 6}
기타 = {0, 4, 5, 7}

결과는 ~/data/tiger/tissue_segmentation/{train,val}/{images,masks} 구조로 저장.
train/val split은 tissue-cells 변환 때 썼던 것과 동일한 시드로 재현.
"""
import os
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

SRC_ROOT = Path.home() / "data/tiger/tissue-cells"
DST_ROOT = Path.home() / "data/tiger/tissue_segmentation"
VAL_RATIO = 0.15
SEED = 42

# 원본 클래스 -> 새 클래스 매핑
REMAP = {
    0: 0,  # 배경 -> 기타
    1: 1,  # 침습성 종양 -> 종양
    2: 2,  # 종양연관 간질 -> 간질
    3: 1,  # 상피내암 -> 종양
    4: 0,  # 정상 선조직 -> 기타
    5: 0,  # 괴사 -> 기타
    6: 2,  # 염증성 간질 -> 간질
    7: 0,  # 나머지 -> 기타
}


def remap_mask(mask: np.ndarray) -> np.ndarray:
    out = np.zeros_like(mask, dtype=np.uint8)
    for orig_val, new_val in REMAP.items():
        out[mask == orig_val] = new_val
    return out


def main():
    image_dir = SRC_ROOT / "images"
    mask_dir = SRC_ROOT / "masks"

    stems = sorted([p.stem for p in image_dir.glob("*.png")])
    random.Random(SEED).shuffle(stems)
    n_val = int(len(stems) * VAL_RATIO)
    val_stems = set(stems[:n_val])
    train_stems = stems[n_val:]

    for split in ("train", "val"):
        (DST_ROOT / split / "images").mkdir(parents=True, exist_ok=True)
        (DST_ROOT / split / "masks").mkdir(parents=True, exist_ok=True)

    def process(stem, split):
        src_img = image_dir / f"{stem}.png"
        src_mask = mask_dir / f"{stem}.png"
        if not src_img.exists() or not src_mask.exists():
            return False

        dst_img = DST_ROOT / split / "images" / f"{stem}.png"
        shutil.copyfile(src_img, dst_img)

        mask = np.array(Image.open(src_mask))
        remapped = remap_mask(mask)
        Image.fromarray(remapped).save(DST_ROOT / split / "masks" / f"{stem}.png")
        return True

    n_train, n_val_done = 0, 0
    for stem in train_stems:
        if process(stem, "train"):
            n_train += 1
    for stem in val_stems:
        if process(stem, "val"):
            n_val_done += 1

    print(f"train: {n_train}, val: {n_val_done}")
    print(f"output: {DST_ROOT}")

    # 클래스 분포 확인 (검증용)
    class_pixel_counts = {0: 0, 1: 0, 2: 0}
    sample_masks = list((DST_ROOT / "train" / "masks").glob("*.png"))[:100]
    for p in sample_masks:
        m = np.array(Image.open(p))
        for c in (0, 1, 2):
            class_pixel_counts[c] += int((m == c).sum())
    total = sum(class_pixel_counts.values())
    print("클래스별 픽셀 비율 (train 샘플 100장 기준):")
    for c, name in ((0, "기타"), (1, "종양"), (2, "간질")):
        pct = class_pixel_counts[c] / total * 100
        print(f"  {name}: {pct:.1f}%")


if __name__ == "__main__":
    main()
