"""
기본
"""
import os
def _int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default
def _bool(name: str, default:bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true","yer","on")
def _float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default

MODEL_DIR = os.environ.get("MODEL_DIR", "./weights")
MC_DROPOUT_N = _int("MC_DROPOUT_N", 20)
NUM_CLASSES = _int("NUM_CLASSES", 5)
INPUT_SIZE = _int("INPUT_SIZE", 512)
TILE_SIZE = _int("TILE_SIZE", 512)
MIN_TISSUE_RATIO = _float("MIN_TISSUE_RATIO", 0.1)
MAX_BATCH_SIZE = _int("MAX_BATCH_SIZE", 4)
MAX_WAIT_TIME_MS = _int("MAX_WAIT_TIME_MS", 30)
NUM_PREPROCESS_WORKERS = _int("NUM_PREPROCESS_WORKERS", 2)
NUM_INFERENCE_WORKERS = _int("NUM_INFERENCE_WORKERS", 1)
CUDA_VISIBLE_DEVICES = os.environ.get("CUDA_VISIBLE_DEVICES", "0")
FORCE_DUMMY = _bool("FORCE_DUMMY", False)
HTTP_PORT = _int("HTTP_PORT", 8000)
STROMA_IDX = _int("STROMA_IDX", 1)
IMMUNE_IDX = _int("IMMUNE_IDX", 2)
ENABLE_MEDGEMMA = _bool("ENABLE_MEDGEMMA", False)
NUM_MEDGEMMA_WORKERS = _int("NUM_MEDGEMMA_WORKERS", 1)
TILE_STRIDE = _int("TILE_STRIDE", 256)
