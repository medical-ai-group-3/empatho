#!/usr/bin/env python
"""
CBIS-DDSM -> COCO JSON 변환 — SAM3 검출 학습용.

왜
  SAM3 학습 경로는 coco_json_loaders.COCO_FROM_JSON 으로 데이터를 받는다.
  범주 이름이 그대로 텍스트 프롬프트가 되므로 mass / calcification 두 범주로
  만들면 한 모델이 두 프롬프트로 종괴와 석회를 모두 검출하게 된다.

무엇을 하나
  1. roi_index_{kind}_{split}.csv 에서 전체 영상과 마스크를 찾는다
  2. 마스크의 최소 외접 사각형을 병변 박스로 삼는다
  3. 16비트 DICOM 을 8비트 PNG 로 변환한다 (백분위 절단 + 최소최대 정규화)
     - 학습 코드가 표준 영상 파일을 읽으므로 필요하다
     - 전처리는 mammo_data.py 와 같은 방식이다
  4. 한 영상에 병변이 여럿이면 주석을 여럿 붙인다 (영상 단위로 묶는다)
  5. COCO JSON 을 쓰고, 되읽어 검증한다

분할
  CBIS 의 train -> 학습, test -> 검증. 기존 분할 규율을 그대로 지킨다.

주의
  · CBIS 에는 정상 영상이 없다. 음성 표본은 VinDr 을 붙일 때 들어온다
  · 마스크가 없는 행은 건너뛴다
  · 이미 만든 PNG 는 다시 만들지 않는다 (중단 후 이어서 가능)

사용
  python3 make_coco.py --limit 20              # 20건만 시험
  python3 make_coco.py                          # 전체
  python3 make_coco.py --long-side 1536         # 미세석회용 고해상
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    import pandas as pd
    import pydicom
    from PIL import Image
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}  ->  pip install pandas pydicom pillow")

HOME = Path.home()
RAW = HOME / "workspace/breast/data/cbis/raw"
INDEX = HOME / "workspace/breast/labels/index"

# 범주 이름이 곧 텍스트 프롬프트가 된다
CATEGORIES = [
    {"id": 1, "name": "mass"},
    {"id": 2, "name": "calcification"},
]
KIND_TO_CAT = {"mass": 1, "calc": 2}


def resolve_full_image(image_path):
    """image_path 의 SeriesUID 로 실제 DICOM 을 찾는다."""
    uid = str(image_path).strip().split("/")[-2]
    d = RAW / uid
    if not d.is_dir():
        return None
    files = sorted(d.glob("*.dcm"))
    return files[0] if files else None


def read_dicom(path):
    return pydicom.dcmread(str(path)).pixel_array


def mask_bbox(mask_path):
    """이진 마스크의 최소 외접 사각형. 반환 (x0, y0, x1, y1) 또는 None."""
    try:
        m = read_dicom(mask_path)
    except Exception:
        return None
    if m.ndim != 2:
        return None
    ys, xs = np.nonzero(m > (m.max() * 0.5) if m.max() > 1 else m > 0)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def to_uint8(arr, clip_pct=99.9):
    """mammo_data.py 와 같은 전처리 — 백분위로 자르고 최소최대 정규화."""
    a = arr.astype(np.float32)
    if clip_pct and clip_pct < 100:
        lo = float(np.percentile(a, 100.0 - clip_pct))
        hi = float(np.percentile(a, clip_pct))
        if hi <= lo:
            lo, hi = float(a.min()), float(a.max())
        a = np.clip(a, lo, hi)
    else:
        lo, hi = float(a.min()), float(a.max())
    a = (a - lo) / (hi - lo + 1e-8)
    return (a * 255.0).round().astype(np.uint8)


def collect(kinds, splits, limit):
    """
    영상 단위로 묶는다. 같은 전체 영상에 병변이 여럿일 수 있다.
    반환: {split: {full_path: [(cat_id, bbox_or_maskpath), ...]}}
    """
    out = {s: defaultdict(list) for s in splits}
    stats = defaultdict(int)

    for kind in kinds:
        for split in splits:
            csv = INDEX / f"roi_index_{kind}_{split}.csv"
            if not csv.is_file():
                print(f"  ! 인덱스 없음: {csv}")
                continue
            df = pd.read_csv(csv)
            n_used = 0
            for rec in df.to_dict("records"):
                if limit and n_used >= limit:
                    break
                mp = str(rec.get("mask_file") or "").strip()
                if not mp or not Path(mp).is_file():
                    stats[f"{kind}/{split} 마스크없음"] += 1
                    continue
                full = resolve_full_image(rec.get("image_path", ""))
                if full is None:
                    stats[f"{kind}/{split} 전체영상없음"] += 1
                    continue
                out[split][full].append((KIND_TO_CAT[kind], mp))
                n_used += 1
            print(f"  {kind}/{split}: {n_used}건 수집 (전체 {len(df)})")

    for k, v in sorted(stats.items()):
        print(f"    제외 {k}: {v}")
    return out


def build_split(pairs, split, outdir, long_side, clip_pct):
    """PNG 를 쓰고 COCO 구조를 만든다."""
    imgdir = outdir / "images" / split
    imgdir.mkdir(parents=True, exist_ok=True)

    images, anns = [], []
    img_id, ann_id = 0, 0
    skipped = defaultdict(int)

    total = len(pairs)
    for n, (full, lesions) in enumerate(sorted(pairs.items()), 1):
        img_id += 1
        stem = Path(full).parent.name[-24:]          # SeriesUID 꼬리
        name = f"{split}_{img_id:05d}_{stem}.png"
        dst = imgdir / name

        try:
            arr = read_dicom(full)
        except Exception:
            skipped["전체영상 읽기실패"] += 1
            img_id -= 1
            continue
        H0, W0 = arr.shape[:2]
        sc = min(1.0, long_side / max(H0, W0))       # 확대는 하지 않는다
        W, H = max(1, round(W0 * sc)), max(1, round(H0 * sc))

        boxes = []
        for cat_id, mp in lesions:
            # 마스크가 전체 영상과 같은 크기여야 좌표가 맞는다.
            # 다르면 조용히 어긋난 박스를 만드는 대신 건너뛴다.
            try:
                hd = pydicom.dcmread(mp, stop_before_pixels=True)
                if (int(hd.Rows), int(hd.Columns)) != (H0, W0):
                    skipped["마스크 크기 불일치"] += 1
                    continue
            except Exception:
                skipped["마스크 헤더 읽기실패"] += 1
                continue
            bb = mask_bbox(mp)
            if bb is None:
                skipped["마스크 비어있음"] += 1
                continue
            x0, y0, x1, y1 = [v * sc for v in bb]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 - x0 < 2 or y1 - y0 < 2:
                skipped["박스 너무 작음"] += 1
                continue
            boxes.append((cat_id, [round(x0, 2), round(y0, 2),
                                   round(x1 - x0, 2), round(y1 - y0, 2)]))

        if not boxes:
            img_id -= 1
            continue

        if not dst.exists():                          # 이어서 실행 가능
            im = Image.fromarray(to_uint8(arr, clip_pct))
            if (W, H) != (W0, H0):
                im = im.resize((W, H), Image.BILINEAR)
            im.convert("L").save(dst, optimize=True)

        images.append({"id": img_id, "file_name": name,
                       "width": W, "height": H})
        for cat_id, xywh in boxes:
            ann_id += 1
            anns.append({"id": ann_id, "image_id": img_id,
                         "category_id": cat_id, "bbox": xywh,
                         "area": round(xywh[2] * xywh[3], 2),
                         "iscrowd": 0})
        if n % 50 == 0 or n == total:
            print(f"    {split} {n}/{total}  영상 {len(images)}  주석 {len(anns)}")

    for k, v in sorted(skipped.items()):
        print(f"    {split} 제외 {k}: {v}")
    return {"images": images, "annotations": anns, "categories": CATEGORIES}


def verify(path):
    """SAM3 로더로 되읽어 본다 — 형식이 맞는지 여기서 판가름난다."""
    print(f"\n  되읽기 검증: {path.name}")
    try:
        from sam3.train.data.coco_json_loaders import load_coco_and_group_by_image
    except Exception as e:
        print(f"    로더 임포트 실패 ({type(e).__name__}) — 형식 검증 생략")
        return
    try:
        grouped, cats = load_coco_and_group_by_image(str(path))
        print(f"    통과 — 영상 {len(grouped)}건, 범주 {cats}")
    except Exception as e:
        print(f"    ! 실패: {type(e).__name__}: {e}")
        print("      COCO 필드가 로더 기대와 다르다. 로더 소스를 확인해야 한다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HOME / "workspace/breast/mammo/det"))
    ap.add_argument("--kinds", default="mass,calc")
    ap.add_argument("--long-side", type=int, default=1024,
                    help="긴 변 화소. 미세석회는 1536 이상을 권한다")
    ap.add_argument("--clip-pct", type=float, default=99.9)
    ap.add_argument("--limit", type=int, default=0,
                    help="종류·분할마다 이만큼만 (시험용)")
    a = ap.parse_args()

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    splits = ["train", "test"]
    outdir = Path(a.out).expanduser()

    print("=" * 74)
    print("CBIS-DDSM -> COCO 변환")
    print("=" * 74)
    print(f"  인덱스   {INDEX}")
    print(f"  DICOM   {RAW}")
    print(f"  출력     {outdir}")
    print(f"  긴 변    {a.long_side}px")
    if a.limit:
        print(f"  ! 시험 모드 — 종류·분할마다 {a.limit}건")

    print("\n■ 수집")
    pairs = collect(kinds, splits, a.limit)

    (outdir / "annotations").mkdir(parents=True, exist_ok=True)
    for split, name in (("train", "train"), ("test", "val")):
        if not pairs[split]:
            print(f"\n■ {name}: 수집된 것이 없다 — 건너뛴다")
            continue
        print(f"\n■ {name} 생성")
        coco = build_split(pairs[split], split, outdir, a.long_side, a.clip_pct)
        dst = outdir / "annotations" / f"{name}.json"
        dst.write_text(json.dumps(coco), encoding="utf-8")
        by_cat = defaultdict(int)
        for an in coco["annotations"]:
            by_cat[an["category_id"]] += 1
        detail = "  ".join(f"{c['name']} {by_cat[c['id']]}" for c in CATEGORIES)
        print(f"    -> {dst}")
        print(f"       영상 {len(coco['images'])}  주석 {len(coco['annotations'])}  ({detail})")
        verify(dst)

    print("\n" + "=" * 74)
    print("다음")
    print("=" * 74)
    print("  1. 되읽기 검증이 통과했는지 확인한다")
    print("  2. 통과했으면 학습 설정(odinw_text_only_train.yaml)을 복사해")
    print("     데이터 경로와 범주만 우리 것으로 바꾼다")
    print("  3. 정상 영상이 없다 — VinDr 을 붙여야 음성 표본이 생긴다")


if __name__ == "__main__":
    main()
