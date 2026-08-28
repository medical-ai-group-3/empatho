import numpy as np
from PIL import Image
from pathlib import Path
from collections import Counter

mask_dir = Path.home() / "data/tiger/tissue-cells/masks"
counter = Counter()
files = list(mask_dir.glob("*.png"))
print(f"총 마스크 파일 수: {len(files)}")

for i, f in enumerate(files[:200]):
    m = np.array(Image.open(f))
    for v in np.unique(m):
        counter[int(v)] += 1

print("각 클래스 값이 등장한 이미지 수 (샘플 200장 기준):", dict(sorted(counter.items())))
