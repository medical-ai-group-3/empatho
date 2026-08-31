"""초음파 소켓 (4·5) — MedSAM3 + LoRA + CORAL 등급 헤드.

번들 하나가 소켓 둘을 담당한다. 판독 한 번에 마스크와 등급이 함께 나온다.
번들 출처와 갱신 방법은 models/us/PROVENANCE.txt 참조.
"""

import hashlib
import json
import os
import pathlib
import sys
import threading

import yaml
import gc 
import time 

MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))
US_DIR = MODEL_ROOT / "us"

# 이 모듈이 담당하는 소켓 
SOCKET_IDS = {"4", "5"}

# 적재 허용 스위치, 켜져 있어도 첫 요청이 올 때까지는 gpu를 쓰지 않는다 
ENABLED = os.getenv("LOAD_US", "0") == "1"

# 유휴 시 모델을 내린다. Ollama 의 KEEP_ALIVE 와 같은 취지 — 공유 GPU 라
# 안 쓰는 동안 물고 있으면 안 된다. 0 이면 내리지 않는다.
KEEP_ALIVE = int(os.getenv("US_KEEP_ALIVE", "300"))
_REAP_EVERY = 30
_LAST = {"t": 0.0}

# 있어야 하는 파일 - MODEL_ROOT 기준, 셋은 같은 학습 회차에서 나온 짝이어야한다 
REQUIRED_SEG = [
    "us/ckpt/us_lora_best.pt",
    "us/ckpt/us_pd_best.pt",
]
REQUIRED_GRADE = REQUIRED_SEG + ["us/ckpt/us_heads_ensemble.pt"]

_LOCK = threading.Lock()
_STATE = {} # {"bundel", "predict", "versions"} 또는 비어있음 
_ERROR = {} # {"msg": "..."} 또는 비어있음 

def _versions() -> dict :
    """적재한 가중치의 식별자. 응답에 실어 결과를 재현 가능하게 한다.

    파일 이름만으로는 부족하다 — 학습이 같은 이름으로 덮어쓰기 때문이다.
    LoRA 는 해시까지 찍는다. 백본은 3.2GB 라 이름만 쓴다.
    """
    ck = US_DIR / "ckpt"
    try :
        manifest = json.loads((ck / "us_best_manifest.json").read_text(encoding="utf-8"))
    except Exception :
        manifest = {}
        
    lora = ck / "us_lora_best.pt"
    digest = hashlib.sha256(lora.read_bytes()).hexdigest()[:12] if lora.exists() else "none"
    
    cfg = yaml.safe_load((US_DIR / "configs" / "us_lora.yaml").read_text(encoding="utf-8"))
    backbone = pathlib.Path(cfg["model"]["checkpoint"]).name 
    
    return {
        "model_name": "medsam3",
        "model_version": backbone,
        "lora_version": f"{manifest.get('run', '?')}@ep{manifest.get('epoch', '?')}+{digest}"
    }
    
def _load() -> dict: 
    """번들을 올린다. 약 7초 · VRAM 3.9GB, 판독 peak 6.5GB.

    heads 를 명시적으로 넘긴다 — infer_us 의 기본값은 us_heads_best.pt 인데
    번들에 들어 있는 것은 앙상블이고, 없으면 등급 없이 분할만 조용히 돌아간다.
    """
    sys.path.insert(0, str(US_DIR / "code"))
    from infer_us import load_model, predict as _predict
    
    bundle = load_model(
        str(US_DIR / "configs" / "us_lora.yaml"),
        heads = str(US_DIR / "ckpt" / "us_heads_ensemble.pt"),
    )
    return {"bundle": bundle, "predict": _predict, "versions": _versions()}

def ensure() -> None: 
    """첫 요청 때 올린다. 한 번 올리면 프로세스가 살아 있는 동안 상주한다.

    실패하면 기록만 하고 다음 요청에서 다시 시도한다. GPU 를 학습과 나눠 쓰므로
    적재 실패는 대개 일시적이다 — 학습이 끝나면 저절로 풀린다. 여기서 포기하면
    사람이 재시작할 때까지 그 소켓이 죽어 있게 된다.

    내려놓지 않는 이유 — PyTorch 는 GPU 메모리를 깨끗하게 반환하지 못한다.
    반복하면 회수 안 된 파편이 쌓인다. 내릴 때는 프로세스를 재시작한다.
    """
    if _STATE: 
        return 
    with _LOCK:
        # 락을 기다리는 동안 다른 요청이 이미 올렸을 수 있다 
        if _STATE: 
            return 
        try: 
            _STATE.update(_load())
            _LAST["t"] = time.time() # 올리자마자 자동으로 수거되지 않게 추가
            _ERROR.clear()
        except Exception as exc: 
            _ERROR["msg"] = f"{type(exc).__name__}: {exc}"

def _unload() -> None :
    """모델을 내린다. 호출부가 _LOCK 을 쥐고 있어야 한다.

    PyTorch 가 캐시에 파편을 남길 수 있다. 완전히 회수되는지는 실측해야
    알 수 있어서 gpu_mb() 로 확인할 수 있게 해 뒀다.
    """
    import torch 
    _STATE.clear() 
    gc.collect() 
    torch.cude.empty_cache() 
    
def _reaper() -> None:
    """유휴 시간이 지나면 자동으로 모델을 내림, 판독 중에는 락을 들고있기 때문에 기다림"""
    while True :
        time.sleep(_REAP_EVERY)
        with _LOCK: 
            if _STATE and time.time() - _LAST["t"] > KEEP_ALIVE:
                _unload() 
                
def gpu_mb() :
    """이 프로세스가 잡고 있는 GPU 메모리(MiB). 언로드가 실제로 회수하는지 재는 계기다.

    reserved 가 PyTorch 캐시까지 포함한 값이라 이쪽을 봐야 한다.
    torch 를 아직 안 올렸으면 None.
    """
    t = sys.modules.get("torch")
    if t is None or not t.cuda.is_avaliable() :
        return None 
    return {
        "allocated": round(t.cuda.memory_allocated() / 2**20),
        "reserved": round(t.cuda.memory_reserved() / 2**20),
    }
if KEEP_ALIVE:
    threading.Thread(target=_reaper, daemon=True).start() 

def is_loaded() -> bool :
    return bool(_STATE)

def error() :
    return _ERROR.get("msg")

def versions() -> dict:
    return _STATE.get("versions", {})

def predict(image, **over) -> dict:
    """영상 한 장 → 결과. 전처리·추론·후처리가 전부 이 안에서 일어난다.

    여기서 전처리를 따로 하지 않는 이유는 학습 때와 같은 함수를 써야 하기
    때문이다. 복사해 두면 학습 코드가 바뀔 때 조용히 갈라진다.

      전처리   1008x1008 리사이즈 → mean/std 0.5 정규화
               (바꾸려면 재학습해야 한다 — models/us/README.md)
      추론     MedSAM3 + LoRA. 쿼리별 점수와 마스크가 나온다
      후처리   임계값으로 쿼리 선별 → 마스크 → CORAL 등급 → 폴리곤·형태지표

    _mask 는 numpy 배열이라 JSON 으로 못 나간다. 화면에 그릴 좌표는
    result["polygons"] 에 따로 있어서 버려도 정보가 줄지 않는다.
    """
    with _LOCK:
        if not _STATE: 
            raise RuntimeError('모델이 내려감')
        _LAST["t"] = time.time() 
        result = _STATE["predict"](_STATE["bundle"], image, **over)
    result.pop("_mask", None)
    return result