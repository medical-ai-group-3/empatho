#!/usr/bin/env python
"""
자르기 불일치의 원인 진단 — 정렬 문제인가 밝기 변환 문제인가.  GPU 안 쓴다.

왜
  measure_crop.py 가 정규화 후에도 조각과 원본이 다르다고 했다
  (99퍼 차이 중앙 0.216, 0.02 이하가 7.6%). 그런데 평균 차이는 0.0575 로 작다.
  차이가 전면이 아니라 일부에 몰려 있다는 뜻이고, 그 모양은 두 가지 원인에서
  똑같이 나온다. 어느 쪽인지에 따라 대응이 완전히 달라지므로 가른다.

  ① 정렬이 몇 px 어긋남   -> 정렬을 고치면 끝난다
  ② 비선형 밝기 변환      -> 히스토그램 정합이 필요하다
  ③ 아예 다른 영상        -> 이 경로를 포기하고 다른 방법을 찾는다

무엇을 재는가
  A 정렬 재탐색
      measure_crop 의 미세 조정은 '원시 값의 절대차 최소' 로 자리를 골랐다.
      척도가 다르면 그 기준이 틀린 자리를 고른다. 여기서는 정규화한 영상에서
      정규화 상관으로 다시 찾는다 — 척도에 무관한 기준이다.
      탐색 범위도 ±8 에서 ±24 로 넓힌다. 옛 범위는 축소 정합의 오차 범위와
      같아서 여유가 없었다.

  B 순위 상관 (스피어만)
      어떤 단조 변환에도 변하지 않는다. 1 에 가까우면 두 영상은 같은 장면이고
      값만 다시 매겨진 것이다 — 즉 ② 다. 낮으면 같은 장면이 아니다 — ③ 이다.

  C 히스토그램 정합 후 차이
      ② 라면 원본 조각의 값을 조각의 히스토그램에 맞춰 옮긴 뒤에는 차이가
      사라져야 한다. 사라지면 대응이 확정된다.

  D 차이가 어디에 있나
      경계(고기울기)에 몰려 있으면 정렬 문제다. 고르게 퍼져 있으면 밝기 문제다.

사용
  python3 diag_crop.py               # 20건
  python3 diag_crop.py --n 40 --kind calc
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import cv2
    import numpy as np
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from measure_crop import full_dcm, norm01                      # noqa: E402
from make_tiles import norm8                                    # noqa: E402
from paths import ROI_INDEX                                     # noqa: E402

SC = 8
PAD = 24        # 원본 해상도에서 다시 훑을 반경


def coarse(full, roi):
    """1/8 축소본에서 대략의 자리를 찾는다. measure_crop 과 같다."""
    f8 = cv2.resize(norm8(full, 99.9), None, fx=1 / SC, fy=1 / SC,
                    interpolation=cv2.INTER_AREA)
    r8 = cv2.resize(norm8(roi, 99.9), None, fx=1 / SC, fy=1 / SC,
                    interpolation=cv2.INTER_AREA)
    if r8.shape[0] >= f8.shape[0] or r8.shape[1] >= f8.shape[1]:
        return None
    res = cv2.matchTemplate(f8, r8, cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(res)
    return loc[0] * SC, loc[1] * SC


def refine(full, roi, ax, ay):
    """
    원본 해상도에서 다시 찾는다. 정규화한 영상에 정규화 상관을 쓴다 —
    밝기 척도가 달라도 자리를 옳게 고른다. 옛 방식(원시 절대차)의 결함이 여기다.
    """
    rh, rw = roi.shape[:2]
    H, W = full.shape[:2]
    y0, x0 = max(0, ay - PAD), max(0, ax - PAD)
    y1, x1 = min(H, ay + rh + PAD), min(W, ax + rw + PAD)
    win = full[y0:y1, x0:x1]
    if win.shape[0] < rh or win.shape[1] < rw:
        return None, None
    res = cv2.matchTemplate(norm01(win).astype(np.float32),
                            norm01(roi).astype(np.float32),
                            cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    return (x0 + loc[0], y0 + loc[1]), float(score)


def spearman(a, b, n=20000):
    """순위 상관. 단조 변환에 무관하므로 '같은 장면인가' 만 묻는다."""
    a, b = a.ravel(), b.ravel()
    if a.size > n:
        idx = np.random.default_rng(0).choice(a.size, n, replace=False)
        a, b = a[idx], b[idx]
    ra = np.empty(a.size); ra[np.argsort(a)] = np.arange(a.size)
    rb = np.empty(b.size); rb[np.argsort(b)] = np.arange(b.size)
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / d) if d else 0.0


def hist_match(src, ref, n=512):
    """src 의 값을 ref 의 분포로 옮긴다. 단조 변환이면 이걸로 차이가 사라진다."""
    q = np.linspace(0, 100, n)
    return np.interp(src, np.percentile(src, q), np.percentile(ref, q))


def edge_split(roi_n, d):
    """차이가 경계에 몰려 있는지. 몰려 있으면 정렬 문제다."""
    g = np.abs(cv2.Sobel(roi_n.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)) \
        + np.abs(cv2.Sobel(roi_n.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3))
    thr = np.percentile(g, 90)
    hi = g >= thr
    return float(d[hi].mean()), float(d[~hi].mean())


def one(row):
    fp = full_dcm(row.get("image_path", ""))
    rp = str(row.get("roi_file") or "").strip()
    if not fp or not rp or not Path(rp).is_file():
        return None
    try:
        full = pydicom.dcmread(str(fp)).pixel_array
        roi = pydicom.dcmread(str(rp)).pixel_array
    except Exception:
        return None
    if full.ndim != 2 or roi.ndim != 2 or len(np.unique(roi)) <= 2:
        return None
    c = coarse(full, roi)
    if c is None:
        return None

    # 옛 방식: 원시 절대차 최소, ±8
    rh, rw = roi.shape[:2]
    old, oldd = (c[0], c[1]), None
    for dy in range(-SC, SC + 1):
        for dx in range(-SC, SC + 1):
            y, x = c[1] + dy, c[0] + dx
            if y < 0 or x < 0 or y + rh > full.shape[0] or x + rw > full.shape[1]:
                continue
            v = np.abs(full[y:y + rh, x:x + rw].astype(np.int64)
                       - roi.astype(np.int64)).mean()
            if oldd is None or v < oldd:
                oldd, old = v, (x, y)

    new, score = refine(full, roi, c[0], c[1])
    if new is None:
        return None

    rn = norm01(roi)
    out = dict(shift=float(np.hypot(new[0] - old[0], new[1] - old[1])),
               score=score)
    for tag, xy in (("old", old), ("new", new)):
        sub = full[xy[1]:xy[1] + rh, xy[0]:xy[0] + rw]
        if sub.shape != roi.shape:
            return None
        d = np.abs(norm01(sub) - rn)
        out[f"{tag}_p99"] = float(np.percentile(d, 99))
        out[f"{tag}_mean"] = float(d.mean())
    sub = full[new[1]:new[1] + rh, new[0]:new[0] + rw]
    out["rho"] = spearman(norm01(sub), rn)
    dm = np.abs(hist_match(norm01(sub), rn) - rn)
    out["hm_p99"] = float(np.percentile(dm, 99))
    out["hm_mean"] = float(dm.mean())
    e, f = edge_split(rn, np.abs(norm01(sub) - rn))
    out["edge"], out["flat"] = e, f
    return out


def med(D, c):
    return float(np.median(D[c]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="both", choices=["mass", "calc", "both"])
    ap.add_argument("--split", default="train")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()

    print("=" * 74)
    print("자르기 불일치 진단 — 정렬인가 밝기인가")
    print("=" * 74)

    rows = []
    for kind in (["mass", "calc"] if a.kind == "both" else [a.kind]):
        csv = ROI_INDEX / f"roi_index_{kind}_{a.split}.csv"
        if not csv.is_file():
            continue
        df = pd.read_csv(csv)
        take = df.sample(min(a.n, len(df)), random_state=0)
        print(f"\n  {kind}  {len(take)}건")
        for i, r in enumerate(take.to_dict("records"), 1):
            o = one(r)
            if o:
                o["kind"] = kind
                rows.append(o)
            print(f"\r    {i}/{len(take)}  성공 {len(rows)}   ", end="", flush=True)
        print()

    if not rows:
        sys.exit("측정된 행이 없다")
    D = pd.DataFrame(rows)

    print("\n" + "=" * 74)
    print(f"A. 정렬을 다시 찾으면 나아지는가   (n={len(D)})")
    print("=" * 74)
    print(f"    옛 자리(원시 절대차 · ±8)    99퍼 차이 중앙 {med(D,'old_p99'):.4f}"
          f"   평균 {med(D,'old_mean'):.4f}")
    print(f"    새 자리(정규화 상관 · ±24)   99퍼 차이 중앙 {med(D,'new_p99'):.4f}"
          f"   평균 {med(D,'new_mean'):.4f}")
    print(f"    두 자리의 거리 중앙 {med(D,'shift'):.1f}px"
          f"   (최대 {float(D['shift'].max()):.0f}px)")
    print(f"    새 자리의 정합 점수 중앙 {med(D,'score'):.4f}")
    better = med(D, "new_p99") < med(D, "old_p99") * 0.5
    print(f"\n    -> 정렬을 고쳐서 절반 이하로 줄었나: "
          f"{'예 — 정렬이 원인이었다' if better else '아니오'}")

    print("\n" + "=" * 74)
    print("B. 같은 장면인가 (순위 상관 · 단조 변환에 무관)")
    print("=" * 74)
    print(f"    스피어만 중앙 {med(D,'rho'):.4f}   "
          f"10퍼 {float(np.percentile(D['rho'],10)):.4f}   "
          f"최저 {float(D['rho'].min()):.4f}")
    if med(D, "rho") > 0.95:
        print("    -> 같은 장면이다. 값만 다시 매겨졌다.")
    elif med(D, "rho") > 0.8:
        print("    -> 대체로 같은 장면이나 어긋남이 있다.")
    else:
        print("    ! 같은 장면이라 보기 어렵다. 조각이 다른 영상에서 왔을 수 있다.")

    print("\n" + "=" * 74)
    print("C. 히스토그램을 맞추면 사라지는가")
    print("=" * 74)
    print(f"    정합 전  99퍼 {med(D,'new_p99'):.4f}   평균 {med(D,'new_mean'):.4f}")
    print(f"    정합 후  99퍼 {med(D,'hm_p99'):.4f}   평균 {med(D,'hm_mean'):.4f}")
    ok = int((D["hm_p99"] <= 0.05).sum())
    print(f"    정합 후 99퍼 0.05 이하  {ok}/{len(D)}건 ({100*ok/len(D):.0f}%)")

    print("\n" + "=" * 74)
    print("D. 차이가 어디에 있나")
    print("=" * 74)
    print(f"    경계(상위 10% 기울기)  평균 차이 {med(D,'edge'):.4f}")
    print(f"    평탄한 곳              평균 차이 {med(D,'flat'):.4f}")
    ratio = med(D, "edge") / max(med(D, "flat"), 1e-9)
    print(f"    비  {ratio:.2f}배")
    print("    -> " + ("경계에 몰려 있다. 정렬 문제의 특징이다." if ratio > 2
                       else "고르게 퍼져 있다. 밝기 변환 문제의 특징이다."))

    print("\n" + "=" * 74)
    print("판정")
    print("=" * 74)
    if med(D, "rho") <= 0.8:
        print("  ③ 조각이 원본과 같은 장면이 아니다.")
        print("     원본에서 잘라 서술어에 넣는 경로 자체를 다시 생각해야 한다.")
    elif better:
        print("  ① 정렬이 원인이었다. measure_crop 의 미세 조정을 정규화 상관으로")
        print("     바꾸고 범위를 넓히면 해결된다.")
    elif ok >= 0.8 * len(D):
        print("  ② 비선형 밝기 변환이다. 자르기 전처리에 히스토그램 정합을 넣는다.")
        print("     다만 검출 시점에는 맞출 기준 조각이 없다 — 학습 조각들의 평균")
        print("     히스토그램을 기준으로 삼아야 한다. 그 자체가 근사다.")
    else:
        print("  ①②③ 어느 하나로 설명되지 않는다. 위 네 표를 그대로 보내라.")
    print("\n  어느 경우든 결정은 재서 한다 — eval_end2end.py 의 ① 정답 박스 경로를")
    print("  eval_e2e.py 의 알려진 값(조직검사 84.3%)과 비교하면 이 불일치가")
    print("  실제로 얼마를 깎는지 바로 나온다. 원인을 몰라도 대가는 측정된다.")


if __name__ == "__main__":
    main()
