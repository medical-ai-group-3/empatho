"""G-L2 대화 — 환자 앱의 안내 챗봇. (명세 19-4)

    POST /api/v1/chat   {"question": "미세석회가 뭔가요?"}
    → {"answer": "...", "disclaimer": "...", "stored": false}

응답 모양은 **화면(empatho-view)이 이미 쓰고 있는 것**에 맞췄다.
src/api.js 의 `chat: (q) => post("/api/v1/chat", {question: q})` 와
src/screens/Chat.jsx 의 `r.answer` · `r.disclaimer` 가 그것이다.

── 무엇에 답하나 ────────────────────────────────────────────────

두 가지이고, 둘을 **구분해서** 답해야 한다.

    낱말의 뜻    "미세석회가 뭔가요"  → 일반적인 설명을 해도 된다
    내 결과      "제 결과는 어떤가요"  → 열린 리포트에 적힌 것만

둘을 안 나누면 둘 다 망가진다. 전부 막으면 용어 설명이 "결과에 없습니다" 만
반복하고, 전부 열면 모델이 일반 지식으로 이 환자의 결과를 지어낸다.
규칙은 services/gosvc/internal/chat 에 한 곳으로 모여 있다.

── Django 가 Go 를 부른다 ───────────────────────────────────────

브라우저 → Django → llm-proxy → Ollama 다. 브라우저가 Go 를 직접 부르지
않는다(업로드·알림과 다른 점이다).

그래서 **소견이 브라우저를 거치지 않는다.** 여기서 DB 를 읽어 실어 주므로
화면이 소견을 바꿔치기할 자리가 없고, 티켓도 해시도 필요 없다. 서버 간
호출이라 notify 의 G-N2 발행과 같은 내부 서명을 쓴다 —
「티켓은 사용자용이고 발행은 서버 간 호출이다」.

── 저장하지 않는다 (팀 결정) ────────────────────────────────────

대화 표가 없다. 응답의 stored=false 가 그 뜻이고 화면이 그것을 적어 준다.
환자가 병에 대해 물어본 기록은 그 자체가 민감한 자료다.
"""

import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from hashlib import sha256

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Report
from .errors import ApiError
from .permissions import PATIENT, IsAuthenticatedAccount
from .trace import get_trace_id

logger = logging.getLogger(__name__)

#: 화면이 답마다 함께 보여 주는 한 줄. **모델이 쓴 글이 아니다.**
#: 여기서 보내는 이유는 문구가 바뀔 때 앱 배포를 기다리지 않게 하려는 것이다.
DISCLAIMER = "이 답변은 진단이 아닙니다. 최종 판단은 진료 때 의료진이 합니다."

#: 아직 열린 결과가 없는 사람에게. 용어 설명은 그대로 되므로 막지 않는다.
DISCLAIMER_NO_REPORT = ("아직 열람할 수 있는 검사 결과가 없어 낱말 뜻만 "
                        "안내해 드립니다. 결과는 대면 설명 후에 열립니다.")


def evidence_ids(report):
    """report.evidence_links 에서 근거 id 목록.

    지금 들어가는 모양은 문자열 목록이다 — llm-proxy 가 I-4 로 보내는
    evidence_links 가 ["MG-01", "MG-02"] 다.

    행(dict)으로 바뀔 수 있어 그쪽도 받는다. 모르는 모양은 **조용히 건너뛰지
    않고 터뜨린다** — 건너뛰면 근거가 빠진 채로 답이 나가는데 화면에서는
    똑같아 보인다.
    """
    ids = []
    for item in report.evidence_links or []:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        else:
            raise ApiError("INTERNAL_ERROR",
                           "근거 목록의 모양을 알 수 없습니다.",
                           details={"report_id": report.pk,
                                    "evidence_link": repr(item)[:100]})
    return ids


def open_report_for(account):
    """이 환자에게 **지금 열려 있는** 리포트. 없으면 None.

    ── 무엇으로 「열렸다」를 판정하나 ────────────────────────────

    explained_at 이 채워졌는지로 본다. 모델 주석이 그 칸을 「잠금 해제
    트리거」라고 적어 둔 그대로다.

    ⚠ 화면(empatho-view)은 lock_status == 'locked' 로 가르고 목업이
    'unlocked' 를 쓴다. 그런데 **lock_status 에는 값 집합이 없다** —
    models.py 에 default='locked' 만 있고 「풀린 상태」 문자열을 아무도
    정해 놓지 않았다. 여기서 우리가 'unlocked' 라고 정해 버리면 리포트
    담당이 다른 값을 쓰는 순간 대화가 조용히 전부 막히거나 전부 열린다.
    값 집합이 생기면 여기도 같이 보도록 고칠 것. (리포트 담당 확인 대상)

    ── 왜 여기서 보나 ───────────────────────────────────────────

    안 보면 **의사가 대면 설명을 하기 전에 환자가 챗봇으로 자기 결과를 먼저
    읽는다.** 잠금이 막으려던 바로 그 일이고, 리포트 화면보다 대화 쪽이 더
    나쁘다 — 물어보면 더 말해 준다.

    2026-09-17 확인 — report.lock_status 를 읽는 코드가 models.py 밖에
    없다. 리포트 조회 경로에도 없다. 그래서 그쪽 구현을 기다리지 않고
    대화 경로에서 자체적으로 막는다.

    ⚠ 리포트가 여러 건이면 **가장 최근에 설명한 것** 하나를 쓴다.
      화면의 챗봇은 리포트 안이 아니라 독립된 탭이라 어느 것인지 말해 주지
      않는다. 화면이 report_id 를 실어 보내기 시작하면 그것을 우선할 것.
    """
    return (Report.objects
            .filter(patient__account=account,
                    audience="patient",
                    explained_at__isnull=False)
            .order_by("-explained_at")
            .first())


def ask(question, report):
    """llm-proxy 에 묻는다. 서명은 notify 의 G-N2 발행과 같은 식이다."""
    secret = settings.CALLBACK_SECRET
    if not secret:
        logger.error("CALLBACK_SECRET 이 비어 있다 — 대화를 보낼 수 없다")
        raise ApiError("INTERNAL_ERROR", "대화 설정이 되어 있지 않습니다.")

    payload = {
        "report_id": str(report.pk) if report else "",
        # 없으면 빈 문자열이다. Go 는 그때 용어 설명만 하도록 규칙이 갈린다.
        "narrative_text": (report.narrative_text or "") if report else "",
        "evidence": evidence_ids(report) if report else [],
        # 화면이 아직 이력을 안 보낸다(Chat.jsx 가 질문 하나만 싣는다).
        # Go 는 여러 마디를 받게 돼 있으니 화면이 보내기 시작하면 그대로 흐른다.
        "messages": [{"role": "user", "content": question}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ts = str(int(time.time()))
    # 구분자를 넣는다 — 없으면 (ts="1", body="23") 과 (ts="12", body="3") 이
    # 같은 서명을 낸다. Go 의 callback.Sign 과 같은 계산이어야 한다.
    sig = hmac.new(secret.encode("utf-8"),
                   ts.encode("utf-8") + b"." + body, sha256).hexdigest()

    req = urllib.request.Request(
        settings.LLM_BASE.rstrip("/") + "/svc/v1/llm/chat", body,
        {"Content-Type": "application/json",
         "X-Timestamp": ts, "X-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT_SEC) as res:
            return json.loads(res.read().decode("utf-8"))
    # 코드는 UPSTREAM_LLM_UNAVAILABLE(503) 이다 — llm-proxy 가 같은 코드를 쓴다.
    # 카탈로그(errors.py)에 없는 코드를 던지면 spec_for 가 KeyError 를 내고
    # **500 으로 터진다.** 새 코드를 만들기 전에 거기부터 넣을 것.
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        logger.error("[chat] llm-proxy %s: %s", e.code, detail)
        raise ApiError("UPSTREAM_LLM_UNAVAILABLE",
                       "지금은 답변을 가져올 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("[chat] llm-proxy 에 못 닿았다 (%s): %s", settings.LLM_BASE, e)
        raise ApiError("UPSTREAM_LLM_UNAVAILABLE",
                       "지금은 답변을 가져올 수 없습니다. 잠시 뒤 다시 시도해 주세요.")


class ChatView(APIView):
    """POST /api/v1/chat"""

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="chat",
        summary="안내 챗봇",
        description="낱말 뜻과, 열려 있는 검사 결과에 적힌 범위 안의 질문에 답한다. "
                    "대화는 저장되지 않는다.",
        request={"application/json": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        }},
        responses={200: {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "disclaimer": {"type": "string"},
                "stored": {"type": "boolean"},
            },
        }},
    )
    def post(self, request):
        account = request.user
        # 환자 앱 전용이다. 의료진에게는 규칙이 반대라야 쓸모가 있어서
        # 같은 봇을 양쪽에 붙이지 않는다.
        if account.role != PATIENT:
            raise ApiError("ROLE_FORBIDDEN",
                           details={"reason": "환자 앱 전용입니다."})

        question = (request.data.get("question") or "").strip()
        if not question:
            raise ApiError("VALIDATION_ERROR", "질문을 입력해 주세요.",
                           details={"missing": ["question"]})

        report = open_report_for(account)
        out = ask(question, report)

        # 되돌렸는지는 화면에 알리지 않는다. 환자에게는 「답을 못 드린다」가
        # 전부이고, 왜 못 드리는지(모델이 규칙을 어겼다)는 우리 사정이다.
        # 대신 로그에는 남긴다 — 되돌리기가 늘면 규칙이나 모델을 손봐야 한다.
        if out.get("fallback"):
            logger.warning("[chat] trace=%s account=%s 되돌림(%s)",
                           get_trace_id(), account.account_id,
                           out.get("fallback_reason"))

        return Response({
            "answer": out.get("text", ""),
            "disclaimer": DISCLAIMER if report else DISCLAIMER_NO_REPORT,
            "stored": False,
        })
