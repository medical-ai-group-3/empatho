"""
2단계: SAM-H binary 검출로 찾은 모든 세포 좌표와, TIGER 원본 TIL(림프구/형질세포) 좌표를
매칭해서 이진분류 학습 데이터를 만든다.

- 검출된 세포 중 TIGER TIL 좌표와 가까운 것(거리 임계값 이내) -> label 1 (TIL)
- 나머지 검출된 세포 -> label 0 (nonTIL)

결과는 ~/data/tiger/cellvit_detection/{split}/labels/*.csv 를 덮어쓴다.
원본(TIGER 라벨만 있던 버전)은 백업해둔다.
"""
import argparse
import csv
import json
import math
import os
import shutil
from pathlib import Path

MATCH_DIST_PX = 15.0  # 이 거리(px) 이내면 같은 세포로 간주


def load_til_labels(labels_dir: Path):
    """기존 csv (x,y,0 형태, TIGER가 표시한 TIL 좌표들)를 읽어온다."""
    til_by_stem = {}
    for csv_path in labels_dir.glob("*.csv"):
        pts = []
        with open(csv_path) as f:
            reader = csv.reader(f)
            for row in reader:
                x, y = float(row[0]), float(row[1])
                pts.append((x, y))
        til_by_stem[csv_path.stem] = pts
    return til_by_stem


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", type=str, required=True, choices=["train", "test"])
    parser.add_argument(
        "--dataset_path",
        type=str,
        default=os.path.expanduser("~/data/tiger/cellvit_detection"),
    )
    parser.add_argument(
        "--detection_json",
        type=str,
        default=None,
        help="1단계에서 만든 {split}_all_cells.json 경로. 기본값은 ~/data/tiger/binary_detection/{split}_all_cells.json",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset_path)
    labels_dir = dataset_path / args.split / "labels"
    backup_dir = dataset_path / args.split / "labels_til_only_backup"

    detection_json = args.detection_json or os.path.expanduser(
        f"~/data/tiger/binary_detection/{args.split}_all_cells.json"
    )
    with open(detection_json) as f:
        all_detections = json.load(f)

    til_by_stem = load_til_labels(labels_dir)

    # 백업 (처음 한 번만)
    if not backup_dir.exists():
        shutil.copytree(labels_dir, backup_dir)
        print(f"백업 완료: {backup_dir}")

    total_til = 0
    total_nontil = 0
    n_images = 0

    for stem, detected_cells in all_detections.items():
        til_points = til_by_stem.get(stem, [])
        out_rows = []
        for cell in detected_cells:
            dx, dy = cell["x"], cell["y"]
            is_til = False
            for tx, ty in til_points:
                if math.hypot(dx - tx, dy - ty) <= MATCH_DIST_PX:
                    is_til = True
                    break
            label = 1 if is_til else 0
            out_rows.append((round(dx), round(dy), label))
            if is_til:
                total_til += 1
            else:
                total_nontil += 1

        out_path = labels_dir / f"{stem}.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            for row in out_rows:
                writer.writerow(row)
        n_images += 1

    print(f"처리 이미지 수: {n_images}")
    print(f"TIL(label=1): {total_til}, nonTIL(label=0): {total_nontil}")
    if total_til == 0:
        print("경고: TIL로 매칭된 세포가 0개입니다. MATCH_DIST_PX 값이나 좌표계를 확인하세요.")


if __name__ == "__main__":
    main()
