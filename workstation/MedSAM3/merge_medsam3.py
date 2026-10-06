#!/usr/bin/env python
"""
MedSAM3 LoRA 를 SAM 3 베이스에 병합한다.

  facebook/sam3 (베이스)  +  lal-Joey/MedSAM3_v1 (LoRA)  ->  medsam3_merged.pt

결과물은 어댑터가 없는 순수 가중치라, 이후 우리 LoRA 를 새로 붙일 동결 베이스가 된다.
한 번 만들면 facebook/sam3 게이팅 승인은 더 이상 필요 없다.

──────────────────────────────────────────────────────────────────────────
반드시 알아야 할 것 두 가지
──────────────────────────────────────────────────────────────────────────
1) 이 저장소의 LoRA 는 peft 와 A·B 방향이 반대다.
     lora_A : (in_features, rank)      lora_B : (rank, out_features)
     forward: x @ A @ B * (alpha/rank)
   nn.Linear 는 y = x @ W.T 이므로 흡수 공식은
     W += (alpha/rank) * (A @ B).T          <- .T 가 핵심

   .T 를 빠뜨리면 어떻게 되는지 실측했다.
     비정사각 층(MLP)      : shape 안 맞아 ValueError 로 즉시 발각
     정사각 층(q/k/v/out_proj, embed_dim -> embed_dim)
                          : shape 이 그대로 맞아 **에러 없이 통과**하고
                            델타의 전치가 더해진다 (실측 최대오차 2.85e+02)
   SAM 3 의 어텐션 투영은 전부 정사각이라 이 실수가 가장 위험하다.
   아래 --verify 가 층 단위로 잡아낸다. 처음 돌릴 때는 반드시 켤 것.

2) apply_lora_to_model() 은 두 가지를 바꾼다.
     STEP 1  nn.MultiheadAttention -> MultiheadAttentionLoRA
             (fused in_proj_weight 가 q_proj/k_proj/v_proj 로 분리된다)
     STEP 2  nn.Linear -> LoRALinear
   병합은 STEP 2 만 되돌린다. STEP 1 의 구조 변경은 남는다.
   따라서 medsam3_merged.pt 는 **바닐라 SAM3 에 그대로 로드되지 않는다.**
   반드시 같이 들어 있는 load_merged_model() 로 불러야 한다.

사용법
  python merge_medsam3.py --lora ckpt/medsam3_lora/<파일>.pt \
                          --lora-config configs/medsam3_lora.yaml \
                          --out ckpt/medsam3_merged.pt --verify
"""

import argparse, json, hashlib, sys
from pathlib import Path

import torch
import torch.nn as nn
import yaml

# GPU matmul 은 fp32 텐서라도 기본으로 TF32(10비트 가수)를 쓴다.
# 검산과 델타 계산 모두 진짜 fp32 정밀도로 돌게 강제로 끈다.
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False


# ── CPU 전용 환경 대응 ────────────────────────────────────────────────────
# 저장소 여러 곳이 device="cuda" 를 하드코딩해 두었다.
#   sam3/model/position_encoding.py  torch.zeros(..., device="cuda")
#   sam3/model/decoder.py            torch.arange(..., device="cuda")
#   그 외 다수
# build_sam3_image_model(device="cpu") 로도 이 값들은 무시된다.
# CUDA 가 없을 때만 텐서 생성 함수의 device 인자를 cpu 로 돌린다.
# CUDA 가 있으면 아무 것도 건드리지 않으므로 5090 머신에서는 무해하다.
def install_cpu_shim() -> bool:
    if torch.cuda.is_available():
        return False

    def redirect(d):
        if isinstance(d, str) and d.startswith("cuda"):
            return "cpu"
        if isinstance(d, torch.device) and d.type == "cuda":
            return torch.device("cpu")
        return d

    def wrap(fn):
        def inner(*args, **kwargs):
            if "device" in kwargs:
                kwargs["device"] = redirect(kwargs["device"])
            return fn(*args, **kwargs)
        inner.__name__ = getattr(fn, "__name__", "wrapped")
        return inner

    for name in ("zeros", "ones", "empty", "full", "tensor", "as_tensor",
                 "arange", "linspace", "eye", "randn", "rand", "randint",
                 "zeros_like", "ones_like", "empty_like"):
        fn = getattr(torch, name, None)
        if fn is not None:
            setattr(torch, name, wrap(fn))

    # .to("cuda") · .cuda() 도 흡수한다
    _to = torch.Tensor.to

    def safe_to(self, *a, **k):
        a = tuple(redirect(x) for x in a)
        if "device" in k:
            k["device"] = redirect(k["device"])
        return _to(self, *a, **k)

    torch.Tensor.to = safe_to
    torch.Tensor.cuda = lambda self, *a, **k: self
    nn.Module.cuda = lambda self, *a, **k: self
    return True


if install_cpu_shim():
    print("[shim] CUDA 없음 — 하드코딩된 device=\"cuda\" 를 cpu 로 우회한다")

sys.path.insert(0, str(Path(__file__).resolve().parent))  # MedSAM3 저장소 루트에서 실행
from sam3.model_builder import build_sam3_image_model
from lora_layers import LoRAConfig, LoRALinear, LoRALayer, apply_lora_to_model


# ────────────────────────────── 베이스 + 어댑터 ──────────────────────────────
def build_with_lora(lora_cfg_path: str, device: str, load_from_hf: bool = True):
    """
    inference_lora.py 와 동일한 순서로 모델을 세운다.

    load_from_hf=True   병합용. facebook/sam3 의 sam3.pt 를 받는다 (게이트 승인 필요).
    load_from_hf=False  재로딩용. 구조만 세우고 가중치는 건드리지 않는다.
                        곧바로 병합본으로 전체를 덮어쓰므로 랜덤 초기화라도 무방하다.
                        팀원들은 이 경로라서 HF 토큰도 승인도 필요 없다.
    """
    print(f"[1/5] SAM 3 구조 빌드 (베이스 가중치 {'다운로드' if load_from_hf else '생략'})")
    model = build_sam3_image_model(
        device=device,
        compile=False,
        load_from_HF=load_from_hf,
        bpe_path="sam3/assets/bpe_simple_vocab_16e6.txt.gz",
        eval_mode=True,
    )

    cfg = yaml.safe_load(open(lora_cfg_path))["lora"]
    print(f"[2/5] LoRA 주입  rank={cfg['rank']} alpha={cfg['alpha']} "
          f"(scaling={cfg['alpha'] / cfg['rank']:.4f})")
    lora_config = LoRAConfig(
        rank=cfg["rank"], alpha=cfg["alpha"],
        dropout=0.0,                        # 병합 시 dropout 은 반드시 0
        target_modules=cfg["target_modules"],
        apply_to_vision_encoder=cfg["apply_to_vision_encoder"],
        apply_to_text_encoder=cfg["apply_to_text_encoder"],
        apply_to_geometry_encoder=cfg["apply_to_geometry_encoder"],
        apply_to_detr_encoder=cfg["apply_to_detr_encoder"],
        apply_to_detr_decoder=cfg["apply_to_detr_decoder"],
        apply_to_mask_decoder=cfg["apply_to_mask_decoder"],
    )
    model = apply_lora_to_model(model, lora_config)
    model = model.to(device)  # LoRA 로 새로 생긴 파라미터는 기본이 CPU
    return model, cfg


def load_lora_strict(model: nn.Module, path: str):
    """
    저장소의 load_lora_weights() 는 strict=False 라 키가 안 맞아도 조용히 넘어간다.
    rank/alpha 를 잘못 잡았거나 SAM 3.1 을 받았을 때 여기서 걸러야 한다.
    """
    print(f"[3/5] MedSAM3 LoRA 적재  {path}")
    ckpt = torch.load(path, map_location="cpu")
    if isinstance(ckpt, dict) and "state_dict" in ckpt:
        ckpt = ckpt["state_dict"]

    expected = set()
    for name, m in model.named_modules():
        if isinstance(m, LoRALayer):
            expected |= {f"{name}.lora_A", f"{name}.lora_B"}

    got = set(ckpt.keys())
    missing, unexpected = expected - got, got - expected
    print(f"      모델이 기대하는 LoRA 텐서 {len(expected)}개 · 파일에 있는 것 {len(got)}개")

    if missing or unexpected:
        print("\n  ✗ 키가 맞지 않는다. 병합을 중단한다.")
        if missing:
            print(f"    없음 {len(missing)}개 예) {sorted(missing)[:3]}")
        if unexpected:
            print(f"    남음 {len(unexpected)}개 예) {sorted(unexpected)[:3]}")
        print("\n  확인할 것")
        print("    - facebook/sam3.1 이 아니라 facebook/sam3 를 받았는가")
        print("    - lora-config 의 rank/alpha/target_modules 가 MedSAM3 학습 설정과 같은가")
        print("    - apply_to_* 플래그가 학습 때와 같은가")
        sys.exit(1)

    for name, m in model.named_modules():
        if isinstance(m, LoRALayer):
            for p in ("lora_A", "lora_B"):
                t = ckpt[f"{name}.{p}"]
                tgt = getattr(m, p)
                if t.shape != tgt.shape:
                    sys.exit(f"  ✗ shape 불일치 {name}.{p}: {tuple(t.shape)} vs {tuple(tgt.shape)}")
                tgt.data.copy_(t.to(tgt.dtype))
    print("      ✓ 전 텐서 적재 완료")


# ────────────────────────────── 병합 ──────────────────────────────
def _delta(lora: LoRALayer, like: torch.Tensor) -> torch.Tensor:
    """W 에 더할 값.  (in,r) @ (r,out) -> (in,out) -> .T -> (out,in) = W shape"""
    d = (lora.lora_A.detach().float() @ lora.lora_B.detach().float()).T * lora.scaling
    return d.to(dtype=like.dtype, device=like.device)


@torch.no_grad()
def verify_layers(model: nn.Module, n_probe: int = 64, tol: float = 1e-3):
    """
    병합 전에 층 단위로 검산한다. W · A · B · x 를 전부 fp32 로 뽑아
    ref(원본 forward 재현) 와 got(병합 후 재현) 을 직접 계산해 비교한다.

    절대오차가 아니라 상대오차로 판정한다 — 458층은 각기 다른 규모(출력 크기)를
    가지므로, 같은 절대오차라도 층에 따라 의미가 다르다(큰 출력에서는 정상 잡음,
    작은 출력에서는 진짜 문제). 공식 자체(전치 실수 등)가 틀렸으면 상대오차가
    수십~수백 배로 뛰므로 이 기준으로도 100% 걸린다.
    """
    print(f"[4/5] 병합 공식 검산  (fp32 · 상대오차 기준 · 층당 무작위 입력 {n_probe}개)")
    worst_abs, worst_rel, checked = 0.0, 0.0, 0
    for name, m in model.named_modules():
        if not isinstance(m, LoRALinear):
            continue
        lin, lora = m.original_layer, m.lora
        W = lin.weight.detach().float()
        b = lin.bias.detach().float() if lin.bias is not None else None
        A = lora.lora_A.detach().float()
        B = lora.lora_B.detach().float()
        x = torch.randn(n_probe, lin.in_features, dtype=torch.float32, device=lin.weight.device)

        ref = x @ W.T + (b if b is not None else 0.0) + (x @ A @ B) * lora.scaling
        Wm = W + (A @ B).T * lora.scaling
        got = x @ Wm.T + (b if b is not None else 0.0)

        d = (ref - got).abs().max().item()
        rel = d / (ref.abs().max().item() + 1e-6)
        worst_abs = max(worst_abs, d)
        worst_rel = max(worst_rel, rel)
        checked += 1

    print(f"      검사한 층 {checked}개 · 최대 절대오차 {worst_abs:.3e} · 최대 상대오차 {worst_rel:.3e}")
    if worst_rel > tol:
        sys.exit(f"  ✗ 상대오차 허용치 {tol:.0e} 초과. 병합 공식이 이 구현과 맞지 않는다. 중단한다.")
    print("      ✓ 통과 — 절대오차는 출력 크기가 큰 층에서 나온 것뿐, 상대오차는 fp32 정상 범위다.")
    return checked, worst_rel


@torch.no_grad()
def merge_(model: nn.Module) -> int:
    """LoRALinear -> 순수 nn.Linear. 델타를 weight 에 흡수하고 어댑터를 떼어낸다."""
    print("[5/5] 병합 및 어댑터 제거")
    targets = [(n, m) for n, m in model.named_modules() if isinstance(m, LoRALinear)]
    for name, m in targets:
        lin = m.original_layer
        lin.weight.data += _delta(m.lora, lin.weight)
        *parent_path, attr = name.split(".")
        parent = model
        for p in parent_path:
            parent = getattr(parent, p)
        setattr(parent, attr, lin)                              # 부모에 순수 Linear 재부착
    left = sum(1 for _, m in model.named_modules() if isinstance(m, (LoRALinear, LoRALayer)))
    if left:
        sys.exit(f"  ✗ 어댑터 {left}개가 남아 있다. 중단한다.")
    print(f"      ✓ {len(targets)}개 층 병합 · 잔여 어댑터 0")
    return len(targets)


# ────────────────────────────── 재로딩 ──────────────────────────────
def strip_lora_(model: nn.Module):
    """LoRA 를 주입만 하고 학습은 안 한 상태에서 껍데기를 벗긴다 (재로딩용)."""
    for name, m in [(n, m) for n, m in model.named_modules() if isinstance(m, LoRALinear)]:
        *parent_path, attr = name.split(".")
        parent = model
        for p in parent_path:
            parent = getattr(parent, p)
        setattr(parent, attr, m.original_layer)
    return model


def load_merged_model(merged_path: str, lora_cfg_path: str, device: str = "cuda"):
    """
    병합본을 다시 불러온다.

    바닐라 SAM3 에는 로드되지 않는다 — MultiheadAttentionLoRA 로 구조가 바뀐 상태이기 때문.
    같은 변환을 거친 뒤 LoRALinear 껍데기만 벗겨서 형태를 맞춘다.

    load_from_hf=False 이므로 HF 를 전혀 건드리지 않는다.
    팀원들은 게이트 승인도 토큰도 없이 이 함수로 병합본을 바로 쓸 수 있다.
    필요한 것은 저장소 코드(sam3/ + lora_layers.py)와 medsam3_merged.pt 뿐이다.
    """
    model, _ = build_with_lora(lora_cfg_path, device, load_from_hf=False)
    strip_lora_(model)
    sd = torch.load(merged_path, map_location="cpu")
    missing, unexpected = model.load_state_dict(sd["model"], strict=False)
    if missing or unexpected:
        print(f"  ! missing={len(missing)} unexpected={len(unexpected)}")
        print(f"    예) missing {missing[:3]} / unexpected {unexpected[:3]}")
    model.to(device).eval()
    return model


# ────────────────────────────── main ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lora", required=True, help="MedSAM3_v1 LoRA 가중치 파일")
    ap.add_argument("--lora-config", required=True, help="rank/alpha/target_modules 가 든 yaml")
    ap.add_argument("--out", default="ckpt/medsam3_merged.pt")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--verify", action="store_true", help="병합 전 층 단위 검산 (권장)")
    ap.add_argument("--tol", type=float, default=1e-3, help="검산 상대오차 허용치")
    a = ap.parse_args()

    model, cfg = build_with_lora(a.lora_config, a.device)
    load_lora_strict(model, a.lora)
    model.eval()

    checked, worst = (0, 0.0)
    if a.verify:
        checked, worst = verify_layers(model, tol=a.tol)
    else:
        print("[4/5] 검산 건너뜀 — 처음 만들 때는 --verify 를 권한다")

    n = merge_(model)

    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model.state_dict(),
        "meta": {
            "base": "facebook/sam3",
            "lora": str(a.lora),
            "lora_sha256": hashlib.sha256(Path(a.lora).read_bytes()).hexdigest()[:16],
            "lora_config": cfg,
            "merged_layers": n,
            "verified_layers": checked,
            "max_rel_err": worst,
            "note": "MultiheadAttentionLoRA 구조 유지 — load_merged_model() 로만 로드할 것",
        },
    }
    torch.save(payload, out)
    print(f"\n저장 {out}  ({out.stat().st_size / 1e9:.2f} GB)")
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2, default=str))
    print("\n다음 — 이 파일을 동결 베이스로 삼아 우리 LoRA + 서술어 헤드를 붙인다.")


if __name__ == "__main__":
    main()
