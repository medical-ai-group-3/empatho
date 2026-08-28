import csv
from pathlib import Path

val_csv = Path.home() / "data/tiger/cellvit_detection/splits/fold_0/val.csv"
image_dir = Path.home() / "data/tiger/cellvit_detection/val/images"

stems_in_csv = []
with open(val_csv) as f:
    reader = csv.reader(f)
    for row in reader:
        stems_in_csv.append(row[0])

image_stems = set(p.stem for p in image_dir.glob("*.png"))

print("CSV 항목 수:", len(stems_in_csv))
print("이미지 폴더 파일 수:", len(image_stems))
print("첫 CSV 항목:", repr(stems_in_csv[0]))
matched = [s for s in stems_in_csv if s in image_stems]
print("매칭된 개수:", len(matched))
if not matched:
    sample_image_stem = next(iter(image_stems))
    print("이미지 폴더 실제 stem 예시:", repr(sample_image_stem))
