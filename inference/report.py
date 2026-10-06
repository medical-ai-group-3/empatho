"""판독 결과를 소견 문장으로 옮기는 서버 — 소켓 6.

추론 서버(8001)와 별도 프로세스다. GPU 수명주기가 다르고 — Ollama 가
모델을 알아서 올렸다 유휴 90초 뒤 내린다(_ask 가 keep_alive 를 보낸다) — 한쪽이
죽어도 다른 쪽은 살아야 한다.

리포트를 못 만들어도 판독 결과는 유효하다. 실패는 기권으로 돌려준다.
500 을 내면 앱 서버가 판독까지 실패로 처리한다.
"""

import json
import os
import re
import urllib.request

from fastapi import FastAPI

import replay
from prompts import PROMPTS, base

# Ollama 주소. 이 서버와 같은 워크스테이션에 있으므로 기본이 127.0.0.1 이다.
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# 소견 문장을 쓰는 모델. 판독은 하지 않는다 — 이미 나온 값을 옮기기만 한다.
#
# 4B 는 반복 항목을 못 버틴다 — 맘모 6병변에서 서술어 2건을 지우고
# 「1~5번은」으로 묶었다(09-09 실측). 12B 는 6건을 각각 정확히 쓴다.
# 의료 지식이 필요한 일이 아니라 값을 빠짐없이 옮기는 일이라, 의료 특화보다
# 지시 이행력이 중요하다. VRAM 은 2.9GB → 8GB 로 는다.
MODEL = os.getenv("REPORT_MODEL", "gemma3:12b-it-q4_K_M")

ALIAS = {"4": "5", "2": "1"}

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
        # 모델을 얼마나 붙들고 있을지. Ollama 기본은 300초인데 그동안 2.9GB 를
        # 잡고 있어, 판독(소켓 1~5)이 GPU 를 크게 쓸 때 여유를 깎는다.
        # 90초로 줄인다 — 한 검사에서 소견을 잇달아 뽑는 동안은 유지되고,
        # 끝나면 곧 내려간다. 다시 올리는 데 드는 시간은 약 1초다.
        "keep_alive": "90s",
        # 0  같은 입력에 같은 리포트가 나와야 한다. 의료 기록이라 문체보다 중요하다.
        # 09-08 실측 — 0 은 50/50 글자까지 동일. 0.3 은 36/50, 0.5 는 24/50.
        # 0.7 은 6회 중 1회가 "수술 후 6개월" 이라는 없는 사실을 지어냈다.
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(json.loads(r.read())["response"])
    
def _done(socket_id: str, p, text:str, notes:list[str], fallback,
          cited:list[str] | None = None):
    """응답 한 벌을 만든다.

      p         이 소켓의 프롬프트 모듈
      text      소견문. 모델이 쓴 것이거나 코드가 만든 뼈대다
      notes     안내 문장들. 모델을 거치지 않는다
      fallback  None 이면 모델이 쓴 것, 문자열이면 그 사유로 뼈대를 쓴 것
      cited     소견문이 실제로 인용한 근거 id

    안내(notes)를 모델에 넘기지 않는 이유 — 「형태 지표를 믿지 마십시오」 같은
    문장은 다시 쓰면 뜻이 흐려지고, 받는 쪽이 「문제 없음」으로 읽는다.

    뼈대로 되돌아간 갈래에는 cited 가 없다. 모델 출력을 통째로 버렸으니
    인용도 없는 것이 맞다 — 빈 목록으로 나간다.

    dropped 는 늘 빈 목록이다. 「모델이 지어낸 인용을 문장 단위로 버린다」는
    검사가 아직 없다 — 지금은 수치 검사에서 걸리면 출력을 통째로 버린다.
    앱 서버의 dropped_sentence_log 자리를 비워 두는 것이라 키는 남긴다.
    """
    # 병변마다 줄을 바꾼다. 모델에 맡기면 매번 달랐다 — 빈 줄로 흩거나
    # 한 줄로 붙였다(09-29). 문장 사이 공백만 바꾸므로 수치 검사와 무관하다
    text = re.sub(r"(?<=[.])[ \t]+(?=병변 )", "\n", text)
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
        "dropped": [],
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
    """시연용 재생을 거쳐 _report 로 간다 (REPLAY_DIR 이 있을 때만 — replay.py).

    같은 판독값으로 전에 쓴 소견문이 있으면 LLM 을 건너뛰고 그 응답을 준다.
    본문 인자 둘(result · evidence)은 아래 _report 주석 때문에 그대로 둔다.
    """
    k = replay.key(socket_id, json.dumps(replay.stable(result), sort_keys=True, ensure_ascii=False),
                   json.dumps(evidence, ensure_ascii=False)) if replay.enabled() else None
    cached = replay.load("report", k) if k else None
    if cached is not None:
        return cached
    out = _report(socket_id, result, evidence)
    if k and not out.get("abstained"):
        try:                                  # 저장이 실패해도 소견문은 나간다
            replay.save("report", k, out)
        except Exception as exc:
            print(f"[replay_save_failed] {type(exc).__name__}: {exc}", flush=True)
    return out


def _report(socket_id: str, result: dict, evidence: list[str]):
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
    # 판독 창구와 같은 별칭을 쓴다(main.py ALIAS). 소켓 4 는 5 로, 2 는 1 로
    # 넘어가 판독되므로 소견문도 같은 번호로 쓴다. 여기서 안 넘기면
    # /report/4 의 응답만 socket_id 가 4 로 남아, 같은 판독인데 판독 결과와
    # 리포트가 다른 번호를 가리킨다.
    socket_id = ALIAS.get(socket_id, socket_id)
    
    p = PROMPTS.get(socket_id)
    if p is None:
        return {"socket_id": socket_id, "abstained": True, "reason":"unknown_socket"}

    # 입력 모양 검사. 부르는 쪽의 실수지만 그래도 200 에 기권으로 돌려준다 —
    # 판독 서버와 같은 규칙이다. 422 를 내면 Go 가 오류로 처리해 리포트가
    # 통째로 안 나가고, 무엇이 없었는지도 응답에 안 남는다.
    #
    # 조용히 「병변이 검출되지 않았습니다」가 나가지 않게, 기권 사유에
    # 빠진 항목 이름을 담는다.
    absent = [k for k in p.REQUIRED if k not in result]
    if absent:
        return {
            "socket_id": socket_id, 
            "abstained": True, 
            "reason": f"missing_fields: {','.join(absent)}"
        }

    # fact_lines  수치와 판단을 코드가 만든 문장. 여기 숫자는 틀릴 수 없다.
    # note_lines  안내. 모델을 거치지 않고 그대로 나간다.
    # skeleton    모델이 없거나 수치를 바꿨을 때 대신 내보낼 완성 문장.
    fact_lines = p.facts(result)
    note_lines = p.notes(result)
    # 뼈대를 잇는 문자. 종합 소견서는 검사마다 문단을 나눈다(summary.JOIN)
    skeleton = getattr(p, "JOIN", " ").join(fact_lines)
    
    # 지킬 수치가 하나도 없으면 모델 출력을 검사할 방법이 없다. 맘모 기권 ·
    # 초음파 병변 없음 · 병리 간질 없음이 그렇다. 그대로 모델을 태우면
    # 「임계값을 넘는 검출이 없어 판정하지 않았습니다」가 「정상 소견입니다」로
    # 바뀌어도 걸러낼 수 없다 — 검사망이 없는 유일한 구간이었다.
    #
    # 이 세 경우의 뼈대는 한두 문장이라 다듬을 여지도 적다. 모델을 건너뛴다.
    keep = p.numbers(result)
    if not keep:
        return _done(socket_id, p, skeleton, note_lines, "no_numbers_to_verify")
    
    try :
        # 청중이 둘인 소켓은 규칙이 다르게 적용
        system = p.system(result) if hasattr(p, "system") else base.SYSTEM
        schema = p.schema(result) if hasattr(p, "schema") else base.SCHEMA
        out = _ask(system, base.build(p.values(result)), schema)
        # 환자용 종합 소견서는 검사별 문단을 받아 코드가 잇는다(summary.text)
        text = (p.text(result, out) if hasattr(p, "text")
                else (out.get("소견") or "")).strip()
    except Exception as exc :
        return _done(socket_id, p, skeleton, note_lines, f"llm_failed:{type(exc).__name__}")

    # 검사 방향이 소켓마다 다르다.
    #   보존  수치가 글에 그대로 남아 있어야 한다 (지금까지)
    #   금지  수치가 나타나면 안 된다 — 환자용 소견서가 그렇다.
    #         수치를 순화하기로 했으므로, 남아 있다는 것은 모델이 안 순화했다는 뜻이다
    ban = hasattr(p, "forbidden") and p.forbidden(result)
    hit = [n for n in keep if bool(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", text)) is bool(ban)]
    
    if ban and hit:
        return  _done(socket_id, p, skeleton, note_lines, f"numbers_leaked: {','.join(hit)}")
    
    if not ban and hit:
        return  _done(socket_id, p, skeleton, note_lines, f"numbers_changed: {','.join(hit)}")

    # 수치가 아니라 문장을 지켜야 하는 것도 있다. 등급을 환자 말로 바꾼 문장이
    # 그렇다 — 「시급한 정도입니다」를 「필요할 것으로 보입니다」로 낮춰 쓰면
    # 숫자 검사에 안 걸리고 뜻만 약해진다. 글자 그대로 있는지 본다.
    #
    # 빠졌으면 **덧붙인다**. 버리지 않는 이유 — 09-21 실측으로 모델이 이 문장을
    # 거의 매번 풀어 썼다. 표를 나눠 「· 그대로」로 표시해 봐도 마찬가지였다.
    # 버리는 규칙으로 두면 환자용이 영영 뼈대로만 나가서, 모델을 쓰는 뜻이 없다.
    # 모델이 비슷한 말을 이미 썼더라도 정확한 표현을 한 번 더 붙이는 쪽이
    # 뜻이 약해진 채 나가는 것보다 낫다.
    miss = [s for s in (p.must_keep(result) if hasattr(p, "must_keep") else [])
            if s not in text]
    if miss:
        text = text.rstrip() + " " + " ".join(s + "." for s in miss)
    # evidence 는 받은 것을 그대로 돌려준다. 문장별이 아니라 리포트 단위다 -
    # 어느 사진 어느 병변인지는 화면이 마스크와 수치로 따로 보여준다.
    return _done(socket_id, p, text, note_lines, None, evidence)