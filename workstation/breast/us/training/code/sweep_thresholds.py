#!/usr/bin/env python3
"""
임계값 격자표 산출 — 운영에서 조정할 수 있도록 남기는 산출물.

기본값을 acc 최대로 잡지 않는다. 과소평가(5→4)와 과잉검사(2→3 이상) 중
무엇을 피할지는 임상 운영 정책이고 우리가 정할 값이 아니다.
표를 남기고, 5 recall 하한을 조건으로 받아 그 안에서 acc 최대를 제시한다.

  python3 sweep_thresholds.py --config configs/us_lora.yaml --min-r5 0.8
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from heads import BIRADS_MIN
from train_heads_grid import Heads
import train_us_lora as T

GRADES = [2, 3, 4, 5]
GRID = [round(x, 2) for x in np.arange(0.10, 0.96, 0.05)]


def evaluate(p, gt, t2, t3, t4):
    pred = 2 + (p[:, 0] > t2) + (p[:, 1] > t3) + (p[:, 2] > t4)
    cm = {(g, q): int(((gt == g) & (pred == q)).sum()) for g in GRADES for q in GRADES}
    tot = {g: int((gt == g).sum()) for g in GRADES}
    return {
        "t2": t2, "t3": t3, "t4": t4,
        "acc": float((gt == pred).mean()),
        "w1": float((np.abs(gt - pred) <= 1).mean()),
        "mae": float(np.abs(gt - pred).mean()),
        **{f"r{g}": cm[(g, g)] / max(tot[g], 1) for g in GRADES},
        "3to2": cm[(3, 2)], "4to5": cm[(4, 5)], "5to4": cm[(5, 4)],
        "over": sum(cm[(g, q)] for g in GRADES for q in GRADES if q > g),
        "under": sum(cm[(g, q)] for g in GRADES for q in GRADES if q < g),
        "cm": cm,
    }


def show(r, gt):
    print(f"    t2={r['t2']:.2f} t3={r['t3']:.2f} t4={r['t4']:.2f}   "
          f"acc {r['acc']:.4f}  ±1 {r['w1']:.4f}  MAE {r['mae']:.3f}   "
          f"과대 {r['over']}장 · 과소 {r['under']}장")
    print("          " + "".join(f"{g:>6}" for g in GRADES) + f"{'계':>7}  recall")
    for g in GRADES:
        tot = sum(r["cm"][(g, q)] for q in GRADES)
        print(f"      {g}   " + "".join(f"{r['cm'][(g,q)]:>6}" for q in GRADES)
              + f"{tot:>7}   {r[f'r{g}']:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--heads", default=None)
    ap.add_argument("--min-r5", type=float, default=None,
                    help="5 recall 하한. 지정하면 그 조건 안에서 acc 최대를 제시한다")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seeds", type=int, default=10,
                    help="확률을 평균할 헤드 seed 수. 1 이면 저장된 헤드 그대로")
    args = ap.parse_args()

    cfg = T.load_config(Path(args.config).resolve())
    ckpt_dir = Path(cfg["output"]["ckpt_dir"])
    cache = Path(args.cache) if args.cache else ckpt_dir / "features_best.pt"
    hpath = Path(args.heads) if args.heads else ckpt_dir / "us_heads_grid_best.pt"
    out = Path(args.out) if args.out else ckpt_dir.parent / "eval_out" / "threshold_sweep.csv"

    full = torch.load(cache, map_location="cpu", weights_only=False)
    d = full["valid"]
    hb = torch.load(hpath, map_location="cpu", weights_only=False)
    meta = hb["meta"]
    gt = d["grade"].numpy()

    # 헤드 하나에 맞춘 임계값은 그 seed 에만 맞는다. seed 를 여러 개 재학습해
    # 확률을 평균한 뒤 격자를 쓴다 — 재현되는 임계값을 고르기 위해서다.
    if args.seeds > 1:
        from train_heads_grid import fit
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        acc = []
        for s in range(args.seeds):
            _, st = fit(full["train"], d, meta["p_exp"], meta["aux"], s, dev)
            h = Heads(d["feat"].shape[1], aux=meta["aux"])
            h.load_state_dict({k: v.cpu() for k, v in st.items()})
            h.eval()
            with torch.no_grad():
                acc.append(torch.sigmoid(h(d["feat"])[0]).numpy())
        probs = np.mean(acc, axis=0)
        src = f"seed {args.seeds}개 확률 평균"
    else:
        h = Heads(d["feat"].shape[1], aux=meta["aux"])
        h.load_state_dict(hb["state"])
        h.eval()
        with torch.no_grad():
            probs = torch.sigmoid(h(d["feat"])[0]).numpy()
        src = "단일 헤드"

    print("=" * 78)
    print(f"임계값 격자표   헤드 p={meta['p_exp']} aux={meta['aux']}   "
          f"valid {len(gt)}장   {src}")
    print("=" * 78)

    rows = [evaluate(probs, gt, t2, t3, t4)
            for t2 in GRID for t3 in GRID for t4 in GRID]

    out.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in rows[0] if c != "cm"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in cols})
    print(f"전체 {len(rows)}개 조합 → {out}\n")

    print("── 참고 1 · 현재 기본값 (0.5 / 0.5 / 0.5)")
    show(evaluate(probs, gt, .5, .5, .5), gt)

    print("\n── 참고 2 · acc 최대 (정책 무시)")
    show(max(rows, key=lambda r: r["acc"]), gt)

    print("\n── 5 recall 하한별 최적")
    print(f"  {'하한':>6} {'t2':>5} {'t3':>5} {'t4':>5} {'acc':>7} {'±1':>7} "
          f"{'r2':>6} {'r3':>6} {'r4':>6} {'r5':>6} {'과소':>5}")
    for lo in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        c = [r for r in rows if r["r5"] >= lo]
        if not c:
            print(f"  {lo:>6.2f}   (해당 조합 없음)")
            continue
        b = max(c, key=lambda r: r["acc"])
        print(f"  {lo:>6.2f} {b['t2']:>5.2f} {b['t3']:>5.2f} {b['t4']:>5.2f} "
              f"{b['acc']:>7.4f} {b['w1']:>7.4f} " +
              " ".join(f"{b[f'r{g}']:>6.3f}" for g in GRADES) + f" {b['under']:>5}")

    if args.min_r5 is not None:
        c = [r for r in rows if r["r5"] >= args.min_r5]
        if c:
            print(f"\n── 제안 기본값 (5 recall >= {args.min_r5})")
            show(max(c, key=lambda r: r["acc"]), gt)
        else:
            print(f"\n! 5 recall >= {args.min_r5} 를 만족하는 조합이 없다")


if __name__ == "__main__":
    main()