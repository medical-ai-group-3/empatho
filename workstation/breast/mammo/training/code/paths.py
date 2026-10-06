"""
맘모 파트의 경로를 한 곳에서 정한다.

왜
  경로를 스크립트마다 박아두면 구조가 바뀔 때 전부 찾아 고쳐야 하고,
  하나를 빠뜨리면 조용히 옛 데이터를 읽는다. 여기만 고치면 되게 한다.

기준점
  이 파일의 위치에서 거슬러 올라간다. 실행 위치(cwd)에 기대지 않는다.
  import_medsam3 가 os.chdir 를 하므로 cwd 기준 경로는 반드시 깨진다.

구조 (초음파 파트와 같은 모양)
  mammo/
    medsam3/     MedSAM3 연결 — 심볼릭 링크
    docs/        보고서 · 일지 · 기획서
    training/    code/ · configs/ · ckpt/ · logs/
    data/        det · det_tile · det_tile1008
    runs/        det_run  (기준선 · 전체 미세조정)
    archive/     끝난 갈래
"""

import contextlib
import os
from pathlib import Path

# .../mammo/training/code/paths.py  ->  .../mammo
ROOT = Path(__file__).resolve().parents[2]

MEDSAM3 = ROOT / "medsam3"          # sam3 · lora_layers.py · merge_medsam3.py · ckpt · configs
DOCS = ROOT / "docs"
DATA = ROOT / "data"
RUNS = ROOT / "runs"
ARCHIVE = ROOT / "archive"

TRAINING = ROOT / "training"
CODE = TRAINING / "code"
CONFIGS = TRAINING / "configs"      # 우리 학습 설정 (초음파의 training/configs 와 같은 뜻)
CKPT = TRAINING / "ckpt"            # 우리 학습 결과
LOGS = TRAINING / "logs"

# MedSAM3 자산 — 이름을 여기서 고정해 오타를 막는다
BASE_CKPT = MEDSAM3 / "ckpt" / "medsam3_merged.pt"          # 어텐션 분리형
BASE_CKPT_FUSED = MEDSAM3 / "ckpt" / "medsam3_merged_fused.pt"   # 통합형 (구 검출 학습용)
BASE_CFG = MEDSAM3 / "configs" / "medsam3_v1.yaml"

# 다른 파트와 공유하는 원본 — 절대 쓰기 금지
BREAST = ROOT.parent
RAW_CBIS = BREAST / "data" / "cbis" / "raw"
RAW_VINDR = BREAST / "data" / "vindr"
LABELS = BREAST / "labels"
ROI_INDEX = LABELS / "index"


def check(*paths):
    """없는 경로를 모아 돌려준다. 스크립트 시작에서 한 번 부르면 된다."""
    return [p for p in paths if not Path(p).exists()]


@contextlib.contextmanager
def medsam3_cwd():
    """
    MedSAM3 저장소를 현재 폴더로 두고 블록을 실행한다. 모델을 세울 때만 쓴다.

    왜 필요한가
      SAM 3 의 텍스트 토크나이저가 자기 자산을 상대경로로 찾는다
      ('sam3/assets/bpe_simple_vocab_16e6.txt.gz'). 재배치 전에는 코드가
      mammo/ 에 있었고 거기 sam3 링크가 있어서 우연히 맞았다. training/code/
      에서 돌리면 안 맞아 모델을 세우다 FileNotFoundError 로 죽는다.

      검출 쪽은 import_medsam3 가 os.chdir 를 해서 문제가 없었다. 서술어 쪽
      (train_mammo · eval_e2e · eval_end2end)만 그 chdir 이 없어서 재배치
      뒤에 깨졌다. 같은 사고를 또 만들지 않으려고 여기 한 곳에 둔다.

    반드시 블록 안에서만 바꾸고 되돌린다
      cwd 를 바꿔놓고 나오면 그 뒤의 상대경로가 전부 다른 곳을 가리킨다.
      추론이 끝난 마지막 줄에서 저장이 실패해 83분치 결과를 날린 적이 있다.
      그래서 finally 로 원위치시킨다. 스크립트의 인자 경로는 이것과 별개로
      시작할 때 절대경로로 굳혀두는 편이 안전하다.
    """
    prev = os.getcwd()
    os.chdir(str(MEDSAM3.resolve()))
    try:
        yield
    finally:
        os.chdir(prev)
