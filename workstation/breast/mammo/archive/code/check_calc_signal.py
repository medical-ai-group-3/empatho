#!/usr/bin/env python
"""
전처리가 미세석회를 지우고 있는지 확인한다.

의심
  검출용 PNG 를 만들 때 상위 0.1%(99.9 백분위) 를 잘라냈다.
  미세석회는 유방촬영에서 가장 밝은 구조이고, 전체 영상에서 차지하는 면적은
  0.1% 보다 작을 수 있다. 그러면 잘려나가는 쪽에 석회가 통째로 들어간다.

  서술어 파이프라인은 '잘린 병변 조각' 안에서 백분위를 계산하므로 석회가
  큰 비중을 차지해 안 잘린다. 검출용은 '전체 영상'에서 계산한다.
  석회 검출만 실패하고 종괴는 되는 것과 앞뒤가 맞는 가설이다.

무엇을 재나
  병변 박스 안에서
    1. 절단선(99.9 백분위)을 넘는 화소 비율   — 얼마나 잘려나가나
    2. 절단 전후의 대비                        — 병변이 배경과 얼마나 구분되나
    3. 병변 안 밝기의 분포                      — 다양성이 뭉개지나
  종괴와 석회를 나눠 비교한다. 종괴가 멀쩡하고 석회만 망가지면 가설이 맞다.

무엇을 안 하나
  GPU 를 안 쓴다. DICOM 을 읽고 통계만 낸다.

사용
  python3 check_calc_signal.py                 # 종류별 40건씩
  python3 check_calc_signal.py --n 100
  python3 check_calc_signal.py --save look/    # 절단 전후 비교 그림
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

HOME = Path.home()
RAW = HOME / "workspace/breast/data/cbis/raw"
INDEX = HOME / "workspace/breast/labels/index"

CLIPS = (99.9, 99.99, 100.0)      # 100 = 절단 안 함


def resolve_full(image_path):
    uid = str(image_path).strip().split("/")[-2]
    d = RAW / uid
    if not d.is_dir():
        return None
    fs = sorted(d.glob("*.dcm"))
    return fs[0] if fs else None


def mask_bbox(mask_path):
    try:
        m = pydicom.dcmread(str(mask_path)).pixel_array
    except Exception:
        return None
    if m.ndim != 2:
        return None
    ys, xs = np.nonzero(m > (m.max() * 0.5) if m.max() > 1 else m > 0)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def stats_one(arr, box, clip_pct):
    """
    한 병변에 대해 절단의 영향을 잰다.
    반환: dict 또는 None
    """
    x0, y0, x1, y1 = box
    H, W = arr.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None

    a = arr.astype(np.float32)
    if clip_pct >= 100:
        lo, hi = float(a.min()), float(a.max())
    else:
        lo = float(np.percentile(a, 100.0 - clip_pct))
        hi = float(np.percentile(a, clip_pct))
        if hi <= lo:
            lo, hi = float(a.min()), float(a.max())

    patch = a[y0:y1, x0:x1]
    # 배경 = 병변 밖의 유방 조직 (아주 어두운 곳은 공기라 제외)
    outside = a[a > np.percentile(a, 20)]

    clipped = float((patch > hi).mean())          # 잘려나가는 화소 비율
    v = np.clip(a, lo, hi)
    v = (v - lo) / (hi - lo + 1e-8)
    vp = v[y0:y1, x0:x1]

    return dict(
        clipped=clipped,
        # 절단 후 최댓값에 붙어버린 화소 비율 — 내부 질감이 뭉개진 정도
        saturated=float((vp >= 0.999).mean()),
        contrast=float(vp.mean() - v.mean()),
        p95=float(np.percentile(vp, 95)),
        spread=float(vp.std()),
        area_frac=float((x1 - x0) * (y1 - y0) / (H * W)),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="종류마다 몇 건")
    ap.add_argument("--split", default="train")
    ap.add_argument("--save", default="", help="절단 전후 비교 그림 폴더")
    ap.add_argument("--n-save", type=int, default=4)
    a = ap.parse_args()

    print("=" * 78)
    print("전처리가 병변 신호를 지우는가 — 절단 백분위별 비교")
    print("=" * 78)

    out = {}
    for kind in ("calc", "mass"):
        csv = INDEX / f"roi_index_{kind}_{a.split}.csv"
        if not csv.is_file():
            print(f"  인덱스 없음: {csv}")
            continue
        df = pd.read_csv(csv)
        rows, used = {c: [] for c in CLIPS}, 0
        saved = 0

        for rec in df.to_dict("records"):
            if used >= a.n:
                break
            mp = str(rec.get("mask_file") or "").strip()
            if not mp or not Path(mp).is_file():
                continue
            full = resolve_full(rec.get("image_path", ""))
            if full is None:
                continue
            try:
                hd = pydicom.dcmread(mp, stop_before_pixels=True)
                arr = pydicom.dcmread(str(full)).pixel_array
                if (int(hd.Rows), int(hd.Columns)) != arr.shape[:2]:
                    continue
            except Exception:
                continue
            bb = mask_bbox(mp)
            if bb is None:
                continue

            ok = True
            for c in CLIPS:
                s = stats_one(arr, bb, c)
                if s is None:
                    ok = False
                    break
                rows[c].append(s)
            if ok:
                used += 1
                if a.save and saved < a.n_save:
                    save_pair(arr, bb, Path(a.save), f"{kind}_{used}")
                    saved += 1
            if used % 10 == 0 and used:
                print(f"\r  {kind} {used}/{a.n}   ", end="", flush=True)
        print(f"\r  {kind} {used}건 분석 완료          ")
        out[kind] = rows

    # ── 표 ─────────────────────────────────────────────────────────────
    print(f"\n{'='*78}")
    print("절단선을 넘어 잘려나가는 화소 비율 (병변 박스 안)")
    print("=" * 78)
    print(f"  {'종류':6s} {'절단':>8s}  {'잘림 평균':>10s} {'잘림 최대':>10s} "
          f"{'포화 화소':>10s} {'대비':>8s} {'내부 편차':>10s}")
    print("  " + "-" * 74)
    for kind, rows in out.items():
        for c in CLIPS:
            r = rows[c]
            if not r:
                continue
            lab = "없음" if c >= 100 else f"{c}"
            print(f"  {kind:6s} {lab:>8s}  "
                  f"{np.mean([x['clipped'] for x in r]):9.2%} "
                  f"{np.max([x['clipped'] for x in r]):10.2%} "
                  f"{np.mean([x['saturated'] for x in r]):10.2%} "
                  f"{np.mean([x['contrast'] for x in r]):+8.3f} "
                  f"{np.mean([x['spread'] for x in r]):10.3f}")
        print()

    print("=" * 78)
    print("읽는 법")
    print("=" * 78)
    print("  잘림 화소  99.9 절단에서 병변 안 화소가 몇 %나 잘려나가는가")
    print("  포화 화소  절단 후 최댓값에 붙어버린 비율 — 내부 질감이 뭉개진 정도")
    print("  대비       병변 평균 밝기 − 영상 평균. 클수록 눈에 띈다")
    print("  내부 편차  병변 안 밝기의 다양성. 작아지면 평평해진 것이다")
    print()
    print("  석회만 '잘림·포화' 가 크고 절단을 없애면 '대비·편차' 가 오르면")
    print("  -> 전처리가 원인이다. PNG 를 다시 만들어야 한다.")
    print("  종류에 상관없이 값이 비슷하면 -> 전처리는 무죄. 백본 적응으로 간다.")


def save_pair(arr, box, outdir, name):
    """절단 있음/없음을 나란히 저장한다 — 눈으로도 확인한다."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    outdir.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = box
    pad = max(60, (x1 - x0) // 2)
    H, W = arr.shape[:2]
    cy0, cy1 = max(0, y0 - pad), min(H, y1 + pad)
    cx0, cx1 = max(0, x0 - pad), min(W, x1 + pad)
    sub = arr[cy0:cy1, cx0:cx1].astype(np.float32)
    a_full = arr.astype(np.float32)

    tiles = []
    for c in (99.9, 100.0):
        if c >= 100:
            lo, hi = float(a_full.min()), float(a_full.max())
        else:
            lo = float(np.percentile(a_full, 100.0 - c))
            hi = float(np.percentile(a_full, c))
        v = np.clip(sub, lo, hi)
        v = (v - lo) / (hi - lo + 1e-8)
        im = Image.fromarray((v * 255).astype(np.uint8)).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([x0 - cx0, y0 - cy0, x1 - cx0, y1 - cy0],
                    outline=(255, 80, 80), width=2)
        d.text((4, 4), "clip 99.9" if c < 100 else "clip 없음", fill=(255, 255, 0))
        tiles.append(im)

    w = sum(t.width for t in tiles) + 8
    h = max(t.height for t in tiles)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    x = 0
    for t in tiles:
        canvas.paste(t, (x, 0))
        x += t.width + 8
    canvas.save(outdir / f"{name}.png")


if __name__ == "__main__":
    main()
