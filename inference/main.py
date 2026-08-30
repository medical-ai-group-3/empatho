"""워크스테이션 추론 서버.

모델은 첫 판독 요청 때 올리고 이후 상주한다. 서버가 떠 있다는 이유만으로
GPU 를 잡지 않는다 — 학습과 나눠 쓰는 자원이다.
적재에 실패해도 서버는 살아 있어야 한다 — 기권은 실패가 아니고,
경로가 끊기면 앱 서버 쪽에서 오류로 처리되기 때문이다.
"""
import io
import os
import pathlib

import yaml
from fastapi import FastAPI, File, UploadFile
from PIL import Image

from sockets import us

MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))
BASE_ROOT = MODEL_ROOT / "base"
# 소켓별로 있어야 하는 파일 — MODEL_ROOT 기준 상대경로.
# 셋이 짝이어야 하는 초음파처럼, 필요한 것을 전부 적는다.
# 이름 앞글자로 훑지 않는 이유는 그러면 짝이 맞는지 알 수 없기 때문이다.
SOCKETS = {
    "1":  ("virchow2", ["path_seg_head.pth"],  "병리 분할 (Virchow2 + Efficient-UNet)"),
    "2":  ("cellvit",  ["path_cell_head.pth"], "병리 세포검출 (CellViT++)"),
    "3":  ("medsam3",  ["mri/ckpt/mri_lora_best.pt"], "MRI 병변 분할"),
    "4":  ("medsam3",  us.REQUIRED_SEG,   "초음파 분할"),
    "5":  ("medsam3",  us.REQUIRED_GRADE, "초음파 등급 (CORAL 헤드)"),
    "4b": ("medsam3",  ["mammo_mass_lora.pt",
                        "mammo_mass_head.pt"], "유방 엑스레이 서술어 (경로 A)"),
}


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

app = FastAPI(title="inference")

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "weights_version": os.getenv("WEIGHTS_VERSION", "none"),
        "thresholds_version": thresholds_version(),
        "load_us": us.ENABLED,
        "loaded": ["us"] if us.is_loaded() else [],
        "load_errors": {"us": us.error()} if us.error() else {},
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
    if socket_id in us.SOCKET_IDS and us.ENABLED and state == "ready":
        us.ensure() # 첫 요청이면 마운트하는 시간이 있음 
        
    if socket_id not in us.SOCKET_IDS or not us.is_loaded():
        # 아직 모델이 안됨. 이유 출력 
        if state != "ready":
            reason = state
        elif us.error():
            reason = f"load_failed: {us.error()}"
        elif not us.ENABLED:
            reason = "not_loaded: disabled"
        else : 
            reason = "not_implemented"
        return {
            "socket_id": socket_id,
            "abstained": True,
            "reason": reason,
            "image": info,
        }
        
    # GPU 는 직렬이고 워커도 1개라, 여기서 이벤트 루프를 잡고 있는 것이
    # 그대로 요청 큐가 된다. 한 장에 약 420ms.
    # over 는 thresholds.yaml 이 덮어쓰는 값. 비어 있으면 번들 기본값을 쓴다.
    result = us.predict(Image.open(io.BytesIO(data)), **(THRESHOLDS.get("us") or {}))
    
    return {
        "socket_id": socket_id,
        "abstained": False,
        "reason": None,
        **us.versions(),
        "threshold_version": thresholds_version(),
        "image": info,
        "result": result,
    }
