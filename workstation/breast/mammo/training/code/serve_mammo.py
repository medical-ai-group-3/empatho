#!/usr/bin/env python
"""
맘모 판독 보조 FastAPI 라우터 — 단독 시연·확인용.

⚠ **운영 경로가 아니다.** 운영은 소켓 4b 이고 sockets/mammo.py 가
  infer_mammo.load_model / predict 를 직접 부른다. :8011 은 워크스테이션에
  띄워 두지 않는다. 사슬 그림에서도 뺐다(2026-09-04).

  이 파일을 남겨 두는 이유는 영상 한 장을 손으로 확인할 때 쓰기 때문이다.
  응답 모양은 소켓 4b 와 같게 유지한다 — 시연에서 본 것과 운영에서 나가는
  것이 다르면 그때 또 헷갈린다.

    python3 serve_mammo.py                      # 127.0.0.1:8011
    python3 serve_mammo.py --host 0.0.0.0       # 다른 기기에서 부를 때 (아래 주의)

    POST /mammo/predict   multipart file=<DICOM|PNG>  -> 결과 JSON
    POST /mammo/overlay   같은 입력                    -> 표시용 PNG
    GET  /mammo/info      운영점 · 성능 · 못 채우는 필드
    GET  /health          적재 상태

라우터만 쓰고 싶으면 ROUTER 를 가져다 팀 앱에 붙인다.

    from contextlib import asynccontextmanager
    from serve_mammo import ROUTER, startup_load

    @asynccontextmanager
    async def lifespan(app):
        startup_load()          # 백그라운드 적재. 여기서 기다리지 않는다
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(ROUTER)

    (app.add_event_handler("startup", ...) 는 최신 FastAPI 에서 없어졌다)

────────────────────────────────────────────────────────────────────────
설계상 반드시 지켜야 하는 것 세 가지

1. 모델은 프로세스당 한 번만 올린다 (실측 17초 · 상주 6.7GB).
   요청마다 올렸다 내리면 영상당 그만큼씩 더 걸리고, 두 요청이 겹치면
   OOM 이다. 가중치가 디스크 캐시에 없는 첫 적재는 더 걸릴 수 있다.

2. 추론은 한 번에 하나만 돈다 (_GPU 락).
   검출기 1 + 서술어 2 가 상주해 6.7GB 를 쓰고, **추론 중 최대 11.3GB** 까지
   간다(타일 어텐션 활성값). 용량을 잡을 때는 6.7 이 아니라 11~13GB 로 볼 것.
   타일 추론이 겹치면 남은 자리가 모자란다.
   ⚠ 이 GPU(RTX 5090 · 32GB)는 다른 팀과 같이 쓴다. 우리 몫만 계산하면
     안 된다 — 2026-08-31 02:40 에 eval_vindr 이 OOM 으로 죽었을 때 우리가
     쓰던 건 4.43GB 뿐이었고, 남은 자리가 936MB 였다. 나머지는 남의 작업이다.
   FastAPI 워커를 여러 개 띄우지 말 것(--workers 1). 워커마다 6GB 씩 먹는다.

3. 적재는 백그라운드에서 한다. **끝나기 전과 실패했을 때의 답이 다르다.**
   적재 중이면 곧 되므로 503 + Retry-After 로 재시도를 시킨다.
   적재에 실패했으면 다시 물어도 같으므로 /predict 는 200 + 기권으로
   답한다(소켓 4b 와 같게). 대신 /health 가 503 을 내서 감시에 걸린다.
   startup 에서 동기로 올리면 그동안 서버가 응답을 안 해 팀 백엔드가
   '죽었다' 로 판단한다. 17초라도 헬스체크 주기보다 길면 그렇게 된다.

────────────────────────────────────────────────────────────────────────
망 노출 주의

기본은 127.0.0.1 이다. --host 0.0.0.0 은 연구실 망 전체에 포트를 연다.
그렇게 쓸 거면 MAMMO_API_KEY 환경변수를 설정할 것 — 값이 있으면 모든
/mammo/* 요청에 X-API-Key 헤더를 요구한다.

    export MAMMO_API_KEY=$(python3 -c "import secrets;print(secrets.token_hex(16))")

업로드 영상은 디스크에 쓰지 않는다(메모리에서 바로 읽는다). 로그에도
환자 식별자를 남기지 않는다 — DICOM UID 는 응답에만 넣는다.
"""

import argparse
import os
import sys
from contextlib import asynccontextmanager
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 조각화 완화. CUDA 할당자가 이 값을 초기화 때 읽으므로 torch 사용 전에
# 걸어야 한다. 실측에서 1.90GiB 가 "예약됐지만 미사용" 으로 놀다가
# 1.60GiB 할당이 실패했다 — OOM 메시지가 직접 권하는 설정이다.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

try:
    import anyio
    from fastapi import (APIRouter, FastAPI, File, Form, Header, HTTPException,
                         UploadFile)
    from fastapi.responses import JSONResponse, Response
except ImportError as e:
    raise SystemExit(f"라우터 의존성이 없다 ({e.name}):\n"
                     "  pip install 'fastapi[standard]' uvicorn python-multipart\n"
                     "  ※ python-multipart 를 빼먹으면 UploadFile 을 쓰는 순간"
                     " import 가 실패한다")

from infer_mammo import DEFAULTS, LIMITATIONS, load_model, predict

MAX_MB = 120          # 맘모 DICOM 은 보통 20~60MB. 넉넉히 두되 무제한은 아니다
API_KEY = os.environ.get("MAMMO_API_KEY", "")

ROUTER = APIRouter(prefix="/mammo", tags=["mammography"])

_BUNDLE = None
_STATE = {"ready": False, "error": None, "started": None, "loaded_sec": None}
_GPU = threading.Lock()          # 추론은 한 번에 하나. 위 2번 참조


# ────────────────────────────── 적재 ──────────────────────────────
def _load(det=None, calc=None, mass=None):
    global _BUNDLE
    t0 = time.time()
    _STATE["started"] = t0
    try:
        _BUNDLE = load_model(det, calc, mass, verbose=True)
        _STATE["loaded_sec"] = round(time.time() - t0, 1)
        _STATE["ready"] = True
        print(f"[serve] 준비 완료 ({_STATE['loaded_sec']}초)")
    except Exception as e:
        # 스택은 서버 로그로만. 응답에는 경로가 섞여 나갈 수 있어 요약만 준다.
        _STATE["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        print(f"[serve] 적재 실패 — {_STATE['error']}")


def startup_load(det=None, calc=None, mass=None):
    """백그라운드 적재를 시작한다. 팀 앱에 붙일 때도 이걸 startup 에 건다."""
    threading.Thread(target=_load, args=(det, calc, mass), daemon=True).start()


def _need_ready():
    """둘 다 503 으로 막는다.

    ⚠ /predict 는 이걸 그대로 쓰지 않는다 — 적재 실패를 200 + 기권으로
      답한다. 아래 mammo_predict 참고.
    """
    if _STATE["error"]:
        raise HTTPException(503, f"모델 적재 실패 — {_STATE['error']}")
    if not _STATE["ready"]:
        el = int(time.time() - (_STATE["started"] or time.time()))
        # Retry-After 를 붙인다. 없으면 클라이언트가 간격을 추측하고,
        # 대개 너무 자주 두드려 적재 중인 GPU 를 더 느리게 만든다.
        raise HTTPException(503, f"모델 적재 중 ({el}초 경과 · 보통 20초 안팎)",
                            headers={"Retry-After": "10"})


def _need_key(key):
    if API_KEY and key != API_KEY:
        raise HTTPException(401, "X-API-Key 가 필요하다")


async def _read_upload(f):
    data = await f.read()
    if not data:
        raise HTTPException(400, "빈 파일이다")
    if len(data) > MAX_MB * 2 ** 20:
        raise HTTPException(413, f"{MAX_MB}MB 를 넘는다 ({len(data)/2**20:.0f}MB)")
    return data


def _run(data, name, over):
    """락을 잡고 추론한다. 이벤트 루프를 막지 않도록 스레드에서 부른다."""
    with _GPU:
        return predict(_BUNDLE, data, name=name, **over)


# ────────────────────────────── 경로 ──────────────────────────────
@ROUTER.post("/predict")
async def mammo_predict(
    file: UploadFile = File(..., description="DICOM 또는 PNG 한 장"),
    score_calc: float = Form(None),
    score_mass: float = Form(None),
    tissue_frac: float = Form(None),
    topk: int = Form(None),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    """
    영상 한 장 -> 병변 박스 · BI-RADS 서술어 · 등급 · 조직검사 여부.

    임계값은 요청마다 덮어쓸 수 있다. 기본값은 FROC 오탐 1개/영상 지점이고,
    낮추면 민감도가 올라가는 대신 오탐이 는다. 비워 두면 확정 운영점을 쓴다.

    ⚠ 결과의 lesions 가 비어도 '정상' 이 아니다. summary.abstained 를 볼 것.
    """
    _need_key(x_api_key)
    if _STATE["error"]:
        # 소켓 4b 와 같게 200 + 기권이다. 다시 물어도 같은 답이 나오는
        # 상태라 503(재시도하라)은 거짓말이 된다. 사유는 이름으로만 담고
        # 자세한 것은 /health 와 서버 로그에 있다.
        from infer_mammo import abstain_result
        return JSONResponse(abstain_result("load_failed", file.filename))
    _need_ready()
    data = await _read_upload(file)
    over = dict(score_calc=score_calc, score_mass=score_mass,
                tissue_frac=tissue_frac, topk=topk)
    try:
        r = await anyio.to_thread.run_sync(_run, data, file.filename, over)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(400, f"추론 실패 — {type(e).__name__}: {e}")
    return JSONResponse(r)


@ROUTER.post("/overlay")
async def mammo_overlay(
    file: UploadFile = File(...),
    width: int = Form(1400),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    """
    같은 추론에 표시용 PNG 를 얹어 돌려준다. 빨강 = 조직검사, 노랑 = 추적.
    결과 JSON 은 X-Mammo-Summary 헤더에 요약만 넣는다(본문은 PNG 라서).
    """
    _need_key(x_api_key)
    _need_ready()
    data = await _read_upload(file)
    r = await anyio.to_thread.run_sync(_run, data, file.filename, {})

    import cv2
    from mammo_io import norm8, read_mammogram
    arr, _, _ = read_mammogram(data)
    img = cv2.cvtColor(norm8(arr, DEFAULTS["clip"]), cv2.COLOR_GRAY2BGR)
    for l in r["lesions"]:
        x0, y0, x1, y1 = [int(v) for v in l["box"]]
        col = (0, 0, 255) if l["biopsy"] else (0, 220, 255)   # BGR
        cv2.rectangle(img, (x0, y0), (x1, y1), col, 6)
        tag = f"{l['id']} {l['kind'][:4]}" + (
            f" B{l['birads']}" if l["birads"] is not None else " B?")
        cv2.putText(img, tag,
                    (x0, max(30, y0 - 12)), cv2.FONT_HERSHEY_SIMPLEX,
                    1.4, col, 3)
    if width and img.shape[1] > width:
        s = width / img.shape[1]
        img = cv2.resize(img, (width, int(img.shape[0] * s)))
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(500, "PNG 인코딩 실패")
    s = r["summary"]
    head = (f"lesions={s['n_lesions']} biopsy={s['biopsy']} "
            f"max_birads={s['max_birads']} abstained={s['abstained']}")
    return Response(buf.tobytes(), media_type="image/png",
                    headers={"X-Mammo-Summary": head})


@ROUTER.get("/info")
def mammo_info():
    """운영점 · 성능 · 우리가 못 채우는 명세 필드. 붙이는 쪽이 먼저 읽을 것."""
    return {
        "ready": _STATE["ready"],
        "operating_point": (_BUNDLE or {}).get("operating_point"),
        "defaults": {k: (list(v) if isinstance(v, tuple) else v)
                     for k, v in DEFAULTS.items()},
        "performance": {
            "end_to_end_sensitivity": 0.617,
            "with_given_location": 0.900,
            "rule_table_ceiling": 0.922,
            "froc_1fp_center_hit": {"calcification": 0.579, "mass": 0.564},
            "map50": {"mass": 0.177, "calcification": 0.037},
            "measured_on": "CBIS-DDSM test 598장 · 조직검사 대상 병변 459개",
            "external_validation": "VinDr-Mammo 진행 중",
        },
        "limitations": LIMITATIONS,
        "notes": [
            "판독 보조이며 진단이 아니다.",
            "조직검사가 확정된 사례로 학습·평가했다 — 검진 상황의 확률과 다르다.",
            "'소견 없음' 클래스가 없다. 검출이 0건이면 기권이지 정상이 아니다.",
            "미세석회 질의가 종괴에도 반응한다(종류 혼동). 위치는 맞고 종류가 틀린다.",
        ],
    }


@ROUTER.get("/limitations")
def mammo_limitations():
    return LIMITATIONS


# ────────────────────────────── 앱 ──────────────────────────────
def create_app(det=None, calc=None, mass=None):
    # lifespan 을 쓴다. app.add_event_handler("startup", ...) 는 최신 FastAPI 에서
    # 없어졌다 — AttributeError 로 서버가 아예 안 뜬다.
    @asynccontextmanager
    async def lifespan(app):
        startup_load(det, calc, mass)      # 백그라운드 스레드. 여기서 안 기다린다
        yield

    app = FastAPI(title="맘모 판독 보조", version="1.0",
                  description=__doc__.split("─" * 10)[0], lifespan=lifespan)

    @app.get("/health")
    def health():
        """감시가 보는 곳. **여기만은 고장을 숨기지 않는다.**

        /predict 가 적재 실패를 200 + 기권으로 답하기 때문에, 오류율만
        보면 모델이 죽은 것을 영영 모른다. 기권이 조용히 쌓일 뿐이다.
        """
        from fastapi.responses import JSONResponse as _J
        body = {"ready": _STATE["ready"], "error": _STATE["error"],
                "load_seconds": _STATE["loaded_sec"],
                "busy": _GPU.locked(), "auth": bool(API_KEY)}
        if _STATE["error"]:
            return _J(body, status_code=503)
        return body

    app.include_router(ROUTER)
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 은 연구실 망에 포트를 연다. "
                         "그렇게 쓸 거면 MAMMO_API_KEY 를 설정할 것")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--det", default=None)
    ap.add_argument("--calc", default=None)
    ap.add_argument("--mass", default=None)
    a = ap.parse_args()

    if a.host != "127.0.0.1" and not API_KEY:
        print("  ⚠ 외부에 열면서 MAMMO_API_KEY 가 비어 있다 — 누구나 부를 수 있다")

    import uvicorn
    # 워커 1개 — 워커마다 모델을 따로 올려 6GB 씩 먹는다
    uvicorn.run(create_app(a.det, a.calc, a.mass), host=a.host, port=a.port,
                workers=1, log_level="info")


if __name__ == "__main__":
    main()
