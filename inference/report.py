"""판독 결과를 소견 문장으로 옮기는 서버 — 소켓 6.

추론 서버(8001)와 별도 프로세스다. GPU 수명주기가 다르고 — Ollama 가
모델을 알아서 올렸다 60초 뒤 내린다 — 한쪽이 죽어도 다른 쪽은 살아야 한다.

리포트를 못 만들어도 판독 결과는 유효하다. 실패는 기권으로 돌려준다.
500 을 내면 앱 서버가 판독까지 실패로 처리한다.
"""

import json 
import os 
import urllib.request 

from fastapi import FastAPI 
from prompts import us 

OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("REPORT_MODEL", "medgemma1.5:4b-it-q4_K_M")

#모달리티별 프롬프트, 소켓이 추가되면 여기에 추가 
PROMPTS = {sid: us for sid in us.SOCKET_IDS}

app = FastAPI(title="report")

def _ask(system: str, prompt:str, schema:dict, timeout:int = 100) -> dict:
    body = json.dumps({
        "model": MODEL, 
        "system": system,
        "prompt": prompt,
        "format": schema, # 스키마 강제 - 추론 과정 출력 방지 
        "stream": False, 
        "options": {"temperautre": 0.2},
    }).encode() 
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(json.loads(r.read())["response"])
    
@app.get("/healthz")
def healthz() :
    try : 
        with urllib.request.urlopen(f"{OLLAMA}/api/version", timeout=5) as r:
            ollama = json.loads(r.read()).get("version")
    except Exception as exc:
        ollama = f"unreachable: {type(exc).__name__}"
    return {
        "status": "ok",
        "ollama": ollama,
        "model": MODEL,
        "prompts": {sid: p.VERSION for sid, p in PROMPTS.items()},
    }
    
@app.post("/report/{socket_id}")
def report(socket_id: str, result: dict):
    p = PROMPTS.get(socket_id)
    if p is None:
        return {"socket_id": socket_id, "abstained": True, "reason":"unkonwn_socket"}
    try:
        out = _ask(p.SYSTEM, p.buil(result), p.SCHEMA)
    except Exception as exc:
        return {
            "socket_id": socket_id, 
            "abstained": True,
            "reason": f"llm_failed: {type(exc).__name__}: {exc}",
        }
    return {
        "socket_id": socket_id,
        "abstained": False,
        "model_name": MODEL,
        "prompt_version": p.VERSION,
        **out,
    }