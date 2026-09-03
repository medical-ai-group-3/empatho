"""GPU 를 나눠 쓰는 소켓들의 공통 부분 — 락 하나, 유휴 시계 하나, 수거자 하나.

소켓마다 따로 두면 안 된다. 초음파가 30초 놀았다고 프로세스를 끝내면 그때
맘모가 판독 중이어도 같이 죽는다. 맘모는 한 장에 20초까지 간다.
카드가 하나고 프로세스가 하나니 시계도 하나다.
"""

import os 
import sys
import threading 
import time 

# 마지막 판독으로부터 이만큼(초) 놀면 프로세스를 끝낸다.
# 0 이면 안 내린다 — 시험할 때 프로세스가 사라지지 않게 하는 용도다.
# 학습과 카드를 나눠 쓰므로 짧게 잡는다. 다시 올리는 데 초음파 7초·맘모 17초.
KEEP_ALIVE = int(os.getenv("KEEP_ALIVE", "30"))

# 수거자가 유휴 여부를 확인하는 주기(초). KEEP_ALIVE 와 별개다 —
# 실제로 내려가는 시점은 최대 이만큼 늦어진다.
_REAP_EVERY = 30

# 모든 소켓이 함께 쓰는 락. 판독·적재·수거가 전부 이걸 지나간다.
# 소켓마다 따로 두면 한쪽이 판독 중인데 다른 쪽이 프로세스를 끝낼 수 있다.
LOCK = threading.Lock()

# 마지막으로 GPU 를 쓴 시각(epoch 초). 어느 소켓이 썼든 하나로 센다.
_LAST = {"t": 0.0}

# 올라와 있는 소켓 이름들. healthz 가 이걸 보여준다.
#
# 수거 여부를 이것만으로 정하지 않는다 — 적재에 실패하면 여기는 비었는데
# GPU 는 잡혀 있다. 실제 판단은 _reaper 가 reserved 까지 보고 한다.
_LOADED = set()


def touch() -> None:
    """방금 썼다고 표시한다. 판독 직전에 부른다."""
    _LAST["t"] = time.time()


def mark(name: str) -> None:
    """올라왔다고 등록한다. 올리자마자 수거되지 않게 시계도 같이 민다."""
    _LOADED.add(name)
    touch()


def loaded() -> list[str]:
    """healthz 가 보여줄 목록. 지금 GPU 에 올라와 있는 소켓 이름."""
    return sorted(_LOADED)

def mb():
    """이 프로세스가 잡은 GPU 메모리(MiB). 언로드가 실제로 회수하는지 재는 계기다.

      allocated  텐서가 실제로 쓰고 있는 양
      reserved   PyTorch 가 OS 에서 받아 쥐고 있는 양. 판독이 끝나도 안 준다

    reserved 를 봐야 하는 이유 — 이 값이 「남이 못 쓰는 양」이다. allocated 가
    0 이어도 reserved 가 6GB 면 학습 쪽에서는 6GB 가 없는 것과 같다.

    sys.modules 로 torch 를 꺼내는 이유 — 여기서 import 하면 모델을 한 번도
    안 올린 서버가 healthz 한 번에 torch 를 통째로 올린다. 이미 올라와 있을
    때만 들여다본다. 안 올라와 있으면 잴 것도 없으니 None.
    """
    t = sys.modules.get("torch")
    if t is None or not t.cuda.is_available():
        return None
    return {
        "allocated": round(t.cuda.memory_allocated() / 2**20),
        "reserved": round(t.cuda.memory_reserved() / 2**20),
    }


def _reaper() -> None:
    """유휴가 이어지면 프로세스를 끝낸다. supervisor 의 autorestart 가 다시 띄운다.

    ── 왜 프로세스를 죽이나 ─────────────────────────────────────────
    모델 객체를 버리는 것으로는 GPU 가 안 돌아온다. 실측에서 del 과
    empty_cache() 를 한 뒤에도 reserved 6,156 MiB 가 그대로 남았다.
    PyTorch 캐싱 할당자가 한 번 받은 메모리를 OS 에 반환하지 않기 때문이다.
    프로세스가 죽으면 커널이 전부 회수한다. 그래서 죽이는 것이 유일한 방법이다.

    ── 왜 안전한가 ──────────────────────────────────────────────
    LOCK 을 쥐고 확인한다. 판독은 전부 이 락 안에서 돌므로, 어느 소켓이
    판독 중이면 여기서 락을 못 잡고 기다린다. 즉 판독 도중에는 안 죽는다.
    락을 잡았다는 것은 아무도 판독하고 있지 않다는 뜻이고, 그러면 끊길
    요청도 없다.

    ── 무엇이 끊기나 ────────────────────────────────────────────
    healthz 가 재시작하는 몇 초 동안 답하지 않는다. 그 사이 판독 요청이
    오면 연결이 거절되고, 다시 뜬 뒤에는 첫 요청에서 모델을 다시 올린다
    (초음파 7초 · 맘모 17초).

    ── 무엇을 「쥐고 있다」로 보나 ───────────────────────────────
    올라간 모델이 있거나(_LOADED), 없어도 GPU 를 잡고 있으면(reserved > 0)
    쥐고 있는 것으로 본다.

    둘째 조건이 필요한 이유 — 적재하다 OOM 으로 죽으면 _LOADED 는 비었는데
    죽기 전까지 잡은 3GB 가 그대로 남는다. PyTorch 는 실패한 할당분도 OS 에
    돌려주지 않는다. _LOADED 만 보면 그 3GB 를 영원히 쥐고 있게 된다 —
    2026-09-03 에 실제로 8분간 그랬다.

    모델을 한 번도 안 올린 프로세스는 torch 조차 없어 mb() 가 None 이다.
    그래서 놀아도 안 죽는다 — healthz 는 계속 답해야 한다.

    os._exit(0) 을 쓰는 이유 — sys.exit 는 예외라서 uvicorn 이 잡아먹는다.
    정리 없이 즉시 끝내야 한다.
    """
    while True:
        time.sleep(_REAP_EVERY)
        with LOCK:
            m = mb()
            holding = bool(_LOADED) or (m is not None and m["reserved"] > 0)
            if holding and time.time() - _LAST["t"] > KEEP_ALIVE:
                os._exit(0)

# 이 모듈을 import 하는 순간 수거자가 돈다. 소켓 모듈들이 전부 이걸 import
# 하므로 어디서 시작하든 딱 한 번만 뜬다 — 파이썬이 모듈을 한 번만 실행한다.
#
# daemon=True  이 스레드 때문에 프로세스가 안 죽는 일이 없게 한다.
# KEEP_ALIVE=0 이면 아예 안 띄운다. 시험할 때 프로세스가 사라지지 않게 하는 스위치다.
if KEEP_ALIVE:
    threading.Thread(target=_reaper, daemon=True).start()