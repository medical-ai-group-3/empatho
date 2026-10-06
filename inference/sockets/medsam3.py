"""MedSAM3 백본 한 벌을 여러 소켓이 나눠 쓴다.

초음파(소켓 4·5)와 MRI(소켓 3)는 같은 백본 파일을 쓴다
(medsam3_merged.pt · 3.37GB). 지금은 소켓마다 따로 올려서
둘 다 상주하면 9GB 를 먹는다.

  백본    커다란 공통 신경망. 소켓끼리 똑같다.
  어댑터  백본 위에 얹는 작은 보정값(74MB). 소켓마다 다르다.

백본은 한 벌만 두고 어댑터만 갈아 끼우면 4.1GB 다.

소켓의 적재 코드는 남의 것이라 못 고친다(models/us 는 .gitignore,
models/mri 는 남의 작업본 링크). 대신 둘이 공통으로 거치는
load_merged_model 을 우리 것으로 바꿔치기한다. 호출부는 안 바뀐다.

근거 — 2026-09-07 실측
  세 어댑터를 한 백본에 다섯 번 갈아 끼우며(초음파 → 맘모 → MRI →
  맘모 → 초음파) 따로 올린 것과 비교했다. 다섯 번 전부 비트 단위로
  같았다(차이 max 0.000e+00). 교체는 0.06~0.28초.

    따로   초음파 4,454 + MRI 4,534 + 맘모 4,614 = 13,602 MiB
    한 벌  4,148 MiB 상주 · 판독 중 4,942 MiB

락은 잡지 않는다. 여기 함수는 전부 base.Socket 의 gpu.LOCK 안에서만
불린다 — ensure 와 predict 둘 다 with gpu.LOCK 으로 감싸여 있다.
"""

import sys
import torch 

# 상주 백본 
_model = None 

# 현재 사용중인 어댑터 경로, 같은 소켓이 이어지면 교체는 스킵
_active = None 

# 읽어둔 어댑터들, CPU 메모리에 저장하고 필요하면 호출 
_cache = {}

# 가장 넓은 LoRA 설정 - 초음파 MRI 것 / 맘모는 여기에 
_TARGETS = ["q_proj", "k_proj", "v_proj", "out_proj", "qkv", "proj", "fc1", "fc2", "c_fc", "c_proj", "linear1", "linear2"]

# LoRA 자리를 이미 만들었나 확인 / 두 번 만들면 LoRA 위에 LoRA 가 겹친다
_lora_done = False 

# 백본을 처음 세울 때의 원본 픽셀 디코더, 초음파가 갈아 끼우기 전 원본 디코더 
_pd_base = None 

# 어댑터 경로 -> 그 소켓이 갈아 끼운 디코더 
_pd_own = {} 

def _find_pd(model):
    """픽셀 디코더와 그것을 달고 있는 부모를 찾는다.

    us/code/unet_pixel_decoder.find_pixel_decoder 와 같은 규칙이다 —
    경로가 빌드 방식에 따라 달라져 하드코딩하지 않는다. 남의 모듈을
    import 하지 않으려고 여기 다시 쓴다.
    """
    mods = dict(model.named_modules())
    for name, mod in mods.items():
        if name.endswith("pixel_decoder") and "." in name:
            parent, attr = name.rsplit(".", 1)
            return mods[parent], attr, mod
    return None, None, None

def arm(*module_names: str) -> None: 
    """소켓이 부를 import_medsam3 를 미리 우리 것으로 바꿔 둔다.

    소켓의 load_model 은 남의 코드라 못 고친다. 그런데 load_model 은 안에서
    import_medsam3() 를 불러 함수 모음(M)을 받는다. 그 import_medsam3 를
    미리 바꿔 두면, load_model 이 받는 M 이 이미 손본 것이 된다.

    import_medsam3 가 어느 모듈에 있는지는 소켓마다 다르다.
      초음파  model_io
      MRI     eval_mri_lora_v3   (model_io 는 이름만 다시 내보낸다)
    그래서 이름을 여러 개 받아, 이미 올라와 있는 것만 바꾼다.

    우리가 직접 import 하지 않는 이유 — 초음파와 MRI 에 model_io 라는 같은
    이름의 모듈이 있다. 우리가 먼저 import 하면 그 이름을 뺏어서 나중 소켓이
    남의 모듈을 받는다. 소켓의 _load 가 base.own 으로 자리를 잡은 뒤에 부른다.
    """
    for name in module_names:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        original = getattr(mod, "import_medsam3", None)
        if original is None or getattr(original, "_shared", False):
            continue
        
        def wrapped(repo_root, _original=original):
            return patch(_original(repo_root))
        
        # 바꾼 표시를 함수에 직접 붙인다. 모듈 이름으로 하면
        # base.own 이 모듈을 지우고 다시 올리면 모른다
        wrapped._shared = True
        mod.import_medsam3 = wrapped

def patch(M: dict) -> dict :
    # ── apply_lora_to_model 도 가로챈다 ─────────────────────────
    #
    # 소켓마다 LoRA 설정이 다르다.
    #   초음파·MRI  12종 · 6부위 → 자리 458개
    #   맘모 검출기 10종 · 3부위 → 자리 278개
    #
    # 맘모 설정은 mammo_io.build_detector 의 "함수 기본값"이라 호출부에서
    # 못 바꾼다. 맘모가 먼저 올라오면 백본이 278자리로 세워져 초음파·MRI
    # 어댑터가 들어갈 자리가 없다.
    #
    # 그래서 넘어온 설정을 무시하고 항상 가장 넓게, 한 번만 만든다. 남는
    # 자리는 lora_B 가 0 이라 계산에 영향이 없다 — 09-07 에 맘모 어댑터를
    # 넓은 백본에 얹어 따로 세운 것과 비트 단위로 같은 것을 확인했다.
    #
    # rank 16 · alpha 32 가 세 소켓 모두 같다는 전제다. 다른 값으로 학습한
    # 어댑터가 생기면 이 자리를 다시 봐야 한다.
    if getattr(M.get("load_merged_model"), "_shared", False):
            return M 
        
    original = M["load_merged_model"]
        
    
    LoRAConfig = M["LoRAConfig"]
    orig_lora = M["apply_lora_to_model"]
    
    def lora_once(model, config) :
        global _lora_done
        if _lora_done: 
            return model
        widest = LoRAConfig(
            rank=16, alpha=32, dropout=0.0, target_modules=list(_TARGETS),
            apply_to_vision_encoder=True, apply_to_text_encoder=True, 
            apply_to_geometry_encoder=True, apply_to_detr_encoder=True,
            apply_to_detr_decoder=True, apply_to_mask_decoder=True
        )
        out = orig_lora(model, widest)
        _lora_done= True
        return out 
    
    lora_once._shared = True
    M["apply_lora_to_model"] = lora_once
    
        # ── load_lora_weights 도 가로챈다 ───────────────────────────
    #
    # mammo_io.py:128 이 우리를 안 거치고 어댑터를 직접 얹는다. 그때 lora_B 를
    # 0 으로 밀지 않으므로, 백본에 남아 있던 다른 소켓의 값이 맘모가 안 쓰는
    # 180자리에 그대로 살아 있게 된다.
    #
    # 누가 무엇을 얹었는지 우리가 모르니 _active 를 지운다. 그러면 다음 판독의
    # use() 가 "내 것이 아니다"로 보고 반드시 다시 얹는다.
    orig_weights = M["load_lora_weights"]
    
    def weights_tracked(model, path, *a, **kw):
        global _active 
        out = orig_weights(model, path, *a, **kw)
        _active = None 
        return out
    weights_tracked._shared = True 
    M["load_lora_weights"] = weights_tracked
    
    
    def load_once(ckpt, cfg, device="cuda"):
        global _model
        if _model is None:
            _model = original(ckpt, cfg, device=device)
            global _pd_base
            _pd_base = _find_pd(_model)[2]
        return _model
    
    load_once._shared = True 
    M["load_merged_model"] = load_once
    return M 

def use(adapter_path: str) -> None: 
    """어댑터를 갈아 끼운다. 판독 직전 _run 첫 줄에서 부른다.

    ⚠ lora_B 를 전부 0 으로 미는 것이 이 함수의 핵심이다.
      어댑터마다 채우는 자리 수가 다르다 — 초음파·MRI 는 458개, 맘모는 278개.
      좁은 어댑터를 얹을 때 밀지 않으면 남는 180개에 이전 어댑터 값이 그대로
      살아 있다. load_state_dict(strict=False) 는 "없는 키는 건너뛴다"는
      뜻이지 "0 으로 만든다"가 아니다.
      오류가 안 나고 그럴듯한 숫자가 나오므로 위험하다.
    """
    global _active
    if _model is None or _active == adapter_path:
        return  # 백본이 아직 없거나 이미 돌아감 
    
    # 초음파는 적재할 때 공용 백본의 픽셀디코더를 교체한다 
    # lora B만 되돌리면 그 교체가 남아 다름 소켓이 초음파 디코더로 순전파해서 텐서 크기가 어긋난다
    parent, attr, cur = _find_pd(_model)
    want = _pd_own.get(adapter_path, _pd_base)
    if parent is not None and want is not None and cur is not want: 
        setattr(parent, attr, want)
    
    weights = _cache.get(adapter_path)
    if weights is None:
        weights = _cache[adapter_path] = torch.load(adapter_path, map_location="cpu")
    
    with torch.no_grad():
        for name, p in _model.named_parameters():
            if name.endswith("lora_B") :
                p.zero_()
        _model.load_state_dict(weights, strict=False)
    _active = adapter_path
    
def claim(adapter_path: str) -> None:
    """이 소켓이 백본 구조를 바꿨으면 그 모듈을 어댑터에 묶어 둔다.
    _load 가 끝난 뒤 부른다. 바꾼 것이 없으면 아무 일도 하지 않는다.
    """
    if _model is None or _pd_base is None:
        return 
    cur = _find_pd(_model)[2]
    if cur is not _pd_base:
        _pd_own[adapter_path] = cur