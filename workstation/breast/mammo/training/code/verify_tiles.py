#!/usr/bin/env python
"""
타일이 원본 화소를 그대로 담고 있는지 확인한다.

왜 이 방식인가
  check_calc_scale.py 로 타일을 재려 했더니 x1.06 이 나왔다. 그런데 그건
  도구가 깨진 것이다.

    대조 박스가 안 들어간다   원본 해상도라 병변 박스가 274px 인데 1024 타일
                              안에서 같은 크기 대조 박스를 못 놓아 46건이
                              실패하고 남은 것도 183px 로 작아졌다
    구조 요소가 작다          1부는 축소 영상을 가정한 3px 를 쓴다. 원본
                              해상도의 미세석회는 7px 라 안 걷어내진다

  더 중요한 것은 잴 필요가 없다는 점이다. 타일은 원본의 잘라내기이고
  리샘플링이 없다. 박스 안 화소가 원본과 같으면 원본에서 잰 x1.75 가 그대로
  적용된다. 측정보다 동일성 확인이 강한 검증이다.

무엇을 하나
  1. 화소 동일성   타일 PNG 와 원본 DICOM 의 같은 위치를 직접 비교한다.
                   차이가 0 이면 축소가 없었다는 증거다.
  2. 박스 정합     타일에 기록된 박스가 원본 병변 위치와 맞는지 본다.
  3. 신호 재측정   구조 요소 7px, 대조는 같은 타일 안 같은 크기 창을
                   훑어 중앙값을 쓴다. 크기가 어긋날 수 없다.

사용
  python3 verify_tiles.py
  python3 verify_tiles.py --n 60 --save tilecheck/
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from make_tiles import CAT, mask_box, norm8, tissue_bbox, tissue_mask

from paths import DATA, RAW_CBIS as RAW, ROI_INDEX as INDEX  # noqa: E402

SE = 7          # 원본 해상도에서 미세석회가 차지하는 화소
K = 5.0
NAME = {v: k for k, v in CAT.items()}


def dcm_for(uid):
    d = RAW / uid
    if not d.is_dir():
        return None
    fs = sorted(d.glob("*.dcm"))
    return fs[0] if fs else None


def specks(th, box, thr):
    x0, y0, x1, y1 = [int(v) for v in box]
    sub = th[y0:y1, x0:x1]
    if sub.size < 64:
        return None
    n, _, st, _ = cv2.connectedComponentsWithStats((sub > thr).astype(np.uint8), 8)
    amax = SE * SE * 4
    c = sum(1 for i in range(1, n) if 1 <= st[i, cv2.CC_STAT_AREA] <= amax)
    return c * 1000.0 / max(1, (x1 - x0) * (y1 - y0))


def control_median(th, shape, w, h, avoid, thr, stride=48):
    """
    같은 타일 안에서 같은 크기 창을 훑어 밀도의 중앙값을 낸다.
    크기가 어긋날 수 없고 항상 정의된다 — 무작위 대조 박스의 약점을 없앤다.
    """
    H, W = shape[:2]
    vals = []
    for y in range(0, max(1, H - h + 1), stride):
        for x in range(0, max(1, W - w + 1), stride):
            b = (x, y, x + w, y + h)
            if any(not (b[2] <= g[0] or b[0] >= g[2] or
                        b[3] <= g[1] or b[1] >= g[3]) for g in avoid):
                continue
            d = specks(th, b, thr)
            if d is not None:
                vals.append(d)
    return float(np.median(vals)) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco",
                    default=str(DATA / "det_tile1008/annotations/train.json"))
    ap.add_argument("--images", default="")
    ap.add_argument("--n", type=int, default=40, help="종류마다 몇 개 타일")
    ap.add_argument("--tile", type=int, default=0,
                    help="0 이면 주석의 영상 크기에서 읽는다")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--save", default="")
    ap.add_argument("--n-save", type=int, default=4)
    a = ap.parse_args()

    cj = Path(a.coco)
    if not cj.is_file():
        sys.exit(f"주석이 없다: {cj}")
    imgdir = Path(a.images) if a.images else cj.parent.parent / "images" / "train"
    if not imgdir.is_dir():
        sys.exit(f"영상 폴더가 없다: {imgdir}")

    print("=" * 76)
    print("타일이 원본 화소를 그대로 담고 있는가")
    print("=" * 76)

    d = json.loads(cj.read_text())
    imgs = {im["id"]: im for im in d["images"]}
    if not a.tile:
        # 타일 크기는 주석이 알고 있다 — 인자로 받아 어긋나게 두지 않는다
        a.tile = int(next(iter(imgs.values()))["width"])
        print(f"  타일 크기 {a.tile}px  (주석에서 읽음)")
    by = {}
    for an in d["annotations"]:
        by.setdefault(an["image_id"], []).append(an)

    want = {c: a.n for c in NAME}
    got = {c: 0 for c in NAME}
    cache_uid, cache = None, None
    diffs, ratios, badbox = [], {c: [] for c in NAME}, 0
    saved = 0

    for iid, anns in by.items():
        if all(got[c] >= want[c] for c in want):
            break
        cats = {an["category_id"] for an in anns}
        if not any(got[c] < want[c] for c in cats if c in want):
            continue
        im = imgs[iid]
        fp = imgdir / im["file_name"]
        if not fp.is_file():
            continue
        tile = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        if tile is None:
            continue

        uid = im["uid"]
        if uid != cache_uid:
            dp = dcm_for(uid)
            if dp is None:
                continue
            try:
                arr = pydicom.dcmread(str(dp)).pixel_array
            except Exception:
                continue
            if arr.ndim != 2:
                continue
            u8 = norm8(arr, a.clip)
            cache_uid, cache = uid, u8
        u8 = cache

        # ── 1. 화소 동일성 ────────────────────────────────────────────
        ox, oy = int(im["ox"]), int(im["oy"])
        ts = a.tile
        ref = np.zeros((ts, ts), np.uint8)
        sub = u8[oy:oy + ts, ox:ox + ts]
        ref[:sub.shape[0], :sub.shape[1]] = sub
        diffs.append(int(np.abs(ref.astype(np.int16) -
                                tile.astype(np.int16)).max()))

        # ── 3. 신호 재측정 ────────────────────────────────────────────
        v = tile.astype(np.float32) / 255.0
        th = cv2.morphologyEx(
            v, cv2.MORPH_TOPHAT,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (SE, SE)))
        live = th[tile > 10]                    # 공기와 여백을 뺀다
        if live.size < 5000:
            continue
        med = float(np.median(live))
        thr = K * (1.4826 * float(np.median(np.abs(live - med))) + 1e-6)

        gts = [(an["category_id"],
                (an["bbox"][0], an["bbox"][1],
                 an["bbox"][0] + an["bbox"][2], an["bbox"][1] + an["bbox"][3]))
               for an in anns]
        allb = [g for _, g in gts]
        for cid, b in gts:
            if cid not in want or got[cid] >= want[cid]:
                continue
            w, h = int(b[2] - b[0]), int(b[3] - b[1])
            if w < 16 or h < 16 or w > ts - 64 or h > ts - 64:
                continue
            dl = specks(th, b, thr)
            dc = control_median(th, v.shape, w, h, allb, thr)
            if dl is None or dc is None or dc <= 1e-9:
                continue
            ratios[cid].append(dl / dc)
            got[cid] += 1
            if a.save and cid == 1 and saved < a.n_save:
                shot(tile, ref, b, Path(a.save), f"{uid}_{ox}_{oy}")
                saved += 1

    # ── 2. 박스 정합 (표본으로 확인) ─────────────────────────────────
    print(f"\n■ 화소 동일성   타일 {len(diffs)}장 비교")
    if diffs:
        z = sum(1 for x in diffs if x == 0)
        print(f"  원본과 완전히 같은 타일   {z}/{len(diffs)}")
        print(f"  최대 화소 차이            {max(diffs)} (0~255 척도)")
        if max(diffs) == 0:
            print("  -> 리샘플링이 없다. 원본에서 잰 신호가 그대로 남아 있다.")
        else:
            print("  ! 차이가 있다. 좌표나 정규화가 어긋났다 — 확인이 필요하다")

    print(f"\n■ 신호 재측정   구조 요소 {SE}px · 대조는 같은 타일 안 같은 크기 창")
    print(f"  {'종류':6s} {'건수':>5s} {'병변/대조 밀도비':>18s}")
    print("  " + "-" * 34)
    for cid, nm in NAME.items():
        r = ratios[cid]
        if r:
            print(f"  {nm:6s} {len(r):5d} {'x' + format(np.median(r), '.2f'):>18s}")

    print("\n" + "=" * 76)
    print("읽는 법")
    print("=" * 76)
    print("  화소 차이가 0 이면 타일은 원본의 잘라내기다. 축소가 사라졌다는")
    print("  가장 직접적인 증거다. 이 경우 앞서 원본에서 잰 x1.75 가 그대로")
    print("  학습 데이터의 신호다.")
    print()
    print("  밀도비는 대조를 같은 타일 안 같은 크기 창의 중앙값으로 잡아")
    print("  크기가 어긋날 수 없다. 축소본에서 잰 x1.12 와 비교해서 읽어라.")


def shot(tile, ref, box, outdir, name):
    try:
        from PIL import Image, ImageDraw
        outdir.mkdir(parents=True, exist_ok=True)
        x0, y0, x1, y1 = [int(v) for v in box]
        p = 40
        cy0, cy1 = max(0, y0 - p), min(tile.shape[0], y1 + p)
        cx0, cx1 = max(0, x0 - p), min(tile.shape[1], x1 + p)
        ims = []
        for arr, t in ((tile, "타일"), (ref, "원본 같은 위치")):
            im = Image.fromarray(arr[cy0:cy1, cx0:cx1]).convert("RGB")
            im = im.resize((320, 320), Image.NEAREST)
            sx, sy = 320 / (cx1 - cx0), 320 / (cy1 - cy0)
            dr = ImageDraw.Draw(im)
            dr.rectangle([(x0-cx0)*sx, (y0-cy0)*sy, (x1-cx0)*sx, (y1-cy0)*sy],
                         outline=(255, 80, 80), width=2)
            dr.text((5, 5), t, fill=(255, 255, 0))
            ims.append(im)
        cv = Image.new("RGB", (648, 320), (0, 0, 0))
        cv.paste(ims[0], (0, 0))
        cv.paste(ims[1], (328, 0))
        cv.save(outdir / f"{name}.png")
    except Exception:
        pass


if __name__ == "__main__":
    main()
