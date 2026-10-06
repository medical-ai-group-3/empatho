"""응답 모양 — 봉투 · 봉투를 씌우는 두 지점 · 페이지네이션.

명세서 §1-2 의 봉투:

    {success, data, error, trace_id}

성공은 렌더러가, 실패는 예외 핸들러가 씌운다. DRF 가 예외를 렌더러보다 앞에서
처리하기 때문에 두 군데로 갈린다. 조립(ok · fail)은 한 곳에 두어 둘이 어긋나지
않게 한다.

OpenAPI 쪽 반영은 schema.py 가 한다 — spectacular 설정이 한 파일에 모여 있어야
Swagger 가 이상할 때 뒤질 곳이 하나다.
"""

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import connections, transaction
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from .errors import ApiError, spec_for
from .trace import get_trace_id

logger = logging.getLogger(__name__)

KEYS = frozenset({"success", "data", "error", "trace_id"})


# ── 조립 ─────────────────────────────────────────────────────────────────
def ok(data=None):
    return {"success": True, "data": data, "error": None, "trace_id": get_trace_id()}


def fail(code, message=None, details=None):
    spec = spec_for(code)
    error = {"code": spec.code, "message": message or spec.message, "details": details}
    return {"success": False, "data": None, "error": error, "trace_id": get_trace_id()}


def is_envelope(value):
    """이미 봉투인가. 예외 핸들러가 씌운 것을 렌더러가 또 씌우지 않도록."""
    return isinstance(value, dict) and KEYS == set(value)


# ── 성공 ─────────────────────────────────────────────────────────────────
class EnvelopeJSONRenderer(JSONRenderer):
    """성공 응답에 봉투를 씌운다. 실패는 이미 씌워져 오므로 그대로 통과."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # 204 는 본문이 없어야 한다. 봉투를 씌워 보내면 앱(CapacitorHttp)이
        # 없는 끝을 기다리다 72초 뒤 「unexpected end of stream」 으로 실패했다
        # — 서버는 지웠는데 앱은 실패로 알아 복약 체크가 되살아났다(09-29).
        response = (renderer_context or {}).get("response")
        if response is not None and response.status_code == 204:
            return b""
        if not is_envelope(data):
            data = ok(data)
        return super().render(data, accepted_media_type, renderer_context)


# ── 실패 ─────────────────────────────────────────────────────────────────
# DRF 예외 → 명세 코드. 위에서부터 맞는 것을 쓰므로 좁은 것을 먼저 둔다.
_BY_CLASS = [
    (drf.ValidationError, "VALIDATION_ERROR"),
    (drf.NotAuthenticated, "UNAUTHENTICATED"),
    (drf.AuthenticationFailed, "UNAUTHENTICATED"),
    (drf.PermissionDenied, "ROLE_FORBIDDEN"),
    (drf.NotFound, "NOT_FOUND"),
    (drf.Throttled, "RATE_LIMITED"),
]


def _code_for(exc):
    for klass, code in _BY_CLASS:
        if isinstance(exc, klass):
            return code
    return None


def _headers_for(exc):
    headers = {}
    if getattr(exc, "auth_header", None):
        headers["WWW-Authenticate"] = exc.auth_header
    if getattr(exc, "wait", None):
        headers["Retry-After"] = "%d" % exc.wait
    return headers


def _set_rollback():
    """ATOMIC_REQUESTS 를 켠 연결은 예외가 나면 되돌린다."""
    for connection in connections.all():
        if connection.settings_dict["ATOMIC_REQUESTS"] and connection.in_atomic_block:
            transaction.set_rollback(True, using=connection.alias)


def api_exception_handler(exc, context):
    """DRF 기본 예외도 명세 §1-4 의 코드로 옮긴다.

    그래야 클라이언트가 code 하나로만 분기한다 — HTTP 상태와 code 를 같이 봐야
    하면 분기가 두 배로 는다.
    """
    # Django 예외를 DRF 예외로 옮긴다.
    if isinstance(exc, Http404):
        exc = drf.NotFound(*exc.args)
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf.PermissionDenied(*exc.args)

    if isinstance(exc, ApiError):
        _set_rollback()
        return Response(fail(exc.code, exc.message, exc.details),
                        status=exc.status_code, headers=_headers_for(exc))

    if not isinstance(exc, drf.APIException):
        # 우리가 예상하지 못한 예외다.
        logger.exception("처리되지 않은 예외", exc_info=exc)
        if settings.DEBUG:
            return None        # 디버그 페이지가 뜨도록 다시 던지게 둔다
        return Response(fail("INTERNAL_ERROR"), status=500)

    code = _code_for(exc)
    if code is None:
        # DRF 가 아는 예외지만 명세에 대응 코드가 없는 것 (MethodNotAllowed 등).
        logger.warning("명세에 코드가 없는 예외: %s", type(exc).__name__)
        code = "INTERNAL_ERROR"

    if isinstance(exc, drf.ValidationError):
        # 필드별 사유는 details 로. message 는 카탈로그의 기본 문장을 쓴다.
        body = fail(code, details=exc.detail)
    else:
        detail = getattr(exc, "detail", None)
        body = fail(code, str(detail) if detail else None)

    _set_rollback()
    # 상태는 예외가 들고 있는 것을 따른다 — Throttled 처럼 뷰 설정에 따라 달라진다.
    return Response(body, status=exc.status_code, headers=_headers_for(exc))


# ── 페이지네이션 ─────────────────────────────────────────────────────────
class DefaultPagination(PageNumberPagination):
    """?page=1&page_size=20 → {count, next, previous, results} (명세 §1-1).

    이 덩어리는 봉투와 나란히가 아니라 data **안에** 들어간다.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200        # 명세에 없다. 한 번에 전부 긁어가는 요청을 막는 선.
