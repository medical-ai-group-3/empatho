#!/usr/bin/env python
"""
규칙표 finding 축의 외부 검증 — VinDr-Mammo 라벨과 대조한다.

무엇을 하는가
  우리 규칙표는 CBIS-DDSM 만 보고 만들어졌다. VinDr 는 다른 나라 · 다른 장비 ·
  다른 판독의의 데이터이고 서술어 라벨은 없지만 소견 종류와 그 소견에 실제
  매겨진 BI-RADS 를 갖고 있다. 그래서 이렇게 물을 수 있다.

    "규칙표가 ARCHITECTURAL_DISTORTION 에 4c 를 주는데,
     실제 임상에서도 구조 왜곡은 4 이상으로 가는가?"

  영상이 전혀 필요 없다. 라벨 두 파일만 읽는다.

검증 범위 (넘겨짚지 않도록 명시한다)
  VinDr 에는 서술어 라벨이 없다. 따라서 MARGIN_BASE · SHAPE_ADJ ·
  CALCTYPE_BASE · CALCDIST_ADJ 는 이 스크립트로 검증되지 않는다.
  검증되는 것은 FINDING_BASE 뿐이다.
  또 VinDr 의 소견 등급에는 1 · 2 가 없다 (소견이 있으면 이미 3 이상).
  그래서 레벨 0(=카테고리 2) 배정은 확인할 방법이 없다.

규칙표는 실행하지 않고 구문 트리에서 상수만 읽는다.
validate_rules.py 가 모듈 수준에서 argparse 를 돌리기 때문이다.
덕분에 규칙표를 수정하면 이 검증도 자동으로 따라간다.
"""

import argparse, ast, sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas 필요:  pip install pandas")

HOME = Path.home()
def find_rules():
    """
    규칙표 위치를 찾는다. 스크립트와 같은 폴더를 가장 먼저 본다 — 파일을 옮겨도
    따라오게 하려는 것이다. 없으면 알려진 옛 경로를 차례로 확인한다.
    경로를 코드에 박아두면 폴더를 정리할 때마다 스크립트가 깨진다.
    """
    here = Path(__file__).resolve().parent
    for c in (here / "validate_rules.py",
              Path.home() / "workspace/breast/mammo/validate_rules.py",
              Path.home() / "workspace/breast/code/validate_rules.py"):
        if c.exists():
            return c
    return here / "validate_rules.py"      # 없으면 여기서 찾다 에러를 낸다


DEF_RULES = None
DEF_VINDR = HOME / "workspace/breast/labels/finding_annotations.csv"

# ── VinDr 소견 종류 ↔ 우리 finding 서술어 ───────────────────────
# 한 서술어에 여러 VinDr 범주가 대응할 수 있다.
MAP = {
    "ARCHITECTURAL_DISTORTION": ["Architectural Distortion"],
    "FOCAL_ASYMMETRIC_DENSITY": ["Focal Asymmetry"],
    "ASYMMETRIC_BREAST_TISSUE": ["Asymmetry", "Global Asymmetry"],
    "LYMPH_NODE":               ["Suspicious Lymph Node"],
}
# 의미가 어긋나는 쌍은 검증으로 치지 않는다.
# CBIS 의 LYMPH_NODE 는 양성 유방내 림프절이고,
# VinDr 의 Suspicious Lymph Node 는 '의심스러운' 림프절이다. 반대 개념이다.
SEMANTIC_MISMATCH = {
    "LYMPH_NODE": "CBIS 는 양성 유방내 림프절, VinDr 는 의심 림프절 — 반대 개념이라 비교 불가",
}


# ── 규칙표에서 상수만 꺼내기 ────────────────────────────────────
def read_rule_consts(path, names):
    """실행하지 않고 모듈 수준 상수를 읽는다."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id in names:
                try:
                    out[tgt.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    missing = [n for n in names if n not in out]
    if missing:
        sys.exit(f"{path} 에서 못 읽은 상수: {missing}")
    return out


def parse_cats(v):
    """finding_categories 는 \"['Mass']\" 같은 문자열이다."""
    try:
        x = ast.literal_eval(v)
        return list(x) if isinstance(x, (list, tuple)) else [x]
    except (ValueError, SyntaxError):
        return [str(v)]


def birads_num(v):
    """'BI-RADS 4' -> 4"""
    try:
        return int(str(v).strip().split()[-1])
    except (ValueError, IndexError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default=str(find_rules()))
    ap.add_argument("--vindr", default=str(DEF_VINDR))
    a = ap.parse_args()

    C = read_rule_consts(a.rules, ["FINDING_BASE", "LEVEL_TO_CAT", "FOLD",
                                   "BENIGN_OVERRIDE"])
    FB, L2C, FOLD = C["FINDING_BASE"], C["LEVEL_TO_CAT"], C["FOLD"]
    OVR = set(C["BENIGN_OVERRIDE"])

    print("=" * 74)
    print("규칙표 finding 축 × VinDr-Mammo 임상 분포")
    print("=" * 74)
    print(f"  규칙표 : {a.rules}")
    print(f"  VinDr  : {a.vindr}")

    df = pd.read_csv(a.vindr)
    need = {"finding_categories", "finding_birads"}
    if not need <= set(df.columns):
        sys.exit(f"컬럼 부족. 필요: {need}, 실제: {list(df.columns)}")

    df["_cats"] = df["finding_categories"].map(parse_cats)
    df["_bir"] = df["finding_birads"].map(birads_num)

    lesions = df[df["_bir"].notna()].copy()
    single = lesions[lesions["_cats"].map(len) == 1].copy()
    single["_cat"] = single["_cats"].map(lambda x: x[0])

    print(f"\n  전체 행 {len(df):,}  ·  등급 있는 소견 {len(lesions):,}"
          f"  ·  단일 소견 {len(single):,}")
    print("  복합 소견은 어느 범주가 등급을 끌어올렸는지 분리할 수 없어 제외한다.")

    # ── 서술어별 대조 ──────────────────────────────────────────
    print("\n" + "=" * 74)
    print("[1] 서술어별 대조")
    print("=" * 74)
    print(f"  {'서술어':26s} {'규칙표':>8s} {'VinDr최빈':>10s} {'≥4비율':>8s} "
          f"{'n':>6s}  판정")
    print("  " + "-" * 70)

    rows = []
    for desc, base in sorted(FB.items(), key=lambda kv: -kv[1]):
        cat = L2C.get(base)
        folded = FOLD.get(cat)
        tag = " [override]" if desc in OVR else ""

        vin_cats = MAP.get(desc, [])
        sub = single[single["_cat"].isin(vin_cats)]
        n = len(sub)

        if desc in SEMANTIC_MISMATCH:
            print(f"  {desc:26s} {str(cat)+tag:>8s} {'-':>10s} {'-':>8s} "
                  f"{n:6d}  비교 불가")
            print(f"    └ {SEMANTIC_MISMATCH[desc]}")
            continue
        if n == 0:
            print(f"  {desc:26s} {str(cat):>8s} {'-':>10s} {'-':>8s} "
                  f"{0:6d}  대응 없음")
            continue

        dist = sub["_bir"].value_counts(normalize=True).sort_index()
        mode = int(sub["_bir"].mode().iloc[0])
        ge4 = float((sub["_bir"] >= 4).mean()) * 100
        mode_share = float(dist.loc[mode]) * 100

        if folded == mode:
            verdict = "일치"
        elif abs((folded or 0) - mode) == 1 and mode_share < 60:
            verdict = "경계"
        else:
            verdict = "불일치 ★"

        print(f"  {desc:26s} {cat:>8s} {mode:>10d} {ge4:7.1f}% "
              f"{n:6d}  {verdict}")
        detail = "  ".join(f"{int(k)}:{v*100:4.1f}%" for k, v in dist.items())
        print(f"    └ 분포  {detail}   (최빈 {mode_share:.1f}%)")
        rows.append((desc, base, folded, mode, ge4, n))

    # ── 같은 레벨끼리 실제로 같은가 ────────────────────────────
    print("\n" + "=" * 74)
    print("[2] 규칙표가 동일 취급하는 서술어들이 임상에서도 같은가")
    print("=" * 74)
    by_level = {}
    for desc, base, folded, mode, ge4, n in rows:
        by_level.setdefault(base, []).append((desc, ge4, n))

    flagged = False
    for base, items in sorted(by_level.items()):
        if len(items) < 2:
            continue
        spread = max(x[1] for x in items) - min(x[1] for x in items)
        print(f"\n  레벨 {base} (→ {L2C.get(base)}) 로 묶인 서술어 {len(items)}개"
              f"  ·  ≥4비율 격차 {spread:.1f}%p")
        for desc, ge4, n in sorted(items, key=lambda x: -x[1]):
            print(f"    {desc:28s} {ge4:6.1f}%  (n={n})")
        if spread >= 20:
            flagged = True
            print(f"    ★ 규칙표는 같은 등급을 주는데 임상은 {spread:.0f}%p 갈린다.")
    if not by_level or all(len(v) < 2 for v in by_level.values()):
        print("  같은 레벨에 둘 이상 묶인 서술어가 없다.")

    # ── 요약 ───────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("요약")
    print("=" * 74)
    ok = [r for r in rows if FOLD.get(L2C.get(r[1])) == r[3]]
    print(f"  대조 가능 {len(rows)}개 중 최빈 등급 일치 {len(ok)}개")
    print("  검증 범위는 FINDING_BASE 뿐이다. margin · shape · calctype ·")
    print("  calcdist 는 VinDr 에 대응 라벨이 없어 검증되지 않았다.")
    if flagged:
        print("  ★ 표시가 있으면 규칙표가 구분하지 않는 것을 임상은 구분한다는 뜻이다.")
        print("    다만 곧바로 값을 올리는 것이 정답은 아니다 — 반대 방향 오차가")
        print("    더 커질 수 있으므로 양쪽 비율을 보고 판단해야 한다.")


if __name__ == "__main__":
    main()
