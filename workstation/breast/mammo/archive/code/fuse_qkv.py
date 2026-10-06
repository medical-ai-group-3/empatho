#!/usr/bin/env python
"""
medsam3_merged.pt 의 어텐션 가중치를 파이토치 기본 형태로 되돌린다.

왜 필요한가
  merge_medsam3.py 는 nn.MultiheadAttention 을 MultiheadAttentionLoRA 로 교체한
  뒤 저장한다. 교체본은 q/k/v 를 따로 두지만, 파이토치 기본형은 셋을 합쳐
  in_proj_weight 하나로 둔다.

    체크포인트   ...self_attn.q_proj.weight / k_proj.weight / v_proj.weight
    순정 모델    ...self_attn.in_proj_weight

  추론은 항상 같은 교체를 거친 뒤 불러오므로 문제가 없었다. 그러나 학습 코드는
  순정 빌더로 모델을 만들기 때문에 키가 어긋난다. 억지로 넘기면 어텐션 가중치가
  통째로 무작위 초기값이 된다 — 학습해도 아무 의미가 없어진다.

무엇을 하나
  q/k/v 가 셋 다 있는 모듈마다 dim=0 으로 이어 붙여 in_proj_weight / in_proj_bias
  를 만들고 원래 셋은 지운다. 파이토치가 저장하는 순서 그대로다.
  나머지 키(out_proj 포함)는 손대지 않는다.

안전장치
  · 원본을 덮어쓰지 않는다. 새 파일로 쓴다
  · 합친 뒤 크기를 검산한다 (in_proj 행 수 = q 행 수 x 3)
  · 남은 q_proj 가 있으면 알려준다
  · --check 로 결과만 확인할 수 있다

사용
  python3 fuse_qkv.py                       # 미리보기
  python3 fuse_qkv.py --go                  # 변환해서 저장
  python3 fuse_qkv.py --check <파일>         # 이미 만든 파일 확인
"""

import argparse
import sys
from pathlib import Path

HOME = Path.home()
DEF_IN = HOME / "workspace/breast/mammo/ckpt/medsam3_merged.pt"
DEF_OUT = HOME / "workspace/breast/mammo/ckpt/medsam3_merged_fused.pt"

PARTS = ("q", "k", "v")


def plan_fusion(keys):
    """
    합칠 수 있는 모듈 접두사를 찾는다.
    q/k/v 의 weight 와 bias 가 모두 있어야 대상으로 본다.

    반환: 정렬된 접두사 목록
    """
    keys = set(keys)
    out = set()
    tail = ".q_proj.weight"
    for k in keys:
        if not k.endswith(tail):
            continue
        p = k[: -len(tail)]
        need = [f"{p}.{x}_proj.{s}" for x in PARTS for s in ("weight", "bias")]
        if all(n in keys for n in need):
            out.add(p)
    return sorted(out)


def fuse(sd, torch):
    """제자리에서 합친다. (합친 개수, 경고 목록) 을 돌려준다."""
    prefixes = plan_fusion(sd.keys())
    warn = []
    for p in prefixes:
        for suffix, name in (("weight", "in_proj_weight"), ("bias", "in_proj_bias")):
            parts = [sd[f"{p}.{x}_proj.{suffix}"] for x in PARTS]
            merged = torch.cat(parts, dim=0)
            # 검산 — 파이토치는 [q; k; v] 순으로 dim=0 에 쌓는다
            if merged.shape[0] != parts[0].shape[0] * 3:
                warn.append(f"{p}.{name}: 행 수가 {merged.shape[0]}, "
                            f"기대 {parts[0].shape[0] * 3}")
            sd[f"{p}.{name}"] = merged
        for x in PARTS:
            for suffix in ("weight", "bias"):
                sd.pop(f"{p}.{x}_proj.{suffix}", None)
    return len(prefixes), warn


def summarize(sd, label):
    n_q = sum(1 for k in sd if k.endswith(".q_proj.weight"))
    n_in = sum(1 for k in sd if k.endswith(".in_proj_weight"))
    n_seg = sum(1 for k in sd if k.startswith("segmentation_head."))
    print(f"  {label}")
    print(f"    텐서 {len(sd)}개   q_proj {n_q}개   in_proj {n_in}개   "
          f"segmentation_head {n_seg}개")
    return n_q, n_in


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEF_IN))
    ap.add_argument("--out", default=str(DEF_OUT))
    ap.add_argument("--check", default="", help="이미 만든 파일만 확인한다")
    ap.add_argument("--go", action="store_true", help="실제로 저장한다")
    a = ap.parse_args()

    try:
        import torch
    except ImportError:
        sys.exit("torch 없음")

    target = a.check or a.src
    p = Path(target)
    if not p.is_file():
        sys.exit(f"파일이 없다: {p}")

    print("=" * 74)
    print("어텐션 가중치 형태 되돌리기  (q/k/v 분리형 -> in_proj 통합형)")
    print("=" * 74)
    print(f"  대상 {p}  ({p.stat().st_size/1e9:.2f}GB)")

    obj = torch.load(str(p), map_location="cpu", weights_only=False)
    if not (isinstance(obj, dict) and "model" in obj):
        sys.exit(f"예상과 다른 구조다: {type(obj)} "
                 f"{list(obj)[:6] if isinstance(obj, dict) else ''}")
    sd = obj["model"]

    print()
    n_q, n_in = summarize(sd, "현재")

    if a.check:
        print()
        if n_q == 0 and n_in > 0:
            print("  -> 통합형이다. 학습 코드와 맞물린다.")
        elif n_q > 0:
            print("  -> 아직 분리형이 남아 있다. --go 로 변환해야 한다.")
        return

    if n_q == 0:
        print("\n  합칠 것이 없다. 이미 통합형이다.")
        return

    cnt, warn = fuse(sd, torch)
    print()
    summarize(sd, f"변환 후 (모듈 {cnt}개 합침)")

    if warn:
        print("\n  ! 검산 경고")
        for w in warn:
            print(f"    {w}")
        sys.exit("\n  크기가 맞지 않는다 — 저장하지 않는다.")
    print("\n  검산 통과 — 모든 in_proj 행 수가 q 의 3배다")

    left = [k for k in sd if k.endswith(".q_proj.weight")]
    if left:
        print(f"\n  ! 합치지 못한 q_proj {len(left)}개 (bias 가 없는 등):")
        for k in left[:5]:
            print(f"    {k}")

    if not a.go:
        print("\n" + "=" * 74)
        print("미리보기다. 저장하려면 --go 를 붙여라.")
        print("=" * 74)
        return

    out = Path(a.out)
    obj["model"] = sd
    tmp = out.with_suffix(out.suffix + ".tmp")
    torch.save(obj, tmp)
    tmp.replace(out)            # 이름 바꾸기는 원자적 — 반쯤 쓴 파일이 안 남는다

    print(f"\n  -> {out}  ({out.stat().st_size/1e9:.2f}GB)")
    print(f"     원본은 그대로 둔다: {p}")
    print("\n  설정을 새 파일로 바꾼다:")
    print(f"    python3 make_train_cfg.py --drop-missing --go \\")
    print(f"      --ckpt {out} \\")
    print(f"      --out sam3/train/configs/mammo/mammo_det.yaml")


if __name__ == "__main__":
    main()
