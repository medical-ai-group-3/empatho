#!/usr/bin/env python3
"""
확정 설정의 등급 헤드를 **앙상블 파일 하나**로 저장한다.

확정 설정은 "seed 10개의 확률을 평균"이다(docs/experiments.md 10-4).
그런데 지금까지는 그 앙상블이 파일로 존재하지 않았고, 평가할 때마다
캐시된 특징으로 10개를 다시 학습했다. 서빙에서는 그럴 수 없으므로
10개 헤드를 한 파일에 담는다. 헤드가 1,540개짜리라 전부 담아도 100KB 남짓이다.

임계값 t4=0.45 는 **10개 확률의 평균** 위에서 고른 값이다.
단일 헤드로 서빙하면 그 근거와 어긋나므로 앙상블이어야 한다.

저장 후 valid 로 재현 검증한다 — 확정값(acc 0.5321 · ±1 0.9412)과 일치해야 한다.

  python3 make_heads_ensemble.py --config configs/us_lora.yaml
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from heads import GradingHeads                                   # noqa: E402
from train_heads_grid import fit                                 # noqa: E402
import train_us_lora as T                                        # noqa: E402

P_EXP, AUX, N_SEEDS = 0.25, False, 10
T2, T3, T4 = 0.50, 0.50, 0.45
EXPECT = {"acc": 0.5321, "w1": 0.9412}          # docs/experiments.md 10-4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = T.load_config(Path(args.config).resolve())
    ck = Path(cfg["output"]["ckpt_dir"])
    out = Path(args.out) if args.out else ck / "us_heads_ensemble.pt"
    cache = torch.load(ck / "features_best.pt", map_location="cpu", weights_only=False)
    tr, va = cache["train"], cache["valid"]
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    print("=" * 70)
    print(f"등급 헤드 앙상블 생성 — p={P_EXP} · aux={AUX} · seed {N_SEEDS}개")
    print("=" * 70)

    states, per_seed = [], []
    for s in range(N_SEEDS):
        m, st = fit(tr, va, P_EXP, AUX, s, dev)
        states.append({k: v.cpu() for k, v in st.items()})
        per_seed.append(m["acc"])
        print(f"  seed {s}  단일 acc {m['acc']:.4f}")

    # 앙상블 확률 = 각 헤드 sigmoid 출력의 평균 (로짓 평균이 아니다)
    gt = va["grade"].numpy()
    probs = []
    for st in states:
        h = GradingHeads(in_dim=va["feat"].shape[1])
        h.load_state_dict(st)
        h.eval()
        with torch.no_grad():
            probs.append(torch.sigmoid(h(va["feat"])[0]).numpy())
    p = np.mean(probs, axis=0)

    pred = 2 + (p[:, 0] > T2) + (p[:, 1] > T3) + (p[:, 2] > T4)
    acc = float((gt == pred).mean())
    w1 = float((np.abs(gt - pred) <= 1).mean())

    print()
    print(f"  단일 헤드 acc 평균 {np.mean(per_seed):.4f} (범위 "
          f"{min(per_seed):.4f}~{max(per_seed):.4f})   ※ 임계값 0.5 기준")
    print(f"  앙상블 acc {acc:.4f}   ±1 {w1:.4f}   "
          f"(t2={T2} t3={T3} t4={T4})")
    print(f"  확정값     acc {EXPECT['acc']:.4f}   ±1 {EXPECT['w1']:.4f}")
    ok = abs(acc - EXPECT["acc"]) < 1e-4 and abs(w1 - EXPECT["w1"]) < 1e-4
    print(f"  → {'✓ 일치' if ok else '✗ 불일치 — 어딘가 잘못됐다'}")
    if not ok:
        sys.exit(1)

    payload = {
        "heads": states,
        "meta": {"p_exp": P_EXP, "aux": AUX, "n_seeds": N_SEEDS,
                 "in_dim": int(va["feat"].shape[1]),
                 "thresholds": {"t2": T2, "t3": T3, "t4": T4},
                 "valid_acc": round(acc, 6), "valid_w1": round(w1, 6),
                 "source": str(ck / "features_best.pt"),
                 "note": "확률(sigmoid) 평균. 로짓 평균이 아니다."},
    }
    torch.save(payload, out)
    print(f"\n저장 {out}  ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()