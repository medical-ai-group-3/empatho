#!/usr/bin/env python
"""
mass 와 calc 를 한 번에 학습한다 — 백본 LoRA 하나를 공유하고 헤드만 둘로 나눈다.

왜
  LoRA 파라미터 8.4M 을 mass 는 사진 1,010장, calc 는 1,260장으로 학습한다.
  클래스가 5개 이상인 축(margin 5개 · calctype 9개)이 개선되지 않는 이유를
  '클래스당 표본이 100장 남짓' 으로 진단했는데, 그렇다면 LoRA 가 보는 사진을
  늘리는 것이 직접적인 처방이다.

  mass 와 calc 는 같은 유방 조직 질감을 공유한다. 저수준 표현을 공유해도
  손해가 없고, 서술어 체계만 다르다. 그래서 백본 LoRA 는 합치고 헤드는 나눈다.

      사진 ─→ 동결 백본 + 공유 LoRA ─┬─→ mass 헤드 (12차원)
                  ↑ 2,270장으로 학습  └─→ calc 헤드 (13차원)

  라벨 충돌은 없다. mass 사진은 mass 헤드로만 역전파된다.

★ 이 스크립트는 train_mammo.py 를 고치지 않는다. 부품만 가져다 쓴다.

저장물
  체크포인트 두 개를 eval_e2e.py 가 그대로 읽을 수 있는 형식으로 낸다.
  각 병변의 검증 최고 시점에 독립적으로 저장하므로 두 파일의 LoRA 상태가
  서로 다를 수 있다. 의도한 것이다 — 우리가 쓸 것은 각 병변의 최선이다.

시간
  에폭당 mass 4분 + calc 5분 = 약 9분. 20에폭에 3시간.
  --epochs 를 줄이면 그만큼 줄지만 LoRA 는 후반에 붙는 경향이 있다.
"""

import argparse, sys, time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Subset

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from train_mammo import (FeatExtractor, DescriptorNet, make_head, inject_lora,
                         load_merged_model, report_levels, evaluate, fmt,
                         score_of, CFG, CKPT, INDEX_DIR, SCHEMA)
from mammo_data import (MammoROIDataset, make_datasets, load_schema,
                        label_columns, axis_slices)

KINDS = ("mass", "calc")


def build_split(kind, a, pad, cols, device):
    """
    한 병변의 학습/검증/테스트 로더를 만든다.

    이 경로는 사진 한 장이 행 하나다(증강이 매번 무작위로 걸린다) — 행 단위로
    갈라도 뒤집기 누수가 없다. 다만 검증은 증강을 꺼야 테스트와 조건이 같다.
    """
    tr_ds, te_ds = make_datasets(INDEX_DIR, SCHEMA, kind, size=a.size,
                                 pad_square=pad, clip_pct=a.clip)
    te = DataLoader(te_ds, batch_size=a.batch, num_workers=a.workers,
                    pin_memory=True)

    if a.val <= 0:
        tr = DataLoader(tr_ds, batch_size=a.batch, shuffle=True,
                        num_workers=a.workers, pin_memory=True, drop_last=True)
        pos = torch.tensor(tr_ds.df[cols].values, dtype=torch.float32).mean(0)
        return tr, None, te, pos, len(tr_ds)

    va_ds = MammoROIDataset(Path(INDEX_DIR) / f"roi_index_{kind}_train.csv",
                            SCHEMA, kind, size=a.size, augment=False,
                            pad_square=pad, clip_pct=a.clip)
    order = np.random.RandomState(a.seed).permutation(len(tr_ds))
    n_val = max(1, int(round(len(order) * a.val)))
    vi, ti = order[:n_val], order[n_val:]
    tr = DataLoader(Subset(tr_ds, ti.tolist()), batch_size=a.batch, shuffle=True,
                    num_workers=a.workers, pin_memory=True, drop_last=True)
    va = DataLoader(Subset(va_ds, vi.tolist()), batch_size=a.batch,
                    num_workers=a.workers, pin_memory=True)
    pos = torch.tensor(tr_ds.df[cols].values[ti], dtype=torch.float32).mean(0)
    print(f"    {kind:5s} 사진 {len(order)}장 -> 학습 {len(ti)} / 검증 {len(vi)}"
          f" · 테스트 {len(te_ds)}")
    return tr, va, te, pos, len(ti)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--lora-lr", type=float, default=1e-5)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--size", type=int, default=1008)
    ap.add_argument("--ckpt", default=CKPT)
    ap.add_argument("--no-pad", action="store_true", default=True,
                    help="확정 구성이 패딩 끔이라 기본값을 True 로 둔다")
    ap.add_argument("--pad", dest="no_pad", action="store_false")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--src", choices=["trunk", "vb", "blocks"], default="trunk")
    ap.add_argument("--pool", choices=["gap", "gapmax", "grid"], default="grid")
    ap.add_argument("--grid", type=int, default=4)
    ap.add_argument("--levels", choices=["last", "all"], default="last")
    ap.add_argument("--hidden", type=int, default=512,
                    help="eval_e2e.py 가 기본값 512 로 헤드를 다시 만든다. 바꾸지 마라")
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--val", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--pw-max", type=float, default=20.0)
    ap.add_argument("--select", choices=["f1", "top1"], default="f1")
    ap.add_argument("--init-mass", default=None,
                    help="mass 헤드 초기값 체크포인트. 실측으로 검증 F1 0.584 -> 0.610")
    ap.add_argument("--init-calc", default=None)
    ap.add_argument("--out-prefix", default="ckpt/mammo_joint")
    a = ap.parse_args()

    device = "cuda"
    pad = not a.no_pad
    schema = load_schema(SCHEMA)
    cols = {k: label_columns(schema, k) for k in KINDS}
    slices = {k: axis_slices(schema, k) for k in KINDS}

    ptag = f"{a.pool}{a.grid}" if a.pool == "grid" else a.pool
    dtag = f"pad{int(pad)}_clip{'0' if not a.clip else str(a.clip).replace('.','')}"
    tag = f"{a.src}_{a.levels}_{ptag}_{dtag}"

    print("=" * 78)
    print("합동 학습 — 백본 LoRA 공유 · 헤드 분리")
    print("=" * 78)
    for k in KINDS:
        print(f"  {k:5s} 출력 {len(cols[k])}차원   축 {list(slices[k])}")
    print(f"  구성  src={a.src} levels={a.levels} pool={ptag} "
          f"패딩={'켬' if pad else '끔'} 절단={a.clip}")

    # ── 데이터 ────────────────────────────────────────────────
    print("\n■ 데이터")
    loaders, pos = {}, {}
    n_train = {}
    for k in KINDS:
        tr, va, te, p, n = build_split(k, a, pad, cols[k], device)
        loaders[k] = dict(tr=tr, va=va, te=te)
        pos[k] = p
        n_train[k] = n
    total = sum(n_train.values())
    print(f"    합계 학습 사진 {total}장  "
          f"(단독 학습 대비 mass {total/n_train['mass']:.2f}배 · "
          f"calc {total/n_train['calc']:.2f}배)")

    # ── 백본 + 공유 LoRA ──────────────────────────────────────
    print("\n■ 백본 로드")
    full = load_merged_model(a.ckpt, CFG, device=device)
    vb = full.backbone.vision_backbone
    del full
    for p_ in vb.parameters():
        p_.requires_grad = False
    ext = FeatExtractor(vb, a.src)

    n_inj = inject_lora(ext.net, a.rank, a.alpha, {"qkv", "proj", "fc1", "fc2"})
    # LoRALinear 가 만드는 lora_A/lora_B 는 CPU 에서 태어난다. 이미 GPU 에 올라간
    # trunk 안에 꽂히므로 여기서 장치를 다시 맞춰야 한다. 빠뜨리면 forward 에서
    # "mat2 is on cpu" 로 죽는다.
    ext = ext.to(device)
    for name, p_ in ext.named_parameters():
        if "lora_A" in name or "lora_B" in name:
            p_.requires_grad = True
    print(f"    공유 LoRA 주입 {n_inj}개 층 (rank {a.rank} alpha {a.alpha})")

    with torch.no_grad():
        d = torch.zeros(1, 3, a.size, a.size, device=device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            feat_dim = report_levels(ext(d), a.pool, a.levels, a.grid)
        del d
    torch.cuda.empty_cache()

    # ── 헤드 둘 ───────────────────────────────────────────────
    heads, nets, crit = {}, {}, {}
    init_of = {"mass": a.init_mass, "calc": a.init_calc}
    for k in KINDS:
        h = make_head(len(cols[k]), feat_dim, a.hidden, a.dropout).to(device)
        if init_of[k]:
            # 2.6 기본값 weights_only=True 로는 못 읽는다 (지표가 numpy 스칼라)
            d0 = torch.load(init_of[k], map_location="cpu", weights_only=False)
            h.load_state_dict(d0["head"])
            print(f"    {k:5s} 헤드 초기값 <- {Path(init_of[k]).name}"
                  f"  (ep {d0.get('epoch')})")
        heads[k] = h
        nets[k] = DescriptorNet(ext, h, a.pool, a.levels, a.grid).to(device)

        pw = ((1 - pos[k]) / (pos[k] + 1e-6)).clamp(0.5, a.pw_max).to(device)
        crit[k] = nn.BCEWithLogitsLoss(pos_weight=pw)

    lora_p = [p_ for n_, p_ in ext.named_parameters() if p_.requires_grad]
    head_p = [p_ for k in KINDS for p_ in heads[k].parameters()]
    n_lora = sum(p_.numel() for p_ in lora_p)
    n_head = sum(p_.numel() for p_ in head_p)
    print(f"    학습 파라미터  LoRA {n_lora/1e6:.2f}M (공유) + "
          f"헤드 {n_head/1e6:.2f}M (분리) = {(n_lora+n_head)/1e6:.2f}M")

    opt = torch.optim.AdamW(
        [{"params": head_p, "lr": a.lr},
         {"params": lora_p, "lr": a.lora_lr}], weight_decay=0.01)

    # ── 학습 ──────────────────────────────────────────────────
    print(f"\n■ 학습 시작  epochs {a.epochs}  헤드 lr {a.lr}  LoRA lr {a.lora_lr}")
    print(f"  한 에폭 = 두 병변 전체를 한 번씩. 배치 순서는 섞는다.")
    best = {k: (-1.0, -1, None) for k in KINDS}      # (score, epoch, test)
    rng = np.random.RandomState(a.seed)

    for ep in range(1, a.epochs + 1):
        for k in KINDS:
            nets[k].train()
        iters = {k: iter(loaders[k]["tr"]) for k in KINDS}
        # 두 병변의 배치를 한 통에 넣고 섞는다. 한쪽을 몰아서 돌리면 LoRA 가
        # 뒤에 온 병변 쪽으로 치우친다.
        sched = [k for k in KINDS for _ in range(len(loaders[k]["tr"]))]
        rng.shuffle(sched)

        tot = {k: 0.0 for k in KINDS}
        nb = {k: 0 for k in KINDS}
        t0 = time.time()
        for i, k in enumerate(sched):
            try:
                x, y = next(iters[k])
            except StopIteration:
                continue
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = crit[k](nets[k](x), y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            tot[k] += loss.item(); nb[k] += 1
            if (i + 1) % 50 == 0:
                el = time.time() - t0
                eta = el / (i + 1) * (len(sched) - i - 1)
                print(f"\r    ep {ep:2d}  {i+1}/{len(sched)}  "
                      f"{el:.0f}s 경과 · 남은 {eta:.0f}s   ", end="", flush=True)
        print(f"\r{' ' * 70}\r", end="")

        line = (f"  ep {ep:3d}  "
                + "  ".join(f"{k} loss {tot[k]/max(nb[k],1):.4f}" for k in KINDS))
        print(line + f"   ({time.time()-t0:.0f}s)")

        for k in KINDS:
            nets[k].eval()
            tf1, ttop1 = evaluate(nets[k], loaders[k]["te"], device, slices[k])
            if loaders[k]["va"] is not None:
                vf1, vtop1 = evaluate(nets[k], loaders[k]["va"], device, slices[k])
                sel = score_of(vf1, vtop1, a.select)
            else:
                sel = score_of(tf1, ttop1, a.select)
            star = ""
            if sel > best[k][0]:
                best[k] = (sel, ep, (tf1, ttop1))
                out = Path(f"{a.out_prefix}_{k}_{tag}_lora.pt")
                out.parent.mkdir(parents=True, exist_ok=True)
                # 임시 파일에 쓰고 이름을 바꾼다. 제자리에 직접 쓰면 저장 도중
                # 죽었을 때 직전 체크포인트까지 깨진다(실제로 겪었다 —
                # 디스크 쓰기 실패로 합동 calc 체크포인트가 EOFError 가 됐다).
                # rename 은 같은 파일시스템에서 원자적이라 중간 상태가 안 남는다.
                tmp = out.with_suffix(".pt.tmp")
                # eval_e2e.py 가 그대로 읽는 형식이다. args 에 백본 재구성에
                # 필요한 값이 전부 들어가야 한다.
                torch.save({
                    "head": heads[k].state_dict(),
                    "lora": {n_: v for n_, v in ext.state_dict().items()
                             if "lora_" in n_},
                    "kind": k, "cols": cols[k], "epoch": int(ep),
                    "val_score": float(sel),
                    "test_f1": float(tf1["overall"][2]),
                    "test_top1": float(ttop1["mean"]),
                    "feat_dim": int(feat_dim),
                    "joint": True,
                    "args": dict(src=a.src, levels=a.levels, pool=a.pool,
                                 grid=a.grid, size=a.size, no_pad=a.no_pad,
                                 clip=a.clip, ckpt=a.ckpt, rank=a.rank,
                                 alpha=a.alpha, hidden=a.hidden,
                                 dropout=a.dropout, kind=k),
                }, tmp)
                tmp.replace(out)
                star = "  *저장"
            print(f"      {k:5s} val {sel:.3f}  test {fmt(tf1, ttop1)}{star}")

    # ── 정리 ──────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("결과")
    print("=" * 78)
    for k in KINDS:
        s, ep, t = best[k]
        print(f"  {k:5s} 검증 최고 {s:.4f} (ep {ep})")
        print(f"        그 시점 테스트  {fmt(*t)}")
        print(f"        -> {a.out_prefix}_{k}_{tag}_lora.pt")
    print("\n  두 파일의 LoRA 상태는 서로 다를 수 있다 (각자 최고 에폭에서 저장).")
    print("  단독 학습본과 비교하려면 eval_e2e.py 를 양쪽에 돌려라:")
    for k in KINDS:
        print(f"    python3 -u eval_e2e.py --ckpt {a.out_prefix}_{k}_{tag}_lora.pt")
    print("\n  ★ 판정선 — 실행 간 변동(variance_check.py)을 넘어야 개선이다.")
    print("    mass 2σ=0.009 · calc 2σ=0.005")


if __name__ == "__main__":
    main()
