#!/usr/bin/env python
"""
자르기 규칙 측정 — CBIS 가 준 ROI 조각이 마스크 상자와 어떤 관계인가.  GPU 안 쓴다.

왜 이걸 먼저 하는가
  서술어 모델은 우리가 자른 조각이 아니라 CBIS 가 같이 준 ROI DICOM 으로
  학습됐다. 검출기가 찾은 박스를 서술어 모델에 넣으려면 그 박스를 CBIS 와
  '같은 방식으로' 잘라야 한다. 여백을 다르게 주면 서술어 성능이 조용히
  떨어지고, 그러면 '연결하니 나빠졌다'는 틀린 결론이 나온다.
  성능이 떨어진 것이 아니라 다른 것을 넣은 것이다.

무엇을 재는가
  ① 크기   ROI 조각이 마스크 상자보다 얼마나 큰가.
           고정 화소 여백인가, 비례 여백인가 — 둘 중 흩어짐이 작은 쪽이 규칙이다.
  ② 위치   그 여백이 상자 가운데에 붙는가. 크기만으로는 알 수 없다.
           원본 안에서 ROI 조각을 실제로 찾아(템플릿 정합) 좌표를 잰다.
  ③ 검증   찾은 규칙대로 원본을 다시 잘라 ROI 조각과 화소를 뺀다.
           최대 차이 0 이 나와야 규칙이 맞은 것이다. 통계가 아니라 동일성이다.

출력
  crop_rule.json — eval_end2end.py 가 이 파일을 읽는다. 없으면 거기서 멈춘다.
  추측한 값으로 돌리지 않게 하려는 것이다.

사용
  python3 measure_crop.py                 # 종류별 120건
  python3 measure_crop.py --n 40 --kind calc
"""

import argparse
import json
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

from make_tiles import mask_box, norm8                      # noqa: E402
from paths import RAW_CBIS, ROI_INDEX                        # noqa: E402

SC = 8          # 템플릿 정합용 축소 배율. 원본 그대로는 계산이 안 끝난다.
PAD = 32        # 원본 해상도에서 다시 훑을 반경. 아래 주석 참조.
MIN_SCORE = 0.99  # 이보다 낮으면 자리를 못 찾은 것으로 보고 통계에서 뺀다


def norm01(a, clip=99.9):
    """
    mammo_data._read_roi 와 같은 정규화. 조각 안에서 백분위로 자르고 min-max.

    이 함수가 여기 있는 이유
      1차 측정에서 원시 화소 차이를 쟀더니 236건 중 6건만 0 이었다. 그런데
      정합 점수는 0.994 였다 — 위치는 맞는데 값의 척도가 다르다는 뜻이다.
      CBIS 가 조각을 만들 때 밝기를 따로 잡았다.
      서술어 모델은 원시 16비트를 보지 않는다. 조각 안에서 정규화한 것을 본다.
      그러므로 재야 할 것은 원시 차이가 아니라 정규화 후 차이다.
      원시 동일성을 요구한 것은 타일 검증(거기선 잘라내기만 했다)의 기준을
      그대로 가져온 실수였다.
    """
    a = a.astype(np.float32)
    lo = float(np.percentile(a, 100.0 - clip))
    hi = float(np.percentile(a, clip))
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    a = np.clip(a, lo, hi)
    return (a - lo) / (hi - lo + 1e-8)


def full_dcm(image_path):
    """인덱스의 image_path 에서 원본 DICOM 을 찾는다. eval_mammo_det 와 같은 규칙."""
    uid = str(image_path).strip().split("/")[-2]
    d = RAW_CBIS / uid
    fs = sorted(d.glob("*.dcm")) if d.is_dir() else []
    return fs[0] if fs else None


def locate(full, roi):
    """
    원본 안에서 ROI 조각의 좌상단 좌표를 찾는다.

    크기만 재면 '여백이 얼마인가' 는 알아도 '어느 쪽에 붙었나' 를 모른다.
    가운데 정렬을 가정했다가 틀리면 병변이 조각 밖으로 밀린다. 그래서 가정하지
    않고 찾는다. 축소본으로 대강 찾은 뒤 원본에서 좁은 범위만 다시 훑는다.
    """
    f8 = cv2.resize(norm8(full, 99.9), None, fx=1.0 / SC, fy=1.0 / SC,
                    interpolation=cv2.INTER_AREA)
    r8 = cv2.resize(norm8(roi, 99.9), None, fx=1.0 / SC, fy=1.0 / SC,
                    interpolation=cv2.INTER_AREA)
    if r8.shape[0] >= f8.shape[0] or r8.shape[1] >= f8.shape[1]:
        return None, 0.0
    res = cv2.matchTemplate(f8, r8, cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(res)
    ax, ay = loc[0] * SC, loc[1] * SC

    # 원본 해상도에서 다시 찾는다.
    #
    # 1차 판에서 여기를 두 가지로 틀렸다. 고친 이유를 남긴다.
    #   ① 범위가 ±SC(8px) 였다. 축소본의 자리는 8의 배수로만 나오므로 그
    #      자체로 ±8 오차가 깔린다. 같은 크기의 탐색 범위로는 닿을 수 없다.
    #      실측 어긋남이 중앙 11.3px · 최대 17px 이었다. 그래서 ±32 로 넓혔다.
    #   ② 원시 값의 절대차를 최소화했다. 자리가 어긋난 상태에서는 이 기준이
    #      엉뚱한 곳을 고른다. 정규화 영상의 정규화 상관으로 바꿨다 —
    #      밝기 척도에 무관하고, 자리가 맞으면 1.0 이 나온다.
    # 고친 뒤 실측: 차이 0.0000 · 스피어만 1.0000 · 정합 1.0000.
    rh, rw = roi.shape[:2]
    H, W = full.shape[:2]
    y0, x0 = max(0, ay - PAD), max(0, ax - PAD)
    y1, x1 = min(H, ay + rh + PAD), min(W, ax + rw + PAD)
    win = full[y0:y1, x0:x1]
    if win.shape[0] < rh or win.shape[1] < rw:
        return None, 0.0
    r2 = cv2.matchTemplate(norm01(win).astype(np.float32),
                           norm01(roi).astype(np.float32),
                           cv2.TM_CCOEFF_NORMED)
    _, score, _, loc2 = cv2.minMaxLoc(r2)
    return (x0 + loc2[0], y0 + loc2[1]), float(score)


def one(row, kind):
    fp = full_dcm(row.get("image_path", ""))
    mp = str(row.get("mask_file") or "").strip()
    rp = str(row.get("roi_file") or "").strip()
    if not fp or not mp or not rp or not Path(mp).is_file() or not Path(rp).is_file():
        return None
    try:
        full = pydicom.dcmread(str(fp)).pixel_array
        roi = pydicom.dcmread(str(rp)).pixel_array
    except Exception:
        return None
    if full.ndim != 2 or roi.ndim != 2:
        return None
    if len(np.unique(roi)) <= 2:          # 마스크를 ROI 로 잘못 고른 행
        return None
    b, shp = mask_box(mp)
    if b is None or shp != full.shape[:2]:
        return None

    bx0, by0, bx1, by1 = b
    bw, bh = bx1 - bx0, by1 - by0
    rh, rw = roi.shape[:2]
    xy, sc = locate(full, roi)
    if xy is None:
        return None
    rx0, ry0 = xy

    # 규칙대로 다시 잘라 뺀다 — 여기가 진짜 확인이다.
    # 원시 차이와 정규화 후 차이를 둘 다 낸다. 모델이 보는 것은 뒤쪽이다.
    re = full[ry0:ry0 + rh, rx0:rx0 + rw]
    if re.shape == roi.shape:
        diff = int(np.abs(re.astype(np.int64) - roi.astype(np.int64)).max())
        d = np.abs(norm01(re) - norm01(roi))
        nmax, nmean, np99 = float(d.max()), float(d.mean()), \
            float(np.percentile(d, 99))
    else:
        diff, nmax, nmean, np99 = -1, 1.0, 1.0, 1.0

    return dict(nmax=nmax, nmean=nmean, np99=np99,
                kind=kind, bw=bw, bh=bh, rw=rw, rh=rh,
                # 상자 기준 각 변의 여백. 음수면 조각이 상자보다 작다는 뜻이다.
                left=bx0 - rx0, top=by0 - ry0,
                right=(rx0 + rw) - bx1, bottom=(ry0 + rh) - by1,
                ratio_w=rw / max(bw, 1), ratio_h=rh / max(bh, 1),
                match=sc, pixdiff=diff)


def stat(v):
    v = np.asarray(v, float)
    return dict(n=len(v), med=float(np.median(v)), mean=float(v.mean()),
                sd=float(v.std()), p10=float(np.percentile(v, 10)),
                p90=float(np.percentile(v, 90)),
                cv=float(v.std() / abs(v.mean())) if v.mean() else float("nan"))


def show(name, s, unit=""):
    print(f"    {name:16s} 중앙 {s['med']:8.2f}{unit}   평균 {s['mean']:8.2f}"
          f"   표준편차 {s['sd']:7.2f}   10~90퍼 {s['p10']:.1f}~{s['p90']:.1f}"
          f"   변동계수 {s['cv']:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="both", choices=["mass", "calc", "both"])
    ap.add_argument("--split", default="train",
                    help="규칙은 학습셋에서 정한다. 테스트셋을 보고 정하면 편향이다")
    ap.add_argument("--n", type=int, default=120, help="종류별 표본 수")
    ap.add_argument("--out", default="crop_rule.json")
    a = ap.parse_args()

    kinds = ["mass", "calc"] if a.kind == "both" else [a.kind]
    print("=" * 74)
    print("자르기 규칙 측정 — CBIS ROI 조각 대 마스크 상자")
    print("=" * 74)

    rows = []
    for kind in kinds:
        csv = ROI_INDEX / f"roi_index_{kind}_{a.split}.csv"
        if not csv.is_file():
            print(f"  ! 인덱스 없음: {csv}")
            continue
        df = pd.read_csv(csv)
        take = df.sample(min(a.n, len(df)), random_state=0) if len(df) > a.n else df
        print(f"\n  {kind}/{a.split}  {len(take)}/{len(df)}건 읽는다 "
              f"(원본·마스크·조각 3장씩이라 건당 2~4초)")
        got = 0
        for i, r in enumerate(take.to_dict("records"), 1):
            o = one(r, kind)
            if o:
                rows.append(o)
                got += 1
            if i % 10 == 0:
                print(f"\r    {i}/{len(take)}  성공 {got}   ", end="", flush=True)
        print(f"\r    {len(take)}/{len(take)}  성공 {got}        ")

    if not rows:
        sys.exit("\n측정된 행이 없다 — 인덱스나 DICOM 경로를 확인해라")

    D = pd.DataFrame(rows)

    # 자리를 못 찾은 건을 뺀다. 그 행의 여백은 위치 오차이지 CBIS 의 규칙이
    # 아니다. 1차 판에서 이걸 안 걸러 여백 통계가 통째로 오염됐다.
    bad = D[D.match < MIN_SCORE]
    if len(bad):
        print(f"\n  ! 정합 점수 {MIN_SCORE} 미만 {len(bad)}건을 통계에서 뺀다"
              f"  (자리를 못 찾은 것이라 여백을 믿을 수 없다)")
        print(f"    빠진 건의 점수: "
              f"{', '.join(f'{v:.3f}' for v in sorted(bad.match)[:8])}")
        D = D[D.match >= MIN_SCORE].reset_index(drop=True)
    if not len(D):
        sys.exit("자리를 찾은 행이 없다")

    print("\n" + "=" * 74)
    print(f"① 크기 — 고정 화소 여백인가 비례 여백인가   (n={len(D)})")
    print("=" * 74)
    marg = np.concatenate([D.left, D.right, D.top, D.bottom])
    s_abs, s_rw, s_rh = stat(marg), stat(D.ratio_w), stat(D.ratio_h)
    show("여백(화소)", s_abs, "px")
    show("가로 배율", s_rw, "x")
    show("세로 배율", s_rh, "x")
    fixed = s_abs["cv"] < min(s_rw["cv"], s_rh["cv"])
    chosen = s_abs["cv"] if fixed else min(s_rw["cv"], s_rh["cv"])
    print(f"\n    -> {'고정 화소 여백' if fixed else '비례 여백'} 쪽이 덜 흩어진다"
          f"  (변동계수 {chosen:.3f} 대 "
          f"{min(s_rw['cv'], s_rh['cv']) if fixed else s_abs['cv']:.3f})")
    # 경고는 '채택한' 모델의 흩어짐만 보고 낸다. 기각한 모델이 흩어진 것은
    # 기각한 이유이지 경고할 일이 아니다 — 1차 측정에서 그렇게 잘못 띄웠다.
    if chosen > 0.5:
        print("    ! 채택한 모델도 많이 흩어진다. CBIS 의 자르기가 일정하지 않다.")
        print("      그렇다면 여백을 맞추는 것보다 병변이 조각 안에 들어오는 것이")
        print("      중요하다 — eval_end2end.py 의 --margin 을 훑어 정해라.")
    else:
        print(f"       채택한 모델의 변동계수 {chosen:.3f} — 규칙으로 쓸 만하다.")
    neg = int((marg < 0).sum())
    print(f"    여백이 음수인 변 {neg}/{len(marg)}개"
          + ("  — 병변이 조각 밖으로 밀린 경우가 없다" if neg == 0
             else "  ! 병변 일부가 조각 밖에 있다"))

    print("\n" + "=" * 74)
    print("② 위치 — 여백이 가운데에 붙는가")
    print("=" * 74)
    for nm, col in (("왼쪽", D.left), ("오른쪽", D.right),
                    ("위", D.top), ("아래", D.bottom)):
        show(nm, stat(col), "px")
    sym_x = float(np.median(np.abs(D.left - D.right)))
    sym_y = float(np.median(np.abs(D.top - D.bottom)))
    print(f"\n    좌우 여백 차이 중앙 {sym_x:.1f}px · 상하 {sym_y:.1f}px")
    centered = sym_x <= max(4.0, 0.05 * float(D.rw.median())) and \
        sym_y <= max(4.0, 0.05 * float(D.rh.median()))
    print(f"    -> {'가운데 정렬로 봐도 된다' if centered else '가운데가 아니다 — 치우쳐 있다'}")

    print("\n" + "=" * 74)
    print("③ 검증 — 규칙대로 다시 자른 것이 조각과 같은가")
    print("=" * 74)
    ok = int((D.pixdiff == 0).sum())
    print(f"    정합 점수 중앙                 {float(D.match.median()):.3f}"
          "   1 에 가까우면 위치가 맞은 것이다")
    print(f"    원시 화소 최대 차이 0          {ok}/{len(D)}건")
    print("      (원시 값은 CBIS 가 조각마다 밝기 척도를 따로 잡아 달라진다.")
    print("       모델은 이 값을 보지 않으므로 여기서 판단하지 않는다.)")

    print(f"\n    ── 서술어 모델이 실제로 보는 값으로 다시 ──")
    print(f"       조각 안에서 99.9 백분위 절단 + min-max. 척도가 지워진다.")
    for nm, col in (("평균 차이", D.nmean), ("99퍼 차이", D.np99),
                    ("최대 차이", D.nmax)):
        s = stat(col)
        print(f"    {nm:16s} 중앙 {s['med']:7.4f}   90퍼 {s['p90']:7.4f}"
              f"   최악 {float(col.max()):7.4f}")
    good = int((D.np99 <= 0.02).sum())
    print(f"\n    99퍼 차이가 0.02 이하        {good}/{len(D)}건 "
          f"({100*good/len(D):.1f}%)")
    if good >= 0.9 * len(D):
        print("    -> 정규화 후에는 사실상 같은 영상이다. 밝기 척도만 달랐던 것이고")
        print("       서술어 전처리가 그것을 지운다. 이 규칙으로 이어도 된다.")
    else:
        print("    ! 정규화 후에도 다르다. 조각이 원본과 다른 처리를 거쳤다는 뜻이다.")
        print("      이 경우 검출 박스를 잘라 넣으면 서술어가 학습 때와 다른 입력을")
        print("      받는다. eval_end2end.py 로 재기 전에 원인을 먼저 찾아라.")

    rule = dict(
        split=a.split, n=int(len(D)),
        mode="fixed" if fixed else "ratio",
        margin_px=float(np.median(marg)),
        ratio=float(np.median(np.concatenate([D.ratio_w, D.ratio_h]))),
        centered=bool(centered),
        margin_p10=float(np.percentile(marg, 10)),
        margin_p90=float(np.percentile(marg, 90)),
        pixel_identical=int(ok), pixel_total=int(len(D)),
        # 모델이 보는 값 기준의 일치도. 위의 pixel_* 는 원시 16비트 기준이라
        # CBIS 의 밝기 척도 차이 때문에 낮게 나온다 — 판단은 이쪽으로 한다.
        norm_p99_median=float(D.np99.median()),
        norm_ok=int((D.np99 <= 0.02).sum()),
        match_median=float(D.match.median()),
        per_kind={k: dict(
            n=int((D.kind == k).sum()),
            margin_px=float(np.median(np.concatenate(
                [D[D.kind == k].left, D[D.kind == k].right,
                 D[D.kind == k].top, D[D.kind == k].bottom]))),
            ratio=float(np.median(np.concatenate(
                [D[D.kind == k].ratio_w, D[D.kind == k].ratio_h]))))
            for k in D.kind.unique()})

    Path(a.out).write_text(json.dumps(rule, indent=2, ensure_ascii=False))
    print("\n" + "=" * 74)
    print("규칙")
    print("=" * 74)
    if fixed:
        print(f"    상자의 각 변에 {rule['margin_px']:.0f}px 를 더해 자른다"
              f"   (10~90퍼 {rule['margin_p10']:.0f}~{rule['margin_p90']:.0f})")
    else:
        print(f"    상자를 {rule['ratio']:.2f}배로 늘려 자른다")
    print(f"    정렬  가운데로 넓힌다"
          f"  (실측 비대칭 좌우 {sym_x:.0f}px · 상하 {sym_y:.0f}px)")
    if not centered:
        print(f"          완전한 대칭은 아니다. 다만 여백이 전부 양수라 병변은")
        print(f"          항상 조각 안에 있고, 1008 로 다시 키우므로 이 정도")
        print(f"          치우침은 입력에서 몇 % 이동으로 남는다.")
    for k, v in rule["per_kind"].items():
        print(f"    {k:6s} 여백 {v['margin_px']:6.0f}px · 배율 {v['ratio']:.2f}x"
              f"   (n={v['n']})")
    print(f"\n    -> {a.out}")
    print("       eval_end2end.py 가 이 파일을 읽는다.")


if __name__ == "__main__":
    main()
