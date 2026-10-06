# 소켓별 공통 부분 모듈화 

"""소켓 공통부 — 적재 · 상태 · 판독 감싸기. 소켓마다 베끼지 않는다.

소켓이 주는 것은 넷이다.
  load()                    번들을 올려 dict 로 돌려준다 ({"bundle", "predict", "versions"} …)
  run(state, data, filename, **kw)   입력을 번들 predict 에 맞춰 부른다. 락 안에서 돈다
  drop                      응답에서 지울 열쇠 — numpy 등 JSON 으로 못 나가는 것
  상수                      NAME · SOCKET_IDS · ENABLED
"""
import pathlib
import sys
import traceback
from sockets import gpu

class Socket: 
    def __init__(self, name, socket_ids, enabled, load, run, drop=()):
        self.NAME = name
        self.SOCKET_IDS = socket_ids
        self.ENABLED = enabled
        self._load, self._run, self._drop = load, run, tuple(drop)
        self._state, self._error = {}, {} # 올라간 번들, 마지막 적재 실패 사유 
        
    def ensure(self) :
        """첫 요청 때 올린다. 실패하면 기록만 하고 다음 요청에서 다시 시도한다.

        락 밖에서 한 번, 안에서 한 번 본다 — 동시에 온 첫 요청들이 번들을
        각각 올리지 않게. 예외는 밖으로 안 올린다. 올리면 요청이 500 이 되고
        앱 서버가 판독을 오류로 처리한다. 사유만 남기고 기권시킨다.
        """
        if self._state:
            return
        with gpu.LOCK:
            if self._state:
                return
            try:
                self._state.update(self._load())
                gpu.mark(self.NAME)
                self._error.clear()
            except Exception as exc:
                self._error["msg"] = f"{type(exc).__name__}: {exc}"
                traceback.print_exc() 
                
    def is_loaded(self): return bool(self._state)
    def error(self): return self._error.get("msg")
    def versions(self): return self._state.get("versions", {})
    
    def predict(self, data, filename=None, **kw):
        with gpu.LOCK:
            # 락을 잡고서야 확인한다 — ensure 와 판독 사이에 수거자가 프로세스를
            # 끝냈을 수 있다. 락 안에서는 그 일이 일어나지 않는다.
            if not self._state:
                raise RuntimeError("모델이 내려감")
            gpu.touch()
            try:
                result = self._run(self._state, data, filename, **kw)
            finally: 
                # 끝난 시각으로 다시 민다. 이게 없으면 시계가 "판독 시작"에
                # 멈춰 있어, 긴 판독이 락을 놓는 순간 수거자가 유휴로 보고
                # 프로세스를 끝낸다 — 응답이 나가기 전에. MRI 는 636초다.
                # 실패해도 밀어야 한다. 기권 응답도 나갈 시간이 필요하다.
                gpu.touch() 
        for k in self._drop:
            result.pop(k, None)
        return result
    
def own(code_dir: pathlib.Path, *names: str) -> None : 
    """내 code 폴더를 sys.path 맨 앞에 두고, 남이 차지한 모듈 이름을 비운다.

    us 와 mri 에 model_io 라는 같은 이름의 모듈이 있다. 파이썬은 모듈을 이름으로
    한 번만 올리므로, 초음파가 먼저 판독한 프로세스에서 MRI 를 부르면 MRI 의
    infer_mri 가 us 의 model_io 를 받는다.

      ImportError: cannot import name 'load_model' from 'model_io'
      (.../models/us/code/model_io.py)

    sys.path 를 앞에 꽂는 것만으로는 안 된다 — 이미 sys.modules 에 있으면
    파이썬이 경로를 다시 보지 않는다. 그 이름을 지워야 다시 찾는다.

    지우는 것은 __file__ 이 code_dir 밖인 것만이다. 내 것까지 지우면
    판독마다 다시 읽는다.

    공용화 이전부터 있던 결함이다. 소켓을 하나만 올려 시험할 때는 안 드러났다.
    """
    
    d = str(code_dir) 
    while d in sys.path: 
        sys.path.remove(d)
    sys.path.insert(0, d)
    for n in names:
        mod = sys.modules.get(n)
        if mod is not None and not str(getattr(mod, "__file__", "")).startswith(d):
            del sys.modules[n]
            
    