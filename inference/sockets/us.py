"""초음파 소켓 (4·5) — MedSAM3 + LoRA + CORAL 등급 헤드.

번들 하나가 소켓 둘을 담당한다. 판독 한 번에 마스크와 등급이 함께 나온다.
번들 출처와 갱신 방법은 models/us/PROVENANCE.txt 참조.
"""

import hashlib
import io
import json
import os
import pathlib
import sys

import yaml
from PIL import Image

from sockets import gpu

# 가중치 뿌리. 배포 때 supervisord.conf 가 실제 경로를 넣는다.
MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))

# 초음파 번들. code/ · ckpt/ · configs/ 가 한 벌로 들어 있다.
US_DIR = MODEL_ROOT / "us"

# 로그·healthz·thresholds.yaml 에서 이 소켓 묶음을 가리키는 이름.
NAME = "us"

# 이 모듈이 담당하는 소켓. 번들 하나가 둘을 같이 본다 —
# 판독 한 번에 마스크(4)와 등급(5)이 함께 나온다.
SOCKET_IDS = {"4", "5"}

# 적재 허용 스위치. 꺼져 있으면 요청이 와도 기권한다.
# 켜져 있어도 첫 요청이 올 때까지는 GPU 를 잡지 않는다 — 학습과 나눠 쓴다.
ENABLED = os.getenv("LOAD_US", "0") == "1"

# 이 소켓이 판독하려면 있어야 하는 파일 — MODEL_ROOT 기준 상대경로.
# healthz 가 이 목록으로 ready 인지 아닌지를 정한다.
# 이름 앞글자로 훑지 않는 이유는 그러면 짝이 맞는지 알 수 없기 때문이다.
#
#   us_lora_best.pt      분할 LoRA
#   us_pd_best.pt        픽셀 디코더
#   us_heads_ensemble.pt CORAL 등급 헤드 — 등급(소켓 5)에만 필요하다
#
# 셋은 같은 학습 회차에서 나온 짝이어야 한다. 섞으면 오류 없이 결과만 틀린다.
REQUIRED_SEG = [
    "us/ckpt/us_lora_best.pt",
    "us/ckpt/us_pd_best.pt",
]
REQUIRED_GRADE = REQUIRED_SEG + ["us/ckpt/us_heads_ensemble.pt"]

# 올라간 번들. {"bundle", "predict", "versions"} 또는 비어 있음.
# 비어 있다 = 아직 안 올렸거나 내려갔다.
_STATE = {}

# 마지막 적재 실패 사유. {"msg": "..."} 또는 비어 있음.
# 실패해도 다음 요청에서 다시 시도하므로 영구 상태가 아니다.
_ERROR = {}

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
    from infer_us import load_model
    from infer_us import predict as _predict
    
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
    # 락을 잡기 전에 한 번 본다. 이미 올라와 있으면 락을 기다릴 이유가 없다 —
    # 판독 중인 요청이 락을 쥐고 있어서 몇 초씩 멈춘다.
    if _STATE:
        return
    with gpu.LOCK:
        # 락을 기다리는 동안 다른 요청이 이미 올렸을 수 있다.
        # 이 두 번째 검사가 없으면 동시에 들어온 첫 요청들이 번들을 각각 올린다.
        if _STATE:
            return
        try:
            _STATE.update(_load())
            gpu.mark(NAME)   # 올리자마자 수거되지 않게 시계도 같이 민다
            _ERROR.clear()   # 지난 실패 기록을 지운다. 이제 올라왔다
        except Exception as exc:
            # 예외를 밖으로 올리지 않는다. 올리면 요청이 500 이 되고,
            # 앱 서버가 판독을 오류로 처리한다. 사유만 남기고 기권시킨다.
            _ERROR["msg"] = f"{type(exc).__name__}: {exc}"

def is_loaded() -> bool :
    """지금 GPU 에 올라와 있나. main.py 가 판독 전에 확인한다."""
    return bool(_STATE)

def error() :
    """마지막 적재 실패 사유. 없으면 None — 기권 사유를 만들 때 쓴다."""
    return _ERROR.get("msg")

def versions() -> dict:
    """응답에 실을 가중치 식별자. 안 올라와 있으면 빈 dict."""
    return _STATE.get("versions", {})


def predict(data: bytes, filename: str | None = None, **over) -> dict:
    """영상 한 장 → 결과. 전처리·추론·후처리가 전부 이 안에서 일어난다.

    여기서 전처리를 따로 하지 않는 이유는 학습 때와 같은 함수를 써야 하기
    때문이다. 복사해 두면 학습 코드가 바뀔 때 조용히 갈라진다.

      전처리   1008x1008 리사이즈 → mean/std 0.5 정규화
               (바꾸려면 재학습해야 한다 — models/us/README.md)
      추론     MedSAM3 + LoRA. 쿼리별 점수와 마스크가 나온다
      후처리   임계값으로 쿼리 선별 → 마스크 → CORAL 등급 → 폴리곤·형태지표

      data      원본 바이트. 맘모 소켓과 창구를 맞추려고 bytes 로 받는다 —
                맘모는 DICOM 이라 PIL 로 못 열어서 main.py 가 디코딩을 못 한다.
      filename  초음파는 쓰지 않는다. 소켓마다 창구가 갈라지지 않게 받아만 둔다.
      over      요청 단위 임계값 덮어쓰기. thresholds.yaml 의 us: 항목이
                여기로 들어온다. 비면 번들 기본값을 쓴다.

    _mask 는 numpy 배열이라 JSON 으로 못 나간다. 화면에 그릴 좌표는
    result["polygons"] 에 따로 있어서 버려도 정보가 줄지 않는다.
    """
    with gpu.LOCK:
        # 락을 잡고서야 확인하는 이유 — ensure 와 판독 사이에 수거자가
        # 프로세스를 끝냈을 수 있다. 락 안에서는 그 일이 일어나지 않는다.
        if not _STATE:
            raise RuntimeError('모델이 내려감')
        gpu.touch()   # 방금 썼다고 표시. 이게 없으면 판독 중에 수거 대상이 된다
        result = _STATE["predict"](_STATE["bundle"], Image.open(io.BytesIO(data)), **over)
    # 락 밖에서 지운다. numpy 배열 하나 버리는 데 GPU 를 잡고 있을 이유가 없다.
    result.pop("_mask", None)
    return result