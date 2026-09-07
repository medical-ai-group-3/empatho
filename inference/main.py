"""워크스테이션 추론 서버.

모델은 첫 판독 요청 때 올리고 이후 상주한다. 서버가 떠 있다는 이유만으로
GPU 를 잡지 않는다 — 학습과 나눠 쓰는 자원이다.
적재에 실패해도 서버는 살아 있어야 한다 — 기권은 실패가 아니고,
경로가 끊기면 앱 서버 쪽에서 오류로 처리되기 때문이다.

── 요청 한 건이 지나는 길 ────────────────────────────────────────────
    POST /analyze/{소켓번호}  +  영상 파일 한 장
      │
      │  ① SOCKETS 에 아는 번호인가            → 모르면 unknown_socket 기권
      │  ② socket_state() — 파일이 다 있나      → 없으면 no_base·no_weights 기권
      │  ③ HANDLER 에서 담당 모듈을 찾는다      → 없으면 not_implemented 기권
      │  ④ mod.ensure()  첫 요청이면 GPU 에 올린다
      │  ⑤ mod.predict(바이트)  판독            → 터지면 predict_failed 기권
      ▼
    {socket_id, abstained, reason, 가중치 판, 임계값 판, image, result}

  네 갈래 모두 200 으로 나간다. 500 을 내지 않는 이유 — 앱 서버가 판독을
  실패로 처리하고 배포까지 되돌린다. 못 한 것은 실패가 아니라 기권이다.

── 소켓을 하나 더 붙이려면 ───────────────────────────────────────────
    1. sockets/<이름>.py 를 만든다.
       us.py · mammo.py 와 같은 표면을 갖춰야 한다 —
       NAME · SOCKET_IDS · ENABLED · REQUIRED · ensure · is_loaded ·
       error · versions · predict(data: bytes, filename=None, **over)
    2. 위에서 import 하고 MODULES 에 더한다.
    3. SOCKETS 에 그 소켓 줄을 적는다.
    4. supervisord.conf 의 LOAD_<이름> 을 켠다.
  HANDLER 는 MODULES 에서 자동으로 만들어지므로 따로 손대지 않는다.
"""
import os
import pathlib

import yaml
from fastapi import FastAPI, File, Form, UploadFile

from sockets import gpu, mammo, mri, pathology, us

# 가중치 뿌리. 배포 때 supervisord.conf 가 실제 경로를 넣는다.
MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))

# 백본이 놓이는 곳. 소켓별 가중치와 달리 여러 소켓이 나눠 쓴다.
BASE_ROOT = MODEL_ROOT / "base"

# 소켓 번호 → (필요한 백본, 있어야 하는 파일 목록, 화면에 보일 설명).
#
#   백본       BASE_ROOT 아래 폴더 이름. 없으면 no_base 다.
#   파일 목록  MODEL_ROOT 기준 상대경로. 하나라도 없으면 no_weights 다.
#              이름 앞글자로 훑지 않는 이유는 그러면 짝이 맞는지 알 수 없기
#              때문이다 — 초음파는 셋이, 맘모는 셋이 한 벌이어야 한다.
#   설명       healthz 에 그대로 나간다. 사람이 읽는 값이다.
SOCKETS = {
    "1":  ("virchow2", pathology.REQUIRED,  "병리 분할 (Virchow2 + linear_tand)"),
    "2":  ("cellvit",  pathology.REQUIRED, "병리 세포검출 (CellViT-SAM-H)"),
    "3":  ("medsam3",  mri.REQUIRED, "MRI 병변 분할"),
    "4":  ("medsam3",  us.REQUIRED_SEG,   "초음파 분할"),
    "5":  ("medsam3",  us.REQUIRED_GRADE, "초음파 등급 (CORAL 헤드)"),
    "4b": ("medsam3",  mammo.REQUIRED,    "유방 엑스레이 서술어 (경로 A)"),
}

# 서빙 코드를 가진 소켓 모듈들. 소켓을 붙일 때 여기에 더한다.
#
# 위 SOCKETS 와 역할이 다르다. SOCKETS 는 「파일이 있느냐」를 보고,
# 이쪽은 「그 파일로 판독할 코드가 있느냐」를 본다. 둘 다 있어야 ready 다.
# 가중치만 있고 코드가 없는 상태(소켓 3 MRI 가 지금 그렇다)가 실제로 있다.
MODULES = (us.SOCKET, mammo.SOCKET, pathology.SOCKET, mri.SOCKET)

# 소켓 번호 → 그 소켓을 맡은 모듈. 요청이 이 표를 보고 갈라진다.
#
# 각 모듈이 자기가 맡은 번호를 SOCKET_IDS 로 들고 있고, 여기서 뒤집어
# 번호로 찾을 수 있게 만든다. 지금 만들어지는 표는 이렇다.
#
#     {"4": us, "5": us, "4b": mammo}
#
# 초음파는 번들 하나가 소켓 둘을 맡는다 — 판독 한 번에 마스크(4)와
# 등급(5)이 같이 나오므로 나눌 이유가 없다. 그래서 값이 겹친다.
HANDLER = {sid: m for m in MODULES for sid in m.SOCKET_IDS}

# 서빙 코드가 있는 소켓 번호. 가중치가 있어도 여기 없으면 판독을 못 한다.
# HANDLER 의 열쇠를 그대로 쓰므로 모듈을 더하면 저절로 늘어난다.
IMPLEMENTED = set(HANDLER)

def socket_state(socket_id: str, base_dir: str, required: list[str]) -> str:
    """이 소켓이 지금 판독할 수 있는지, 없다면 왜 못 하는지.

    돌려주는 값은 넷 중 하나다. 순서대로 검사하므로 앞의 것이 먼저 걸린다.

      abstain_only:no_base           백본이 없다. 소켓 여럿이 나눠 쓰는 큰 파일이다
      abstain_only:no_weights        이 소켓 전용 가중치가 하나 이상 없다
      abstain_only:not_implemented   파일은 다 있는데 서빙 코드가 아직 없다
      ready                          판독할 수 있다

    healthz 와 analyze 가 같은 함수를 쓴다. 두 곳이 다른 답을 하면
    「healthz 는 ready 인데 판독은 기권」 같은 상태가 생긴다.

    exists() 는 심볼릭 링크를 따라가므로, 대상이 사라진 바로가기는 없는 것으로 센다.
    """
    if not (BASE_ROOT / base_dir).exists():
        return "abstain_only:no_base"
    if any(not (MODEL_ROOT / f).exists() for f in required):
        return "abstain_only:no_weights"
    if socket_id not in IMPLEMENTED:
        return "abstain_only:not_implemented"
    return "ready"

# 임계값 파일의 위치. 실행 위치가 아니라 이 파일 옆을 본다 —
# supervisor 가 어디서 띄우든 같은 파일을 읽어야 한다.
#
# 임계값을 레포에 두는 이유. 값이 바뀐 시점과 이유가 git 에 남아야
# threshold_version 으로 결과 차이를 추적할 수 있다.
THRESHOLDS_PATH = pathlib.Path(__file__).resolve().parent/'thresholds.yaml'
def load_thresholds() -> dict:
    """thresholds.yaml 을 읽는다. 못 읽어도 서버는 뜬다.

    파일이 없으면 {} — 전부 번들 기본값으로 돈다.
    YAML 이 깨졌으면 {"version": "parse_error"} — 판독은 기본값으로 계속하되
    응답의 threshold_version 에 parse_error 가 찍혀 눈에 띈다. 여기서
    예외를 올리면 오타 하나에 서버가 안 뜬다.
    """
    if not THRESHOLDS_PATH.exists():
        return {}
    try:
        return yaml.safe_load(THRESHOLDS_PATH.read_text(encoding='utf-8')) or {}
    except Exception:
        return {"version": "parse_error"}

# 읽어둔 임계값. 최상위 열쇠는 소켓 모듈 이름(us · mammo)과 version 이다.
# analyze 가 THRESHOLDS[모듈이름] 을 꺼내 predict 에 넘긴다.
#
# 시작할 때 한 번만 읽는다. 고치면 재시작해야 반영된다 — 배포가 곧 재시작이다.
# 요청마다 읽지 않는 이유는 판독 도중에 값이 바뀌면 같은 배치의 결과가
# 서로 다른 임계값으로 나오기 때문이다.
THRESHOLDS = load_thresholds()

def thresholds_version() :
    """응답에 실을 임계값 판. 어떤 값으로 나온 결과인지 나중에 추적하는 단서다."""
    return THRESHOLDS.get('version')

app = FastAPI(title="inference")

@app.get("/healthz")
def healthz():
    """서버가 지금 무엇을 할 수 있는지. 붙는 것이 늘 때마다 항목이 는다.

    status 는 언제나 ok 다. 이 서버가 답한다는 뜻일 뿐이고, 판독할 수
    있는지는 sockets 를 봐야 한다. 여기서 500 을 내면 배포 검사가
    실패로 읽는다 — 모델이 안 올라온 것은 서버 고장이 아니다.
    """
    return {
        "status": "ok",
        # 가중치 묶음의 판. supervisord.conf 가 넣는다. 아직 안 매겨서 none.
        "weights_version": os.getenv("WEIGHTS_VERSION", "none"),
        # thresholds.yaml 의 판. parse_error 면 파일이 깨진 것이다.
        "thresholds_version": thresholds_version(),
        # 적재가 허용된 소켓 (LOAD_US · LOAD_MAMMO).
        # 허용돼 있어도 첫 요청 전에는 안 올라간다 — 여기 있다고 GPU 를 쓰는 게 아니다.
        "enabled": [m.NAME for m in MODULES if m.ENABLED],
        # 지금 실제로 GPU 에 올라와 있는 소켓. 유휴가 길면 프로세스째 죽으므로
        # 조금 전까지 있던 것이 사라져 있을 수 있다 — 정상이다.
        "loaded": gpu.loaded(),
        # 이 프로세스가 잡고 있는 GPU(MiB). 소켓별이 아니라 프로세스 전체다.
        # allocated 는 실제 사용량, reserved 는 PyTorch 가 쥐고 있는 캐시까지.
        # 모델을 한 번도 안 올렸으면 None.
        "gpu": gpu.mb(),
        # 적재를 시도했다가 실패한 소켓과 사유. 다음 요청에서 다시 시도하므로
        # 여기 값이 있어도 영구 고장이 아니다 — 대개 학습이 GPU 를 다 쓴 것이다.
        "load_errors": {m.NAME: m.error() for m in MODULES if m.error()},
        # 소켓별 판독 가능 여부. 여기가 이 서버의 진도표다.
        #   state  ready 또는 abstain_only:*   (socket_state 참조)
        #   desc   사람이 읽을 설명
        "sockets": {
            sid: {"state": socket_state(sid, b, req), "desc": d}
            for sid, (b, req, d) in SOCKETS.items()
        },
    }


@app.post("/analyze/{socket_id}")
async def analyze(socket_id: str, image: UploadFile = File(...), post: UploadFile | None = File(None), dataset_tag: str | None = Form(None)):
    """영상 한 장을 받아 소켓 번호에 맞는 모델로 보낸다.

    앱 서버(Celery 워커)가 부르는 유일한 판독 창구다. 어느 모달리티인지는
    URL 의 소켓 번호가 정한다 — 우리가 영상을 열어보고 짐작하지 않는다.

    환자 정보는 받지 않는다. 판독에 쓰지 않는 값을 GPU 워크스테이션까지
    옮길 이유가 없다. 어느 환자인지 맞추는 일은 앱 서버가 한다.

    어떤 경우에도 200 을 낸다. 실패는 abstained=True 와 reason 으로 알린다.
    """
    # ① 아는 소켓 번호인가. SOCKETS 에 없으면 오타이거나 아직 없는 소켓이다.
    known = SOCKETS.get(socket_id)
    if known is None:
        return {"socket_id": socket_id, "abstained": True, "reason": "unknown_socket"}

    # base_dir  이 소켓이 필요로 하는 백본 폴더 이름 (BASE_ROOT 아래)
    # required  있어야 하는 가중치 목록 (MODEL_ROOT 기준)
    # state     판독 가능 여부. ready 또는 abstain_only:*
    # mod       이 소켓을 맡은 모듈(us · mammo). None 이면 서빙 코드가 없다.
    base_dir, required, _ = known
    state = socket_state(socket_id, base_dir, required)
    mod = HANDLER.get(socket_id)

    # ② 영상을 통째로 읽는다. 디스크에 쓰지 않는다 — 환자 영상이 워크스테이션에
    #    남지 않아야 하고, 남겨도 우리가 지울 방법이 없다.
    #    info 는 기권할 때도 함께 나가서, 무엇을 보냈는지 되짚을 수 있게 한다.
    data = await image.read()
    info = {
        "filename": image.filename,
        "content_type": image.content_type,
        "bytes": len(data),
    }

    # ③ 판독할 수 있는 상태일 때만 모델을 올린다.
    #    파일이 없는데 올리려 들면 매 요청 실패 기록만 쌓인다.
    #    ensure 는 이미 올라와 있으면 아무 일도 하지 않는다.
    if mod is not None and mod.ENABLED and state == "ready":
        mod.ensure()  # 첫 요청이면 올리는 시간이 있다 — 초음파 7초 · 맘모 17초

    # ④ 그래도 모델이 없으면 기권한다. 왜 없는지를 하나로 좁혀 돌려준다 —
    #    사유가 비면 받는 쪽이 「확인했는데 문제 없음」으로 읽는다.
    #
    #      abstain_only:*   파일이 없거나 서빙 코드가 없다 (state 그대로)
    #      load_failed:     올리다 터졌다. 대개 학습이 GPU 를 다 쓴 것이다
    #      not_loaded:      LOAD_* 스위치가 꺼져 있다
    #      not_implemented  위 어디에도 안 걸렸는데 안 올라왔다 (여기 오면 이상하다)
    if mod is None or not mod.is_loaded():
        if state != "ready":
            reason = state
        elif mod.error():
            reason = f"load_failed: {mod.error()}"
        elif not mod.ENABLED:
            reason = "not_loaded: disabled"
        else :
            reason = "not_implemented"
        return {
            "socket_id": socket_id,
            "abstained": True,
            "reason": reason,
            "image": info,
        }

    # ⑤ 판독. GPU 는 직렬이고 워커도 1개라, 여기서 이벤트 루프를 잡고 있는 것이
    #    그대로 요청 큐가 된다. 초음파 한 장에 약 420ms · 맘모 5~20초.
    #
    #    바이트를 그대로 넘긴다 — 맘모는 DICOM 이라 여기서 열 수 없다.
    #    영상을 여는 일은 각 소켓이 학습 때 쓰던 함수로 한다. 여기서 열면
    #    전처리가 학습과 갈라지고, 갈라진 것은 오류가 아니라 틀린 결과로 나온다.
    #
    #    THRESHOLDS[모듈이름] 이 없으면 {} 라서 번들 기본값으로 돈다.
    try:
        # MRI 만 두 번째 파일과 dataset_tag 를 쓴다. 값이 있을 때만 넣는다 —
        # 다른 소켓의 predict 는 **over 를 아래 라이브러리로 그대로 넘기므로
        # 모르는 인자가 들어가면 거기서 터진다.
        extra = {} 
        if post is not None:
            extra["post"] = await post.read() 
            extra["post_filename"] = post.filename
        if dataset_tag is not None: 
            extra["dataset_tag"] = dataset_tag
        result = mod.predict(data, filename=image.filename, **extra, **(THRESHOLDS.get(mod.NAME) or {}))
        
    # 판독 실패도 기권이다. GPU 가 모자라면 지금 못 할 뿐 코드가 틀린 게 아니고,
    # 500 을 내면 앱 서버가 판독을 오류로 처리하고 배포까지 롤백된다.
    except Exception as exc :
        return {
            "socket_id": socket_id,
            "abstained": True,
            "reason": f"predict_failed : {type(exc).__name__}: {exc}",
            "image": info,
        }

    # ⑥ 성공. versions() 로 어떤 가중치가 낸 결과인지 함께 실어 보낸다.
    #    학습이 같은 이름으로 덮어쓰기 때문에 파일 이름만으로는 부족하다.
    #    나중에 「이 결과는 어느 모델이 냈나」에 답할 수 있는 유일한 단서다.
    return {
        "socket_id": socket_id,
        "abstained": False,
        "reason": None,
        **mod.versions(),
        "threshold_version": thresholds_version(),
        "image": info,
        "result": result,
    }
