"""
학습과 평가가 같은 설정으로 모델을 세우게 한다.

왜 필요한가
  지금은 두 스크립트에 LoRA 인자를 각각 타이핑한다.

    train_mammo_det.py  --rank 16 --alpha 32 --target-modules q_proj,...
    eval_mammo_det.py   --rank 16 --alpha 32 --target-modules q_proj,...

  하나라도 어긋나면 평가가 다른 구조의 모델을 세우고, 학습된 가중치가
  엉뚱한 자리에 얹힌다. 그러면 성능이 아니라 구성 오류를 재게 되는데
  숫자는 그럴듯하게 나온다. 조용히 틀리는 종류다.

  configs/mammo_det.yaml 한 곳에서 읽으면 그 가능성이 사라진다.

어떻게 쓰나
  설정에 있는 값만 argparse 기본값을 덮는다. 명령줄에서 준 값이 우선한다.
  설정 파일이 없으면 스크립트의 기존 기본값을 그대로 쓴다 — 파일이 사라져도
  동작이 멈추지 않는다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import CONFIGS  # noqa: E402

DEFAULT = CONFIGS / "mammo_det.yaml"


def load(path=None):
    p = Path(path or DEFAULT)
    if not p.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        print(f"  ! pyyaml 이 없어 설정을 못 읽는다: {p}")
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"  ! 설정을 못 읽었다 ({type(e).__name__}: {e}) — 기본값을 쓴다")
        return {}


def lora_args(cfg):
    """
    학습과 평가가 함께 쓰는 값. 여기서만 정한다.
    설정에 없는 항목은 돌려주지 않는다 — 스크립트 기본값이 남는다.
    """
    l = cfg.get("lora") or {}
    ap = l.get("apply_to") or {}
    out = {}
    for k in ("rank", "alpha"):
        if k in l:
            out[k] = int(l[k])
    if "dropout" in l:
        out["dropout"] = float(l["dropout"])
    if l.get("target_modules"):
        out["target_modules"] = ",".join(str(x) for x in l["target_modules"])
    for key, arg in (("vision_encoder", "vision"), ("text_encoder", "text"),
                     ("detr_encoder", "detr_enc"), ("detr_decoder", "detr_dec"),
                     ("mask_decoder", "mask_dec")):
        if key in ap:
            out[arg] = int(bool(ap[key]))
    for k, arg in (("trainable_pct_min", "pct_lo"),
                   ("trainable_pct_max", "pct_hi")):
        if k in l:
            out[arg] = float(l[k])
    return out


def model_args(cfg):
    m = cfg.get("model") or {}
    out = {}
    if "resolution" in m:
        out["res"] = int(m["resolution"])
    return out


def train_args(cfg):
    t = cfg.get("training") or {}
    d = cfg.get("data") or {}
    out = {}
    for k, arg in (("epochs", "epochs"), ("batch_size", "batch"),
                   ("warmup_steps", "warmup"), ("val_batches", "val_batches")):
        if k in t:
            out[arg] = int(t[k])
    for k, arg in (("lr", "lr"), ("weight_decay", "wd"), ("grad_clip", "clip")):
        if k in t:
            out[arg] = float(t[k])
    if "amp" in t:
        out["amp"] = str(t["amp"])
    if d.get("root"):
        from paths import ROOT
        p = Path(d["root"])
        out["data"] = str(p if p.is_absolute() else ROOT / p)
    return out


def eval_args(cfg):
    e = cfg.get("eval") or {}
    out = {}
    for k, arg in (("tile", "tile"), ("overlap", "overlap")):
        if k in e:
            out[arg] = int(e[k])
    for k, arg in (("score_threshold", "thr"), ("nms_iou", "nms"),
                   ("iou_hit", "iou")):
        if k in e:
            out[arg] = float(e[k])
    if e.get("split"):
        out["split"] = str(e["split"])
    return out


def show(cfg, path, extra=None):
    """무엇을 읽었는지 화면에 남긴다. 나중에 로그만 보고도 재현할 수 있게."""
    if not cfg:
        print(f"  설정 없음 ({path}) — 스크립트 기본값을 쓴다")
        return
    l = cfg.get("lora") or {}
    ap = l.get("apply_to") or {}
    # detr_encoder 와 detr_decoder 가 둘 다 'detr' 로 줄어들면 구분이 안 된다
    short = {"vision_encoder": "vision", "text_encoder": "text",
             "geometry_encoder": "geom", "detr_encoder": "detr-enc",
             "detr_decoder": "detr-dec", "mask_decoder": "mask-dec"}
    on = [short.get(k, k) for k, v in ap.items() if v]
    print(f"  설정 {path}")
    print(f"    LoRA rank {l.get('rank')} alpha {l.get('alpha')} · "
          f"붙일 곳 {'·'.join(on) or '없음'}")
    if extra:
        print(f"    {extra}")
