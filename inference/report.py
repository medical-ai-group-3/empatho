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

from fastapi import FastAPI, HTTPException

import narrative
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
    
def _done(socket_id: str, p, text:str, notes:list[str], fallback,
          cited:list[str] | None = None, dropped:list[dict] | None = None):
    """응답 한 벌을 만든다.

      p         이 소켓의 프롬프트 모듈
      text      소견문. 모델이 쓴 것이거나 코드가 만든 뼈대다
      notes     안내 문장들. 모델을 거치지 않는다
      fallback  None 이면 모델이 쓴 것, 문자열이면 그 사유로 뼈대를 쓴 것
      cited     소견문이 실제로 인용한 근거 id
      dropped   근거 검사가 버린 문장과 그 이유

    안내(notes)를 모델에 넘기지 않는 이유 — 「형태 지표를 믿지 마십시오」 같은
    문장은 다시 쓰면 뜻이 흐려지고, 받는 쪽이 「문제 없음」으로 읽는다.

    뼈대로 되돌아간 갈래에는 cited·dropped 가 없다. 모델 출력을 통째로 버렸으니
    인용도 없는 것이 맞다 — 빈 목록으로 나간다.
    """
    return {
        "socket_id": socket_id,
        "abstained": False,
        "소견": text,
        "안내": notes,
        "model_name": None if fallback else MODEL,
        "prompt_version": p.VERSION,
        "fallback": fallback,
        # DB 의 evidence_links · dropped_sentence_log 로 간다.
        "evidence": cited or [],
        "dropped": dropped or [],
    }
    
    
# 경로가 둘인 이유 — Go 의 report.Client.Health() 가 {base}/health 를 부른다.
# 우리 다른 서버는 /healthz 라 이름을 맞추기보다 둘 다 받는 편이 안전하다.
@app.get("/health")
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
def report(socket_id: str, result: dict, evidence: list[str] = []):
    """판독 결과 한 벌 → 소견문 + 안내.

    Go 의 llm-proxy 가 부른다. 본문은 열쇠 둘이다.

      result    /analyze 가 낸 result 를 그대로
      evidence  근거 id 목록 — 모델이 지어낸 인용을 거르는 데 쓴다

    ⚠ 본문 인자가 하나면 FastAPI 가 본문 전체를 거기 담는다. 둘이라서 키별로
    나뉜다 — evidence 를 지우면 {result, evidence} 가 통째로 result 에 들어가고
    facts() 가 lesion_found 를 못 찾아 「병변이 검출되지 않았습니다」가 나간다.

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

    # 입력 모양 검사. 모델·GPU 실패는 기권으로 돌려주지만 이건 부르는 쪽의
    # 실수라 422 로 알린다 — 조용히 「병변이 검출되지 않았습니다」가 나가면
    # 실제로 병변이 없는 것과 구분이 안 된다.
    absent = [k for k in p.REQUIRED if k not in result]
    if absent:
        raise HTTPException(422, f"result 에 {', '.join(absent)} 가 없다")

    # fact_lines  수치와 판단을 코드가 만든 문장. 여기 숫자는 틀릴 수 없다.
    # note_lines  안내. 모델을 거치지 않고 그대로 나간다.
    # skeleton    모델이 없거나 수치를 바꿨을 때 대신 내보낼 완성 문장.
    fact_lines = p.facts(result)
    note_lines = p.notes(result)
    skeleton = " ".join(fact_lines)

    try:
        out = _ask(p.SYSTEM, p.build(fact_lines, evidence), p.SCHEMA)
        text = (out.get("소견") or "").strip()
    except Exception as exc:
        # 모델이 없어도 리포트는 나간다. 뼈대는 완성된 문장이다
        return _done(socket_id, p, skeleton, note_lines, f"llm_failed: {type(exc).__name__}")

    # 근거 검사. 표시가 없거나 없는 ID 를 인용한 문장을 버리고 표시를 지운다.
    #
    # 수치 검사보다 먼저 하는 이유 — 반대로 하면 지어낸 근거가 붙은 문장이
    # 수치 검사를 통과한 뒤 사라져서, 최종 문장에 없는 숫자를 통과시킨 셈이 된다.
    #
    # evidence 가 비면 건너뛴다. 병변이 없으면 인용할 근거도 없기 때문이고,
    # Go 쪽 report.Request 주석이 그렇게 못 박고 있다 —
    # 「비워 보내면 근거 검사를 건너뛰고 숫자 검사만 한다」.
    # narrative.filter_ 는 빈 목록을 「전부 버림」으로 보므로 그냥 부르면 안 된다.
    cited, dropped = [], []
    if evidence:
        kept = narrative.filter_(text, evidence)
        text, cited, dropped = kept["text"], kept["evidence"], kept["dropped"]
    else :
        # 근거 목록이 비면 검사는 건너뛰지만 표시는 지워야 한다 
        # SYSTEM이 언제나 표시를 붙이라고 하므로 안 지우면 원래 모양이 그래도 소견문에 나간다 
        # filter_는 목록이 비면 "전부 버림"이라 못 쓴다 
        text = narrative.TAG.sub("", text).strip().replace(" .", ".")

    # 넘긴 수치가 소견문에 그대로 남아 있는지 본다. 글자열로 찾는 단순한 검사다.
    # 값을 바꿔 쓰면 그 값은 사라지므로 여기서 걸린다. 반대로 문장을 어떻게
    # 다듬든 숫자만 그대로면 통과한다 — 우리가 막으려는 것은 문체가 아니다.
    missing = [n for n in p.numbers(result) if n not in text]
    if missing:
        # 모델이 수치를 바꿨거나, 그 값을 담은 문장이 근거 검사에서 버려졌다.
        # 어느 쪽이든 남은 문장은 불완전하므로 출력을 통째로 버린다.
        # 어느 값이 사라졌는지 fallback 에 남겨 나중에 프롬프트를 고칠 단서로 쓴다.
        return  _done(socket_id, p, skeleton, note_lines, "numbers_changed: "+",".join(missing))

    return _done(socket_id, p, text, note_lines, None, cited, dropped)