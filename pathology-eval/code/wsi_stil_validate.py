"""
WSI sTIL 파이프라인 출력 vs TIGER WSITILS GT (tiger-til-scores) 검증.
Spearman rho / Pearson r / MAE / RMSE, 산점도, Bland-Altman, 스케일 캘리브레이션.

캘리브레이션: slide_stil = nc_ratio * slide_stil_nucleus 이므로 스케일 인자는 분리 가능.
  - 원점통과 최소제곱:  k* = sum(GT . nuc) / sum(nuc^2)     -> --nc_ratio k*
  - 아핀 회귀:          GT ~ a . nuc + b
주의: k* 는 '핵->세포' 생물학적 비율(~2)이 아니라, 그 위에 밀집구역 병합검출 +
분류기 recall + 육안 vs 형태계측 편차까지 흡수한 경험적 종합 인자.
"""
import argparse
import json
import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

# GT 자체가 복잡한(육안 스코어가 림프구 이외 요소에 영향받는) 슬라이드
FLAGGED = {"108S": "many neutrophils", "123S": "necrosis+++++", "224B": "few tumor nests"}


def calib(gt, nuc):
    k = float(np.sum(gt * nuc) / np.sum(nuc ** 2))
    a, b = np.polyfit(nuc, gt, 1)
    gt_hat = a * nuc + b
    r2 = 1 - np.sum((gt - gt_hat) ** 2) / np.sum((gt - gt.mean()) ** 2)
    return k, a, b, r2


def stats_block(gt, nuc, label):
    rho, rp = stats.spearmanr(gt, nuc)
    r, pp = stats.pearsonr(gt, nuc)
    k, a, b, r2 = calib(gt, nuc)
    pred = k * nuc
    mae = np.mean(np.abs(pred - gt))
    rmse = np.sqrt(np.mean((pred - gt) ** 2))
    print(f"\n[{label}] n={len(gt)}")
    print(f"  Spearman rho = {rho:.3f} (p={rp:.4f})   Pearson r = {r:.3f} (p={pp:.4f})")
    print(f"  스케일 캘리브:  k* = {k:.1f}  (원점최소제곱)   |   GT ~ {a:.1f}*nuc + {b:.1f}  (R2={r2:.3f})")
    print(f"  캘리브 후:  MAE = {mae:.1f}   RMSE = {rmse:.1f}   (GT 0~100 스케일)")
    return dict(n=len(gt), spearman=rho, pearson=r, k_star=k, affine_a=a, affine_b=b,
                affine_r2=r2, calib_mae=mae, calib_rmse=rmse)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.expanduser("~/pathology-eval/code/stil_results/wsi_stil_results.json"))
    ap.add_argument("--outdir", default=os.path.expanduser("~/pathology-eval/code/stil_results"))
    args = ap.parse_args()

    rows = [r for r in json.load(open(args.results))
            if r["slide_stil"] is not None and r["gt_tils_score"] is not None]
    rows.sort(key=lambda r: r["gt_tils_score"])
    gt = np.array([r["gt_tils_score"] for r in rows], float)
    pred = np.array([r["slide_stil"] for r in rows], float)
    nuc = np.array([r["slide_stil_nucleus"] for r in rows], float)
    stems = [r["stem"] for r in rows]
    nc_used = pred[0] / nuc[0] if nuc[0] else 1.5
    flag = np.array([s in FLAGGED for s in stems])

    print(f"n = {len(rows)} slides.  현재 nc_ratio = {nc_used:.2f}")
    print(f"\n{'stem':8s} {'GT':>4} {'pred':>7} {'nuc':>7}  {'GTrank':>6} {'predrank':>8}  flag")
    gr, ur = stats.rankdata(gt), stats.rankdata(nuc)
    for i in range(len(rows)):
        print(f"{stems[i]:8s} {gt[i]:>4.0f} {pred[i]:>7.2f} {nuc[i]:>7.3f}  {gr[i]:>6.0f} {ur[i]:>8.0f}  "
              f"{FLAGGED.get(stems[i], '')}")

    s_all = stats_block(gt, nuc, "전체")
    s_clean = stats_block(gt[~flag], nuc[~flag], "이상치 제외 (" + ", ".join(FLAGGED) + ")")

    k = s_all["k_star"]
    pred_cal = k * nuc

    # ---- plots ----
    fig, ax = plt.subplots(1, 2, figsize=(14, 6))
    lim = max(gt.max(), pred_cal.max()) * 1.1
    ax[0].plot([0, lim], [0, lim], "k--", lw=1, alpha=.5, label="y = x")
    ax[0].scatter(gt[~flag], pred_cal[~flag], s=70, zorder=3, label=f"calibrated (k*={k:.1f})")
    ax[0].scatter(gt[flag], pred_cal[flag], s=70, marker="x", c="crimson", zorder=3, label="flagged GT")
    for i in range(len(rows)):
        ax[0].annotate(stems[i], (gt[i], pred_cal[i]), fontsize=7, alpha=.7,
                       xytext=(3, 3), textcoords="offset points")
    ax[0].set_xlabel("TIGER pathologist TIL score (GT)")
    ax[0].set_ylabel("pipeline slide_stil, calibrated (%)")
    ax[0].set_title(f"WSI sTIL vs GT   n={len(rows)}, Spearman rho={s_all['spearman']:.2f} "
                    f"(clean {s_clean['spearman']:.2f})")
    ax[0].legend(); ax[0].grid(alpha=.3)

    m = (pred_cal + gt) / 2
    diff = pred_cal - gt
    md, sd = diff.mean(), diff.std(ddof=1)
    ax[1].axhline(md, color="C0", label=f"mean diff {md:.1f}")
    ax[1].axhline(md + 1.96 * sd, color="C1", ls="--",
                 label=f"+/-1.96 SD ({md-1.96*sd:.0f}, {md+1.96*sd:.0f})")
    ax[1].axhline(md - 1.96 * sd, color="C1", ls="--")
    ax[1].scatter(m[~flag], diff[~flag], s=70, zorder=3)
    ax[1].scatter(m[flag], diff[flag], s=70, marker="x", c="crimson", zorder=3)
    for i in range(len(rows)):
        ax[1].annotate(stems[i], (m[i], diff[i]), fontsize=7, alpha=.7,
                       xytext=(3, 3), textcoords="offset points")
    ax[1].set_xlabel("(calibrated pred + GT) / 2")
    ax[1].set_ylabel("calibrated pred - GT")
    ax[1].set_title("Bland-Altman (after calibration)")
    ax[1].legend(); ax[1].grid(alpha=.3)

    fig.tight_layout()
    png = os.path.join(args.outdir, "wsi_stil_validation.png")
    fig.savefig(png, dpi=110)
    json.dump({"all": s_all, "clean": s_clean, "nc_ratio_used": nc_used,
               "recommend_nc_ratio": round(k, 1)},
              open(os.path.join(args.outdir, "wsi_stil_calibration.json"), "w"), indent=2)
    print(f"\n플롯: {png}")
    print(f"캘리브 요약: {os.path.join(args.outdir, 'wsi_stil_calibration.json')}")
    print(f"\n>>> 권장: --nc_ratio {k:.0f}  (또는 아핀 {s_all['affine_a']:.0f}*nuc + {s_all['affine_b']:.0f})")


if __name__ == "__main__":
    main()
