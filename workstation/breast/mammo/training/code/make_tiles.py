#!/usr/bin/env python
"""
검출 학습용 데이터를 원본 해상도 타일로 다시 만든다.

왜 다시 만드나
  진단 결과 축소가 미세석회를 지우고 있었다.

    석회 병변/대조 알갱이 배수   원본 x1.75 -> 1024px 축소 x1.12
    종괴 병변/대조 알갱이 배수   원본 x1.72 -> 1024px 축소 x1.59

  석회는 대조군 대비 초과분의 84% 를 잃고 종괴는 18% 만 잃는다. 축소는
  저주파를 보존하고 고주파를 지우기 때문이다. 미세석회는 고주파 구조다.
  검출기는 석회를 배울 재료를 못 받은 상태로 학습했다.

  서술어 파이프라인이 석회를 잘 다루는 이유도 같다 — 거기는 원본 해상도
  ROI 조각을 쓴다. 축소를 안 거친다.

무엇이 바뀌나
  전체를 1024 로 줄이는 대신, 원본 해상도에서 1024 타일로 자른다.
  화소 크기가 그대로라 알갱이가 살아남는다.

부수 효과 — 음성 표본
  지금 학습 데이터는 2,220장 전부에 병변이 있다. 검출기가 '어딘가에 반드시
  있다' 를 전제로 배운다. 타일로 자르면 같은 영상에서 정상 조직 타일이
  나온다. 촬영 방식이 같은 음성이라 도메인 함정이 없다.
  FROC(영상당 오탐 개수별 민감도)을 제대로 재려면 이게 있어야 한다.

타일 판정
  양성    원본 박스의 min-keep 이상이 타일 안에 들어온 병변이 하나라도 있다
  음성    어떤 병변과도 전혀 겹치지 않고 조직이 충분히 차 있다
  버림    병변이 걸쳐만 있다 — 라벨을 못 붙이니 음성으로도 쓸 수 없다

정규화
  전체 영상 기준 99.9 백분위로 편다. 앞선 진단에서 이 절단은 무죄로 확인됐다.
  타일마다 따로 펴면 국소 대비가 올라 석회에 유리하겠지만, 해상도와 정규화를
  동시에 바꾸면 무엇이 효과를 냈는지 알 수 없다. 한 번에 하나만 바꾼다.
  (--per-tile-norm 으로 나중에 따로 시험할 수 있게 남겨둔다)

사용
  python3 make_tiles.py --dry-run           # 타일 수와 용량만 추정
  python3 make_tiles.py --jobs 8 --go
  python3 make_tiles.py --limit 20 --go     # 소규모 확인
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

try:
    import cv2
    import pandas as pd
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from paths import DATA, RAW_CBIS as RAW, ROI_INDEX as INDEX  # noqa: E402

# 번호와 이름은 기존 det/ 와 같게 맞춘다.
# 어긋나면 평가기를 잘못 겨눴을 때 종류가 조용히 뒤바뀐다 — 그럴듯한 오답이 나온다.
CAT = {"mass": 1, "calc": 2}
CATS = [{"id": 1, "name": "mass"}, {"id": 2, "name": "calcification"}]
SPLITS = {"train": "train", "test": "val"}     # 인덱스 분할 -> 출력 분할

CFG = {}       # 작업자에게 넘길 설정 — 전역으로 두어 피클을 줄인다


# ── 영상 하나에 붙은 병변 모으기 ─────────────────────────────────────────

def collect(split):
    """{uid: {"dcm": path, "rois": [(kind, mask_path), ...]}}"""
    out = {}
    for kind in CAT:
        csv = INDEX / f"roi_index_{kind}_{split}.csv"
        if not csv.is_file():
            print(f"  ! 인덱스 없음: {csv}")
            continue
        for rec in pd.read_csv(csv).to_dict("records"):
            mp = str(rec.get("mask_file") or "").strip()
            if not mp or not Path(mp).is_file():
                continue
            uid = str(rec.get("image_path", "")).strip().split("/")[-2]
            d = RAW / uid
            if not d.is_dir():
                continue
            fs = sorted(d.glob("*.dcm"))
            if not fs:
                continue
            e = out.setdefault(uid, {"dcm": fs[0], "rois": []})
            e["rois"].append((kind, mp))
    return out


# ── 화소 처리 ────────────────────────────────────────────────────────────

def norm8(a, clip):
    a = a.astype(np.float32)
    lo = float(np.percentile(a, 100.0 - clip))
    hi = float(np.percentile(a, clip))
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    v = np.clip((a - lo) / (hi - lo + 1e-8), 0.0, 1.0)
    return (v * 255.0).astype(np.uint8)


def tissue_mask(u8):
    _, m = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    if m.mean() < 20:
        m = ((u8 > np.percentile(u8, 45)) * 255).astype(np.uint8)
    return m > 0


def tissue_bbox(mask, pad):
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    H, W = mask.shape[:2]
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
            min(W, int(xs.max()) + 1 + pad), min(H, int(ys.max()) + 1 + pad))


def mask_box(path):
    import pydicom
    try:
        m = pydicom.dcmread(str(path)).pixel_array
    except Exception:
        return None, None
    if m.ndim != 2:
        return None, None
    b = m > (m.max() * 0.5) if m.max() > 1 else m > 0
    ys, xs = np.nonzero(b)
    if ys.size == 0:
        return None, None
    return ((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
            m.shape[:2])


def positions(n, size, stride):
    """마지막 위치는 끝에 붙인다 — 가장자리가 빠지면 안 된다."""
    if n <= size:
        return [0]
    p = list(range(0, n - size + 1, stride))
    if p[-1] != n - size:
        p.append(n - size)
    return p


def inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if (x1 > x0 and y1 > y0) else None


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


# ── 영상 하나 처리 ───────────────────────────────────────────────────────

def one(job):
    uid, ent, split = job
    c = CFG
    ts, ov = c["tile"], c["overlap"]
    stride = max(1, ts - ov)
    import pydicom
    try:
        arr = pydicom.dcmread(str(ent["dcm"])).pixel_array
    except Exception as e:
        return dict(uid=uid, err=f"dcm: {e}", tiles=[])
    if arr.ndim != 2:
        return dict(uid=uid, err="2차원이 아니다", tiles=[])

    boxes = []
    for kind, mp in ent["rois"]:
        b, shp = mask_box(mp)
        if b is None:
            continue
        if shp != arr.shape[:2]:          # 마스크와 원본 크기가 다르면 버린다
            continue
        boxes.append((CAT[kind], b))
    if not boxes:
        return dict(uid=uid, err="쓸 수 있는 병변이 없다", tiles=[])

    u8 = norm8(arr, c["clip"])
    mask = tissue_mask(u8)
    tb = tissue_bbox(mask, c["pad"])
    if tb is None:
        return dict(uid=uid, err="조직을 못 찾았다", tiles=[])
    cx0, cy0, cx1, cy1 = tb
    img = u8[cy0:cy1, cx0:cx1]
    msk = mask[cy0:cy1, cx0:cx1]
    boxes = [(k, (b[0] - cx0, b[1] - cy0, b[2] - cx0, b[3] - cy0))
             for k, b in boxes]
    H, W = img.shape[:2]

    pos, neg = [], []
    for ty in positions(H, ts, stride):
        for tx in positions(W, ts, stride):
            t = (tx, ty, tx + ts, ty + ts)
            keep, touched = [], False
            for k, b in boxes:
                it = inter(t, b)
                if it is None:
                    continue
                touched = True
                if area(it) >= c["min_keep"] * max(1, area(b)):
                    keep.append((k, (it[0] - tx, it[1] - ty,
                                     it[2] - tx, it[3] - ty)))
            if keep:
                pos.append((t, keep))
            elif not touched:
                frac = float(msk[ty:ty + ts, tx:tx + ts].mean())
                if frac >= c["min_tissue"]:
                    neg.append((t, frac))
            # touched 인데 keep 이 없으면 버린다 — 라벨을 못 붙인다

    rng = np.random.default_rng(abs(hash(uid)) % (2 ** 31))
    if c["neg"] > 0 and neg:
        k = min(c["neg"], len(neg))
        idx = rng.choice(len(neg), size=k, replace=False)
        neg = [neg[i] for i in idx]
    else:
        neg = []

    tiles = []
    outdir = Path(c["out"]) / "images" / split
    for i, (t, keep) in enumerate(pos + [(t, []) for t, _ in neg]):
        tx, ty = t[0], t[1]
        sub = img[ty:ty + ts, tx:tx + ts]
        if sub.shape[0] != ts or sub.shape[1] != ts:      # 가장자리 보정
            p = np.zeros((ts, ts), np.uint8)
            p[:sub.shape[0], :sub.shape[1]] = sub
            sub = p
        name = f"{uid}_{tx}_{ty}.png"
        rec = dict(file_name=name, width=ts, height=ts, uid=uid,
                   ox=int(tx + cx0), oy=int(ty + cy0),
                   anns=[dict(category_id=k, bbox=[float(b[0]), float(b[1]),
                                                   float(b[2] - b[0]),
                                                   float(b[3] - b[1])])
                         for k, b in keep])
        if c["dry"]:
            ok, buf = cv2.imencode(".png", sub)
            rec["bytes"] = int(buf.size) if ok else 0
        else:
            outdir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(outdir / name), sub)
        tiles.append(rec)
    return dict(uid=uid, err=None, tiles=tiles,
                npos=len(pos), nneg=len(neg), nbox=len(boxes))


def init(cfg):
    global CFG
    CFG = cfg
    cv2.setNumThreads(1)          # 작업자마다 스레드를 쓰면 서로 잡아먹는다


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "det_tile1008"))
    ap.add_argument("--tile", type=int, default=1024)
    ap.add_argument("--overlap", type=int, default=256,
                    help="병변이 타일 경계에 잘리지 않게 겹친다")
    ap.add_argument("--min-keep", type=float, default=0.6,
                    help="박스의 이 비율 이상이 들어와야 라벨로 인정")
    ap.add_argument("--min-tissue", type=float, default=0.7,
                    help="음성 타일이 되려면 조직이 이만큼 차 있어야 한다")
    ap.add_argument("--neg", type=int, default=2, help="영상당 음성 타일 수")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--per-tile-norm", action="store_true",
                    help="쓰지 마라. 해상도와 함께 바꾸면 원인을 못 가린다")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--limit", type=int, default=0, help="영상 수 제한 (확인용)")
    ap.add_argument("--dry-run", action="store_true",
                    help="타일 수와 용량만 추정하고 아무것도 안 쓴다")
    ap.add_argument("--go", action="store_true", help="실제로 쓴다")
    a = ap.parse_args()

    if a.per_tile_norm:
        sys.exit("--per-tile-norm 은 이번 실험에서 쓰지 않는다. "
                 "해상도만 바꿔서 효과를 분리해야 한다.")
    if not (a.go or a.dry_run):
        sys.exit("--dry-run 으로 먼저 용량을 보고, --go 로 실행해라")

    dry = a.dry_run and not a.go
    print("=" * 78)
    print(f"원본 해상도 타일 생성 — {a.tile}px, 겹침 {a.overlap}px"
          + ("   [추정만]" if dry else ""))
    print("=" * 78)

    cfg = dict(out=a.out, tile=a.tile, overlap=a.overlap,
               min_keep=a.min_keep, min_tissue=a.min_tissue, neg=a.neg,
               clip=a.clip, pad=a.pad, dry=dry)

    total_bytes, grand = 0, {}
    for isplit, osplit in SPLITS.items():
        ents = collect(isplit)
        if not ents:
            continue
        jobs = [(u, e, osplit) for u, e in sorted(ents.items())]
        if a.limit:
            jobs = jobs[:a.limit]
        print(f"\n■ {isplit} -> {osplit}   영상 {len(jobs):,}장")

        recs, npos, nneg, nerr, t0 = [], 0, 0, 0, time.time()
        with ProcessPoolExecutor(a.jobs, initializer=init,
                                 initargs=(cfg,)) as ex:
            for i, r in enumerate(ex.map(one, jobs, chunksize=1), 1):
                if r["err"]:
                    nerr += 1
                else:
                    recs += r["tiles"]
                    npos += r["npos"]
                    nneg += r["nneg"]
                if i % 25 == 0 or i == len(jobs):
                    el = time.time() - t0
                    eta = el / i * (len(jobs) - i)
                    print(f"\r  {i}/{len(jobs)}   타일 {len(recs):,}   "
                          f"남은 시간 {eta/60:.0f}분   ", end="", flush=True)
        print()
        if nerr:
            print(f"  ! 건너뛴 영상 {nerr}장")
        print(f"  양성 타일 {npos:,}   음성 타일 {nneg:,}   합계 {len(recs):,}")

        if dry:
            b = [r["bytes"] for r in recs if r.get("bytes")]
            sz = sum(b)
            total_bytes += sz
            if b:
                print(f"  용량 {sz/2**30:.1f}GB   타일 평균 {np.mean(b)/1024:.0f}KB")
            grand[osplit] = len(recs)
            continue

        # ── COCO 로 묶는다 ─────────────────────────────────────────────
        images, anns, aid = [], [], 1
        for iid, r in enumerate(recs, 1):
            images.append(dict(id=iid, file_name=r["file_name"],
                               width=r["width"], height=r["height"],
                               uid=r["uid"], ox=r["ox"], oy=r["oy"]))
            for an in r["anns"]:
                anns.append(dict(id=aid, image_id=iid,
                                 category_id=an["category_id"],
                                 bbox=an["bbox"], iscrowd=0,
                                 area=float(an["bbox"][2] * an["bbox"][3])))
                aid += 1
        ad = Path(a.out) / "annotations"
        ad.mkdir(parents=True, exist_ok=True)
        jp = ad / f"{osplit}.json"
        jp.write_text(json.dumps(dict(images=images, annotations=anns,
                                      categories=CATS)))
        cnt = defaultdict(int)
        for an in anns:
            cnt[an["category_id"]] += 1
        print(f"  -> {jp}")
        print(f"     영상 {len(images):,}   병변 {len(anns):,} "
              f"(종괴 {cnt[CAT['mass']]:,} · 석회 {cnt[CAT['calc']]:,})")
        grand[osplit] = len(images)

    print("\n" + "=" * 78)
    if dry:
        print(f"추정 합계   타일 {sum(grand.values()):,}장   "
              f"약 {total_bytes/2**30:.1f}GB")
        print()
        print("  용량이 감당되면 --go 로 실행해라.")
        print("  줄이려면  --neg 1   또는  --overlap 128")
    else:
        print("완료. 다음은 학습 설정을 이 데이터로 돌리는 것이다.")
        print(f"  주석  {Path(a.out)/'annotations'}")
        print(f"  영상  {Path(a.out)/'images'}")
        print()
        print("  ! 평가도 같은 방식으로 타일링해야 한다. 축소본으로 평가하면")
        print("    학습과 다른 화면을 보게 된다. eval 쪽을 이어서 고친다.")
    print("=" * 78)


if __name__ == "__main__":
    main()
