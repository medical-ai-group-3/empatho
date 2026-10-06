"""
BI-RADS rule table validation  --  runs WITHOUT any model or image
===================================================================
Feeds the ground-truth descriptor labels through the rule table and
compares the resulting category against the ground-truth `assessment`.

Input : labels/labels_{mass,calc}_{train,test}.csv  (from normalize_labels.py)
Usage : python validate_rules.py --labels /path/to/labels/labels

Tweak the LEVEL TABLES below and re-run to see the effect immediately.
Output is ASCII-only so it survives any terminal encoding.
"""

import argparse, glob, itertools, os, sys
from pathlib import Path
from collections import Counter, defaultdict

try:
    import pandas as pd
except ImportError:
    sys.exit("need pandas ->  pip install pandas")

# ============ LEVEL TABLES  (edit here, re-run) ============
MARGIN_BASE = {
    "SPICULATED":     5,
    "INDISTINCT":     3,
    "MICROLOBULATED": 3,
    "OBSCURED":       2,
    "CIRCUMSCRIBED":  1,
}
SHAPE_ADJ = {"IRREGULAR": +1, "OVAL": 0, "ROUND": 0}
# fallback when margin is missing: derive a base from shape alone
SHAPE_FALLBACK_BASE = {"IRREGULAR": 3, "OVAL": 1, "ROUND": 1}

FINDING_BASE = {
    "ARCHITECTURAL_DISTORTION": 4,
    "FOCAL_ASYMMETRIC_DENSITY": 1,   # -> ASYMMETRY
    "ASYMMETRIC_BREAST_TISSUE": 1,   # -> ASYMMETRY
    "LYMPH_NODE":               0,
}
# A definitive benign identification IS the diagnosis -- it must not be
# out-voted by max(). An intramammary lymph node described as "circumscribed
# oval" is still a lymph node, i.e. category 2.
BENIGN_OVERRIDE = {"LYMPH_NODE"}

CALCTYPE_BASE = {
    "FINE_LINEAR_BRANCHING": 5,
    "PLEOMORPHIC":           3,
    "AMORPHOUS":             3,
    "PUNCTATE":              1,
    "ROUND_AND_REGULAR":     0,
    "LUCENT_CENTER":         0,
    "VASCULAR":              0,
    "COARSE":                0,
    "BENIGN_TYPICAL":        0,
}
CALCDIST_ADJ = {
    "SEGMENTAL":           +1,
    "LINEAR":              +1,
    "CLUSTERED":            1,
    "REGIONAL_OR_DIFFUSE": -1,
}

LEVEL_TO_CAT = {0: "2", 1: "3", 2: "4a", 3: "4b", 4: "4c", 5: "5"}
FOLD = {"2": 2, "3": 3, "4a": 4, "4b": 4, "4c": 4, "5": 5}
# ===========================================================

args = None    # main() 에서 채운다



# ── 라벨 폴더 탐색 ────────────────────────────────────────────────────────
#    breast/mammo 로 옮긴 뒤 "labels" 한 곳만 보면 못 찾는다. 후보를 훑는다.
def find_labels(given=None):
    """labels_*.csv 가 실제로 들어 있는 첫 폴더를 돌려준다."""
    here = Path(__file__).resolve().parent
    home = Path.home()
    cands = []
    if given:
        cands.append(Path(given))
    cands += [
        here, here / "labels",
        Path.cwd(), Path.cwd() / "labels",
        home / "workspace/breast/mammo",
        home / "workspace/breast/mammo/labels",
        home / "workspace/breast/labels",
        home / "workspace/breast/labels/labels",
        home / "workspace/MedSAM3",
        home / "workspace/MedSAM3/labels",
    ]
    seen = set()
    for c in cands:
        try:
            c = c.expanduser().resolve()
        except OSError:
            continue
        if c in seen or not c.is_dir():
            continue
        seen.add(c)
        if any(c.glob("labels_*_*.csv")):
            return str(c)
    return str(Path(given).expanduser()) if given else "labels"


def present(row, axis, table):
    """descriptors of this axis that are switched on, restricted to the table"""
    return [k for k in table if row.get(f"{axis}__{k}", 0) == 1]


def clamp(v):
    return max(0, min(5, v))


def level_mass(row):
    marg = present(row, "margin", MARGIN_BASE)
    shp  = present(row, "shape",  SHAPE_ADJ)
    fnd  = present(row, "finding", FINDING_BASE)

    used_fallback = False
    if marg:
        base = max(MARGIN_BASE[m] for m in marg)
    elif shp:
        base = max(SHAPE_FALLBACK_BASE[s] for s in shp)
        used_fallback = True
    else:
        base = None

    if base is None:
        mass_lv = None
    else:
        mass_lv = clamp(base + sum(SHAPE_ADJ[s] for s in shp))

    sig = "margin=" + ("+".join(sorted(marg)) or "-") + \
          " shape=" + ("+".join(sorted(shp)) or "-") + \
          (" finding=" + "+".join(sorted(fnd)) if fnd else "")

    ovr = [f for f in fnd if f in BENIGN_OVERRIDE]
    if ovr:
        return min(FINDING_BASE[f] for f in ovr), sig + " [override]", used_fallback

    fnd_lv = max((FINDING_BASE[f] for f in fnd), default=None)
    cands = [x for x in (mass_lv, fnd_lv) if x is not None]
    lv = max(cands) if cands else None
    return lv, sig, used_fallback


def level_calc(row):
    typ = present(row, "calctype", CALCTYPE_BASE)
    dst = present(row, "calcdist", CALCDIST_ADJ)
    if not typ:
        return None, "calctype=- calcdist=" + ("+".join(sorted(dst)) or "-"), False
    base = max(CALCTYPE_BASE[t] for t in typ)
    adj = sum(CALCDIST_ADJ[d] for d in dst)
    if adj < 0 and base > 2:   # 의심스러운 형태에는 하향을 적용하지 않는다
        adj = 0
    lv = clamp(base + adj)
    sig = "type=" + "+".join(sorted(typ)) + " dist=" + ("+".join(sorted(dst)) or "-")
    return lv, sig, False


def load(kind):
    fs = sorted(glob.glob(os.path.join(args.labels, f"labels_{kind}_*.csv")))
    if not fs:
        return None
    print(f"[{kind}] files: {[os.path.basename(f) for f in fs]}")
    return pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)


def evaluate(df, kind, fn):
    rows, skipped, fallback = [], 0, 0
    for r in df.to_dict("records"):
        lv, sig, fb = fn(r)
        if lv is None:
            skipped += 1
            continue
        fallback += int(fb)
        try:
            actual = int(r.get("assessment"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        cat = LEVEL_TO_CAT[lv]
        rows.append({"sig": sig, "level": lv, "cat": cat,
                     "pred": FOLD[cat], "actual": actual,
                     "malignant": r.get("malignant")})
    out = pd.DataFrame(rows)
    print(f"[{kind}] evaluated {len(out)} | skipped(no descriptor) {skipped}"
          f" | margin-missing fallback {fallback}")
    return out


def report(res, kind):
    if res.empty:
        print(f"[{kind}] nothing to report"); return
    n = len(res)
    exact = (res.pred == res.actual).mean()
    within1 = ((res.pred - res.actual).abs() <= 1).mean()
    print(f"\n{'='*66}\n## {kind.upper()}  n={n}\n{'='*66}")
    print(f"  exact match      : {exact:6.1%}")
    print(f"  within +/-1      : {within1:6.1%}   <-- pass mark 90%")
    print(f"  mean signed err  : {(res.pred-res.actual).mean():+.2f}"
          f"   (positive = we over-call)")

    cats = sorted(set(res.actual) | set(res.pred))
    print(f"\n  confusion  (row = actual, col = predicted)")
    print("       " + "".join(f"{c:>7}" for c in cats) + "     tot")
    for a in cats:
        sub = res[res.actual == a]
        line = f"   {a:>3} " + "".join(f"{int((sub.pred==p).sum()):>7}" for p in cats)
        print(line + f"{len(sub):>8}")
    print("   tot " + "".join(f"{int((res.pred==p).sum()):>7}" for p in cats) + f"{n:>8}")

    print(f"\n  predicted category detail (before folding 4a/4b/4c)")
    for c, k in sorted(Counter(res.cat).items(), key=lambda x: FOLD[x[0]]):
        print(f"     {c:>3} : {k:5d}  ({k/n:5.1%})")

    print(f"\n  worst descriptor combinations (by total error contribution)")
    g = defaultdict(lambda: {"n": 0, "err": 0, "pairs": Counter()})
    for r in res.to_dict("records"):
        d = abs(r["pred"] - r["actual"])
        g[r["sig"]]["n"] += 1
        g[r["sig"]]["err"] += d
        if d:
            g[r["sig"]]["pairs"][(r["pred"], r["actual"])] += 1
    ranked = sorted(g.items(), key=lambda x: -x[1]["err"])[:args.top]
    for sig, v in ranked:
        if not v["err"]:
            continue
        worst = ", ".join(f"pred{p}->act{a} x{c}" for (p, a), c in v["pairs"].most_common(3))
        print(f"     n={v['n']:<5} err={v['err']:<5} {sig}")
        print(f"           {worst}")

    # sanity: does our level track actual malignancy?
    if "malignant" in res and res.malignant.notna().any():
        print(f"\n  malignancy rate by predicted level (should rise monotonically)")
        for lv in range(6):
            sub = res[res.level == lv]
            if len(sub):
                print(f"     L{lv} -> {LEVEL_TO_CAT[lv]:>3}"
                      f"  n={len(sub):5d}  malignant {sub.malignant.mean():6.1%}")


def main(argv=None):
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=None,
                    help="labels_*.csv 가 든 폴더 (생략하면 자동 탐색)")
    ap.add_argument("--top", type=int, default=15,
                    help="틀린 조합을 몇 개까지 보여줄지")
    args = ap.parse_args(argv)
    args.labels = find_labels(args.labels)
    print(f"[labels] {args.labels}")

    print("=" * 66)
    print("BI-RADS RULE TABLE VALIDATION")
    print("=" * 66)

    allres = []
    for kind, fn in (("mass", level_mass), ("calc", level_calc)):
        df = load(kind)
        if df is None:
            print(f"[{kind}] no label files in {args.labels} -- skipped")
            continue
        res = evaluate(df, kind, fn)
        report(res, kind)
        allres.append(res)

    if allres:
        comb = pd.concat(allres, ignore_index=True)
        print(f"\n{'='*66}\n## COMBINED  n={len(comb)}\n{'='*66}")
        print(f"  exact match : {(comb.pred==comb.actual).mean():6.1%}")
        print(f"  within +/-1 : {((comb.pred-comb.actual).abs()<=1).mean():6.1%}")
        print("\n  -> paste this whole output back for interpretation")
    print("=" * 66)


if __name__ == "__main__":
    main()
