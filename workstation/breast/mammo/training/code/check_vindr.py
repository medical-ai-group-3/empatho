#!/usr/bin/env python
"""
VinDr 외부 검증 전 점검 — 무엇을 받았고 CBIS 와 무엇이 다른가.  GPU 안 쓴다.

왜 평가기보다 먼저인가
  VinDr 은 CBIS 와 촬영 방식이 다르다(디지털 대 필름 스캔). 그 차이가
  파이프라인의 어디를 건드리는지 모르고 평가부터 돌리면, 나온 숫자가
  '외부 데이터에서의 성능' 인지 '전처리가 깨진 결과' 인지 구분이 안 된다.

무엇을 확인하나
  ① 받은 영상과 라벨이 맞는가 (개수 · 짝 · 읽히는가)
  ② PhotometricInterpretation
       CBIS 는 400/400 이 MONOCHROME2 였다. VinDr 에 MONOCHROME1 이 섞이면
       밝기가 반전돼 tissue_mask 가 공기를 조직으로 잡는다.
       오류는 안 나고 숫자만 조용히 이상해진다. 반드시 먼저 본다.
  ③ VOI LUT · WindowCenter/Width
       CBIS 에는 없었다. 있으면 화면용 밝기 변환이 걸려 있다는 뜻이고,
       적용하고 안 하고에 따라 영상이 크게 달라진다.
  ④ BitsStored · 화소값 범위 · 영상 크기
  ⑤ tissue_mask 가 제대로 도는가 — 조직 비율이 CBIS 와 비슷한가
       CBIS 는 유방이 화면의 30~60% 다. 90% 가 나오면 반전이거나 마스크 실패다.
  ⑥ 우리가 검출하는 두 종류(Mass · Suspicious Calcification)가 몇 건인가
       VinDr 에는 비대칭·구조왜곡 등 우리가 안 찾는 소견도 있다.

사용
  python3 check_vindr.py
  python3 check_vindr.py --n 40        # 화소까지 볼 표본 수
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from make_tiles import norm8, tissue_bbox, tissue_mask         # noqa: E402
from paths import LABELS, RAW_VINDR                            # noqa: E402

# 우리가 검출하는 것. VinDr 의 소견 이름은 이 두 개만 쓴다.
WANT = {"Mass": "mass", "Suspicious Calcification": "calcification"}


def head(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def find_csv():
    for c in (LABELS / "finding_annotations.csv",
              LABELS / "labels" / "finding_annotations.csv",
              RAW_VINDR / "finding_annotations.csv"):
        if c.is_file():
            return c
    return None


def find_images():
    """받은 DICOM 을 전부 찾는다. 폴더 구조를 가정하지 않는다."""
    if not RAW_VINDR.is_dir():
        return {}
    out = {}
    for ext in ("*.dicom", "*.dcm", "*.DCM"):
        for f in RAW_VINDR.rglob(ext):
            out[f.stem] = f          # image_id 가 파일명이다
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25, help="화소까지 볼 표본 수")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    a = ap.parse_args()

    print("=" * 74)
    print("VinDr 점검 — 평가 전에 데이터의 모양부터 본다")
    print("=" * 74)
    print(f"  영상 폴더  {RAW_VINDR}")
    print(f"  라벨 폴더  {LABELS}")

    # ── ① 받은 것 ──────────────────────────────────────────────────────
    head("① 받은 영상과 라벨")
    imgs = find_images()
    print(f"  DICOM {len(imgs):,}개")
    if not imgs:
        sys.exit(f"  받은 영상이 없다. {RAW_VINDR} 를 확인해라.")

    csv = find_csv()
    if csv is None:
        print("  ! finding_annotations.csv 를 못 찾았다 — 라벨 대조를 건너뛴다")
        df = None
    else:
        df = pd.read_csv(csv)
        print(f"  라벨 {csv}  행 {len(df):,}")
        print(f"       컬럼 {list(df.columns)}")

    if df is not None:
        idcol = next((c for c in ("image_id", "image", "img_id")
                      if c in df.columns), None)
        if idcol is None:
            print("  ! image_id 컬럼을 못 찾았다")
            df = None
        else:
            have = set(imgs)
            lab = set(df[idcol].astype(str))
            print(f"  짝지음  라벨에 있고 받은 것 {len(have & lab):,} · "
                  f"받았는데 라벨에 없음 {len(have - lab):,} · "
                  f"라벨에 있는데 안 받음 {len(lab - have):,}")

    # ── ⑥ 소견 종류 ────────────────────────────────────────────────────
    if df is not None:
        head("⑥ 소견 종류 — 우리가 찾는 것이 몇 건인가")
        fc = next((c for c in ("finding_categories", "finding_category",
                               "category") if c in df.columns), None)
        if fc is None:
            print("  ! finding_categories 컬럼이 없다")
        else:
            sub = df[df[idcol].astype(str).isin(set(imgs))]
            print(f"  받은 영상에 걸린 라벨 행 {len(sub):,}")
            cnt = Counter()
            for v in sub[fc].astype(str):
                # "['Mass']" 같은 문자열이라 부분일치로 센다
                for k in WANT:
                    if k in v:
                        cnt[k] += 1
                if not any(k in v for k in WANT):
                    cnt["(그 외)"] += 1
            for k, v in cnt.most_common():
                mark = "  ← 검출 대상" if k in WANT else ""
                print(f"    {k:28s} {v:6,}{mark}")
            n_img = sub[sub[fc].astype(str).str.contains(
                "|".join(WANT), regex=True, na=False)][idcol].nunique()
            print(f"\n  검출 대상 소견이 있는 영상 {n_img:,}장")
            print("  ! 나머지 소견(비대칭·구조왜곡 등)만 있는 영상은 평가에서")
            print("    제외한다. CBIS 평가도 두 종류가 있는 영상만 썼다.")

    # ── ②③④⑤ 헤더와 화소 ───────────────────────────────────────────
    head("②③④ DICOM 헤더  (전부 · 화소는 안 읽는다)")
    photo, bits, sizes, win, lut = Counter(), Counter(), Counter(), 0, 0
    bad = 0
    for i, (iid, f) in enumerate(imgs.items(), 1):
        try:
            d = pydicom.dcmread(str(f), stop_before_pixels=True)
        except Exception:
            bad += 1
            continue
        photo[str(getattr(d, "PhotometricInterpretation", "?"))] += 1
        bits[int(getattr(d, "BitsStored", 0))] += 1
        sizes[f"{getattr(d,'Rows','?')}x{getattr(d,'Columns','?')}"] += 1
        if hasattr(d, "WindowCenter"):
            win += 1
        if "VOILUTSequence" in d:
            lut += 1
        if i % 100 == 0:
            print(f"\r  {i}/{len(imgs)}   ", end="", flush=True)
    print(f"\r  {len(imgs)}개 읽음" + (f" · 실패 {bad}" if bad else "") + "        ")

    print(f"\n  PhotometricInterpretation")
    for k, v in photo.most_common():
        mark = ""
        if k == "MONOCHROME1":
            mark = "   ★ 반전이다. 그대로 넣으면 안 된다"
        elif k == "MONOCHROME2":
            mark = "   (CBIS 와 같다)"
        print(f"    {k:16s} {v:6,}{mark}")

    print(f"\n  BitsStored      " + " · ".join(f"{k}bit {v:,}" for k, v in bits.most_common()))
    print(f"  WindowCenter 있음  {win:,}/{len(imgs):,}"
          + ("   (CBIS 에는 없었다)" if win else ""))
    print(f"  VOILUTSequence 있음 {lut:,}/{len(imgs):,}")
    print(f"\n  영상 크기 상위 5")
    for k, v in sizes.most_common(5):
        print(f"    {k:16s} {v:6,}")

    # ── ⑤ 화소 · 조직 마스크 ───────────────────────────────────────────
    head(f"⑤ 화소와 조직 마스크  (표본 {a.n}장)")
    print("  CBIS 는 유방이 화면의 30~60% 다. 90% 가 나오면 반전이거나 실패다.")
    print(f"\n  {'영상':22s}{'크기':14s}{'화소범위':18s}{'조직%':>7s}{'Photo':>14s}")
    print("  " + "-" * 76)
    fr, ok = [], 0
    for iid, f in list(imgs.items())[:a.n]:
        try:
            d = pydicom.dcmread(str(f))
            arr = d.pixel_array
        except Exception as e:
            print(f"  {iid[:20]:22s} 읽기 실패: {type(e).__name__}")
            continue
        if arr.ndim != 2:
            continue
        ph = str(getattr(d, "PhotometricInterpretation", "?"))
        m = tissue_mask(norm8(arr, a.clip))
        frac = float((m > 0).mean())
        fr.append(frac)
        ok += 1
        tb = tissue_bbox(m, a.pad)
        flag = "  ★" if frac > 0.85 or frac < 0.05 or tb is None else ""
        print(f"  {iid[:20]:22s}{arr.shape[1]}x{arr.shape[0]:<9d}"
              f"{int(arr.min())}~{int(arr.max()):<12d}{frac:6.1%}{ph[-1]:>14s}{flag}")

    if fr:
        v = np.array(fr)
        print(f"\n  조직 비율  중앙 {np.median(v):.1%} · "
              f"10~90퍼 {np.percentile(v,10):.1%}~{np.percentile(v,90):.1%}")
        if np.median(v) > 0.85:
            print("  ★ 조직 비율이 너무 높다 — 밝기가 반전됐을 가능성이 크다.")
            print("    MONOCHROME1 이면 읽을 때 arr = arr.max() - arr 로 뒤집어야 한다.")
        elif 0.2 <= np.median(v) <= 0.7:
            print("  -> CBIS 와 비슷하다. 전처리를 그대로 써도 된다.")
        else:
            print("  ! CBIS 와 다르다. 평가 결과를 해석할 때 감안해야 한다.")

    # ── 판정 ──────────────────────────────────────────────────────────
    head("판정")
    m1 = photo.get("MONOCHROME1", 0)
    if m1:
        print(f"  ★ MONOCHROME1 이 {m1:,}장 있다. 평가기에서 반드시 뒤집어야 한다.")
    else:
        print("  PhotometricInterpretation 은 CBIS 와 같다 — 반전 처리 불필요.")
    if win:
        print(f"  WindowCenter 가 {win:,}장에 있다. 우리 전처리는 백분위 절단 +")
        print("    min-max 라 이것을 무시한다. 그대로 두는 것이 CBIS 와 같은")
        print("    처리라 일관되지만, 영상이 화면용과 다르게 보일 수 있다.")
    print("\n  다음 — 이 결과를 보고 eval_vindr.py 를 짠다.")
    print("  검출 대상 소견이 있는 영상만 평가하고, FROC 은 CBIS 와 같은")
    print("  코드(eval_det)로 낸다. 그래야 두 데이터셋 수치가 비교된다.")


if __name__ == "__main__":
    main()
