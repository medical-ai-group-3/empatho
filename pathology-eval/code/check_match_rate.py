import json
import math
from pathlib import Path

with open('/home/wsuser/data/tiger/binary_detection/test_all_cells.json') as f:
    detections = json.load(f)

backup_dir = Path('/home/wsuser/data/tiger/cellvit_detection/test/labels_til_only_backup')

total_til_gt = 0
matched_til_gt = 0

for csv_path in backup_dir.glob('*.csv'):
    stem = csv_path.stem
    til_points = []
    with open(csv_path) as f:
        for line in f:
            x, y, _ = line.strip().split(',')
            til_points.append((float(x), float(y)))
    total_til_gt += len(til_points)

    detected = detections.get(stem, [])
    for tx, ty in til_points:
        for cell in detected:
            if math.hypot(tx - cell['x'], ty - cell['y']) <= 15.0:
                matched_til_gt += 1
                break

print(f'TIGER 원본 TIL 좌표 수: {total_til_gt}')
print(f'그 중 검출기가 근처에서 찾아낸 비율: {matched_til_gt}/{total_til_gt} = {matched_til_gt/total_til_gt*100:.1f}%')
