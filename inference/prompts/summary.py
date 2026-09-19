"""종합 소견서(소켓 7) — 검사별 소견문을 한 벌로 묶는다.

    초음파 · 맘모 · MRI · 병리 판독  ─▶  소켓 7  ─┬─▶ 의사용
                                                └─▶ 환자용

문장을 여기서 새로 쓰지 않는다. 각 모달리티 프롬프트의 facts() · plain() · numbers()
를 그대로 부른다 — 베끼면 모달리티가 늘 때마다 두 곳을 고쳐야 하고, 두 곳이 어긋나면
종합 소견서만 조용히 옛 규칙으로 쓰인다.

받는 모양
    {"stages":   [{"socket": "5", "result": {...}}, ...],
     "audience": "clinician" | "patient"}

  stages 를 무엇으로 채울지는 앱 서버가 정한다 — 유방외과 의사가 고른 판독문들이다.

청중이 둘이다
    clinician  지금까지와 같다. 수치를 그대로 옮기고 **보존**을 검사한다
    patient    수치와 전문 용어를 걷어낸다. 검사가 반대다 — 수치가 **남아 있으면** 버린다

⚠ 환자용은 어디서도 facts() 를 쓰지 않는다 — 모델 입력도 뼈대도 plain() 이다.
  facts() 에는 수치와 전문 용어가 들어 있고, 모델은 모르는 말을 아는 말로 바꾼다.
  간질(stroma)이 간(liver)이 되어 「암세포가 간에 침투」로 나갔다(2026-09-20 실측).
"""
from prompts import base

# 2026-09-19.a  신규
# 2026-09-20.a  환자용은 facts() 가 아니라 plain() 을 넘긴다
# 2026-09-20.b  환자용 뼈대도 plain() 으로 · must_keep() — 등급 문장 보존
VERSION = "summary-2026-09-20.b"

SOCKET_IDS = {"7"}
REQUIRED = ("stages",)

# 소켓 → 검사 이름. 의사용과 환자용의 부르는 말이 다르다.
NAME = {"5": "초음파", "4b": "유방촬영", "3": "유방 MRI", "1": "조직검사"}
PLAIN = {"5": "초음파 검사", "4b": "유방 엑스레이 검사",
         "3": "유방 MRI 검사", "1": "조직 검사"}

SYSTEM_PATIENT = """
아래 검사 결과를 환자에게 보여줄 안내문으로 쓴다.
읽는 사람은 의학을 모르는 사람이다.

지키는 것
  구체적인 수치를 쓰지 않는다. 크기 · 개수 · 비율 · 등급 번호를 글에 남기지 않는다.
  BI-RADS 같은 분류 기호를 쓰지 않는다.
  전문 용어는 쉬운 말로 바꾼다. 바꿀 수 없으면 괄호로 풀어 준다.
  판독값에 없는 소견을 지어내지 않는다.
  「없다」 · 「정상이다」로 단정하지 않는다. 확인되지 않은 것과 다르다.
  장기 이름을 바꿔 쓰지 않는다. 모르는 용어는 옮기지 말고 빼라.
  검사 결과의 정도를 낮추거나 높여 쓰지 않는다. 준 문장 그대로 옮긴다.
  악성 여부를 말하지 않는다. 진단하지 않고 치료를 권하지 않는다.
  검사마다 문장을 끊는다.
  존댓말로 쓴다. 머리말 없이 내용부터 쓴다.
  마지막 문장은 자세한 내용을 담당 의사에게 듣도록 안내한다.
"""

NOTES = {
    "SU-N01": "검사별 소견문을 묶은 것입니다. 각 검사의 수치는 해당 판독 화면에서 확인하십시오.",
    "SU-N02": "최종 판정은 담당 의사가 합니다.",
    "SU-P01": "이 안내문은 검사 결과를 쉽게 정리한 것입니다. 정확한 내용은 담당 의사의 설명을 따르십시오.",
}


def _patient(r) :
    return r.get("audience") == "patient"


def _stages(r) :
    """아는 소켓만 남긴다. 모르는 번호가 섞여도 나머지는 쓴다."""
    from prompts import PROMPTS          # 순환 참조를 피해 부를 때 가져온다
    out = []
    for s in (r.get("stages") or []) :
        p = PROMPTS.get(s.get("socket"))
        if p is not None and isinstance(s.get("result"), dict) :
            out.append((s["socket"], p, s["result"]))
    return out


def _plain(p, res) :
    """환자용 문장. plain() 이 없는 소켓은 유무조차 말하지 않는다 —
    facts() 로 되돌리면 수치와 전문 용어가 그대로 나간다."""
    return p.plain(res) if hasattr(p, "plain") else ["결과가 나왔습니다."]


def values(r) :
    """모델에 넘길 표. 청중에 따라 **넘기는 값 자체가** 다르다.

    환자용에 facts() 를 넘기면 안 된다. 전문 용어가 들어 있고, 모델은 모르는
    말을 아는 말로 바꾼다 — 간질(stroma)이 간(liver)이 되어 「암세포가 간에
    침투한 림프구」로 나갔다(2026-09-20 실측). 수치 검사는 숫자만 보므로
    이런 것을 하나도 못 잡는다. 그래서 순화를 모델이 아니라 모달리티가 한다.
    """
    out = []
    for socket, p, res in _stages(r) :
        name = (PLAIN if _patient(r) else NAME).get(socket, socket)
        say = _plain(p, res) if _patient(r) else p.facts(res)
        out.append((name, " ".join(say)))
    return out or [("검사", "묶을 판독 결과가 없습니다.")]


def facts(r) :
    """뼈대. 모델이 실패하거나 검사에 걸리면 이것이 그대로 나간다."""
    if _patient(r) :
        # 모델에 넘긴 것과 같은 문장을 쓴다. 뼈대가 모델 입력보다 적게 말하면,
        # 되돌림이 일어날 때마다 환자가 받는 정보가 조용히 줄어든다.
        out = [f"{PLAIN.get(socket, socket)} — " + " ".join(_plain(p, res))
               for socket, p, res in _stages(r)]
        if not out :
            return ["묶을 검사 결과가 없습니다."]
        out.append("자세한 내용은 담당 의사의 설명으로 확인해 주십시오.")
        return out

    out = []
    for socket, p, res in _stages(r) :
        out.append(f"[{NAME.get(socket, socket)}] " + " ".join(p.facts(res)))
    return out or ["묶을 판독 결과가 없습니다."]


def notes(r) :
    if _patient(r) :
        return [base.note(NOTES, "SU-P01")]
    return [base.note(NOTES, "SU-N01"), base.note(NOTES, "SU-N02")]


def numbers(r) :
    """각 검사가 지키라고 한 수치의 합집합. 순서는 유지하고 중복만 뺀다.

    의사용은 이것이 「남아 있어야 하는」 목록이고,
    환자용은 같은 목록이 「나타나면 안 되는」 목록이 된다(forbidden).
    """
    out, seen = [], set()
    for _socket, p, res in _stages(r) :
        for n in p.numbers(res) :
            if n not in seen :
                seen.add(n)
                out.append(n)
    return out


def forbidden(r) :
    """참이면 report.py 가 검사 방향을 뒤집는다."""
    return _patient(r)


def must_keep(r) :
    """글자 그대로 남아 있어야 하는 문장. 바뀌면 모델 출력을 버린다.

    수치 검사로는 못 잡는 구멍을 막는다. BI-RADS 4~5 라서 코드가 넘긴
    「추가 확인이 시급한 정도입니다」를 모델이 「추가적으로 확인이 필요할
    것으로 보입니다」로 낮춰 쓴 것을 확인했다(2026-09-20). 숫자가 아니니
    숫자 검사에 걸리지 않고, 환자를 안심시키는 방향이라 위험한 쪽이다.

    등급 문장만 본다. 나머지는 모델이 다시 써도 뜻이 안 바뀐다 —
    이 문장은 「얼마나 급한가」 하나만 싣고 있어서 바꿔 쓸 여지가 없다.
    """
    if not _patient(r) :
        return []
    bands = set(base.BIRADS_PLAIN.values())
    out = []
    for _socket, p, res in _stages(r) :
        for s in _plain(p, res) :
            s = s.rstrip(".")
            if s in bands and s not in out :
                out.append(s)
    return out


def system(r) :
    return SYSTEM_PATIENT if _patient(r) else base.SYSTEM