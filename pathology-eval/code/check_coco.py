import json, os

f = os.path.expanduser('~/data/tiger/tissue-cells/tiger-coco.json')
with open(f) as fp:
    d = json.load(fp)

print('keys:', list(d.keys()))
print('num images:', len(d.get('images', [])))
print('num annotations:', len(d.get('annotations', [])))
print('categories:', d.get('categories', []))
print('sample annotation:', d['annotations'][0] if d.get('annotations') else None)
print('sample image entry:', d['images'][0] if d.get('images') else None)
