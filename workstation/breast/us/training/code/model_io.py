#!/usr/bin/env python3
"""
모델 적재·전처리 공통 모듈 — 서빙과 평가가 함께 쓴다.

원래 eval_us_lora.py 안에 있었으나 서빙에 필요한 것만 떼어냈다.
eval_us_lora.py 의 나머지(평가·시각화)는 scipy · pycocotools · ImageDraw 를
끌고 오는데, 아래 함수들은 그것들을 쓰지 않는다.
덕분에 서버에는 이 파일만 올리면 되고 평가 의존성이 따라가지 않는다.

의존성 — torch · numpy · yaml · torchvision · heads · unet_pixel_decoder

주의 — import_medsam3() 은 내부에서 os.chdir 한다.
호출 전에 모든 경로를 절대경로로 확정할 것. 서빙에서는 infer_us.load_model()
이 호출 후 원래 디렉토리로 되돌린다.
"""

import os
import sys
from pathlib import Path

import numpy as np
import torch
import yaml

from heads import GradingHeads

# 텍스트 프롬프트. COCO 의 category name 과 같아야 한다 —
# 학습 때 class_name.lower() 로 이 값이 쓰였다.
CLASS_NAME = "lesion"


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def import_medsam3(repo_root: str):
    # 주의: 내부에서 os.chdir 한다. 호출 전에 경로를 절대경로로 확정할 것.
    repo = str(Path(repo_root).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    os.chdir(repo)

    from merge_medsam3 import load_merged_model
    from lora_layers import LoRAConfig, apply_lora_to_model, load_lora_weights
    from sam3.train.data.collator import collate_fn_api
    from sam3.train.data.sam3_image_dataset import (
        Datapoint, FindQueryLoaded, Image, InferenceMetadata,
    )

    return dict(
        load_merged_model=load_merged_model, LoRAConfig=LoRAConfig,
        apply_lora_to_model=apply_lora_to_model, load_lora_weights=load_lora_weights,
        collate_fn_api=collate_fn_api, Datapoint=Datapoint,
        FindQueryLoaded=FindQueryLoaded, Image=Image,
        InferenceMetadata=InferenceMetadata,
    )


def move_to_device(obj, device):
    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, list):
        return [move_to_device(x, device) for x in obj]
    if isinstance(obj, tuple):
        return tuple(move_to_device(x, device) for x in obj)
    if isinstance(obj, dict):
        return {k: move_to_device(v, device) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        for f in obj.__dataclass_fields__:
            setattr(obj, f, move_to_device(getattr(obj, f), device))
        return obj
    return obj


def _unwrap(obj):
    """새 형식은 {"state":..., "meta":...}, 옛 형식은 state_dict 그대로."""
    if isinstance(obj, dict) and "state" in obj and "meta" in obj:
        return obj["state"], obj["meta"]
    return obj, None


def build_model(cfg, weights_path, M, device, load_lora=True):
    ckpt = Path(cfg["model"]["checkpoint"]).resolve()
    merge_cfg = Path(cfg["model"]["merge_lora_config"]).resolve()
    print(f"병합본 로드   {ckpt}")
    model = M["load_merged_model"](str(ckpt), str(merge_cfg), device=device)

    lc = cfg["lora"]
    model = M["apply_lora_to_model"](model, M["LoRAConfig"](
        rank=lc["rank"], alpha=lc["alpha"], dropout=0.0,
        target_modules=lc["target_modules"],
        apply_to_vision_encoder=lc["apply_to_vision_encoder"],
        apply_to_text_encoder=lc["apply_to_text_encoder"],
        apply_to_geometry_encoder=lc["apply_to_geometry_encoder"],
        apply_to_detr_encoder=lc["apply_to_detr_encoder"],
        apply_to_detr_decoder=lc["apply_to_detr_decoder"],
        apply_to_mask_decoder=lc["apply_to_mask_decoder"],
    ))
    if load_lora:
        print(f"US LoRA 로드  {weights_path}")
        M["load_lora_weights"](model, str(weights_path))
    else:
        # lora_B 가 zeros 초기화라(lora_layers.py:209) 가중치를 안 실으면
        # LoRA 출력이 정확히 0 — 병합본 단독과 수학적으로 같다.
        print("US LoRA 로드 생략 — 병합본 단독 (--no-lora)")

    model.to(device).eval()
    return model


def load_heads(path, cfg, device):
    """등급 헤드 로드. 없으면 None (분할만 평가)."""
    if not path or not Path(path).exists():
        return None
    h = cfg.get("heads", {})
    heads = GradingHeads(in_dim=h.get("in_dim", 256), hidden=h.get("hidden"),
                         dropout=0.0)
    state, meta = _unwrap(torch.load(str(path), map_location="cpu"))
    heads.load_state_dict(state)
    print(f"등급 헤드 로드 {path}" + (f"  (epoch {meta['epoch']})" if meta else ""))
    return heads.to(device).eval()


def load_pixel_decoder(model, path, cfg, device):
    """학습된 UNet 픽셀 디코더를 얹는다. save_lora_weights 가 Conv2d 를
    저장하지 않으므로 이 파일이 없으면 디코더가 무작위 초기값으로 남는다."""
    pdcfg = cfg.get("pixel_decoder", {})
    if pdcfg.get("block_type", "original") == "original":
        return None
    import unet_pixel_decoder as UPD
    UPD.swap_in(model, block_type=pdcfg["block_type"], warm_start=False)
    _, _, mod = UPD.find_pixel_decoder(model)
    if not Path(path).exists():
        sys.exit(f"✗ 픽셀 디코더 가중치가 없다: {path}\n"
                 f"  설정이 block_type={pdcfg['block_type']} 인데 학습된 디코더가 없으면 "
                 f"무작위 가중치로 추론하게 된다")
    state, meta = _unwrap(torch.load(str(path), map_location="cpu"))
    mod.load_state_dict(state)
    print(f"픽셀 디코더 로드 {path}" + (f"  (epoch {meta['epoch']})" if meta else ""))
    return mod.to(device).eval()


def pred_union(mask_logits, keep_idx, h, w, mask_threshold):
    """쿼리 마스크 로짓 → 원본 해상도 이진 마스크.

    ⚠ 순서를 바꾸지 말 것 — 보간 → sigmoid → 이진화.
      pred_masks 는 확률이 아니라 로짓이다. 이진화 후 보간하면 경계가 뭉개진다.
      SAM3 공식 후처리와 같은 순서다.
    """
    if mask_logits is None or len(keep_idx) == 0:
        return np.zeros((h, w), dtype=bool)
    sel = mask_logits[keep_idx][:, None].float()
    sel = torch.nn.functional.interpolate(sel, size=(h, w), mode="bilinear",
                                          align_corners=False)
    return (sel.sigmoid() > mask_threshold).any(dim=0).squeeze(0).cpu().numpy()


def run_one_query(model, M, image_tensor, resolution, orig_h, orig_w, device):
    # original_size 를 넘기지만 raw forward 는 쓰지 않는다(PostProcessor 전용).
    # 마스크 리사이즈는 pred_union 에서 직접 한다.
    image_obj = M["Image"](data=image_tensor, objects=[], size=(resolution, resolution))
    meta = M["InferenceMetadata"](
        coco_image_id=0, original_image_id=0, original_category_id=0,
        original_size=(orig_h, orig_w), object_id=-1, frame_index=-1,
    )
    query = M["FindQueryLoaded"](
        query_text=CLASS_NAME, image_id=0, object_ids_output=[],
        is_exhaustive=True, query_processing_order=0, inference_metadata=meta,
    )
    dp = M["Datapoint"](find_queries=[query], images=[image_obj], raw_images=[None])
    batch = M["collate_fn_api"]([dp], dict_key="input", with_seg_masks=True)
    return model(move_to_device(batch["input"], device))[-1]


class HeadBundle:
    """단일 헤드와 앙상블을 같은 인터페이스로 감싼다.

    ⚠ 확률(sigmoid)을 평균한다. 로짓 평균은 다른 값이다.
    """

    def __init__(self, heads, meta):
        self.heads = heads
        self.meta = meta or {}
        self.n = len(heads)

    @torch.no_grad()
    def probs(self, feat):
        """(coral_prob (B,3), malig_prob (B,)) 를 돌려준다."""
        c, m = [], []
        for h in self.heads:
            a, b = h(feat)
            c.append(torch.sigmoid(a))
            m.append(torch.sigmoid(b))
        return torch.stack(c).mean(0), torch.stack(m).mean(0)


def load_grading_heads(path, cfg, device):
    """등급 헤드 로드. 앙상블 {"heads":[...]} 와 단일 {"state":...} 을 모두 받는다.
    없으면 None → 분할만 수행."""
    if not path or not Path(path).exists():
        return None
    d = torch.load(str(path), map_location="cpu", weights_only=False)
    h = cfg.get("heads", {}) or {}
    in_dim = h.get("in_dim", 256)

    if isinstance(d, dict) and "heads" in d:
        states, meta = d["heads"], d.get("meta", {})
        in_dim = meta.get("in_dim", in_dim)
    else:
        st, meta = _unwrap(d)
        states = [st]

    mods = []
    for st in states:
        g = GradingHeads(in_dim=in_dim, hidden=h.get("hidden"), dropout=0.0)
        g.load_state_dict(st)
        mods.append(g.to(device).eval())

    kind = f"앙상블 {len(mods)}개" if len(mods) > 1 else "단일"
    extra = f" · p={meta.get('p_exp')}" if meta.get("p_exp") is not None else ""
    print(f"등급 헤드 로드 {path}  ({kind}{extra})")
    return HeadBundle(mods, meta)
