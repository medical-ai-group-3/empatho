"""
CellViT++ DetectionDataset은 train/val 데이터셋을 만들 때 둘 다 split="train"으로 고정하고,
파일 목록(filelist)만 다르게 줘서 구분한다. 즉 val로 쓸 이미지도 train/images, train/labels
안에 실제로 존재해야 한다.

지금까지 train(1598장)과 test(281장)를 별도 폴더에 나눠뒀으므로, test 폴더의 파일들을
train 폴더로 복사한다. (파일명이 겹치지 않으므로 안전하게 합칠 수 있음)
"""
import shutil
from pathlib import Path

DATASET_ROOT = Path.home() / "data/tiger/cellvit_detection"

src_images = DATASET_ROOT / "test" / "images"
src_labels = DATASET_ROOT / "test" / "labels"
dst_images = DATASET_ROOT / "train" / "images"
dst_labels = DATASET_ROOT / "train" / "labels"

count = 0
for img_path in src_images.glob("*.png"):
    dst_img = dst_images / img_path.name
    if not dst_img.exists():
        shutil.copyfile(img_path, dst_img)
    stem = img_path.stem
    src_label = src_labels / f"{stem}.csv"
    dst_label = dst_labels / f"{stem}.csv"
    if src_label.exists() and not dst_label.exists():
        shutil.copyfile(src_label, dst_label)
    count += 1

print(f"{count}개 이미지/라벨을 train 폴더로 복사 완료")
print(f"train/images 총 파일 수: {len(list(dst_images.glob('*.png')))}")
