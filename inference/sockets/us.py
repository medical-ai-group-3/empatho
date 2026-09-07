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
    sys.path.insert(0, str(US_DIR / "code"))
    from infer_us import load_model
    from infer_us import predict as _predict

    # 백본을 공용으로. load_model 안에서 import_medsam3 → load_merged_model 순으로
    # 부르므로, 그 모듈의 함수를 미리 캐시판으로 바꿔 둔다.
    #
    # 우리가 model_io 를 import 하지 않는 이유 — us 와 mri 에 같은 이름의 모듈이
    # 있다. 먼저 부른 쪽이 sys.modules["model_io"] 를 차지해서, 나중 소켓이
    # 자기 model_io 를 부르면 남의 것이 나온다(09-07 에 MRI 가 그렇게 깨졌다).
    medsam3.arm("model_io")

    bundle = load_model(
        str(US_DIR / "configs" / "us_lora.yaml"),
        heads = str(US_DIR / "ckpt" / "us_heads_ensemble.pt"),
    )
    return {"bundle": bundle, "predict": _predict, "versions": _versions(),
            # 판독 직전에 얹을 어댑터. 공용 백본을 다른 소켓과 나눠 쓰므로
            # 내 어댑터가 아직 얹혀 있다는 보장이 없다.
            "adapter": str(US_DIR / "ckpt" / "us_lora_best.pt")}

def _run(state, data, filename, **over):
    """초음파 고유 부분만 — PIL 로 열어 번들 predict 에 넘긴다. 락은 base 가 잡는다."""
    medsam3.use(state["adapter"])   # 다른 소켓이 쓰고 갔을 수 있다. 락 안이다
    return state["predict"](state["bundle"], Image.open(io.BytesIO(data)), **over)

SOCKET = base.Socket(NAME, SOCKET_IDS, ENABLED, _load, _run, drop=("_mask",))