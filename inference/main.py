import os
import pathlib

import yaml
from fastapi import FastAPI, File, UploadFile

# 환경 변수 설정
MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))
BASE_ROOT = MODEL_ROOT / "base"

# 서버
app = FastAPI(title="inference")

# 소켓 세팅 표
SOCKETS = {
    # 소켓 ID : 베이스 폴더, 파일 앞글자(가중치), 설명
    "1":  ("virchow2", "path_seg",  "병리 분할 (Virchow2)"),
    "2":  ("cellvit",  "path_cell", "병리 세포검출 (CellViT++)"),
    "3":  ("medsam3",  "mri_seg",   "MRI 병변 분할"),
    "4":  ("medsam3",  "us_seg",    "초음파 분할"),
    "5":  ("medsam3",  "us_coral",  "초음파 등급 (CORAL 헤드)"),
    "4b": ("medsam3",  "mammo",     "유방 엑스레이 서술어 (경로 A)"),
}

# 모델 확인
def socket_state(base_dir: str, prefix: str | None) -> str:
    if prefix is None:
        return "abstain_only" # 안쓰는 소켓
    if not (BASE_ROOT / base_dir).exists():
        return "abstain_only:no_base" # 베이스 모델 없음
    # glob 은 이름만 센다. 대상이 사라진 바로가기도 목록에 남아
    # 파일이 없는데 ready 가 되므로, 실제로 열 수 있는지까지 본다.
    if not any(p.exists() for p in MODEL_ROOT.glob(f"{prefix}*")):
        return "abstain_only:no_weights" # 가중치 없음
    return "ready" # 작동 준비

# 임계값 버전 확인
def thresholds_version():
    path = MODEL_ROOT / "thresholds.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text()).get("version")
    except Exception:
        return "parse_error"

#
@app.get("/healthz") # => 누가 GET 으로 healthz 부르면 실행해라
def healthz():
    return {
        "status": "ok",
        "weights_version": os.getenv("WEIGHTS_VERSION", "none"),
        "thresholds_version": thresholds_version(),
        "sockets": {
            sid: {"state": socket_state(b, p), "desc": d}
            for sid, (b, p, d) in SOCKETS.items()
        },
    }

@app.post("/analyze/{socket_id}")
async def analyze(socket_id:str, image: UploadFile = File(...)):
    known=  SOCKETS.get(socket_id)
    if known is None :
        return {
            "socket_id" : socket_id,
            "abstained" : True,
            "reason": "unknown_socket",
        }
    # 데이터 받는 비동기 처리
    data = await image.read()

    return {
        "socket_id": socket_id,
        "abstained": True,
        "reason" : socket_state(known[0], known[1]),
        "image": {
            "filename": image.filename,
            "content_type" : image.content_type,
            "bytes": len(data),
        },
    }
