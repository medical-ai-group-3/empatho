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
import base64

import yaml
from PIL import Image

from sockets import base, gpu, medsam3

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
    base.own(US_DIR / "code", "model_io", "infer_us", "heads", "shape_metrics")
    from infer_us import load_model
    from infer_us import predict as _predict
    
    # 백본을 공용으로. infer_us 를 import 한 "뒤"에 불러야 한다 —
    # arm 은 sys.modules 에 이미 올라온 모듈만 바꾼다.
    #
    # infer_us 도 넘기는 것이 핵심이다. infer_us.py:32 가
    #   from model_io import (..., import_medsam3, ...)
    # 로 원본을 자기 이름표에 복사해 두고 82줄에서 그 복사본을 쓴다.
    # model_io 만 바꾸면 안 닿는다 — 09-08 에 실측으로 드러났다.
    
    medsam3.arm("model_io", "infer_us")
    
    bundle = load_model(
        str(US_DIR / "configs" / "us_lora.yaml"),
        heads = str(US_DIR / "ckpt" / "us_heads_ensemble.pt"),
    )
    # 초음파는 픽셀디코더를 갈아 끼운다  
    # 공용 백본이라 다른 소켓이 그대로 쓰면 안 되기 때문에, 이 어댑터에 묶어놓고 되돌린다
    medsam3.claim(str(US_DIR / "ckpt" / "us_lora_best.pt"))
    return {"bundle": bundle, "predict": _predict, "versions": _versions(), "adapter": str(US_DIR / "ckpt" / "us_lora_best.pt")}

def _run(state, data, filename, **over):
    """초음파 고유 부분만 — PIL 로 열어 번들 predict 에 넘긴다. 락은 base 가 잡는다."""
    medsam3.use(state["adapter"]) # 다른 소켓이 쓰고 갔을 수 있다, 락 안이다 
    result = state["predict"](state["bundle"], Image.open(io.BytesIO(data)), **over)
    
    # 픽셀 마스크를 PNG 로 만들어 싣는다. 값이 0·1 두 가지라 잘 줄어든다.
    #
    # 윤곽 좌표(polygons)도 그대로 둔다 — 둘 다 쓴다. 화면이 원본 위에
    # 마스크를 채우고 그 위에 테두리를 그린 다음 투명도를 조절한다.
    # 채우기는 마스크라야 하고 테두리는 좌표라야 깨끗하게 나온다.
    #
    # 원본 numpy 는 JSON 으로 못 나가므로 아래 SOCKET 의 drop 이 뺀다.
    mask = result.get("_mask")
    if mask is not None :
        buf = io.BytesIO()
        Image.fromarray((mask > 0).astype("uint8") * 255, mode="L").save(
            buf, format="PNG", optimize = True
        )
        result["mask_png"] = base64.b64encode(buf.getvalue()).decode()
    return result

SOCKET = base.Socket(NAME, SOCKET_IDS, ENABLED, _load, _run, drop=("_mask",))