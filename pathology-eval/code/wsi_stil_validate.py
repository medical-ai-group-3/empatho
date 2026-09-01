"""
WSI sTIL 파이프라인 출력 vs TIGER WSITILS GT (tiger-til-scores) 검증.

- Spearman rho / Pearson r / MAE / RMSE, 산점도, Bland-Altman
- 스케일 캘리브레이션: slide_stil = nc_ratio * slide_stil_nucleus 이므로 스케일 인자 분리 가능
    원점통과 최소제곱  k* = sum(GT.nuc) / sum(nuc^2)      -> --nc_ratio k*
    아핀 회귀          GT ~ a.nuc + b
- GT CSV comment 파싱 -> pitfall 그룹 vs clean 그룹 각각 상관
- 저/중/고 TIL 3분류 임계값 (데이터 기반 + 임상 컷오프)
"""
import argparse
import csv
import json
import os
import re

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

# comment 필드 pitfall 카테고리
PITFALL_PATTERNS = {
    "neutrophils": r"neutrophil",
    "necrosis": r"necrosis|necrotic",
    "DCIS": r"dcis",
    "normal_structures": r"normal (structure|lobul|glan)|with normal|normal structures",
    "granulation_biopsy": r"granulation|biopsy",
    "fibroblasts": r"fibroblast",
    "cancer_mimic": r"crushed|small cancer|poorly fixed|tumor cells = pitfall",
    "lymph_node": r"lymph node|involved lymph",
    "fat_necrosis": r"fatnecrosis|fat necrosis",
    "lymphoid_aggregate": r"lymphoid aggregate",
    "tiny_fragment": r"tiny fragment",
}
# 임상 컷오프 (Salgado et al. 2015 / TIL Working Group)
#   low <10, intermediate 10-39, high >=40 ; LPBC >=50~60
CLIN_LOW, CLIN_HIGH = 10, 40


def parse_pitfalls(gt_csv):
    tags = {}
    for r in csv.DictReader(open(gt_csv)):
        c = (r["comment"] or "").lower()
        t = [k for k, p in PITFALL_PATTERNS.items() if re.search(p, c)]
        tags[r["image-id"]] = {"tags": t, "is_pitfall": bool(t) or "pitfall" in c,
                               "comment": r["comment"] or ""}
    return tags


def corr(gt, nuc):
    rho, rp = stats.spearmanr(gt, nuc)
    r, pp = stats.pearsonr(gt, nuc)
    k = float(np.sum(gt * nuc) / np.sum(nuc ** 2)) if np.sum(nuc ** 2) else np.nan
    a, b = np.polyfit(nuc, gt, 1)
    gh = a * nuc + b
    r2 = 1 - np.sum((gt - gh) ** 2) / np.sum((gt - gt.mean()) ** 2)
    pred = k * nuc
    return dict(n=len(gt), spearman=float(rho), spearman_p=float(rp), pearson=float(r),
               k_star=k, affine_a=float(a), affine_b=float(b), affine_r2=float(r2),
               calib_mae=float(np.mean(np.abs(pred - gt))),
               calib_rmse=float(np.sqrt(np.mean((pred - gt) ** 2))))


def show(c, label):
    print(f"\n[{label}]  n={c['n']}")
    print(f"  Spearman rho = {c['spearman']:.3f} (p={c['spearman_p']:.4f})   Pearson r = {c['pearson']:.3f}")
    print(f"  k* = {c['k_star']:.1f}   affine GT ~ {c['affine_a']:.1f}*nuc + {c['affine_b']:.1f} (R2={c['affine_r2']:.2f})")
    print(f"  캘리브 후 MAE = {c['calib_mae']:.1f}   RMSE = {c['calib_rmse']:.1f}")


def tertile_analysis(gt, pred_cal, stems):
    print("\n" + "=" * 60)
    print("저/중/고 TIL 3분류")
    gt_t1, gt_t2 = np.percentile(gt, [100 / 3, 200 / 3])
    print(f"  GT 3분위 경계 (데이터): {gt_t1:.0f} / {gt_t2:.0f}")
    print(f"  임상 컷오프 (Salgado/WG): low <{CLIN_LOW}, intermediate {CLIN_LOW}-{CLIN_HIGH-1}, high >={CLIN_HIGH}")
    gt_cls = np.digitize(gt, [CLIN_LOW, CLIN_HIGH])  # 0/1/2

    # 캘리브 pred 에서 임상 클래스와 가장 잘 맞는 컷오프 탐색 (Cohen's kappa 최대화)
    from sklearn.metrics import cohen_kappa_score, confusion_matrix
    best = (-1, None)
    grid = np.arange(3, 60, 1.0)
    for lo in grid:
        for hi in grid[grid > lo]:
            pc = np.digitize(pred_cal, [lo, hi])
            kap = cohen_kappa_score(gt_cls, pc, weights="quadratic")
            if kap > best[0]:
                best = (kap, (lo, hi))
    lo, hi = best[1]
    pc = np.digitize(pred_cal, [lo, hi])
    print(f"\n  캘리브 pred 최적 컷오프: low <{lo:.0f}, intermediate {lo:.0f}-{hi:.0f}, high >={hi:.0f}")
    print(f"  quadratic-weighted kappa (임상클래스 vs pred클래스) = {best[0]:.3f}")
    print(f"  혼동행렬 (행=GT임상, 열=pred):\n{confusion_matrix(gt_cls, pc)}")
    acc = (gt_cls == pc).mean()
    print(f"  3분류 정확도 = {acc:.2f}")
    return (lo, hi), best[0], acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.expanduser("~/pathology-eval/code/stil_results/wsi_stil_results.json"))
    ap.add_argument("--gt_csv", default=os.path.expanduser("~/data/tiger/wsitils/tiger-til-scores-wsitils.csv"))
    ap.add_argument("--outdir", default=os.path.expanduser("~/pathology-eval/code/stil_results"))
    args = ap.parse_args()

    pf = parse_pitfalls(args.gt_csv)
    rows = [r for r in json.load(open(args.results))
            if r["slide_stil"] is not None and r["gt_tils_score"] is not None]
    rows.sort(key=lambda r: r["gt_tils_score"])
    gt = np.array([r["gt_tils_score"] for r in rows], float)
    nuc = np.array([r["slide_stil_nucleus"] for r in rows], float)
    stems = [r["stem"] for r in rows]
    is_pf = np.array([pf.get(s, {}).get("is_pitfall", False) for s in stems])
    nc_used = rows[0]["slide_stil"] / rows[0]["slide_stil_nucleus"] if rows[0]["slide_stil_nucleus"] else 1.5

    print(f"n = {len(rows)} slides   |   pitfall {is_pf.sum()}  /  clean {(~is_pf).sum()}")
    print(f"\n{'stem':30s} {'GT':>4} {'nuc':>7}  {'pitfall tags'}")
    for i in range(len(rows)):
        print(f"{stems[i]:30s} {gt[i]:>4.0f} {nuc[i]:>7.3f}  "
              f"{','.join(pf.get(stems[i], {}).get('tags', [])) or ('' if not is_pf[i] else 'pitfall')}")

    c_all = corr(gt, nuc); show(c_all, "전체")
    c_clean = corr(gt[~is_pf], nuc[~is_pf]); show(c_clean, "clean (comment 무해/공란)")
    if is_pf.sum() >= 3:
        c_pf = corr(gt[is_pf], nuc[is_pf]); show(c_pf, "pitfall (comment 교란요소 언급)")
    else:
        c_pf = None

    k = c_all["k_star"]
    pred_cal = k * nuc
    cuts, kappa, acc3 = tertile_analysis(gt, pred_cal, stems)

    # ---- plot ----
    fig, ax = plt.subplots(1, 2, figsize=(14, 6))
    lim = max(gt.max(), pred_cal.max()) * 1.1
    ax[0].plot([0, lim], [0, lim], "k--", lw=1, alpha=.4, label="y = x")
    ax[0].scatter(gt[~is_pf], pred_cal[~is_pf], s=45, zorder=3, label=f"clean (n={(~is_pf).sum()})")
    ax[0].scatter(gt[is_pf], pred_cal[is_pf], s=45, marker="x", c="crimson", zorder=3,
                  label=f"pitfall (n={is_pf.sum()})")
    for xc in cuts:
        ax[0].axhline(xc, color="green", ls=":", alpha=.5)
    ax[0].set_xlabel("TIGER pathologist TIL score (GT)")
    ax[0].set_ylabel(f"pipeline slide_stil, calibrated x{k:.0f} (%)")
    ax[0].set_title(f"WSI sTIL vs GT   n={len(rows)}   Spearman rho={c_all['spearman']:.2f} "
                    f"(clean {c_clean['spearman']:.2f})")
    ax[0].legend(); ax[0].grid(alpha=.3)

    diff = pred_cal - gt
    m = (pred_cal + gt) / 2
    md, sd = diff.mean(), diff.std(ddof=1)
    ax[1].axhline(md, color="C0", label=f"mean {md:.1f}")
    ax[1].axhline(md + 1.96 * sd, color="C1", ls="--", label=f"+/-1.96SD ({md-1.96*sd:.0f},{md+1.96*sd:.0f})")
    ax[1].axhline(md - 1.96 * sd, color="C1", ls="--")
    ax[1].scatter(m[~is_pf], diff[~is_pf], s=45, zorder=3)
    ax[1].scatter(m[is_pf], diff[is_pf], s=45, marker="x", c="crimson", zorder=3)
    ax[1].set_xlabel("(calibrated pred + GT) / 2")
    ax[1].set_ylabel("calibrated pred - GT")
    ax[1].set_title("Bland-Altman (after calibration)")
    ax[1].legend(); ax[1].grid(alpha=.3)
    fig.tight_layout()
    png = os.path.join(args.outdir, "wsi_stil_validation.png")
    fig.savefig(png, dpi=110)

    summary = {
        "n": len(rows), "nc_ratio_used": nc_used, "recommend_nc_ratio": round(k, 1),
        "all": c_all, "clean": c_clean, "pitfall": c_pf,
        "tertile_cutoffs_calibrated": [round(x, 1) for x in cuts],
        "tertile_weighted_kappa": round(kappa, 3), "tertile_accuracy": round(acc3, 3),
        "clinical_cutoffs": [CLIN_LOW, CLIN_HIGH],
    }
    json.dump(summary, open(os.path.join(args.outdir, "wsi_stil_calibration.json"), "w"),
              indent=2, ensure_ascii=False)
    print(f"\n플롯: {png}")
    print(f">>> 권장 --nc_ratio {k:.0f}")


if __name__ == "__main__":
    main()
