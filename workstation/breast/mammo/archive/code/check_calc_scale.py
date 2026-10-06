#!/usr/bin/env python
"""
1024px 학습 영상에 미세석회가 남아 있는가 — 대조군과 비교한다.

앞선 두 진단
  절단(99.9 백분위)   무죄. 석회 박스에서 잘려나가는 화소가 0.00% 였다.
  1차 축소 측정        측정이 깨졌다. 잡음을 영상 전체에서 쟀는데 맘모그램은
                       절반이 공기라 중앙값 절대편차가 0으로 수렴했다.
                       문턱이 0이 되어 국소 최대점이 전부 통과했다.

이번 설계
  절대값을 척도 간에 비교하지 않는다. 보정이 필요하고 보정이 논쟁거리가 된다.
  같은 척도 안에서 대조군과 비교한다.

    병변 박스   석회 또는 종괴
    대조 박스   같은 크기, 유방 조직 안 임의 위치, 병변과 겹치지 않음

  석회 박스가 대조 박스와 구분되지 않으면 검출기는 원리적으로 석회를 찾을 수
  없다. 종괴는 대조군과 벌어지는데 석회만 안 벌어지는지 본다.

무엇을 재나
  알갱이   탑햇 변환 — 구조 요소보다 작은 밝은 물체만 남기는 형태학 연산.
           고전적 미세석회 검출기가 이 방식이다. 문턱은 유방 조직 안에서만
           잰 잡음의 배수로 잡는다. 공기는 뺀다.
  밝기     박스 평균 − 조직 평균. 종괴처럼 뭉툭한 구조를 잡는 저주파 지표.

  석회는 알갱이로, 종괴는 밝기로 대조군과 갈려야 정상이다.

무엇을 안 하나
  GPU 를 안 쓴다.

사용
  python3 check_calc_scale.py
  python3 check_calc_scale.py --coco det/annotations/train.json
  python3 check_calc_scale.py --save scalecheck/
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

HOME = Path.home()
MAMMO = HOME / "workspace/breast/mammo"
RAW = HOME / "workspace/breast/data/cbis/raw"
INDEX = HOME / "workspace/breast/labels/index"

CLIP = 99.9        # make_coco.py 와 같은 값
K_SPECK = 5.0      # 알갱이로 세려면 잡음의 몇 배를 넘어야 하나
SE_SMALL = 3       # 축소된 영상에서 미세석회가 차지할 화소 (하한이다)
SE_FULL = 7        # 원본에서 미세석회가 차지할 화소 (약 0.3mm / 50um)
NAME = {1: "calc", 2: "mass"}


# ── 기본 도구 ────────────────────────────────────────────────────────────

def norm(a, clip=CLIP):
    a = a.astype(np.float32)
    lo = float(np.percentile(a, 100.0 - clip))
    hi = float(np.percentile(a, clip))
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    return np.clip((a - lo) / (hi - lo + 1e-8), 0.0, 1.0)


def tissue_mask(v):
    """공기를 뺀다. 오츠 문턱 — 맘모그램은 공기와 조직이 뚜렷이 갈린다."""
    u8 = (np.clip(v, 0, 1) * 255).astype(np.uint8)
    _, m = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    if m.mean() < 25:                       # 문턱이 과하게 잡힌 경우의 대비책
        m = ((v > np.percentile(v, 45)) * 255).astype(np.uint8)
    return m > 0


def tophat(v, se):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (se, se))
    return cv2.morphologyEx(v, cv2.MORPH_TOPHAT, k)


def noise_in_tissue(th, mask):
    """조직 안에서만 잰다. 중앙값 절대편차 — 병변에 안 휘둘린다."""
    x = th[mask]
    if x.size < 1000:
        return None
    med = float(np.median(x))
    mad = 1.4826 * float(np.median(np.abs(x - med)))
    return max(mad, 1e-6)


def count_specks(th, box, thr, se):
    """
    박스 안에서 '작고 밝은 덩어리' 를 센다.
    너무 큰 덩어리는 석회가 아니라 조직 구조라 뺀다.
    """
    x0, y0, x1, y1 = box
    sub = th[y0:y1, x0:x1]
    if sub.size < 64:
        return None
    bw = (sub > thr).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    amax = se * se * 4
    cnt = sum(1 for i in range(1, n) if 1 <= stats[i, cv2.CC_STAT_AREA] <= amax)
    return cnt


def clipbox(box, shape):
    H, W = shape[:2]
    x0, y0, x1, y1 = [int(round(q)) for q in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    return (x0, y0, x1, y1) if (x1 - x0 >= 8 and y1 - y0 >= 8) else None


def control_box(box, mask, rng, avoid, tries=60):
    """
    같은 크기의 대조 박스를 조직 안에서 고른다.
    병변 박스들과 겹치면 버린다.
    """
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    H, W = mask.shape[:2]
    if w >= W or h >= H:
        return None
    for _ in range(tries):
        cx = int(rng.integers(0, W - w))
        cy = int(rng.integers(0, H - h))
        c = (cx, cy, cx + w, cy + h)
        if mask[cy:cy + h, cx:cx + w].mean() < 0.9:      # 거의 전부 조직이어야
            continue
        if any(not (c[2] <= b[0] or c[0] >= b[2] or
                    c[3] <= b[1] or c[1] >= b[3]) for b in avoid):
            continue
        return c
    return None


def measure(v, th, box, thr, se, tmean):
    b = clipbox(box, v.shape)
    if b is None:
        return None
    n = count_specks(th, b, thr, se)
    if n is None:
        return None
    x0, y0, x1, y1 = b
    w, h = x1 - x0, y1 - y0
    return dict(
        specks=n,
        density=n * 1000.0 / (w * h),          # 넓이로 나눠 크기 영향을 뺀다
        bright=float(v[y0:y1, x0:x1].mean() - tmean),
        side=float(np.sqrt(w * h)),
    )


# ── 한 영상 처리 ─────────────────────────────────────────────────────────

def do_image(v, boxes, se, rng, bag, kind_of):
    """boxes = [(kind, box), ...]. bag[kind]['병변'|'대조'] 에 쌓는다."""
    mask = tissue_mask(v)
    th = tophat(v, se)
    nz = noise_in_tissue(th, mask)
    if nz is None:
        return 0
    thr = K_SPECK * nz
    tmean = float(v[mask].mean())
    allb = [b for _, b in boxes]
    got = 0
    for kind, box in boxes:
        m = measure(v, th, box, thr, se, tmean)
        if m is None:
            continue
        bag[kind]["병변"].append(m)
        c = control_box(clipbox(box, v.shape), mask, rng, allb)
        if c is not None:
            mc = measure(v, th, c, thr, se, tmean)
            if mc:
                bag[kind]["대조"].append(mc)
        got += 1
    return got


def new_bag():
    return {k: {"병변": [], "대조": []} for k in ("calc", "mass")}


# ── 1부: 실제 학습용 PNG ─────────────────────────────────────────────────

def find_coco(given):
    if given:
        p = Path(given).expanduser()
        if not p.is_absolute():
            p = MAMMO / p
        return p if p.is_file() else None
    for pat in ("det/annotations/*train*.json", "coco/*train*.json",
                "**/instances_train*.json", "**/*train*.json"):
        for p in sorted(MAMMO.glob(pat)):
            return p
    return None


def resolve_root(cj, sample):
    """
    주석 파일 위치에서 영상 폴더를 찾는다.
    file_name 이 상대 경로일 수도, 파일 이름만일 수도 있다.
    """
    name = Path(sample).name
    cands = [cj.parent, cj.parent.parent,
             cj.parent.parent / "images", cj.parent.parent / "train",
             cj.parent.parent / "images" / "train", MAMMO]
    for d in cands:
        if (d / sample).is_file():
            return d, True                     # file_name 을 그대로 붙인다
    for d in cands:
        if not d.is_dir():
            continue
        hit = next(iter(d.glob(f"**/{name}")), None)
        if hit is not None:
            # sample 의 뒤쪽 경로를 벗겨 공통 뿌리를 얻는다
            return hit.parent, False           # 파일 이름만 쓴다
    return None, False


def part_png(cj, n, se, seed, save, n_save):
    print(f"■ 1부  실제 학습용 PNG — {cj}")
    d = json.loads(cj.read_text())
    imgs = {im["id"]: im for im in d["images"]}
    byimg = {}
    for an in d["annotations"]:
        byimg.setdefault(an["image_id"], []).append(an)

    sides = [max(im["width"], im["height"]) for im in imgs.values()]
    side_med = int(np.median(sides))
    print(f"  영상 {len(imgs):,}장   긴 변 중앙값 {side_med}px "
          f"(최소 {min(sides)} · 최대 {max(sides)})")

    sample = next(iter(imgs.values()))["file_name"]
    root, joined = resolve_root(cj, sample)
    if root is None:
        print(f"  ! 영상 폴더를 못 찾았다. 주석의 file_name 예: {sample}")
        print(f"    찾아본 곳: {cj.parent}, {cj.parent.parent}, .../images, .../train\n")
        return new_bag(), side_med
    print(f"  영상 폴더 {root}")

    rng = np.random.default_rng(seed)
    bag, used, miss, saved = new_bag(), 0, 0, 0
    for iid, anns in byimg.items():
        if all(len(bag[k]["병변"]) >= n for k in bag):
            break
        im = imgs[iid]
        fp = (root / im["file_name"]) if joined else (root / Path(im["file_name"]).name)
        g = cv2.imread(str(fp), cv2.IMREAD_UNCHANGED) if fp.is_file() else None
        if g is None:
            miss += 1
            continue
        if g.ndim == 3:
            g = g[..., 0]
        v = g.astype(np.float32) / (65535.0 if g.dtype == np.uint16 else 255.0)

        boxes = []
        for an in anns:
            c = an.get("category_id")
            if c not in NAME or len(bag[NAME[c]]["병변"]) >= n:
                continue
            x, y, w, h = an["bbox"]
            boxes.append((NAME[c], (x, y, x + w, y + h)))
        if not boxes:
            continue
        if do_image(v, boxes, se, rng, bag, None) and save and saved < n_save:
            for kind, b in boxes:
                if kind == "calc" and saved < n_save:
                    look(v, b, Path(save), f"png_{saved}", se)
                    saved += 1
        used += 1
        if used % 50 == 0:
            print(f"\r  {used}장 처리   ", end="", flush=True)
    print(f"\r  {used}장 처리          ")
    if miss:
        print(f"  ! 못 연 영상 {miss}장")
    return bag, side_med


# ── 2부: 원본 DICOM, 줄이기 전후 ─────────────────────────────────────────

def part_dicom(n, scale_to, split, seed, save, n_save):
    try:
        import pandas as pd
        import pydicom
    except ImportError as e:
        print(f"■ 2부  건너뜀 — {e}")
        return None, None

    print(f"■ 2부  원본 DICOM — 긴 변 {scale_to}px 로 줄이기 전후")
    rng = np.random.default_rng(seed)
    big, small, saved = new_bag(), new_bag(), 0

    for kind in ("calc", "mass"):
        csv = INDEX / f"roi_index_{kind}_{split}.csv"
        if not csv.is_file():
            print(f"  인덱스 없음: {csv}")
            continue
        used = 0
        for rec in pd.read_csv(csv).to_dict("records"):
            if used >= n:
                break
            mp = str(rec.get("mask_file") or "").strip()
            if not mp or not Path(mp).is_file():
                continue
            uid = str(rec.get("image_path", "")).strip().split("/")[-2]
            fs = sorted((RAW / uid).glob("*.dcm")) if (RAW / uid).is_dir() else []
            if not fs:
                continue
            try:
                hd = pydicom.dcmread(mp, stop_before_pixels=True)
                arr = pydicom.dcmread(str(fs[0])).pixel_array
                if (int(hd.Rows), int(hd.Columns)) != arr.shape[:2]:
                    continue
                m = pydicom.dcmread(mp).pixel_array
            except Exception:
                continue
            if m.ndim != 2:
                continue
            ys, xs = np.nonzero(m > (m.max() * 0.5) if m.max() > 1 else m > 0)
            if ys.size == 0:
                continue
            box = (int(xs.min()), int(ys.min()),
                   int(xs.max()) + 1, int(ys.max()) + 1)

            v = norm(arr)
            f = scale_to / float(max(v.shape[:2]))
            if f >= 1.0:
                continue
            vs = cv2.resize(v, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            bs = tuple(q * f for q in box)

            a = do_image(v, [(kind, box)], SE_FULL, rng, big, None)
            b = do_image(vs, [(kind, bs)], SE_SMALL, rng, small, None)
            if not (a and b):
                continue
            used += 1
            if save and kind == "calc" and saved < n_save:
                pair(v, box, vs, bs, Path(save), f"dcm_{saved}")
                saved += 1
            if used % 10 == 0:
                print(f"\r  {kind} {used}/{n}   ", end="", flush=True)
        print(f"\r  {kind} {used}건          ")
    return big, small


# ── 표 ───────────────────────────────────────────────────────────────────

def show(title, blocks):
    print("=" * 80)
    print(title)
    print("=" * 80)
    print(f"  {'조건':>14s} {'종류':6s} {'구분':6s} {'건수':>5s} {'한 변':>7s} "
          f"{'알갱이':>8s} {'알갱이 밀도':>12s} {'밝기':>8s}")
    print("  " + "-" * 76)
    for cond, bag in blocks:
        if bag is None:
            continue
        for kind in ("calc", "mass"):
            for tag in ("병변", "대조"):
                r = bag[kind][tag]
                if not r:
                    continue
                print(f"  {cond:>14s} {kind:6s} {tag:6s} {len(r):5d} "
                      f"{np.mean([x['side'] for x in r]):6.0f}px "
                      f"{np.mean([x['specks'] for x in r]):8.1f} "
                      f"{np.mean([x['density'] for x in r]):12.2f} "
                      f"{np.mean([x['bright'] for x in r]):+8.3f}")
            # 병변이 대조군보다 얼마나 앞서나 — 이것이 학습 재료다
            L, C = bag[kind]["병변"], bag[kind]["대조"]
            if L and C:
                dl = np.mean([x['density'] for x in L])
                dc = np.mean([x['density'] for x in C])
                bl = np.mean([x['bright'] for x in L])
                bc = np.mean([x['bright'] for x in C])
                r = dl / dc if dc > 1e-9 else float("inf")
                print(f"  {'':>14s} {kind:6s} {'차이':6s} {'':5s} {'':8s} "
                      f"{'':8s} {'x' + format(r, '.2f'):>12s} "
                      f"{bl - bc:+8.3f}")
            print("  " + "-" * 76)
        cond = ""
    print()


# ── 그림 ─────────────────────────────────────────────────────────────────

def _tile(v, box, size=320):
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = [int(round(q)) for q in box]
    p = max(20, (x1 - x0) // 2)
    H, W = v.shape[:2]
    cy0, cy1 = max(0, y0 - p), min(H, y1 + p)
    cx0, cx1 = max(0, x0 - p), min(W, x1 + p)
    sub = np.clip(v[cy0:cy1, cx0:cx1], 0, 1)
    im = Image.fromarray((sub * 255).astype(np.uint8)).convert("RGB")
    im = im.resize((size, size), Image.NEAREST)
    sx, sy = size / max(1, im.width if False else (cx1 - cx0)), size / max(1, cy1 - cy0)
    d = ImageDraw.Draw(im)
    d.rectangle([(x0 - cx0) * sx, (y0 - cy0) * sy,
                 (x1 - cx0) * sx, (y1 - cy0) * sy],
                outline=(255, 80, 80), width=2)
    return im


def look(v, box, outdir, name, se):
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        _tile(v, box).save(outdir / f"{name}.png")
    except Exception:
        pass


def pair(v, box, vs, bs, outdir, name):
    """원본과 축소본을 같은 화면 크기로 키워 나란히 — 눈으로 본다."""
    try:
        from PIL import Image, ImageDraw
        outdir.mkdir(parents=True, exist_ok=True)
        a, b = _tile(v, box), _tile(vs, bs)
        for im, t in ((a, "원본"), (b, "축소")):
            ImageDraw.Draw(im).text((5, 5), t, fill=(255, 255, 0))
        cv = Image.new("RGB", (648, 320), (0, 0, 0))
        cv.paste(a, (0, 0))
        cv.paste(b, (328, 0))
        cv.save(outdir / f"{name}.png")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco", default="", help="학습용 COCO 주석 (train)")
    ap.add_argument("--n", type=int, default=150, help="1부 종류마다 몇 건")
    ap.add_argument("--n-dcm", type=int, default=40, help="2부 종류마다 몇 건")
    ap.add_argument("--scale-to", type=int, default=0,
                    help="2부 축소 목표. 0 이면 PNG 크기를 따른다")
    ap.add_argument("--split", default="train")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", default="")
    ap.add_argument("--n-save", type=int, default=4)
    a = ap.parse_args()

    print("=" * 80)
    print("학습 영상에 미세석회가 남아 있는가 — 같은 척도 안에서 대조군과 비교")
    print("=" * 80)

    blocks, side = [], a.scale_to or 1024
    cj = find_coco(a.coco)
    if cj is None:
        print("■ 1부  건너뜀 — COCO 주석을 못 찾았다. --coco 로 지정해라\n")
    else:
        bag, side_med = part_png(cj, a.n, SE_SMALL, a.seed, a.save, a.n_save)
        blocks.append(("학습용 PNG", bag))
        if not a.scale_to:
            side = side_med
        print()

    big, small = part_dicom(a.n_dcm, side, a.split, a.seed, a.save, a.n_save)
    if big is not None:
        blocks.append(("원본 DICOM", big))
        blocks.append((f"{side}px 축소", small))
    print()

    show("측정 결과", blocks)

    print("=" * 80)
    print("읽는 법")
    print("=" * 80)
    print("  알갱이 밀도  탑햇으로 잡은 작고 밝은 덩어리 수 / 박스 넓이")
    print("               미세석회 군집의 정의에 해당하는 지표다")
    print("  밝기         박스 평균 − 조직 평균. 종괴 같은 뭉툭한 구조를 잡는다")
    print("  차이         병변 대 대조 — 검출기가 쓸 수 있는 학습 재료의 크기")
    print()
    print("  석회는 알갱이 밀도로, 종괴는 밝기로 대조군과 갈려야 정상이다.")
    print()
    print("  학습용 PNG 에서 석회의 알갱이 배수가 1 에 가까우면")
    print("  -> 검출기는 석회를 배울 재료를 못 받았다. 원인은 축소다.")
    print("     조치  원본 해상도 타일 학습, 또는 더 큰 입력으로 PNG 재생성")
    print("  원본에서도 배수가 1 에 가까우면")
    print("  -> 축소가 아니라 라벨·측정 쪽을 다시 봐야 한다.")
    print("  석회 배수가 원본에서 크고 축소에서 1 에 가까워지면")
    print("  -> 축소가 원인임이 직접 확인된 것이다.")


if __name__ == "__main__":
    main()
