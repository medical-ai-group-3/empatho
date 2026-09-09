"""trace_id — 요청 하나를 처음부터 끝까지 따라가는 값.

봉투의 trace_id 와 응답 헤더 X-Trace-Id 가 같은 값이다. 감사 로그와 대조할 때
이 값으로 잇는다.

요청에 X-Trace-Id 가 이미 있으면 이어받는다 — Go 계층이나 게이트웨이를 거친
요청이 Django 에서 새 id 를 받아버리면 추적이 거기서 끊긴다.
"""

import re
import uuid
from contextvars import ContextVar

HEADER = "X-Trace-Id"
_META_KEY = "HTTP_X_TRACE_ID"

# 남이 준 값을 그대로 로그에 넣기 때문에 모양을 제한한다.
_SAFE = re.compile(r"\A[A-Za-z0-9._-]{8,64}\Z")

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def new_trace_id():
    return uuid.uuid4().hex


def get_trace_id():
    """지금 요청의 trace_id. 요청 밖(배치 · 셸)에서는 빈 문자열."""
    return _trace_id.get()


def set_trace_id(value):
    return _trace_id.set(value)


def reset_trace_id(token):
    _trace_id.reset(token)


class TraceIdMiddleware:
    """요청마다 trace_id 를 세우고 응답 헤더에 실어 보낸다.

    contextvar 라 뷰 · 렌더러 · 예외 핸들러가 인자 없이 같은 값을 읽는다.
    요청이 끝나면 되돌린다 — 워커 스레드가 재사용될 때 값이 새지 않도록.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(_META_KEY, "")
        trace_id = incoming if _SAFE.match(incoming or "") else new_trace_id()

        token = set_trace_id(trace_id)
        try:
            response = self.get_response(request)
        finally:
            reset_trace_id(token)

        response[HEADER] = trace_id
        return response
