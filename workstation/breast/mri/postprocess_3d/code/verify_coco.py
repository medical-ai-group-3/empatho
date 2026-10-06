"""
build_coco_from_npy.py 결과를 눈으로 확인하기 위한 스크립트.
각 데이터셋(tumor/breast+dense/lesion)별로 대표 이미지 1장씩 골라
원본 위에 폴리곤 마스크를 그려서 저장한다.

사용법:
    python verify_coco.py --coco-dir data/mri/coco_2d --split train --out verify_out
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco-dir", required=True)
    ap.add_argument("--split", default="train")
    ap.add_argument("--out", default="verify_out")
    ap.add_argument("--n-per-tag", type=int, default=2)
    args = ap.parse_args()

    coco_dir = Path(args.coco_dir)
    split_dir = coco_dir / args.split
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(split_dir / "_annotations.coco.json") as f:
        coco = json.load(f)

    cat_names = {c["id"]: c["name"] for c in coco["categories"]}
    img_by_id = {im["id"]: im for im in coco["images"]}

    anns_by_image = {}
    for a in coco["annotations"]:
        anns_by_image.setdefault(a["image_id"], []).append(a)

    # 파일명 태그(mamamia/duke/ambl)별로 이미지 그룹핑
    tag_to_images = {"mamamia": [], "duke": [], "ambl": []}
    for img_id, im in img_by_id.items():
        if img_id not in anns_by_image:
            continue
        fname = im["file_name"]
        for tag in tag_to_images:
            if fname.startswith(tag):
                tag_to_images[tag].append(img_id)
                break

    colors = {
        "tumor": (0, 0, 255),
        "breast": (255, 0, 0),
        "dense tissue": (0, 255, 255),
        "benign lesion": (0, 255, 0),
        "malignant lesion": (0, 0, 255),
    }

    for tag, img_ids in tag_to_images.items():
        if not img_ids:
            print(f"{tag}: 마스크 있는 이미지 없음")
            continue
        sample_ids = random.sample(img_ids, min(args.n_per_tag, len(img_ids)))
        for img_id in sample_ids:
            im_info = img_by_id[img_id]
            img_path = split_dir / im_info["file_name"]
            img = cv2.imread(str(img_path))
            if img is None:
                print(f"  ! 이미지 로드 실패: {img_path}")
                continue

            for ann in anns_by_image[img_id]:
                cat_name = cat_names[ann["category_id"]]
                color = colors.get(cat_name, (255, 255, 255))
                seg = ann["segmentation"][0]
                pts = np.array(seg, dtype=np.int32).reshape(-1, 2)
                cv2.polylines(img, [pts], isClosed=True, color=color, thickness=1)
                x, y, w, h = [int(v) for v in ann["bbox"]]
                cv2.rectangle(img, (x, y), (x + w, y + h), color, 1)
                cv2.putText(img, cat_name, (x, max(y - 3, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

            out_path = out_dir / f"{tag}_{im_info['file_name']}"
            cv2.imwrite(str(out_path), img)
            print(f"저장: {out_path}  (카테고리: {[cat_names[a['category_id']] for a in anns_by_image[img_id]]})")

    print(f"\n확인용 이미지 위치: {out_dir}")
    print("scp로 로컬로 받아서 눈으로 확인하세요:")
    print(f'  scp -P 22 -r wsuser@lan-host:{out_dir.resolve()} .')


if __name__ == "__main__":
    main()
