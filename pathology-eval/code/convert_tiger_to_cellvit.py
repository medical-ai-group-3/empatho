import json
import os
import shutil
import random
import csv

SRC_ROOT = os.path.expanduser("~/data/tiger/tissue-cells")
DST_ROOT = os.path.expanduser("~/data/tiger/cellvit_detection")
COCO_JSON = os.path.join(SRC_ROOT, "tiger-coco.json")
VAL_RATIO = 0.15
SEED = 42

def main():
    with open(COCO_JSON) as f:
        coco = json.load(f)

    categories = sorted(coco["categories"], key=lambda c: c["id"])
    cat_id_to_label = {c["id"]: i for i, c in enumerate(categories)}
    label_names = {i: c["name"] for i, c in enumerate(categories)}

    images_by_id = {img["id"]: img for img in coco["images"]}

    anns_by_image = {}
    for ann in coco["annotations"]:
        img_id = ann["image_id"]
        x, y, w, h = ann["bbox"]
        cx, cy = x + w / 2.0, y + h / 2.0
        label = cat_id_to_label[ann["category_id"]]
        anns_by_image.setdefault(img_id, []).append((cx, cy, label))

    image_ids = list(images_by_id.keys())
    random.Random(SEED).shuffle(image_ids)
    n_val = int(len(image_ids) * VAL_RATIO)
    val_ids = set(image_ids[:n_val])
    train_ids = image_ids[n_val:]

    for split in ("train", "test"):
        os.makedirs(os.path.join(DST_ROOT, split, "images"), exist_ok=True)
        os.makedirs(os.path.join(DST_ROOT, split, "labels"), exist_ok=True)
    os.makedirs(os.path.join(DST_ROOT, "splits", "fold_0"), exist_ok=True)

    def process(img_id, split_dir):
        img_info = images_by_id[img_id]
        basename = os.path.basename(img_info["file_name"])
        src_img = os.path.join(SRC_ROOT, "images", basename)
        dst_img = os.path.join(DST_ROOT, split_dir, "images", basename)
        if not os.path.exists(src_img):
            return None
        shutil.copyfile(src_img, dst_img)

        stem = os.path.splitext(basename)[0]
        label_path = os.path.join(DST_ROOT, split_dir, "labels", stem + ".csv")
        cells = anns_by_image.get(img_id, [])
        with open(label_path, "w", newline="") as f:
            writer = csv.writer(f)
            for cx, cy, label in cells:
                writer.writerow([round(cx), round(cy), label])
        return stem

    train_stems, val_stems = [], []
    for img_id in train_ids:
        stem = process(img_id, "train")
        if stem:
            train_stems.append(stem)
    for img_id in val_ids:
        stem = process(img_id, "test")
        if stem:
            val_stems.append(stem)

    with open(os.path.join(DST_ROOT, "splits", "fold_0", "train.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        for s in train_stems:
            writer.writerow([s])
    with open(os.path.join(DST_ROOT, "splits", "fold_0", "val.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        for s in val_stems:
            writer.writerow([s])

    with open(os.path.join(DST_ROOT, "label_map.yaml"), "w") as f:
        for i, name in label_names.items():
            f.write(str(i) + ": " + str(name) + "\n")

    print("train images:", len(train_stems), "val(test) images:", len(val_stems))
    print("labels:", label_names)
    print("output:", DST_ROOT)

if __name__ == "__main__":
    main()
