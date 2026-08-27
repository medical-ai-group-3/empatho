import os
import pathlib

import yaml
from fastapi import FastAPI

# 로컬 push 테스트

MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))
BASE_ROOT = MODEL_ROOT / "base"

app = FastAPI(title="inference")

SOCKETS = {
    "1":  ("virchow2", "path_seg",  "병리 분할 (Virchow2 + Efficient-UNet)"),
    "2":  ("cellvit",  "path_cell", "병리 세포검출 (CellViT++)"),
    "3":  ("medsam3",  "mri_seg",   "MRI 병변 분할"),
    "4":  ("medsam3",  "us_seg",    "초음파 분할"),
    "5":  ("medsam3",  "us_coral",  "초음파 등급 (CORAL 헤드)"),
    "4b": ("medsam3",  "mammo",     "유방 엑스레이 서술어 (경로 A)"),
}

def socket_state(base_dir: str, prefix: str | None) -> str:
    if prefix is None:
        return "abstain_only"
    if not (BASE_ROOT / base_dir).exists():
        return "abstain_only:no_base"
    if not list(MODEL_ROOT.glob(f"{prefix}*")):
        return "abstain_only:no_weights"
    return "ready"

def thresholds_version():
    path = MODEL_ROOT / "thresholds.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text()).get("version")
    except Exception:
        return "parse_error"

@app.get("/healthz")
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
def analyze(socket_id: str):
    known = SOCKETS.get(socket_id)
    return {
        "socket_id": socket_id,
        "abstained": True,
        "reason": socket_state(known[0], known[1]) if known else "unknown_socket",
    }
