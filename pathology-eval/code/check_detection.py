import json

with open('/home/wsuser/data/tiger/binary_detection/test_all_cells.json') as f:
    data = json.load(f)

counts = [len(v) for v in data.values()]
print('이미지 수:', len(counts))
print('평균 세포 수:', sum(counts) / len(counts))
print('최소/최대:', min(counts), max(counts))
print('0개 검출된 이미지 수:', sum(1 for c in counts if c == 0))
