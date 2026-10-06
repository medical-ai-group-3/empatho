import csv
import random
from pathlib import Path

SPLITS_DIR = Path.home() / "data/tiger/cellvit_detection_v2/splits/fold_0"
RATIO = 0.10
SEED = 42

with open(SPLITS_DIR / "train.csv") as f:
    reader = csv.reader(f)
    all_stems = [row[0] for row in reader]

n_sample = max(1, int(len(all_stems) * RATIO))
random.Random(SEED).shuffle(all_stems)
subset = all_stems[:n_sample]

with open(SPLITS_DIR / "train_fewshot10.csv", "w", newline="") as f:
    writer = csv.writer(f)
    for s in subset:
        writer.writerow([s])

print(f"전체 train: {len(all_stems)}, 서브셋(10%): {len(subset)}")
