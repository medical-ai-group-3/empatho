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

from sockets import base, medsam3

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


def _own(code_dir: pathlib.Path, *names: str) -> None:
    """내 code 폴더를 sys.path 맨 앞에 두고, 남이 차지한 모듈 이름을 비운다.

    맘모는 us·mri 와 겹치는 모듈 이름이 지금은 없다(model_io 가 아니라
    mammo_io 다). 그래도 같은 방식으로 잡아 둔다 — 남의 폴더에 같은 이름이
    생기면 조용히 남의 모듈을 받게 되고, 그때 원인을 찾기가 어렵다.
    """
    d = str(code_dir)
    while d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)
    for n in names:
        mod = sys.modules.get(n)
        if mod is not None and not str(getattr(mod, "__file__", "")).startswith(d):
            del sys.modules[n]


def _load() -> dict:
    """번들을 올린다. 약 17초 · 상주 6.7GB, 판독 중 최대 11.3GB(실측).

    load_model 이 안에서 os.chdir 한다(MedSAM3 가 상대경로를 하드코딩).
    기본값이 원위치시키므로 keep_cwd 는 건드리지 않는다.
    """
    _own(MAMMO_DIR / "training" / "code",
         "mammo_io", "infer_mammo", "train_mammo", "paths", "mammo_data", "eval_e2e")
    from infer_mammo import load_model
    from infer_mammo import predict as _predict

    # 백본을 공용으로. load_model 이 import_medsam3 → build_detector 순으로
    # 부르는데, build_detector 의 LoRA 설정이 us·mri 보다 좁다(10종·3부위).
    # medsam3 가 가장 넓은 설정으로 한 번만 붙이므로 어느 소켓이 먼저 와도 된다.
    #
    # 서술어 트렁크 2벌은 공용화되지 않는다 — build_descriptor 는 M 을 안 거치고
    # train_mammo 의 load_merged_model 을 직접 부른다. 그래서 이 소켓은
    # 백본 한 벌(공용) + 서술어 트렁크 2벌을 쓴다.
    medsam3.arm("mammo_io")

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
        # 판독 직전에 얹을 검출기 어댑터. 공용 백본을 나눠 쓰므로 내 것이
        # 아직 얹혀 있다는 보장이 없다.
        "adapter": str(CKPT / DET),
    }
    

def _run(state, data, filename, **over):
    medsam3.use(state["adapter"])   # 다른 소켓이 쓰고 갔을 수 있다. 락 안이다
    return state["predict"](state["bundle"], data, name = filename, **over)

SOCKET = base.Socket(NAME, SOCKET_IDS, ENABLED, _load, _run, drop=())