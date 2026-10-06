#!/usr/bin/env python
"""
CBIS 와 VinDr 의 화소 간격을 잰다 — eval_vindr --target-mm 에 넣을 값을 구한다.

왜 필요한가
  VinDr 외부 검증에서 운영점 민감도가 미세석회 57.9 → 43.2%,
  종괴 56.4 → 41.7% 로 떨어졌다. 둘 다 -14.7%p 다.

  가설이 둘이다.
    ① 해상도    VinDr 이 0.085mm/px 라 낱개 미세석회가 2.4~5.9px 로 찍힌다.
                우리 검출기는 CBIS 의 더 큰 알갱이를 보고 배웠다.
    ② 라벨 정의  CBIS 정답은 조직검사 확정, VinDr 정답은 판독의가 표시만 한 것.
                조직검사까지 간 병변이 평균적으로 더 뚜렷하다.

  ① 이 맞으면 VinDr 을 CBIS 화소 간격으로 키웠을 때 미세석회가 회복돼야 한다.
  그 실험을 하려면 CBIS 의 화소 간격을 먼저 알아야 한다. 그게 이 스크립트다.

  ※ 예상은 ② 다. ① 이라면 종류별로 다르게 떨어졌어야 하는데 똑같이 떨어졌다.
    그래도 재서 확인한다 — 예측이 이미 한 번 빗나갔다.

주의 — CBIS 는 1990년대 필름 스캔이다. PixelSpacing 태그가 없거나 믿을 수
       없을 수 있다. 그래서 태그가 몇 장에 있는지부터 세고, 없으면 영상 크기
       비율로 대신 추정한다. 둘을 구분해서 보고한다.

화소는 안 읽는다(헤더만). 몇 초면 끝나고 GPU 를 안 쓴다.

사용
  python3 measure_spacing.py
  python3 measure_spacing.py --n 200
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

try:
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import RAW_CBIS, RAW_VINDR                      # noqa: E402


def spacings(root, n, min_long=0, exts=("*.dcm", "*.dicom")):
    """
    (간격목록, 긴변목록, 태그있음, 읽은수, 제외수)

    min_long — 긴 변이 이보다 작으면 제외한다.

    ⚠ 왜 필요한가. CBIS 폴더에는 전체 유방 촬영 · ROI 조각 · 마스크가 같은
      확장자로 섞여 있다. 구분 없이 긁으면 292px 짜리 ROI 조각이 표본에
      들어가 중앙값을 끌어내린다 — 첫 측정에서 실제로 그랬고, 거기서 나온
      배율은 못 쓴다. 전체 촬영만 남기려면 크기로 거를 수밖에 없다.
    """
    files = []
    for e in exts:
        files += sorted(Path(root).rglob(e))
    files = files[:n * 4 if min_long else n]
    mm, longside, has, drop = [], [], 0, 0
    for f in files:
        if len(longside) >= n:
            break
        try:
            d = pydicom.dcmread(str(f), stop_before_pixels=True)
        except Exception:
            continue
        r, c = getattr(d, "Rows", None), getattr(d, "Columns", None)
        if not (r and c):
            continue
        L = max(int(r), int(c))
        if min_long and L < min_long:
            drop += 1
            continue
        longside.append(L)
        ps = getattr(d, "PixelSpacing", None) or \
            getattr(d, "ImagerPixelSpacing", None)
        if ps:
            try:
                mm.append(float(ps[0]))
                has += 1
            except Exception:
                pass
    return mm, longside, has, len(longside), drop


def show(name, mm, ls, has, tot, drop=0):
    print(f"\n  {name}")
    print(f"    표본 {tot}장 · PixelSpacing 있음 {has}장 ({has/max(tot,1):.0%})"
          + (f" · 작아서 제외 {drop}장" if drop else ""))
    if ls:
        v = np.array(ls)
        lo, hi = np.percentile(v, 10), np.percentile(v, 90)
        print(f"    긴 변  중앙 {np.median(v):,.0f}px (10~90퍼 {lo:,.0f}~{hi:,.0f})")
        if hi > 0 and lo / hi < 0.5:
            print(f"    ★ 10퍼와 90퍼가 2배 넘게 벌어졌다 — 크기가 다른 파일이")
            print(f"      섞여 있다는 뜻이다. --min-long 을 올려 다시 잴 것.")
    if mm:
        v = np.array(mm)
        print(f"    화소간격 중앙 {np.median(v):.4f}mm "
              f"(범위 {v.min():.4f}~{v.max():.4f})")
        u = Counter(round(x, 4) for x in mm)
        if len(u) <= 5:
            print("    값 분포  " + " · ".join(f"{k}mm×{c}" for k, c in
                                              u.most_common()))
        return float(np.median(v))
    print("    ! PixelSpacing 이 없다")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120, help="각 데이터셋 표본 수")
    ap.add_argument("--min-long", type=int, default=3000,
                    help="긴 변이 이보다 작은 파일은 제외한다. CBIS 폴더에 "
                         "ROI 조각(수백 px)이 섞여 있어 필요하다. 0 이면 안 거른다")
    a = ap.parse_args()

    print("=" * 74)
    print("화소 간격 실측 — CBIS vs VinDr  (헤더만 읽는다 · GPU 안 씀)")
    print("=" * 74)

    if a.min_long:
        print(f"  긴 변 {a.min_long:,}px 미만은 제외한다 "
              f"(CBIS 폴더의 ROI 조각을 걸러내기 위해서다)")
    c_mm, c_ls, c_has, c_tot, c_dr = spacings(RAW_CBIS, a.n, a.min_long)
    v_mm, v_ls, v_has, v_tot, v_dr = spacings(RAW_VINDR, a.n, a.min_long)
    cbis = show("CBIS-DDSM  (필름 스캔)", c_mm, c_ls, c_has, c_tot, c_dr)
    vindr = show("VinDr-Mammo  (디지털 촬영)", v_mm, v_ls, v_has, v_tot, v_dr)

    print("\n" + "─" * 74)
    if cbis and vindr:
        r = vindr / cbis
        print(f"  두 데이터셋 다 PixelSpacing 이 있다.")
        print(f"  VinDr / CBIS = {vindr:.4f} / {cbis:.4f} = {r:.3f}배")
        if r > 1:
            print(f"  VinDr 화소가 {r:.2f}배 굵다 → 같은 병변이 화소로 "
                  f"{1/r:.2f}배 작게 찍힌다")
        print(f"\n  다음 실험")
        print(f"    python3 eval_vindr.py --target-mm {cbis:.4f} \\")
        print(f"        --save-json ../../archive/outputs/vindr_dets_scaled.json")
        print(f"    → VinDr 을 {r:.2f}배로 키워 CBIS 화소 간격에 맞춘다.")
        print(f"      영상이 커지므로 타일 수가 {r**2:.1f}배로 늘어 시간도 그만큼 는다.")
    elif vindr and not cbis:
        print("  CBIS 에 PixelSpacing 이 없다 — 필름 스캔이라 흔한 일이다.")
        print("  물리 단위로 맞출 수 없으므로 긴 변 비율로 대신한다.")
        if c_ls and v_ls:
            r = float(np.median(c_ls)) / float(np.median(v_ls))
            print(f"    CBIS 긴 변 {np.median(c_ls):,.0f}px · "
                  f"VinDr {np.median(v_ls):,.0f}px  →  {r:.3f}배")
            print(f"    같은 크기의 유방이라고 보면 VinDr 을 {r:.2f}배 키우면 된다.")
            print(f"\n    python3 eval_vindr.py --target-mm {vindr/r:.4f} \\")
            print(f"        --save-json ../../archive/outputs/vindr_dets_scaled.json")
            print(f"\n    ⚠ 이건 '유방 크기가 두 집단에서 같다' 는 가정이 깔린 값이다.")
            print(f"      물리 측정이 아니다. 결과를 그렇게 적을 것.")
    else:
        print("  화소 간격을 못 구했다. 경로를 확인할 것:")
        print(f"    CBIS  {RAW_CBIS}")
        print(f"    VinDr {RAW_VINDR}")

    print("\n  ※ 이 실험이 가리는 것")
    print("    미세석회가 회복되면  → 해상도가 원인")
    print("    회복 안 되면        → 라벨 정의 차이(조직검사 확정 vs 판독의 표시)")
    print("                          해상도 가설은 폐기한다")
    print("=" * 74)


if __name__ == "__main__":
    main()
