"""맘모 소켓 (4b) — MedSAM3 검출기 + 서술어 둘 + 규칙표.

번들 하나에 모델이 셋 올라간다. 상주 6.7GB · 판독 중 최대 11.3GB(실측).
초음파와 달리 마스크가 아니라 박스를 낸다 — 맘모 학습 데이터에 분할 라벨이 없다.

── 판독 한 번이 도는 순서 ──────────────────────────────────────────
    영상 → 조직 영역 찾기 → 타일로 쪼개 검출 → 겹친 박스 합치기(wbf)
         → 조직 밖 버리기 → 점수 문턱 → 남은 박스마다 서술어 → 규칙표 → BI-RADS

  검출기가 병목이다. 위치를 알려주면 90.0% 를 맞추는데 스스로 찾으면 61.7% 다.
  잃는 28.3%p 중 26.8%p 가 검출 단계에서 나온다.

── 받는 쪽이 반드시 알아야 하는 것 ─────────────────────────────────
  1. lesions 가 비어도 「정상」이 아니다. summary.abstained 를 볼 것.
     서술어 모델에 「소견 없음」 클래스가 없어서, 검출이 0건이면 판정
     자체를 못 한다. 화면에 「이상 없음」으로 쓰면 안 된다.
  2. lesion.kind 를 믿지 마라. 종류는 분류 헤드가 아니라 텍스트 질의에서
     나온다. 위치는 맞는데 종류가 틀리는 경우가 실제로 있고, 종류가 틀리면
     서술어와 등급도 함께 틀린다.
  3. box 는 박스이지 병변 경계가 아니다. 학습 데이터에 분할 라벨이 없어
     마스크를 못 낸다. 박스 면적을 병변 면적으로 쓰면 그대로 오독된다.
  4. 다른 장비·다른 기관 영상에서는 검출 민감도가 15%p 가량 낮다
     (외부 검증 VinDr 기준). 특히 화소 간격이 굵으면 미세석회가 약해진다.

응답 스키마 전체는 models/mammo/docs/mammo_api.md 에 있다.
"""

import os 
import pathlib 
import sys 

from sockets import gpu 

# 가중치 뿌리. 배포 때 supervisord.conf 가 실제 경로를 넣는다.
MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))

# 맘모 작업 폴더. 심볼릭 링크이고 실체는 워크스테이션의 학습 폴더다.
# 복사하지 않는 이유 — infer_mammo 의 paths.py 가 자기 파일 위치에서
# parents[2] 로 뿌리를 잡는다. 깊이가 달라지면 조용히 다른 곳을 읽는다.
MAMMO_DIR = MODEL_ROOT / "mammo"

# 학습이 내놓은 가중치가 모여 있는 곳. DET 과 서술어 둘을 여기서 찾는다.
CKPT = MAMMO_DIR / "training" / "ckpt"

# 로그·healthz·thresholds.yaml 에서 이 소켓 묶음을 가리키는 이름.
NAME = "mammo"

# 이 모듈이 담당하는 소켓. main.py 가 이 집합을 보고 요청을 넘긴다.
SOCKET_IDS = {"4b"}

# 적재 허용 스위치. 꺼져 있으면 요청이 와도 기권한다.
# 켜져 있어도 첫 요청이 올 때까지는 GPU 를 잡지 않는다 — 학습과 나눠 쓴다.
ENABLED = os.getenv("LOAD_MAMMO", "0") == "1"

# 검출기 가중치 파일 이름. CKPT 안에서 찾는다.
#
# best_lora.pt 를 쓰면 안 된다 — 점수 눈금이 다르다. 실측에서 상한이
# 석회 0.539 · 종괴 0.682 인데 운영 문턱이 0.594 · 0.767 이라 6장 전부
# 기권했다(last_lora 는 같은 6장에서 11건 검출). 문서의 61.7% 와 짝이 맞는
# 것도 이쪽이고, 평가 스크립트 넷이 전부 last_lora 를 기본값으로 쓴다.
# 담당자 확인 완료. 바꾸려면 FROC 를 다시 쓸어 문턱부터 새로 잡아야 한다.
DET = os.getenv("MAMMO_DET", "last_lora.pt")

# 이 소켓이 판독하려면 있어야 하는 파일 — MODEL_ROOT 기준 상대경로.
# healthz 가 이 목록으로 ready 인지 아닌지를 정한다.
# 서술어는 종류마다 하나씩(석회·종괴). 헤드는 load_model 이 lora 이름에서
# 찾아가므로 여기 적지 않는다 — 적으면 이름 규칙이 두 곳에 생긴다.
REQUIRED = [
    f"mammo/training/ckpt/{DET}",
    "mammo/training/ckpt/mammo_calc_trunk_last_grid4_pad0_clip999_lora.pt",
    "mammo/training/ckpt/mammo_mass_trunk_last_grid4_pad0_clip999_lora.pt",
]

# 올라간 번들. {"bundle", "predict", "versions"} 또는 비어 있음.
# 비어 있다 = 아직 안 올렸거나 내려갔다.
_STATE = {}

# 마지막 적재 실패 사유. {"msg": "..."} 또는 비어 있음.
# 실패해도 다음 요청에서 다시 시도하므로 영구 상태가 아니다.
_ERROR = {}

def _load() -> dict:
    """번들을 올린다. 약 17초 · 상주 6.7GB, 판독 중 최대 11.3GB(실측).

    load_model 이 안에서 os.chdir 한다(MedSAM3 가 상대경로를 하드코딩).
    기본값이 원위치시키므로 keep_cwd 는 건드리지 않는다.
    """
    sys.path.insert(0, str(MAMMO_DIR / "training" / "code"))
    from infer_mammo import load_model
    from infer_mammo import predict as _predict

    # bundle  검출기 1 + 서술어 2 + 규칙표. 프로세스가 사는 동안 재사용한다.
    # verbose 를 끄는 이유 — 켜면 LoRA 를 입힌 458개 모듈을 전부 찍어
    #         supervisor 로그가 요청마다 수백 줄씩 불어난다.
    bundle = load_model(det=str(CKPT / DET), verbose=False)
    return {
        "bundle": bundle,
        "predict": _predict,
        # 응답에 실어 결과를 재현 가능하게 한다. 어느 가중치·어느 운영점으로
        # 나온 값인지 모르면 나중에 결과를 다시 볼 때 해석이 안 된다.
        "versions": {
            "model_name": "medsam3",
            "det_version": DET,
            "operating_point": bundle["operating_point"],
        },
    }
    
def ensure() -> None:
    """첫 요청 때 올린다. 실패하면 기록만 하고 다음 요청에서 다시 시도한다.

    GPU 를 학습과 나눠 쓰므로 적재 실패는 대개 일시적이다. 여기서 포기하면
    사람이 재시작할 때까지 소켓이 죽어 있게 된다.
    """
    # 락을 잡기 전에 한 번 본다. 이미 올라와 있으면 락을 기다릴 이유가 없다 —
    # 판독 중인 요청이 락을 쥐고 있어서 최대 20초 멈춘다.
    if _STATE:
        return
    with gpu.LOCK:
        # 락을 기다리는 동안 다른 요청이 이미 올렸을 수 있다.
        # 락 밖에서 적재하면 첫 요청 둘이 6.7GB 짜리를 각각 올린다.
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

def is_loaded() -> bool:
    """지금 GPU 에 올라와 있나. main.py 가 판독 전에 확인한다."""
    return bool(_STATE)

def error():
    """마지막 적재 실패 사유. 없으면 None — 기권 사유를 만들 때 쓴다."""
    return _ERROR.get("msg")

def versions() -> dict:
    """응답에 실을 가중치 식별자. 안 올라와 있으면 빈 dict."""
    return _STATE.get("versions", {})

def predict(data: bytes, filename: str | None = None, **over) -> dict:
    """영상 한 장(DICOM 또는 PNG) → 병변 박스 · 서술어 · 등급.

      data      원본 바이트. bytes 를 그대로 넘긴다 — DICOM 은 PIL 로 못 연다.
                읽기는 read_mammogram 이 하고, 학습 때와 같은 함수라
                전처리가 갈라지지 않는다.
      filename  결과의 file 필드에 적을 이름. 없으면 "<upload>" 가 된다.
      over      요청 단위 임계값 덮어쓰기(score_calc·score_mass·tissue_frac·topk).
                thresholds.yaml 의 mammo: 항목이 여기로 들어온다.

    락을 쥐고 도는 이유 — 카드가 하나라 판독은 어차피 직렬이고,
    도중에 수거자가 프로세스를 끝내지 못하게 막는 역할도 한다.
    """
    with gpu.LOCK:
        if not _STATE:
            raise RuntimeError("모델이 내려감")
        gpu.touch()
        return _STATE["predict"](_STATE["bundle"], data, name=filename, **over)