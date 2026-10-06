import csv
from pathlib import Path

from PIL import Image

DST_ROOT = Path.home() / "data/tiger/cellvit_detection_v2"


def clip_labels(split: str):
    image_dir = DST_ROOT / split / "images"
    label_dir = DST_ROOT / split / "labels"

    n_fixed = 0
    n_total = 0

    for label_path in label_dir.glob("*.csv"):
        stem = label_path.stem
        img_path = image_dir / f"{stem}.png"
        if not img_path.exists():
            continue

        with Image.open(img_path) as img:
            w, h = img.size

        rows = []
        changed = False
        with open(label_path) as f:
            reader = csv.reader(f)
            for row in reader:
                x, y, label = int(row[0]), int(row[1]), row[2]
                n_total += 1
                new_x = min(max(x, 0), w - 1)
                new_y = min(max(y, 0), h - 1)
                if new_x != x or new_y != y:
                    changed = True
                rows.append((new_x, new_y, label))

        if changed:
            with open(label_path, "w", newline="") as f:
                writer = csv.writer(f)
                for r in rows:
                    writer.writerow(r)
            n_fixed += 1

    print(f"[{split}] 전체 라벨 파일: {len(list(label_dir.glob('*.csv')))}, 좌표 수정된 파일: {n_fixed}, 전체 좌표 수: {n_total}")


if __name__ == "__main__":
    clip_labels("train")
    clip_labels("test")
