import shutil
from pathlib import Path

DST_ROOT = Path.home() / "data/tiger/cellvit_detection_v2"
SRC_ROOT = Path.home() / "data/tiger/cellvit_detection"

def find_final_label(stem):
    for split in ("train", "test"):
        p = SRC_ROOT / split / "labels" / f"{stem}.csv"
        if p.exists():
            return p
    return None

def main():
    n_fixed = 0
    n_missing = 0
    for split in ("train", "val"):
        label_dir = DST_ROOT / split / "labels"
        if not label_dir.exists():
            continue
        for label_path in list(label_dir.glob("*.csv")):
            stem = label_path.stem
            src = find_final_label(stem)
            if src is None:
                n_missing += 1
                continue
            shutil.copyfile(src, label_path)
            n_fixed += 1
    print(f"교체된 라벨 파일: {n_fixed}, 원본 못 찾은 파일: {n_missing}")

if __name__ == "__main__":
    main()
