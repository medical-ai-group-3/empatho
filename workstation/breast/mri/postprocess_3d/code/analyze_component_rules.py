#!/usr/bin/env python3
"""
병변 후보(성분)별 특징으로 오탐을 더 거를 수 있는지 — 규칙 탐색 + 환자 단위 교차검증 (CPU).

2026-09-29 신규 — MRI 병변 오탐 검토. analyze_lesion_fp.py에서 필터를 하나씩만 봤을 때
최선은 유방 영역 필터(breast 10mm 확장, 10% 이상 겹침)로 환자당 순수 오탐 3.7 → 2.9였다.
여기선 서빙에서 이미 계산 가능한 특징들을 조합한다(정답 정보는 판정에만 쓰고 규칙엔 안 씀).

성분 특징 (서빙 predict() 안에서 전부 계산 가능한 것만):
  voxels, score_max, score_mean,
  breast_frac / breast_frac_dil10  — breast 마스크(서빙 임계 0.8) 안 비율, 10mm 확장 버전
  min_mm, aspect                   — bbox 치수(시트형 필터와 같은 정의)
  rel_score                        — score_mean / 그 환자 성분 중 최대 score_mean
  rel_volume                       — voxels / 그 환자 최대 성분 voxels
  is_top                           — 그 환자에서 score_mean 1위 성분(항상 유지해 주 병변 보호)

규칙: is_top이거나, 모든 조건(score_mean>=a, breast_frac_dil10>=b, voxels>=c, rel_score>=d)을 만족하면 유지.
평가: 주 병변(가장 큰 정답) 검출을 지키면서 환자당 순수 오탐 최소.
교차검증: 환자 5-fold — 4/5로 규칙 고르고 1/5로 평가, held-out 결과만 합쳐서 보고.

사용법:
    python3 analyze_component_rules.py                # 특징 추출(처음 1회, 수 분) + 탐색
    python3 analyze_component_rules.py --reuse        # 저장된 특징 CSV로 탐색만
"""

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "serving" / "code"))

from analyze_lesion_fp import postprocess, gt_components, STRUCT  # noqa: E402
from model_io import DEFAULTS  # noqa: E402

THRESHOLDS = [0.40, 0.45, 0.50]
GRID = {
    "a_score_mean": [0.0, 0.55, 0.6, 0.65, 0.7, 0.75],
    "b_breast_dil": [0.0, 0.1, 0.3, 0.5],
    "c_voxels": [0, 50, 100, 200, 500],
    "d_rel_score": [0.0, 0.7, 0.8, 0.85, 0.9],
}


def extract(files, P):
    rows, pats = [], []
    for i, fp in enumerate(files, 1):
        d = np.load(fp)
        pid = json.loads(str(d["meta"]))["pid"]
        if "gt" not in d:
            continue
        print(f"[{i}/{len(files)}] {pid}", flush=True)
        score = d["tumor_score"].astype(np.float32)
        gt = d["gt"].astype(bool)
        breast = d["breast_score"].astype(np.float32) >= P["breast_score_threshold"]
        breast_dil = ndimage.binary_dilation(breast, structure=STRUCT, iterations=10)
        gt_lab, gt_ids = gt_components(gt)
        primary = None
        if gt_ids:
            primary = gt_ids[int(np.argmax(ndimage.sum(gt, gt_lab, gt_ids)))]
        pats.append({"pid": pid, "n_gt": len(gt_ids), "has_primary": primary is not None})
        for t in THRESHOLDS:
            lab, n, _, _ = postprocess(score >= t, P, "serving")
            comps = []
            for k in range(1, n + 1):
                comp = lab == k
                coords = np.argwhere(comp)
                dims = coords.max(0) - coords.min(0) + 1
                sc = score[comp]
                ov = [int(g) for g in np.unique(gt_lab[comp]) if g in gt_ids]
                comps.append({
                    "pid": pid, "threshold": t, "comp": k, "voxels": int(comp.sum()),
                    "score_max": float(sc.max()), "score_mean": float(sc.mean()),
                    "breast_frac": float(breast[comp].mean()), "breast_frac_dil10": float(breast_dil[comp].mean()),
                    "min_mm": int(dims.min()), "aspect": float(dims.min() / dims.max()),
                    "gt_ids": json.dumps(ov), "is_fp": not ov, "hits_primary": primary in ov,
                })
            if comps:
                top_s = max(c["score_mean"] for c in comps)
                top_v = max(c["voxels"] for c in comps)
                best = max(range(len(comps)), key=lambda j: comps[j]["score_mean"])
                for j, c in enumerate(comps):
                    c["rel_score"] = c["score_mean"] / top_s
                    c["rel_volume"] = c["voxels"] / top_v
                    c["is_top"] = j == best
            rows.extend(comps)
    return pd.DataFrame(rows), pd.DataFrame(pats)


def evaluate(comp_df, pats, t, a, b, c, d):
    """규칙 적용 후 환자 집합(pats) 기준 지표."""
    df = comp_df[comp_df["threshold"] == t]
    keep = df["is_top"] | ((df["score_mean"] >= a) & (df["breast_frac_dil10"] >= b)
                           & (df["voxels"] >= c) & (df["rel_score"] >= d))
    k = df[keep]
    n_pat = len(pats)
    fp = int(k["is_fp"].sum())
    prim = k.groupby("pid")["hits_primary"].any()
    prim_hit = int(prim.reindex(pats["pid"], fill_value=False)[pats["has_primary"].values].sum())
    hit_gt = sum(len(set(itertools.chain.from_iterable(json.loads(s) for s in g["gt_ids"])))
                 for _, g in k.groupby("pid"))
    return {"fp_per_pt": fp / n_pat, "primary_hit": prim_hit, "n_primary": int(pats["has_primary"].sum()),
            "lesion_sens": hit_gt / max(int(pats["n_gt"].sum()), 1)}


def search(comp_df, pats, min_sens_drop=0.02):
    """주 병변 전부 유지 + 민감도가 기준 규칙(무필터) 대비 min_sens_drop 이내인 규칙 중 FP 최소."""
    base = evaluate(comp_df, pats, 0.5, 0, 0, 0, 0)
    best = None
    for t in THRESHOLDS:
        for a, b, c, d in itertools.product(*GRID.values()):
            r = evaluate(comp_df, pats, t, a, b, c, d)
            if r["primary_hit"] < r["n_primary"] or r["lesion_sens"] < base["lesion_sens"] - min_sens_drop:
                continue
            key = (r["fp_per_pt"], -r["lesion_sens"])
            if best is None or key < best[0]:
                best = (key, (t, a, b, c, d), r)
    return best, base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, default=HERE / "results" / "raw_predictions")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "lesion_fp_analysis")
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fc, fp_ = args.out / "component_features.csv", args.out / "component_patients.csv"

    if args.reuse and fc.exists():
        comp_df, pats = pd.read_csv(fc), pd.read_csv(fp_)
    else:
        comp_df, pats = extract(sorted(args.inp.glob("*.npz")), dict(DEFAULTS))
        comp_df.to_csv(fc, index=False)
        pats.to_csv(fp_, index=False)

    # 전체 40명에서 고른 규칙(낙관적 — 같은 환자로 고르고 평가)
    best, base = search(comp_df, pats)
    print(f"\n기준(서빙 현행, t=0.5): {base}")
    print(f"전체 데이터로 고른 최선 규칙 (t,a,b,c,d)={best[1]} → {best[2]}  ⚠ 낙관적 수치")

    # 환자 단위 k-fold — held-out 결과만 합산
    rng = np.random.default_rng(args.seed)
    order = rng.permutation(pats["pid"].values)
    folds = np.array_split(order, args.folds)
    tot = {"fp": 0.0, "prim": 0, "n_prim": 0, "hit_gt_w": 0.0, "n_gt": 0, "n": 0}
    chosen = []
    for i, test_ids in enumerate(folds):
        tr = pats[~pats["pid"].isin(test_ids)]
        te = pats[pats["pid"].isin(test_ids)]
        b_tr, _ = search(comp_df[comp_df["pid"].isin(tr["pid"])], tr)
        rule = b_tr[1]
        r = evaluate(comp_df[comp_df["pid"].isin(te["pid"])], te, *rule)
        chosen.append(rule)
        tot["fp"] += r["fp_per_pt"] * len(te)
        tot["prim"] += r["primary_hit"]
        tot["n_prim"] += r["n_primary"]
        tot["hit_gt_w"] += r["lesion_sens"] * int(te["n_gt"].sum())
        tot["n_gt"] += int(te["n_gt"].sum())
        tot["n"] += len(te)
        print(f"  fold {i}: 규칙 {rule} → held-out {len(te)}명 FP/pt {r['fp_per_pt']:.2f}, "
              f"주병변 {r['primary_hit']}/{r['n_primary']}, 민감도 {r['lesion_sens']:.3f}")
    print(f"\n교차검증(held-out 합산) — FP/pt {tot['fp'] / tot['n']:.2f}, "
          f"주병변 {tot['prim']}/{tot['n_prim']}, 병변 민감도 {tot['hit_gt_w'] / tot['n_gt']:.3f}")
    print("fold별로 고른 규칙이 비슷할수록 안정적(규칙이 fold마다 크게 다르면 40명으론 과적합).")


if __name__ == "__main__":
    main()
