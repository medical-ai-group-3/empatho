"""워크스테이션 추론 서버.

모델은 첫 판독 요청 때 올리고 이후 상주한다. 서버가 떠 있다는 이유만으로
GPU 를 잡지 않는다 — 학습과 나눠 쓰는 자원이다.
적재에 실패해도 서버는 살아 있어야 한다 — 기권은 실패가 아니고,
경로가 끊기면 앱 서버 쪽에서 오류로 처리되기 때문이다.
"""

import hashlib
import io
import json
import os
import pathlib
import sys
import threading

import yaml
from fastapi import FastAPI, File, UploadFile
from PIL import Image

MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))
BASE_ROOT = MODEL_ROOT / "base"

# 초음파 서빙 번들. breast/us/serving 을 통째로 복사해 둔 것.
# 출처와 갱신 방법은 models/us/PROVENANCE.txt 참조.
US_DIR = MODEL_ROOT / "us"

# 모델 적재는 기본으로 꺼 둔다. GPU 를 학습과 공유하므로 켤 시점을 사람이 고른다.
# supervisord.conf 의 environment 에 LOAD_US="1" 을 넣으면 켜진다.
LOAD_US = os.getenv("LOAD_US", "0") == "1"

# 소켓별로 있어야 하는 파일 — MODEL_ROOT 기준 상대경로.
# 셋이 짝이어야 하는 초음파처럼, 필요한 것을 전부 적는다.
# 이름 앞글자로 훑지 않는 이유는 그러면 짝이 맞는지 알 수 없기 때문이다.
SOCKETS = {
    "1":  ("virchow2", ["path_seg_head.pth"],  "병리 분할 (Virchow2 + Efficient-UNet)"),
    "2":  ("cellvit",  ["path_cell_head.pth"], "병리 세포검출 (CellViT++)"),
    "3":  ("medsam3",  ["mri/ckpt/mri_lora_best.pt"], "MRI 병변 분할"),
    "4":  ("medsam3",  ["us/ckpt/us_lora_best.pt",
                        "us/ckpt/us_pd_best.pt"], "초음파 분할"),
    "5":  ("medsam3",  ["us/ckpt/us_lora_best.pt",
                        "us/ckpt/us_pd_best.pt",
                        "us/ckpt/us_heads_ensemble.pt"], "초음파 등급 (CORAL 헤드)"),
    "4b": ("medsam3",  ["mammo_mass_lora.pt",
                        "mammo_mass_head.pt"], "유방 엑스레이 서술어 (경로 A)"),
}

# 초음파 번들 하나가 소켓 4·5 를 함께 담당한다 (분할 + 등급 헤드).
US_SOCKETS = {"4", "5"}

# 올라간 모델. 비어 있으면 아직 적재 전이거나 적재에 실패한 것.
LOADED = {}
LOAD_ERROR = {}


def socket_state(base_dir: str, required: list[str]) -> str:
    """ready / abstain_only:no_base / abstain_only:no_weights.

    exists() 는 심볼릭 링크를 따라가므로, 대상이 사라진 바로가기는 없는 것으로 센다.
    """
    if not (BASE_ROOT / base_dir).exists():
        return "abstain_only:no_base"
    if any(not (MODEL_ROOT / f).exists() for f in required):
        return "abstain_only:no_weights"
    return "ready"

# 임계값은 레포에 둔다. 값이 바뀐 시점과 이유가 git 에 남아야
# threshold_version 으로 결과 차이를 추적할 수 있다
THRESHOLDS_PATH = pathlib.Path(__file__).resolve().parent/'thresholds.yaml'
def load_thresholds() -> dict: # 타입지정 
    if not THRESHOLDS_PATH.exists():
        return {}
    try: 
        return yaml.safe_load(THRESHOLDS_PATH.read_text(encoding='utf-8')) or {}
    except Exception:
        return {"version": "parse_error"}

# 시작할 때 한 번 읽는다. 고치면 재시작해야 반영된다 - 배포가 곧 재시작이다
THRESHOLDS = load_thresholds() 

def thresholds_version() : 
    return THRESHOLDS.get('version')

def _us_versions() -> dict :
    """적재한 가중치의 식별자. 응답에 실어 결과를 재현 가능하게 한다.

    파일 이름만으로는 부족하다 — 학습이 같은 이름으로 덮어쓰기 때문이다.
    LoRA 는 해시까지 찍는다. 백본은 3.2GB 라 이름만 쓴다.
    """
    ck = US_DIR / "ckpt"
    try : 
        manifest = json.loads((ck/"us_best_manifest.json").read_text(encoding='utf-8'))
    except Exception:
        manifest = {}
    
    lora = ck / "us_lora_best.pt"
    digest = hashlib.sha256(lora.read_bytes()).hexdigest()[:12] if lora.exists() else "none"
    
    cfg = yaml.safe_load((US_DIR / "configs" / "us_lora.yaml").read_text(encoding='utf-8'))
    backbone = pathlib.Path(cfg["model"]["checkpoint"]).name
    
    return {
        "model_name": "medsam3",
        "model_version": backbone,
        "lora_version": f"{manifest.get('run', '?')}@ep{manifest.get('epoch', '?')}+{digest}"
    }
        
def _load_us():
    """초음파 번들을 올린다. 약 10초 · VRAM 3.9GB, 추론 peak 6.5GB.

    heads 를 명시적으로 넘긴다 — infer_us 의 기본값은 us_heads_best.pt 인데
    번들에 들어 있는 것은 앙상블이고, 없으면 등급 없이 분할만 조용히 돌아간다.
    """
    sys.path.insert(0, str(US_DIR / "code"))
    from infer_us import load_model, predict

    bundle = load_model(
        str(US_DIR / "configs" / "us_lora.yaml"),
        heads=str(US_DIR / "ckpt" / "us_heads_ensemble.pt"),
    )
    return {"bundle": bundle, "predict": predict, "versions": _us_versions()}


_LOAD_LOCK = threading.Lock() 

def _ensure_us() :
    """첫 요청 때 올린다. 한 번 올리면 프로세스가 살아 있는 동안 상주한다.

    내려놓지 않는 이유 — PyTorch 는 GPU 메모리를 깨끗하게 반환하지 못한다.
    반복하면 회수 안 된 파편이 쌓인다. 내릴 때는 프로세스를 재시작한다.
    """
    if "us" in LOADED or "us" in LOAD_ERROR : 
        return 
    with _LOAD_LOCK :
        # 락을 기다리는 동안 다른 요청이 이미 올렸을 수 있다 
        if "us" in LOADED or "us" in LOAD_ERROR: 
            return 
        try: 
            LOADED["us"] = _load_us() 
        except Exception as exc: 
            LOAD_ERROR["us"] = f"{type(exc).__name__}: {exc}"
            
app = FastAPI(title="inference")

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "weights_version": os.getenv("WEIGHTS_VERSION", "none"),
        "thresholds_version": thresholds_version(),
        "load_us": LOAD_US,
        "loaded": sorted(LOADED),
        "load_errors": LOAD_ERROR,
        "sockets": {
            sid: {"state": socket_state(b, req), "desc": d}
            for sid, (b, req, d) in SOCKETS.items()
        },
    }


@app.post("/analyze/{socket_id}")
async def analyze(socket_id: str, image: UploadFile = File(...)):
    known = SOCKETS.get(socket_id)
    if known is None:
        return {"socket_id": socket_id, "abstained": True, "reason": "unknown_socket"}

    base_dir, required, _ = known
    state = socket_state(base_dir, required)
    data = await image.read()
    info = {
        "filename": image.filename,
        "content_type": image.content_type,
        "bytes": len(data),
    }
    if socket_id in US_SOCKETS and LOAD_US and state == "ready" :
        _ensure_us() 

    if socket_id not in US_SOCKETS or "us" not in LOADED:
        # 아직 모델이 없다. 왜 없는지를 그대로 돌려준다.
        if state != "ready":
            reason = state
        elif LOAD_ERROR.get("us"):
            reason = f"load_failed: {LOAD_ERROR['us']}"
        elif not LOAD_US:
            reason = "not_loaded:disabled"
        else:
            reason = "not_implemented"
        return {"socket_id": socket_id, "abstained": True, "reason": reason, "image": info}

    # GPU 는 직렬이고 워커도 1개라, 여기서 이벤트 루프를 잡고 있는 것이
    # 그대로 요청 큐가 된다. 한 장에 약 420ms.
    #
    # 전처리·추론·후처리가 전부 predict() 안에서 일어난다. 여기서 따로 하지
    # 않는 이유는 학습 때와 같은 함수를 써야 하기 때문이다. 복사해 두면
    # 학습 코드가 바뀔 때 조용히 갈라지고, 학습에서 나온 성능이 재현되지 않는다.
    #
    #   전처리   1008x1008 리사이즈 → mean/std 0.5 정규화
    #            (바꾸려면 재학습해야 한다 — models/us/README.md)
    #   추론     MedSAM3 + LoRA. 쿼리별 점수와 마스크가 나온다
    #   후처리   임계값으로 쿼리 선별 → 마스크 → CORAL 등급 → 폴리곤·형태지표
    #
    # over 는 thresholds.yaml 이 덮어쓰는 값. 비어 있으면 번들 기본값을 쓴다.
    over = THRESHOLDS.get("us") or {}
    result = LOADED["us"]["predict"](
        LOADED["us"]["bundle"], Image.open(io.BytesIO(data)), **over
    )

    # result 안에 마스크·폴리곤·BI-RADS 등급·형태지표가 들어 있다.
    # _mask 만 numpy 배열이라 JSON 으로 못 나간다. 화면에 그릴 좌표는
    # result["polygons"] 에 따로 있어서 버려도 정보가 줄지 않는다.
    result.pop("_mask", None)

    return {
        "socket_id": socket_id,
        "abstained": False,
        "reason": None,
        **LOADED["us"]["versions"],
        "threshold_version": thresholds_version(),
        "image": info,
        "result": result,
    }
