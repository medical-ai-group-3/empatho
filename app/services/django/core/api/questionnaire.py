"""문진 문항 정의와 답변 검증.

문항을 표로 두지 않고 파일로 둔다 — 명세 §18 의 thresholds.yaml 과 같은
방식이다. 문항이 바뀌면 판을 올리고, 답변에 그 판을 함께 저장해 과거 문진의
뜻이 바뀌지 않게 한다.

    core/questionnaire/v1.yaml       문항 정의
    {"form_version": "v1", "answers": {"has_symptom": "yes"}}    저장 모양

form_version 은 **서버가 찍는다.** 앱이 보내는 것은 answers 뿐이다 — 앱이
판을 정하게 두면 옛 앱이 새 문항에 옛 판을 붙여 보내는 것을 막을 수 없다.

간호과가 화면에서 문항을 고쳐야 하는 날이 오면 그때 표로 옮긴다. 그때도
form_version 이 이미 있어 이관이 깔끔하다.
"""

import functools
import logging
from pathlib import Path

import yaml

from .errors import ApiError

logger = logging.getLogger(__name__)

DEFINITION_DIR = Path(__file__).resolve().parent.parent / "questionnaire"

#: 지금 쓰는 판. 문항을 바꾸면 다음 판 파일을 만들고 여기를 올린다.
#: 옛 판 파일은 지우지 않는다 — 그 판으로 받은 답을 읽어야 한다.
CURRENT_VERSION = "v2"


@functools.lru_cache(maxsize=None)
def form(version=CURRENT_VERSION):
    """문항 정의. 파일을 매 요청 읽지 않도록 캐시한다.

    고치고 확인하려면 서버를 다시 띄워야 한다 — 배포마다 바뀌는 값이 아니라
    그게 낫다.
    """
    path = DEFINITION_DIR / ("%s.yaml" % version)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("문진 정의가 없다: %s", path)
        raise ApiError("INTERNAL_ERROR", "문진 정의를 찾을 수 없습니다.") from None

    questions = {}
    for q in loaded.get("questions") or []:
        questions[q["code"]] = {
            "text": q.get("text", ""),
            "active": bool(q.get("active", True)),
            "options": {o["id"]: o.get("text", "") for o in (q.get("options") or [])},
        }
    return {"form_version": loaded.get("form_version", version),
            "questions": questions}


def active_questions(version=CURRENT_VERSION):
    """화면이 그릴 문항. 껐던 문항은 빼고 준다."""
    return [
        {"code": code, "text": q["text"],
         "options": [{"id": i, "text": t} for i, t in q["options"].items()]}
        for code, q in form(version)["questions"].items() if q["active"]
    ]


def validate(answers, version=CURRENT_VERSION):
    """앱이 보낸 답변을 검증하고 저장할 모양으로 감싼다.

    덜 채운 것은 통과시킨다 — 간호가 나중에 보완하는 경로(§3.12)가 있다.
    막는 것은 「뜻을 알 수 없는 답」뿐이다.
    """
    if not isinstance(answers, dict):
        raise ApiError("VALIDATION_ERROR", "answers 는 객체여야 합니다.")

    defined = form(version)["questions"]
    unknown_code, unknown_option, inactive = [], [], []

    for code, chosen in answers.items():
        question = defined.get(code)
        if question is None:
            unknown_code.append(code)
            continue
        if not question["active"]:
            # 껐는데도 답이 오면 앱이 낡은 문항을 그리고 있다는 뜻이다.
            inactive.append(code)
            continue
        if chosen not in question["options"]:
            unknown_option.append({"code": code, "given": chosen,
                                   "allowed": sorted(question["options"])})

    problems = {k: v for k, v in (("unknown_code", unknown_code),
                                  ("inactive", inactive),
                                  ("unknown_option", unknown_option)) if v}
    if problems:
        raise ApiError("VALIDATION_ERROR", "문진 답변을 알아볼 수 없습니다.",
                       details=problems)

    # form_version 은 여기서 찍는다. 앱이 보낸 값이 있어도 무시한다.
    return {"form_version": form(version)["form_version"], "answers": dict(answers)}
