"""판독 결과를 소견 문장으로 옮기는 서버 — 소켓 6.

추론 서버(8001)와 별도 프로세스다. GPU 수명주기가 다르고 — Ollama 가
모델을 알아서 올렸다 유휴 5분 뒤 내린다(keep_alive 기본값) — 한쪽이
죽어도 다른 쪽은 살아야 한다.

리포트를 못 만들어도 판독 결과는 유효하다. 실패는 기권으로 돌려준다.
500 을 내면 앱 서버가 판독까지 실패로 처리한다.
"""

import json
import os
import urllib.request

from fastapi import FastAPI
from prompts import us

# Ollama 주소. 이 서버와 같은 워크스테이션에 있으므로 기본이 127.0.0.1 이다.
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# 소견 문장을 엮는 모델. 판독은 하지 않는다 — 이미 나온 사실을 잇기만 한다.
MODEL = os.getenv("REPORT_MODEL", "medgemma1.5:4b-it-q4_K_M")

# 소켓 번호 → 그 모달리티의 프롬프트 모듈.
# 모듈마다 VERSION · SYSTEM · SCHEMA 와 facts/notes/numbers/build 를 갖는다.
# 소켓이 추가되면 여기에 더한다.
PROMPTS = {sid: us for sid in us.SOCKET_IDS}

app = FastAPI(title="report")

def _ask(system: str, prompt:str, schema:dict, timeout:int = 100) -> dict:
    """Ollama 에 한 번 묻고 JSON 을 돌려받는다.

      system   지킬 규칙. 매 요청 같은 값이다.
      prompt   이번에 엮을 사실 문장들.
      schema   응답 형식 강제. 이게 없으면 모델이 생각 과정을 같이 뱉는다.
      timeout  초. 첫 요청은 모델을 올리는 시간이 붙어 오래 걸린다.
    """
    body = json.dumps({
        "model": MODEL,
        "system": system,
        "prompt": prompt,
        "format": schema, # 스키마 강제 - 추론 과정 출력 방지
        "stream": False,  # 앱 서버가 완성본만 쓴다. 토막을 받을 곳이 없다
        # 0.2  같은 판독에서 같은 문장이 나와야 한다. 창의성은 여기서 위험이다
        "options": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(json.loads(r.read())["response"])
    
def _done(socket_id: str, p, text:str, notes:list[str], fallback):
    """응답 한 벌을 만든다.

      p         이 소켓의 프롬프트 모듈
      text      소견문. 모델이 쓴 것이거나 코드가 만든 뼈대다
      notes     안내 문장들. 모델을 거치지 않는다
      fallback  None 이면 모델이 쓴 것, 문자열이면 그 사유로 뼈대를 쓴 것

    안내(notes)를 모델에 넘기지 않는 이유 — 「형태 지표를 믿지 마십시오」 같은
    문장은 다시 쓰면 뜻이 흐려지고, 받는 쪽이 「문제 없음」으로 읽는다.
    """
    return {
        "socket_id": socket_id,
        "abstained": False,
        "소견": text,
        "안내": notes,
        "model_name": None if fallback else MODEL,
        "prompt_version": p.VERSION,
        "fallback": fallback,
    }
    
    
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
    """판독 결과 한 벌 → 소견문 + 안내.

    Go 의 llm-proxy 가 부른다. 본문은 /analyze 가 낸 result 를 그대로 넣는다.

    ── 지키는 규칙 ──────────────────────────────────────────────
    수치와 판단은 코드가 문장으로 만든다(facts). 모델은 그것을 읽기 좋게
    엮기만 한다. 모델에게 수치를 맡겼더니 볼록성 0.914 를 97% 로, 63.9px 를
    81.3mm 로 바꿔 쓰는 것을 확인했다 — 오류가 아니라 그럴듯한 문장으로
    나오므로 위험하다.

    ── 세 갈래 ─────────────────────────────────────────────────
      모델이 잘 엮었다        → 그 문장을 쓴다.            fallback=None
      모델을 못 불렀다        → 뼈대를 그대로 쓴다.        fallback=llm_failed:*
      모델이 수치를 바꿨다    → 그 출력을 버리고 뼈대.     fallback=numbers_changed:*

    뼈대(skeleton)는 facts 를 이어 붙인 것이라 그 자체로 완성된 문장이다.
    읽기에 딱딱할 뿐 내용이 빠지지 않는다. 그래서 모델이 없어도 리포트는 나간다.

    안내(notes)는 어느 갈래에서도 모델을 거치지 않는다.
    """
    p = PROMPTS.get(socket_id)
    if p is None:
        return {"socket_id": socket_id, "abstained": True, "reason":"unknown_socket"}

    # fact_lines  수치와 판단을 코드가 만든 문장. 여기 숫자는 틀릴 수 없다.
    # note_lines  안내. 모델을 거치지 않고 그대로 나간다.
    # skeleton    모델이 없거나 수치를 바꿨을 때 대신 내보낼 완성 문장.
    fact_lines = p.facts(result)
    note_lines = p.notes(result)
    skeleton = " ".join(fact_lines)

    try:
        out = _ask(p.SYSTEM, p.build(fact_lines), p.SCHEMA)
        text = (out.get("소견") or "").strip()
    except Exception as exc:
        # 모델이 없어도 리포트는 나간다. 뼈대는 완성된 문장이다 
        return _done(socket_id, p, skeleton, note_lines, f"llm_failed: {type(exc).__name__}")
    
    # 넘긴 수치가 소견문에 그대로 남아 있는지 본다. 글자열로 찾는 단순한 검사다.
    # 값을 바꿔 쓰면 그 값은 사라지므로 여기서 걸린다. 반대로 문장을 어떻게
    # 다듬든 숫자만 그대로면 통과한다 — 우리가 막으려는 것은 문체가 아니다.
    missing = [n for n in p.numbers(result) if n not in text]
    if missing:
        # 모델이 수치를 바꿨다. 그 출력은 통째로 버린다.
        # 어느 값이 사라졌는지 fallback 에 남겨 나중에 프롬프트를 고칠 단서로 쓴다.
        return  _done(socket_id, p, skeleton, note_lines, "numbers_changed: "+",".join(missing))

    return _done(socket_id, p, text, note_lines ,None)