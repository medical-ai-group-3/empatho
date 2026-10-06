#!/usr/bin/env python3
"""
기존 COCO(coco_2d)에 MAMA-MIA "종양 없는 슬라이스"를 추가한 새 주석 파일을 만든다.

2026-09-29 신규 — MRI 병변 오탐 검토. 배경:
  build_coco_from_npy.py:109-112가 종양 마스크 5픽셀 미만 슬라이스를 건너뛰어서, 모델은
  "종양 없는 슬라이스에 tumor를 물으면 없다고 답하기"를 배운 적이 없다(빈 사진은 "object"
  쿼리로만 학습됨). 그런데 서빙은 볼륨 전 슬라이스에 tumor를 묻는다. 40명 3D 분석에서
  순수 오탐의 72%가 정답에서 10슬라이스 넘게 떨어진 슬라이스에 있었다
  (results/lesion_fp_analysis.log).

설계:
  - 기존 _annotations.coco.json, PNG, 캐시는 건드리지 않는다. 새 주석 파일(기본
    _annotations_tumorneg.coco.json)을 같은 split 폴더에 쓰고, 새 PNG만 추가한다.
  - 환자 train/val 분할은 기존 주석 파일의 파일명에서 그대로 읽는다 — 난수로 다시 나누지
    않으므로 분할이 절대 바뀌지 않는다(val 40명 기준선 비교가 유효하게 유지됨).
  - 추가 이미지에는 "tumor_negative": true 를 붙인다. train_mri_lora.py가 이 표시를 보고
    "object" 대신 "tumor" 쿼리를 정답 없음으로 묻는다.
  - Duke·AMBL은 추가하지 않는다 — 그 환자들도 실제 종양이 있는데 tumor 라벨만 없는 데이터라
    "tumor 없음"으로 가르치면 틀린 정답이 된다.

슬라이스 선택 (환자별):
  - 정답 종양이 있는 슬라이스에서 --margin 슬라이스 이내는 제외(경계 슬라이스의 라벨 애매함 회피)
  - 몸(z-score>0) 비율이 --min-body-frac 미만인 슬라이스 제외(볼륨 끝의 거의 빈 슬라이스)
  - 그 환자의 기존 종양 슬라이스 수 × --ratio 장을 무작위로(별도 seed) 고른다

사용법:
    python3 add_tumor_negative_slices.py --dry-run      # 개수만 계산
    python3 add_tumor_negative_slices.py                # PNG + 새 주석 파일 생성
"""

import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from build_coco_from_npy import build_rgb_2phase

HERE = Path(__file__).resolve().parent
BREAST_ROOT = HERE.parents[2]
DEFAULT_COCO = BREAST_ROOT / "data" / "mri" / "coco_2d"
DEFAULT_MAMA = BREAST_ROOT / "data" / "mri" / "mama_mia_processed"
FNAME_RE = re.compile(r"^mamamia_(.+)_z(\d{4})\.png$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco-root", type=Path, default=DEFAULT_COCO)
    ap.add_argument("--mama-mia-dir", type=Path, default=DEFAULT_MAMA)
    ap.add_argument("--src-ann", default="_annotations.coco.json")
    ap.add_argument("--out-ann", default="_annotations_tumorneg.coco.json")
    ap.add_argument("--ratio", type=float, default=0.5,
                    help="환자별 추가 장수 = 기존 종양 슬라이스 수 × ratio. 1.0이면 에폭이 약 75%% 길어짐")
    ap.add_argument("--margin", type=int, default=3, help="종양 슬라이스에서 이 거리 이내는 제외")
    ap.add_argument("--min-body-frac", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=7, help="슬라이스 샘플링 전용 — 환자 분할과 무관")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    splits = {}
    for split in ("train", "val"):
        with open(args.coco_root / split / args.src_ann) as f:
            splits[split] = json.load(f)
    next_id = max(im["id"] for c in splits.values() for im in c["images"]) + 1

    # 기존 주석에서 split별 mamamia 환자와 그 환자의 종양 슬라이스 수
    pid_split, pid_count = {}, defaultdict(int)
    for split, coco in splits.items():
        for im in coco["images"]:
            m = FNAME_RE.match(im["file_name"])
            if m:
                pid = m.group(1)
                assert pid_split.setdefault(pid, split) == split, f"{pid}가 두 split에 걸침"
                pid_count[pid] += 1

    added = {"train": [], "val": []}
    skipped = []
    for pid in sorted(pid_split):
        split = pid_split[pid]
        img_fp = args.mama_mia_dir / "images" / f"{pid}.npy"
        lbl_fp = args.mama_mia_dir / "labels" / f"{pid}.npy"
        if not (img_fp.exists() and lbl_fp.exists()):
            skipped.append(pid)
            continue
        img = np.load(img_fp, mmap_mode="r")      # (2,Z,Y,X)
        lbl = np.load(lbl_fp, mmap_mode="r")      # (Z,Y,X)
        tumor_z = np.where(np.asarray(lbl).reshape(lbl.shape[0], -1).any(axis=1))[0]
        cand = []
        for z in range(lbl.shape[0]):
            if tumor_z.size and np.abs(tumor_z - z).min() <= args.margin:
                continue
            if float((np.asarray(img[0, z]) > 0).mean()) < args.min_body_frac:
                continue
            cand.append(z)
        n_pick = min(len(cand), int(round(pid_count[pid] * args.ratio)))
        for z in sorted(rng.sample(cand, n_pick)):
            added[split].append((pid, z))

    for split in ("train", "val"):
        print(f"{split}: 기존 이미지 {len(splits[split]['images'])}장 + tumor 음성 {len(added[split])}장 추가 예정")
    if skipped:
        print(f"npy 없어 건너뛴 환자 {len(skipped)}명: {skipped[:10]}")
    if args.dry_run:
        return

    for split in ("train", "val"):
        coco = splits[split]
        split_dir = args.coco_root / split
        existing = {im["file_name"] for im in coco["images"]}
        new_images = []
        for pid, z in added[split]:
            fname = f"mamamia_{pid}_z{z:04d}.png"
            assert fname not in existing, f"파일명 충돌 {fname} — margin 로직 확인"
            fp = split_dir / fname
            if not fp.exists():
                img = np.load(args.mama_mia_dir / "images" / f"{pid}.npy", mmap_mode="r")
                Image.fromarray(build_rgb_2phase(np.asarray(img[0, z]), np.asarray(img[1, z]))).save(fp)
            h, w = Image.open(fp).size[::-1]
            new_images.append({"id": next_id, "file_name": fname, "width": w, "height": h,
                               "tumor_negative": True})
            next_id += 1
        out = {**coco, "images": coco["images"] + new_images}
        with open(split_dir / args.out_ann, "w") as f:
            json.dump(out, f)
        print(f"{split}: {split_dir / args.out_ann} 저장 (이미지 {len(out['images'])}장)")

    # 분할 불변 확인 — 새 주석의 mamamia 환자 split이 기존과 같아야 한다
    for split in ("train", "val"):
        with open(args.coco_root / split / args.out_ann) as f:
            coco = json.load(f)
        for im in coco["images"]:
            m = FNAME_RE.match(im["file_name"])
            if m:
                assert pid_split[m.group(1)] == split, f"분할 변경 감지: {m.group(1)}"
    print("환자 분할 기존과 동일 확인")


if __name__ == "__main__":
    main()
