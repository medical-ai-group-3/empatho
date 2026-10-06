#!/usr/bin/env python3
"""
두 실험의 표본별 CSV 를 대응 비교(paired)한다. 케이스 단위 군집 부트스트랩.

왜 이렇게 재는가 — experiments.md 0-2 절
  · 같은 valid 374장을 두 모델이 평가하므로 독립 2군이 아니라 대응 비교다.
  · 파일명 -l/-r 은 같은 병변의 다른 뷰라 374장이 독립 표본 374개가 아니다
    (서로 다른 병변 212개). 재표집은 **case 단위**로 해야 한다.
  · seed 편차는 학습 재현성이지 표본오차가 아니다. 유의성 근거로 쓰지 않는다.

  python3 paired_compare.py --a eval_out/valid_joint_best.csv \\
                            --b eval_out/valid_sam3unet_best.csv --metric dice
"""

import argparse
import csv
import re
from pathlib import Path

import numpy as np

CASE = re.compile(r"(bus_\d+|case\d+)")


def load(path, metric):
    out = {}
    for x in csv.DictReader(open(path)):
        n = x["file_name"]
        if metric == "grade_acc":
            if not x.get("gt_grade"):
                continue
            out[n] = 1.0 if x["gt_grade"] == x["pred_grade"] else 0.0
        else:
            out[n] = float(x[metric])
    return out


def case_of(n):
    m = CASE.match(n)
    return m.group(1) if m else n


def icc_deff(vals):
    """짝 뷰 ICC(1,1) 와 설계효과. 케이스당 뷰가 1개뿐이면 DEFF=1."""
    g = {}
    for n, v in vals.items():
        g.setdefault(case_of(n), []).append(v)
    pairs = [v for v in g.values() if len(v) == 2]
    mbar = len(vals) / len(g)
    if not pairs:
        return 0.0, 1.0, len(g), mbar
    a = np.array([p[0] for p in pairs], float)
    b = np.array([p[1] for p in pairs], float)
    gm = np.concatenate([a, b]).mean()
    msb = 2 * ((((a + b) / 2) - gm) ** 2).sum() / max(len(a) - 1, 1)
    msw = (((a - (a + b) / 2) ** 2 + (b - (a + b) / 2) ** 2).sum()) / len(a)
    icc = float(np.clip((msb - msw) / (msb + msw), 0, 1)) if (msb + msw) > 0 else 0.0
    return icc, 1 + (mbar - 1) * icc, len(g), mbar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="기준 CSV")
    ap.add_argument("--b", required=True, help="비교 대상 CSV")
    ap.add_argument("--metric", default="dice",
                    choices=["dice", "iou", "grade_acc"])
    ap.add_argument("--boot", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    A, B = load(args.a, args.metric), load(args.b, args.metric)
    common = sorted(set(A) & set(B))
    if not common:
        raise SystemExit("✗ 겹치는 file_name 이 없다")
    a = np.array([A[n] for n in common])
    b = np.array([B[n] for n in common])
    d = b - a

    icc_a, deff_a, k, mbar = icc_deff({n: A[n] for n in common})
    icc_d, deff_d, _, _ = icc_deff({n: float(v) for n, v in zip(common, d)})

    case = np.array([case_of(n) for n in common])
    cs = np.unique(case)
    idx = {c: np.where(case == c)[0] for c in cs}
    rng = np.random.default_rng(args.seed)
    bs = np.array([d[np.concatenate([idx[c] for c in rng.choice(cs, len(cs), True)])].mean()
                   for _ in range(args.boot)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    sig = (lo > 0) or (hi < 0)

    print("=" * 74)
    print(f"대응 비교 — {args.metric}")
    print("=" * 74)
    print(f"  A  {Path(args.a).name}   {a.mean():.4f}")
    print(f"  B  {Path(args.b).name}   {b.mean():.4f}")
    print(f"  겹치는 표본 {len(common)}장 · 서로 다른 case {k}개 (케이스당 {mbar:.2f}장)")
    print(f"  A 의 ICC {icc_a:.3f} · DEFF {deff_a:.3f} → 유효 n {len(common)/deff_a:.1f}")
    print(f"  차이의 ICC {icc_d:.3f} · DEFF {deff_d:.3f}")
    print()
    print(f"  평균차 (B − A)   {d.mean():+.4f}")
    print(f"  95% CI           [{lo:+.4f}, {hi:+.4f}]   (case 단위 부트스트랩 {args.boot}회)")
    print(f"  부트스트랩 SE     {bs.std():.4f}")
    print(f"  p(차이 ≥ 0)      {np.mean(bs >= 0):.4f}")
    print(f"  → {'유의' if sig else '유의하지 않음'}")
    if args.metric == "grade_acc":
        n10 = int(((a == 1) & (b == 0)).sum())
        n01 = int(((a == 0) & (b == 1)).sum())
        print(f"  불일치: A 만 맞음 {n10}장 · B 만 맞음 {n01}장")


if __name__ == "__main__":
    main()