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
    """M 안의 load_merged_model 을 "한 번만 올리는" 판으로 바꿔 돌려준다.

    M 은 import_medsam3 가 주는 함수 모음 dict 다. 소켓의 load_model 이
    그 안의 load_merged_model 을 불러 백본을 세운다. 그 자리만 바꾼다.
    """
    if getattr(M.get("load_merged_model"), "_shared", False):
        return M 
    original = M["load_merged_model"]
    
    def load_once(ckpt, cfg, device="cuda"):
        global _model
        if _model is None:
            _model = original(ckpt, cfg, device=device) 
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
    
    weights = _cache.get(adapter_path)
    if weights is None:
        weights = _cache[adapter_path] = torch.load(adapter_path, map_location="cpu")
    
    with torch.no_grad():
        for name, p in _model.named_parameters():
            if name.endswith("lora_B") :
                p.zero_()
        _model.load_state_dict(weights, strict=False)
    _active = adapter_path