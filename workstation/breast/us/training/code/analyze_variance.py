#!/usr/bin/env python3
"""
seed 편차 측정 + 4↔5 경계 진단.

(1) 같은 설정에서 seed 만 바꿔 재학습했을 때 acc 가 얼마나 흔들리는지.
    설정 간 차이가 이 편차보다 작으면 그 차이는 근거가 되지 못한다.
(2) 4↔5 가 왜 절반만 풀렸는지 — 라벨 자체의 분리 가능성을 본다.

  python3 analyze_variance.py --config configs/us_lora.yaml --seeds 10
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_heads_grid import fit, GRADES
import train_us_lora as T

GRADES_L = [2, 3, 4, 5]


def auc(scores, labels):
    """이진 AUC. labels 1/0."""
    s, y = np.asarray(scores), np.asarray(labels)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    r = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--seeds", type=int, default=10)
    args = ap.parse_args()

    cfg = T.load_config(Path(args.config).resolve())
    ckpt_dir = Path(cfg["output"]["ckpt_dir"])
    d = torch.load(ckpt_dir / "features_best.pt", map_location="cpu", weights_only=False)
    tr, va = d["train"], d["valid"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("=" * 84)
    print(f"1 · seed 편차   같은 설정을 seed 만 바꿔 {args.seeds}회 재학습")
    print("=" * 84)
    print(f"{'p':>5} {'aux':>5} │ {'평균':>7} {'표준편차':>8} {'최소':>7} {'최대':>7} "
          f"{'범위':>7} │ {'±1 평균':>8}")
    print("-" * 84)

    summary = {}
    for p_exp, aux in [(0.25, False), (0.5, False), (1.0, False), (0.25, True)]:
        accs, w1s = [], []
        for s in range(args.seeds):
            m, _ = fit(tr, va, p_exp, aux, s, device)
            accs.append(m["acc"]); w1s.append(m["w1"])
        a = np.array(accs)
        summary[(p_exp, aux)] = a
        print(f"{p_exp:>5.2f} {str(aux):>5} │ {a.mean():>7.4f} {a.std():>8.4f} "
              f"{a.min():>7.4f} {a.max():>7.4f} {a.max()-a.min():>7.4f} │ "
              f"{np.mean(w1s):>8.4f}")

    a25, a10 = summary[(0.25, False)], summary[(1.0, False)]
    aaux = summary[(0.25, True)]
    print()
    print(f"  p=0.25 vs p=1.00   평균차 {a25.mean()-a10.mean():+.4f}   "
          f"seed 범위 {max(a25.max()-a25.min(), a10.max()-a10.min()):.4f}")
    print(f"  aux 유무(p=0.25)   평균차 {aaux.mean()-a25.mean():+.4f}   "
          f"seed 범위 {max(a25.max()-a25.min(), aaux.max()-aaux.min()):.4f}")
    print(f"  참고 — 어제 무증강 기준선 0.5481 과의 평균차 {a25.mean()-0.5481:+.4f}")

    print()
    print("=" * 84)
    print("2 · 4↔5 경계 진단")
    print("=" * 84)

    for split, dd in (("train", tr), ("valid", va)):
        g, m = dd["grade"].numpy(), dd["malig"].numpy()
        print(f"  [{split}] 등급별 악성 비율")
        for k in GRADES_L:
            sel = g == k
            print(f"     BI-RADS {k}   n={int(sel.sum()):>4}   "
                  f"악성 {int(m[sel].sum()):>4}  ({m[sel].mean():>5.1%})")
        s45 = np.isin(g, [4, 5])
        print(f"     → 4·5 부분집합에서 악성으로 4/5 구분 AUC "
              f"{auc(m[s45], (g[s45] == 5).astype(int)):.3f}")
        print()

    # 특징 공간에서 4 vs 5 가 선형 분리 가능한지 — 로지스틱 상한
    xtr, gtr = tr["feat"].numpy(), tr["grade"].numpy()
    xva, gva = va["feat"].numpy(), va["grade"].numpy()
    print("  특징 256차원에서 각 경계의 분리 가능성 (train 로지스틱 → valid AUC)")
    try:
        from sklearn.linear_model import LogisticRegression
        for k in (2, 3, 4):
            clf = LogisticRegression(max_iter=2000, C=1.0)
            clf.fit(xtr, (gtr > k).astype(int))
            pv = clf.predict_proba(xva)[:, 1]
            print(f"     P(y>{k})   valid AUC {auc(pv, (gva > k).astype(int)):.3f}"
                  f"   (양성 {int((gva>k).sum())}/{len(gva)})")
        sub_tr, sub_va = np.isin(gtr, [4, 5]), np.isin(gva, [4, 5])
        clf = LogisticRegression(max_iter=2000, C=1.0)
        clf.fit(xtr[sub_tr], (gtr[sub_tr] == 5).astype(int))
        pv = clf.predict_proba(xva[sub_va])[:, 1]
        print(f"     4 vs 5 만 놓고   valid AUC "
              f"{auc(pv, (gva[sub_va] == 5).astype(int)):.3f}"
              f"   (5등급 {int((gva[sub_va]==5).sum())}/{int(sub_va.sum())})")
    except ImportError:
        print("     (sklearn 없음 — 생략)")


if __name__ == "__main__":
    main()