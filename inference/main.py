"""워크스테이션 추론 서버.

모델은 서버가 켜질 때 한 번 올리고 (lifespan), 요청마다 추론만 한다.
적재에 실패해도 서버는 살아 있어야 한다 — 기권은 실패가 아니고,
경로가 끊기면 앱 서버 쪽에서 오류로 처리되기 때문이다.
"""

import io
import os
import pathlib
import sys
from contextlib import asynccontextmanager

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
    return {"bundle": bundle, "predict": predict}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if LOAD_US and socket_state(*SOCKETS["4"][:2]) == "ready":
        try:
            LOADED["us"] = _load_us()
        except Exception as exc:
            # 여기서 예외를 흘려보내면 서버가 아예 안 켜지고 healthz 도 죽는다.
            LOAD_ERROR["us"] = f"{type(exc).__name__}: {exc}"
    yield
    LOADED.clear()


app = FastAPI(title="inference", lifespan=lifespan)


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
    over = THRESHOLDS.get("us") or {} 
    result = LOADED["us"]["predict"] (
        LOADED["us"]["bundle"], Image.open(io.BytesIO(data)), **over 
    )
    result.pop("_mask", None)   # numpy 배열 — JSON 으로 못 나간다

    return {
        "socket_id": socket_id,
        "abstained": False,
        "reason": None,
        "threshold_version": thresholds_version(),
        "image": info,
        "result": result,
    }
