"""병리 소켓 (1·2) — Virchow2 조직분할 + CellViT-SAM-H 세포검출 → sTIL.

번들 하나가 소켓 둘을 담당한다. 판독 한 번에 조직 분할과 세포 검출이 함께
돌고, 그 둘로 sTIL·TSR 을 계산한다. 초음파(4·5)와 같은 구조다.

상주 7.7GB · 적재 13.5초(체크섬 검증 포함 17.7초). 큰 이미지는 predict 가
안에서 타일로 자른다(overlap 64 · batch 4) — 우리가 자르지 않는다.

── 화면에 그대로 내보내면 안 되는 값 ─────────────────────────────
  stil_percent      임상 육안 TIL 대비 약 1/12 스케일이다(비보정).
                    영역 하나의 값에 12 를 곱하는 것도 검증 범위 밖이다 —
                    캘리브는 슬라이드 단위 합산값에만 적용한다(담당자 확인).
                    합산과 저/중/고 3분류는 앱 서버가 한다.
  stil_interval_*   소켓2 분류기 재현성 하한일 뿐이다.
                    「신뢰구간」으로 표기하면 안 된다.

stroma_status 가 absent 면 stil_percent 는 None 이다. 0% 가 아니라
「평가 불가」다 — 간질이 없으면 분모가 없어 정의되지 않는다.

응답 필드와 한계는 pathology-eval 의 MANIFEST.md ·
docs/stil_pipeline_limitations.md 참조.
"""

import os 
import io 
import pathlib 
import sys 

from PIL import Image 
from sockets import base, gpu 

MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))

# 병리 작업 폴더, 심볼릭 링크이고 실체는 워크스테이션의 pathology-eval 
PATH_DIR = MODEL_ROOT / "pathology" 

# CellViT++ 저장소, serving.py 가 import 시점에 이 환경변수를 읽고 
# sys.path 에 넣는다. 그래서 serving을 import 하기 전에 세워야한다 
CELLVIT_REPO = MODEL_ROOT / "base" / "cellvit"

NAME = "pathology"

# 이 모듈이 담당하는 소켓, 번들 하나가 둘을 같이봄 
# 조직분할(1)과 세포 검출(2) 이 한 번의 predict 에서 함께 나온다 
SOCKET_IDS = {"1", "2"}

# 적재 허요 스위치, 꺼져 있으면 요청이 와도 기권 
ENABLED = os.getenv("LOAD_PATHOLOGY", "0") == "1"

# 이 소켓이 판독하려면 있어야하는 파일 - MODEL_ROOT 기준 상대 경로 
# Virchow 는 timm이 HF 캐시에서 받으므로 파일 경로가 없다 
REQUIRED = [
    "pathology/candidates/socket2/model_best.pth",
    "base/cellvit/logs_local/virchow2_linear_tand/best_head.pth",
    "base/cellvit/checkpoints/CellViT-SAM-H-x40-AMP.pth",
]

def _load() -> dict: 
    """번들을 올린다. 약 17.7초(체크섬 4초 + 적재 13.5초) · VRAM 7.7GB.

    체크섬 검증을 켜 두는 이유 — 2.8GB 파일이 별도 채널로 전달돼서,
    받다가 잘린 것을 조용히 쓰는 것보다 기동 때 걸리는 편이 낫다.
    """
    os.environ.setdefault("CELLVIT_REPO", str(CELLVIT_REPO))
    sys.path.insert(0, str(PATH_DIR / "code" / "serving"))
    from serving import load_model 
    from serving import predict as _predict
    
    bundle = load_model({
        "tissue_checkpoint": str(MODEL_ROOT / "base/cellvit/logs_local"
                                "/virchow2_linear_tand/best_head.pth"),
        "cell_head": str(MODEL_ROOT / "pathology/candidates/socket2/model_best.pth"),
        "cellvit_path": str(MODEL_ROOT / "base/cellvit/checkpoints"
                            "/CellViT-SAM-H-x40-AMP.pth"),
        # 마스크는 (H,W) numpy 라 JSON 으로 못 나가고, 저장할 DB 칸도 없다.
        # 아예 안 받으면 계산과 전송이 둘 다 준다.
        "return_tissue_mask": False,
    })
    return {
        "bundle": bundle, 
        "predict": _predict, 
        "versions": {
            "model_name": "virchow2+cellvit-sam-h",
            "model_version": bundle["model_version"],
        }
    }
    

def _run(state, data, filename, **over) :
    return state["predict"](state["bundle"], Image.open(io.BytesIO(data)), **over)

SOCKET = base.Socket(NAME, SOCKET_IDS, ENABLED, _load, _run, drop=("tissue_mask",))