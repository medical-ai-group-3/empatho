"""
CBIS-DDSM 기술어 커버리지 점검  —  이미지 없이 CSV만으로 실행
─────────────────────────────────────────────────────────────
오늘 회의의 A안 / B안 결정 근거를 뽑는 스크립트.

준비물: CSV 4개만 (합쳐서 2MB 내외). 이미지는 필요 없습니다.
    mass_case_description_train_set.csv
    mass_case_description_test_set.csv
    calc_case_description_train_set.csv
    calc_case_description_test_set.csv

TCIA CBIS-DDSM 페이지 → Data Access 섹션에 CSV 링크가 따로 있습니다.
이 파일과 같은 폴더에 넣고 실행:
    pip install pandas
    python 기술어_점검.py
"""

import glob, os, re, sys

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas 가 필요합니다 →  pip install pandas")

CSV_DIR = "."          # CSV 들이 있는 폴더. 다르면 여기만 고치세요.
MIN_PER_CLASS = 50     # 클래스 하나가 학습되려면 최소 이 정도
MIN_TOTAL     = 300    # 축 하나가 학습되려면 최소 이 정도


def find_col(df, *words):
    """컬럼명 표기 흔들림(공백/언더스코어/대소문자)을 흡수해서 찾는다."""
    for c in df.columns:
        norm = re.sub(r'[^a-z]', '', c.lower())
        if all(w in norm for w in words):
            return c
    return None


def load(pattern):
    paths = sorted(glob.glob(os.path.join(CSV_DIR, pattern)))
    if not paths:
        return None, []
    frames = []
    for p in paths:
        try:
            frames.append(pd.read_csv(p))
        except Exception as e:
            print(f"  !! {os.path.basename(p)} 읽기 실패: {e}")
    if not frames:
        return None, paths
    return pd.concat(frames, ignore_index=True), paths


def report(df, axis_name, specs):
    """specs = [(라벨, (검색어들)), ...]"""
    print(f"\n{'=' * 68}")
    print(f"## {axis_name}  —  총 {len(df)}건")
    print("=" * 68)
    print("컬럼:", list(df.columns))

    ok_axis = True
    for label, words in specs:
        col = find_col(df, *words)
        if col is None:
            print(f"\n  ▸ {label}: ★컬럼 없음★ (검색어 {words})")
            ok_axis = False
            continue

        s = df[col].astype(str).str.strip()
        s = s[~s.isin(["nan", "", "N/A", "NA", "None"])]
        vc = s.value_counts()
        cover = len(s) / len(df) if len(df) else 0

        print(f"\n  ▸ {label}   [컬럼: {col}]")
        print(f"      채워진 행 {len(s)} / {len(df)}  ({cover:.1%})   고유값 {len(vc)}종")
        for v, c in vc.items():
            mark = "   ← 부족" if c < MIN_PER_CLASS else ""
            print(f"      {c:6d}  {v}{mark}")

        usable = int((vc >= MIN_PER_CLASS).sum())
        print(f"      >> 학습 가능 클래스 {usable}종 / 전체 {len(vc)}종")
        if len(s) < MIN_TOTAL or usable < 2:
            ok_axis = False

    # 참고 — BI-RADS 와 병리 정답도 같이 본다
    for label, words in [("BI-RADS(assessment)", ("assessment",)),
                         ("병리 정답(pathology)", ("pathology",)),
                         ("subtlety", ("subtlety",))]:
        col = find_col(df, *words)
        if col:
            print(f"\n  ▸ [참고] {label}  [컬럼: {col}]")
            print("      " + df[col].value_counts(dropna=False).to_string().replace("\n", "\n      "))

    return ok_axis


print("=" * 68)
print("CBIS-DDSM 기술어 커버리지 점검")
print("=" * 68)

mass, mp = load("mass_case_description_*.csv")
calc, cp = load("calc_case_description_*.csv")

print(f"\n종괴 CSV : {[os.path.basename(p) for p in mp] or '★없음★'}")
print(f"석회 CSV : {[os.path.basename(p) for p in cp] or '★없음★'}")

mass_ok = calc_ok = False
if mass is not None:
    mass_ok = report(mass, "종괴 (mass)", [
        ("모양 (shape)",   ("mass", "shape")),
        ("경계 (margins)", ("mass", "margin")),
    ])
else:
    print("\n종괴 CSV를 찾지 못했습니다. 파일명/경로를 확인하세요.")

if calc is not None:
    calc_ok = report(calc, "석회화 (calcification)", [
        ("형태 (type)",         ("calc", "type")),
        ("분포 (distribution)", ("calc", "distribution")),
    ])
else:
    print("\n석회 CSV를 찾지 못했습니다. 파일명/경로를 확인하세요.")

print("\n" + "=" * 68)
print("[ 판정 ]")
print("=" * 68)
print(f"  종괴 기술어(모양·경계)    학습 가능 : {'예' if mass_ok else '아니오'}")
print(f"  석회화 기술어(형태·분포)  학습 가능 : {'예' if calc_ok else '아니오'}")
print()
if mass_ok and calc_ok:
    print("  >> B안 — 기술어 출력 후 ACR 규칙표로 BI-RADS 매핑")
    print("     XAI가 '침상 경계라서 4c' 형태로 나옴. 가장 설명력 높음.")
elif mass_ok or calc_ok:
    print("  >> 부분 B안 — 되는 축만 기술어, 나머지 축은 범주 직접 출력")
elif mass is not None or calc is not None:
    print("  >> A안 — 범주 직접 출력 + 기술어는 판독의 수기 입력")
else:
    print("  >> CSV를 못 읽어서 판정 불가")
print()
print("  ※ '← 부족' 표시된 클래스가 많으면 클래스 병합을 검토하세요.")
print("     예) 경계 5종 → '양성형(경계분명·소엽상) / 악성형(침상·불명확)' 2종")
print("=" * 68)
print("\n출력 전체를 복사해서 보내주세요.")
