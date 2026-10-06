"""
tissue_segmentation_v2의 마스크를 배경(0)은 학습 제외(ignore=255)로,
나머지(4,5,7)만 '기타'로 재매핑.
기존 마스크는 백업 후 덮어쓴다.
"""
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

TISSUE_CELLS_MASKS = Path.home() / "data/tiger/tissue-cells/masks"
DST_ROOT = Path.home() / "data/tiger/tissue_segmentation_v2"

IGNORE_LABEL = 255
REMAP = {
    0: IGNORE_LABEL,  # 배경 -> 학습 제외
    1: 1,  # 종양
    2: 2,  # 간질
    3: 1,  # 종양
    4: 0,  # 기타 (정상선조직)
    5: 0,  # 기타 (괴사)
    6: 2,  # 간질
    7: 0,  # 기타 (나머지)
}


def main():
    for split in ("train", "val"):
        image_dir = DST_ROOT / split / "images"
        mask_dir = DST_ROOT / split / "masks"
        backup_dir = DST_ROOT / split / "masks_bgincluded_backup"

        if not backup_dir.exists():
            shutil.copytree(mask_dir, backup_dir)
            print(f"[{split}] 백업 완료: {backup_dir}")

        n = 0
        for img_path in image_dir.glob("*.png"):
            stem = img_path.stem
            src_mask_path = TISSUE_CELLS_MASKS / f"{stem}.png"
            if not src_mask_path.exists():
                continue

            mask = np.array(Image.open(src_mask_path))
            out = np.zeros_like(mask, dtype=np.uint8)
            for orig_val, new_val in REMAP.items():
                out[mask == orig_val] = new_val

            Image.fromarray(out).save(mask_dir / f"{stem}.png")
            n += 1

        print(f"[{split}] 재매핑 완료: {n}장")

        # 배경 비율 확인 (샘플 100장)
        sample_masks = list(mask_dir.glob("*.png"))[:100]
        total_px = 0
        ignore_px = 0
        for p in sample_masks:
            m = np.array(Image.open(p))
            total_px += m.size
            ignore_px += (m == IGNORE_LABEL).sum()
        print(f"[{split}] 배경(제외) 픽셀 비율: {ignore_px/total_px*100:.1f}%")


if __name__ == "__main__":
    main()
