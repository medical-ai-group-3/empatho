"""
CBIS-DDSM 기술어 라벨 정규화  —  B안 학습용 다중 라벨 생성
────────────────────────────────────────────────────────────
회의 확정 사항 반영:
  · B안 (기술어 → ACR 규칙표 → BI-RADS)
  · LOBULATED → OVAL 병합 (ACR 5판 취지)
  · 석회 분포 결측 → "해당 없음" (전 클래스 0)

입력: CSV 4개 (기술어_점검.py 와 같은 파일)
출력: labels_{mass,calc}_{train,test}.csv  +  label_schema.json

    pip install pandas
    python 라벨_정규화.py
"""

import glob, json, os, re, sys
from collections import Counter

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas 가 필요합니다 →  pip install pandas")

CSV_DIR = "."
OUT_DIR = "labels"

# ══ 회의 확정 사항 ═══════════════════════════════════════════
MERGE_LOBULATED_INTO_OVAL = True    # 5판: 모양은 oval/round/irregular 3종
MERGE_REGIONAL_AND_DIFFUSE = True   # 둘 다 양성 시사 조정자 — 규칙상 동일 취급
DROP_ASSESSMENT_0         = True    # 0 = 판정 미완결, 모델이 낼 수 없는 범주
# ════════════════════════════════════════════════════════════

# 소견 유형 — 모양이 아니므로 별도 축으로 분리
FINDING_TYPES = ["ARCHITECTURAL_DISTORTION", "LYMPH_NODE",
                 "FOCAL_ASYMMETRIC_DENSITY", "ASYMMETRIC_BREAST_TISSUE"]

SHAPE_MAP    = {"LOBULATED": "OVAL"} if MERGE_LOBULATED_INTO_OVAL else {}
SHAPE_CLASSES = ["OVAL", "IRREGULAR", "ROUND"] if MERGE_LOBULATED_INTO_OVAL \
                else ["OVAL", "LOBULATED", "IRREGULAR", "ROUND"]

MARGIN_MAP     = {"ILL_DEFINED": "INDISTINCT"}          # 5판 용어로 통일
MARGIN_CLASSES = ["CIRCUMSCRIBED", "INDISTINCT", "SPICULATED",
                  "OBSCURED", "MICROLOBULATED"]

# 전형적 양성 석회 — 개별 건수가 적고 규칙상 동일 취급(범주 2)
CALC_BENIGN_TYPICAL = ["EGGSHELL", "DYSTROPHIC", "LARGE_RODLIKE",
                       "SKIN", "MILK_OF_CALCIUM"]
CALC_TYPE_MAP = {"LUCENT_CENTERED": "LUCENT_CENTER"}    # 표기 오류 병합
CALC_TYPE_MAP.update({k: "BENIGN_TYPICAL" for k in CALC_BENIGN_TYPICAL})
CALC_TYPE_CLASSES = ["PLEOMORPHIC", "PUNCTATE", "LUCENT_CENTER", "AMORPHOUS",
                     "ROUND_AND_REGULAR", "FINE_LINEAR_BRANCHING",
                     "VASCULAR", "COARSE", "BENIGN_TYPICAL"]

DIST_MAP = {"DIFFUSELY_SCATTERED": "REGIONAL_OR_DIFFUSE",
            "REGIONAL": "REGIONAL_OR_DIFFUSE"} if MERGE_REGIONAL_AND_DIFFUSE else {}
DIST_CLASSES = (["CLUSTERED", "SEGMENTAL", "LINEAR", "REGIONAL_OR_DIFFUSE"]
                if MERGE_REGIONAL_AND_DIFFUSE
                else ["CLUSTERED", "SEGMENTAL", "LINEAR", "REGIONAL", "DIFFUSELY_SCATTERED"])

NULLS = {"nan", "", "n/a", "na", "none", "nan "}


def col(df, *words):
    """컬럼명 표기 흔들림 흡수 (mass shape / mass_shape / breast density ...)"""
    for c in df.columns:
        norm = re.sub(r'[^a-z]', '', c.lower())
        if all(w in norm for w in words):
            return c
    return None


def atoms(cell, mapping):
    """'OBSCURED-ILL_DEFINED' → {'OBSCURED','INDISTINCT'}  (분해·정규화·중복제거)"""
    if cell is None:
        return set()
    s = str(cell).strip()
    if s.lower() in NULLS:
        return set()
    out = set()
    for p in s.split('-'):
        p = p.strip().upper()
        if not p:
            continue
        out.add(mapping.get(p, p))
    return out


def build(df, axes, kind):
    """axes = [(축이름, 컬럼검색어, 매핑, 클래스목록), ...]"""
    rows, dropped_zero, unseen = [], 0, Counter()

    c_assess  = col(df, "assessment")
    c_path    = col(df, "pathology")
    c_pid     = col(df, "patientid")
    c_crop    = col(df, "cropped", "image", "file", "path")
    c_roi     = col(df, "roi", "mask", "file", "path")
    c_img     = col(df, "image", "file", "path")
    c_side    = col(df, "left", "right", "breast")
    c_view    = col(df, "image", "view")
    c_abnid   = col(df, "abnormality", "id")
    c_dens    = col(df, "breast", "density")
    c_subt    = col(df, "subtlety")

    for _, r in df.iterrows():
        if DROP_ASSESSMENT_0 and c_assess is not None:
            try:
                if int(r[c_assess]) == 0:
                    dropped_zero += 1
                    continue
            except (ValueError, TypeError):
                pass

        rec = {
            "patient_id": r[c_pid] if c_pid else None,
            "side":       r[c_side] if c_side else None,
            "view":       r[c_view] if c_view else None,
            "abn_id":     r[c_abnid] if c_abnid else None,
            "kind":       kind,
            "roi_path":   r[c_crop] if c_crop else None,
            "mask_path":  r[c_roi] if c_roi else None,
            "image_path": r[c_img] if c_img else None,
            "density":    r[c_dens] if c_dens else None,
            "subtlety":   r[c_subt] if c_subt else None,
            "assessment": r[c_assess] if c_assess else None,
        }
        if c_path is not None:
            p = str(r[c_path]).strip().upper()
            rec["malignant"] = int(p == "MALIGNANT")
            rec["pathology_raw"] = p

        for axis, words, mapping, classes, ignore in axes:
            c = col(df, *words)
            got = atoms(r[c], mapping) if c is not None else set()
            for g in got:
                if g not in classes and g not in ignore:
                    unseen[f"{axis}:{g}"] += 1
            for cls in classes:
                rec[f"{axis}__{cls}"] = int(cls in got)
            rec[f"{axis}__n"] = sum(1 for cls in classes if cls in got)

        rows.append(rec)

    return pd.DataFrame(rows), dropped_zero, unseen


def summarize(df, axes, title):
    print(f"\n{'=' * 68}\n## {title}  —  {len(df)}건\n{'=' * 68}")
    for axis, _, _, classes, _ig in axes:
        print(f"\n  ▸ {axis}")
        for cls in classes:
            n = int(df[f"{axis}__{cls}"].sum())
            mark = "   ← 부족" if n < 50 else ""
            print(f"      {n:6d}  {cls}{mark}")
        none_n = int((df[f"{axis}__n"] == 0).sum())
        multi_n = int((df[f"{axis}__n"] > 1).sum())
        print(f"      ── 해당 없음 {none_n} ({none_n/len(df):.1%})"
              f" · 다중 라벨 {multi_n} ({multi_n/len(df):.1%})")
    if "malignant" in df:
        print(f"\n  ▸ 악성 비율: {df.malignant.mean():.1%}"
              f"  (악성 {int(df.malignant.sum())} / 양성 {int((1-df.malignant).sum())})")
    if "assessment" in df:
        print("  ▸ assessment:", dict(sorted(Counter(df.assessment.dropna()).items())))


# (축이름, 컬럼검색어, 매핑, 클래스목록, 경고에서 무시할 값)
# shape 와 finding 은 같은 컬럼을 읽으므로 서로의 값을 무시 목록에 넣는다
MASS_AXES = [
    ("shape",   ("mass", "shape"),  SHAPE_MAP,  SHAPE_CLASSES,  set(FINDING_TYPES)),
    ("margin",  ("mass", "margin"), MARGIN_MAP, MARGIN_CLASSES, set()),
    ("finding", ("mass", "shape"),  SHAPE_MAP,  FINDING_TYPES,  set(SHAPE_CLASSES)),
]
CALC_AXES = [
    ("calctype", ("calc", "type"),         CALC_TYPE_MAP, CALC_TYPE_CLASSES, set()),
    ("calcdist", ("calc", "distribution"), DIST_MAP,      DIST_CLASSES,      set()),
]


def run(pattern, axes, kind, split):
    paths = sorted(glob.glob(os.path.join(CSV_DIR, pattern)))
    if not paths:
        print(f"  ★ {pattern} 없음 — 건너뜀")
        return None
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    out, dz, unseen = build(df, axes, kind)
    print(f"\n[{kind} · {split}]  원본 {len(df)} → 정규화 {len(out)}"
          f"   (assessment=0 제외 {dz})")
    if unseen:
        print("  ※ 클래스 목록에 없던 값:", dict(unseen.most_common(10)))
    return out


print("=" * 68)
print("CBIS-DDSM 기술어 라벨 정규화")
print("=" * 68)
print(f"LOBULATED→OVAL 병합 : {MERGE_LOBULATED_INTO_OVAL}")
print(f"REGIONAL+DIFFUSE 병합: {MERGE_REGIONAL_AND_DIFFUSE}")
print(f"assessment=0 제외    : {DROP_ASSESSMENT_0}")

os.makedirs(OUT_DIR, exist_ok=True)
made = {}
for kind, pat, axes in [("mass", "mass_case_description_%s_set.csv", MASS_AXES),
                        ("calc", "calc_case_description_%s_set.csv", CALC_AXES)]:
    for split in ("train", "test"):
        d = run(pat % split, axes, kind, split)
        if d is not None:
            f = os.path.join(OUT_DIR, f"labels_{kind}_{split}.csv")
            d.to_csv(f, index=False)
            made[(kind, split)] = d
            print(f"  → 저장 {f}")

for kind, axes in [("mass", MASS_AXES), ("calc", CALC_AXES)]:
    parts = [made[(kind, s)] for s in ("train", "test") if (kind, s) in made]
    if parts:
        summarize(pd.concat(parts, ignore_index=True), axes,
                  "종괴 (mass)" if kind == "mass" else "석회화 (calc)")

# 환자 누수 점검 — train/test 에 같은 환자가 있으면 성능이 부풀려진다
print(f"\n{'=' * 68}\n## 환자 누수 점검 (0 이어야 정상)\n{'=' * 68}")
for kind in ("mass", "calc"):
    if (kind, "train") in made and (kind, "test") in made:
        tr = set(made[(kind, "train")].patient_id.dropna())
        te = set(made[(kind, "test")].patient_id.dropna())
        n = len(tr & te)
        print(f"  {kind}: train {len(tr)}명 / test {len(te)}명 / 겹침 {n}"
              + ("   ★ 재분할 필요" if n else "   OK"))
if all(k in made for k in [("mass", "train"), ("calc", "train")]):
    m = set(made[("mass", "train")].patient_id.dropna())
    c = set(made[("calc", "test")].patient_id.dropna())
    print(f"  교차(mass_train ∩ calc_test): {len(m & c)}"
          + ("   ★ 두 세트를 합쳐 쓸 경우 재분할 필요" if m & c else "   OK"))

schema = {
    "decisions": {
        "merge_lobulated_into_oval": MERGE_LOBULATED_INTO_OVAL,
        "merge_regional_and_diffuse": MERGE_REGIONAL_AND_DIFFUSE,
        "drop_assessment_0": DROP_ASSESSMENT_0,
        "missing_distribution": "all-zero (해당 없음)",
    },
    "axes": {
        "shape": SHAPE_CLASSES, "margin": MARGIN_CLASSES,
        "finding": FINDING_TYPES, "calctype": CALC_TYPE_CLASSES,
        "calcdist": DIST_CLASSES,
    },
    "mappings": {"shape": SHAPE_MAP, "margin": MARGIN_MAP,
                 "calctype": CALC_TYPE_MAP, "calcdist": DIST_MAP},
    "loss": "축별 sigmoid + BCE (다중 라벨). softmax 아님.",
}
with open(os.path.join(OUT_DIR, "label_schema.json"), "w", encoding="utf-8") as f:
    json.dump(schema, f, ensure_ascii=False, indent=2)
print(f"\n→ 저장 {os.path.join(OUT_DIR, 'label_schema.json')}")

print(f"\n{'=' * 68}")
print("완료. labels/ 폴더 내용과 위 출력을 보내주세요.")
print("=" * 68)
