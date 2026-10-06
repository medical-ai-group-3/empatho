#!/usr/bin/env python3
"""
헤드 전용 재학습 + 격자 탐색.

cache_features.py 가 만든 캐시만 읽는다. 분할 LoRA·픽셀 디코더는 동결 상태이며
여기서 건드리지 않는다. 헤드가 1,540개뿐이라 설정 하나당 수 초에 끝난다.

격자
  pos_weight 지수 p   역빈도 w 를 w**p 로 감쇠. p=1.0 이 현재값, p=0.5 가 제곱근,
                      p=0 이면 가중치 없음. 실측으로 고른다.
  악성 보조 입력      CORAL 헤드 입력에 sigmoid(악성 로짓) 을 detach 해서 덧붙인다.
                      악성 484장이 5등급 120장보다 많고 AUC 0.928 이라 4↔5 경계에
                      쓸 신호가 있는지 본다.

  python3 train_heads_grid.py --config configs/us_lora.yaml
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
from heads import (BIRADS_MIN, NUM_BOUNDARIES, CoralHead, MalignancyHead,
                   coral_targets)
import train_us_lora as T

GRADES = [2, 3, 4, 5]


class Heads(nn.Module):
    """GradingHeads 와 같되, 악성 확률을 CORAL 입력에 덧붙이는 선택지를 둔다."""

    def __init__(self, in_dim, hidden=None, dropout=0.0, aux=False):
        super().__init__()
        self.aux = aux
        self.malignancy = MalignancyHead(in_dim, hidden, dropout)
        self.coral = CoralHead(in_dim + (1 if aux else 0), hidden, dropout)

    def forward(self, feat):
        ml = self.malignancy(feat)
        if self.aux:
            # detach — 등급 손실이 악성 헤드를 역으로 끌지 않게 한다.
            feat = torch.cat([feat, torch.sigmoid(ml).detach()[:, None]], dim=-1)
        return self.coral(feat), ml


def pos_weights(grades, maligs, p):
    """역빈도 w=(neg/pos) 를 w**p 로 감쇠. p=0 이면 전부 1.0."""
    n = len(grades)
    w = []
    for k in range(BIRADS_MIN, BIRADS_MIN + NUM_BOUNDARIES):
        pos = int((grades > k).sum())
        w.append(((n - pos) / max(pos, 1)) ** p)
    m = int(maligs.sum())
    return torch.tensor(w, dtype=torch.float32), torch.tensor(
        ((n - m) / max(m, 1)) ** p, dtype=torch.float32)


def metrics(gt, pred):
    gt, pred = np.asarray(gt), np.asarray(pred)
    cm = {(g, p): int(((gt == g) & (pred == p)).sum()) for g in GRADES for p in GRADES}
    tot = {g: int((gt == g).sum()) for g in GRADES}
    return {
        "acc": float((gt == pred).mean()),
        "w1": float((np.abs(gt - pred) <= 1).mean()),
        "mae": float(np.abs(gt - pred).mean()),
        "r": {g: cm[(g, g)] / max(tot[g], 1) for g in GRADES},
        "3to2": cm[(3, 2)],
        "4to5": cm[(4, 5)],
        "cm": cm,
    }


def fit(tr, va, p_exp, aux, seed, device, epochs=300, lr=3e-3, wd=1e-2, hidden=None):
    torch.manual_seed(seed)
    xtr, gtr, mtr = tr["feat"].to(device), tr["grade"].to(device), tr["malig"].to(device)
    xva, gva = va["feat"].to(device), va["grade"].to(device)

    cw, mw = pos_weights(tr["grade"].numpy(), tr["malig"].numpy(), p_exp)
    cw, mw = cw.to(device), mw.to(device)

    h = Heads(xtr.shape[1], hidden=hidden, aux=aux).to(device)
    opt = torch.optim.AdamW(h.parameters(), lr=lr, weight_decay=wd)

    best = (-1.0, None)
    for ep in range(epochs):
        h.train()
        cl, ml = h(xtr)
        loss = F.binary_cross_entropy_with_logits(cl, coral_targets(gtr), pos_weight=cw)
        loss = loss + F.binary_cross_entropy_with_logits(ml, mtr, pos_weight=mw)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()

        if (ep + 1) % 10 == 0:
            h.eval()
            with torch.no_grad():
                pv = (BIRADS_MIN + (h(xva)[0] > 0).sum(1)).cpu().numpy()
            m = metrics(gva.cpu().numpy(), pv)
            if m["acc"] > best[0]:
                best = (m["acc"], m, {k: v.detach().clone() for k, v in h.state_dict().items()})
    return best[1], best[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--exps", default="0.0,0.25,0.5,0.75,1.0")
    args = ap.parse_args()

    cfg = T.load_config(Path(args.config).resolve())
    ckpt_dir = Path(cfg["output"]["ckpt_dir"])
    cache = Path(args.cache) if args.cache else ckpt_dir / "features_best.pt"
    d = torch.load(cache, map_location="cpu", weights_only=False)
    tr, va = d["train"], d["valid"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("=" * 96)
    print(f"헤드 격자 탐색   train {tuple(tr['feat'].shape)}  valid {tuple(va['feat'].shape)}"
          f"   seed {args.seeds}개 평균   device {device}")
    print("=" * 96)
    print(f"{'p':>5} {'aux':>4} │ {'acc':>7} {'±1':>7} {'MAE':>6} │ {'3→2':>5} {'4→5':>5} │ "
          f"{'r2':>6} {'r3':>6} {'r4':>6} {'r5':>6}")
    print("-" * 96)

    rows, exps = [], [float(x) for x in args.exps.split(",")]
    for p_exp in exps:
        for aux in (False, True):
            ms, states = [], []
            for s in range(args.seeds):
                m, st = fit(tr, va, p_exp, aux, s, device)
                ms.append(m); states.append(st)
            avg = {k: float(np.mean([m[k] for m in ms])) for k in ("acc", "w1", "mae")}
            avg.update({k: float(np.mean([m[k] for m in ms])) for k in ("3to2", "4to5")})
            avg["r"] = {g: float(np.mean([m["r"][g] for m in ms])) for g in GRADES}
            bi = int(np.argmax([m["acc"] for m in ms]))
            rows.append((p_exp, aux, avg, ms[bi], states[bi]))
            print(f"{p_exp:>5.2f} {str(aux):>4} │ {avg['acc']:>7.4f} {avg['w1']:>7.4f} "
                  f"{avg['mae']:>6.3f} │ {avg['3to2']:>5.1f} {avg['4to5']:>5.1f} │ "
                  + " ".join(f"{avg['r'][g]:>6.3f}" for g in GRADES))

    print("-" * 96)
    print(f"{'현재(30ep 결합학습)':>16} │ {0.5000:>7.4f} {0.9278:>7.4f} {0.578:>6.3f} │ "
          f"{53:>5} {62:>5} │ {0.856:>6.3f} {0.195:>6.3f} {0.303:>6.3f} {0.889:>6.3f}")
    print(f"{'어제 무증강 기준선':>16} │ {0.5481:>7.4f} {0.9225:>7.4f} {'':>6} │ "
          f"{39:>5} {57:>5} │")

    best = max(rows, key=lambda r: r[2]["acc"])
    p_exp, aux, avg, m, st = best
    print(f"\n★ 최고 acc  p={p_exp} aux={aux}   acc {avg['acc']:.4f}  ±1 {avg['w1']:.4f}")
    print("        " + "".join(f"{g:>6}" for g in GRADES) + f"{'계':>7}")
    for g in GRADES:
        print(f"    {g}   " + "".join(f"{m['cm'][(g,p)]:>6}" for p in GRADES)
              + f"{sum(m['cm'][(g,p)] for p in GRADES):>7}")

    out = ckpt_dir / "us_heads_grid_best.pt"
    torch.save({"state": st, "meta": {"p_exp": p_exp, "aux": aux, "acc": avg["acc"],
                                      "source": str(cache)}}, out)
    print(f"\n저장 {out}")
    (ckpt_dir / "heads_grid.json").write_text(json.dumps(
        [{"p": p, "aux": a, **{k: v for k, v in av.items() if k != "r"},
          "recall": av["r"]} for p, a, av, _, _ in rows], indent=2, ensure_ascii=False))
    print(f"     {ckpt_dir / 'heads_grid.json'}")


if __name__ == "__main__":
    main()