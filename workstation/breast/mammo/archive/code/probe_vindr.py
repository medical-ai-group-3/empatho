#!/usr/bin/env python
"""
VinDr-Mammo 라벨 점검 — 영상 없이 CSV 두 개만 읽는다.

알아야 하는 것
  1) 컬럼 구조가 무엇인가 (문서 기억이 아니라 실제 파일 기준)
  2) BI-RADS 를 4a/4b/4c 로 세분하는가  ← 규칙표 설계에 직결
  3) 소견 종류별로 실제 매겨진 등급 분포는 어떤가
     우리 규칙표의 등급 배정이 임상 현실과 어긋나지 않는지 대조할 근거
  4) 바운딩 박스 크기 분포 — 나중에 영상을 받으면 크롭 설계에 쓴다
  5) 영상이 몇 장인지 (기획서의 "2만건"과 대조)

읽기만 한다. GPU 를 쓰지 않으므로 학습과 동시에 돌려도 된다.
"""

import sys
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

LAB = Path.home() / "workspace/breast/labels"
FIND = LAB / "finding_annotations.csv"
BRST = LAB / "breast-level_annotations.csv"

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def head(t):
    print("\n" + "=" * 68)
    print(t)
    print("=" * 68)


def show_counts(s, name, top=20):
    vc = s.value_counts(dropna=False)
    print(f"  {name} — 고유값 {len(vc)}개")
    for k, v in vc.head(top).items():
        print(f"    {str(k)[:52]:54s} {v:6d}  ({100*v/len(s):5.1f}%)")
    if len(vc) > top:
        print(f"    ... 외 {len(vc)-top}종")


def main():
    for p in (FIND, BRST):
        if not p.exists():
            sys.exit(f"없음: {p}")

    f = pd.read_csv(FIND)
    b = pd.read_csv(BRST)

    head("[1] 파일 개요")
    print(f"  finding_annotations       {f.shape[0]:7d}행 × {f.shape[1]}열")
    print(f"  breast-level_annotations  {b.shape[0]:7d}행 × {b.shape[1]}열")
    print(f"\n  finding 컬럼: {list(f.columns)}")
    print(f"  breast  컬럼: {list(b.columns)}")

    for col in ("image_id", "study_id"):
        if col in f.columns:
            print(f"\n  finding 의 고유 {col}: {f[col].nunique():,}개")
        if col in b.columns:
            print(f"  breast  의 고유 {col}: {b[col].nunique():,}개")

    head("[2] BI-RADS — 4a/4b/4c 세분 여부")
    for df, col, nm in [(f, "finding_birads", "소견별"), (b, "breast_birads", "유방별"),
                        (f, "breast_birads", "소견표의 유방별")]:
        if col in df.columns:
            show_counts(df[col], f"{nm} {col}")
            vals = " ".join(sorted(str(v) for v in df[col].dropna().unique()))
            sub = any(x in vals.lower() for x in ("4a", "4b", "4c"))
            print(f"    -> 4 세분 {'있음 ★ 규칙표와 직접 대응 가능' if sub else '없음 — 4 로 통합해 비교해야 한다'}")
            print()

    head("[3] 소견 종류")
    cat = next((c for c in f.columns if "categor" in c.lower()), None)
    if cat:
        show_counts(f[cat], cat, top=25)

    head("[4] 소견 종류 × 등급  (규칙표 대조용 핵심)")
    fb = "finding_birads" if "finding_birads" in f.columns else None
    if cat and fb:
        ct = pd.crosstab(f[cat], f[fb])
        keep = ct.sum(1).sort_values(ascending=False).head(12).index
        print(ct.loc[keep].to_string())
        print("\n  행 정규화 (각 소견이 어느 등급을 받는가, %)")
        pct = (ct.loc[keep].T / ct.loc[keep].sum(1)).T * 100
        print(pct.round(1).to_string())
    else:
        print("  소견 종류 또는 등급 컬럼을 찾지 못했다")

    head("[5] 바운딩 박스 — 나중에 크롭할 때 쓴다")
    need = [c for c in ("xmin", "ymin", "xmax", "ymax") if c in f.columns]
    if len(need) == 4:
        d = f.dropna(subset=need)
        w = (d["xmax"] - d["xmin"]).to_numpy(float)
        h = (d["ymax"] - d["ymin"]).to_numpy(float)
        ok = (w > 0) & (h > 0)
        w, h = w[ok], h[ok]
        print(f"  박스 있는 행 {ok.sum():,} / 전체 {len(f):,}")
        for nm, v in (("너비", w), ("높이", h)):
            print(f"    {nm}  최소 {v.min():6.0f} · 중앙 {np.median(v):6.0f} · "
                  f"95퍼 {np.percentile(v,95):6.0f} · 최대 {v.max():6.0f}")
        ar = np.maximum(w, h) / np.minimum(w, h)
        print(f"    종횡비 중앙 {np.median(ar):.2f} · 75퍼 {np.percentile(ar,75):.2f} "
              f"· 95퍼 {np.percentile(ar,95):.2f}")
        print(f"\n  참고 — CBIS ROI 는 중앙 323×329 였다. 크롭 크기를 맞춰야 분포가 어긋나지 않는다.")
    else:
        print(f"  박스 컬럼 부족: {need}")

    head("[6] 밀도 · 뷰")
    for col in ("breast_density", "view_position", "laterality", "split"):
        for df, nm in ((f, "finding"), (b, "breast")):
            if col in df.columns:
                show_counts(df[col], f"[{nm}] {col}", top=8)
                break

    head("판정")
    print("  · 4 세분 있음   -> 규칙표의 4a/4b/4c 를 그대로 채점할 수 있다")
    print("  · 4 세분 없음   -> 우리 출력도 4 로 합쳐 비교한다 (해상도는 낮아진다)")
    print("  · 소견×등급 표  -> 규칙표가 같은 소견에 비슷한 등급을 주는지 대조한다")
    print("  · 영상은 아직 없다. 종단 검증을 하려면 PhysioNet 에서 받아야 한다.")


if __name__ == "__main__":
    main()
