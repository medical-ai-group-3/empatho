"""전송 티켓 발급 — POST /api/v1/tickets (명세 19-1).

Go 는 자체 권한 판정을 하지 않는다. Django 가 서명한 단기 티켓이 있어야만
파일을 받거나 내준다. 그래서 **티켓은 곧 권한**이고, 발급 시점이 유일한
검사 지점이다.

    Django ──서명(TICKET_KEY · HS256)──▶ 클라이언트 ──Bearer──▶ Go 검증

CALLBACK_SECRET 과 방향이 반대다. 그쪽은 Go 가 서명하고 Django 가 검증한다.
두 값은 절대 같으면 안 된다 — core/apps.py 의 시스템 검사가 막는다.

클레임은 services/gosvc/internal/ticket/ticket.go 의 Claims 와 1:1 이다.
patient_id · scope_id 는 **문자열**이다. 숫자로 보내면 Go 의 json.Unmarshal
이 조용히 실패한다.

nonce 는 항상 넣고 항상 유일하다. 읽기(download · tile)는 Go 가 소진을 빼기로
했지만 클레임 자체는 계속 필수이고, 나중에 소진을 다시 켤 때 양쪽을 안 고치게
하려는 것이다.

읽기에서 재사용 방어가 빠지므로 두 가지로 대신한다.
    object_key_prefix   검사 하나로 좁힌다. study/ 처럼 넓게 잡지 않는다.
    exp                 purpose 별로 다르다. download 는 1~2 분이다.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Report, Specimen, Study
from .errors import ApiError
from .permissions import (IsAuthenticatedAccount, NURSING, PATHOLOGY, PATIENT,
                          RADIOLOGY, SURGERY, rule_for)
from .trace import get_trace_id

logger = logging.getLogger(__name__)

# 어느 역할이 그 purpose 의 티켓을 낼 수 있나.
# 비어 있으면 사람은 못 낸다 — Celery 가 issue() 를 직접 부른다.
PURPOSE_ROLES = {
    "dicom_upload": frozenset({RADIOLOGY}),
    "wsi_upload": frozenset({PATHOLOGY}),
    "report_pdf": frozenset({SURGERY}),
    "derived_upload": frozenset(),                       # 시스템 전용
    "download": frozenset({RADIOLOGY, PATHOLOGY, SURGERY, NURSING, PATIENT}),
    "tile": frozenset({RADIOLOGY, PATHOLOGY, SURGERY}),
}

# purpose 가 붙을 수 있는 대상. 하나뿐이면 요청에 scope_kind 가 없어도 된다.
PURPOSE_SCOPES = {
    "dicom_upload": ("study",),
    "wsi_upload": ("specimen",),
    "report_pdf": ("report",),
    "derived_upload": ("study", "specimen"),
    "download": ("study", "specimen", "report"),
    "tile": ("study", "specimen"),
}

# 처방 표가 MVP 밖이라 티켓을 내줘도 파일이 갈 곳이 없다. 콜백도 422 로 막는다.
UNSUPPORTED_PURPOSES = frozenset({"prescription_pdf"})

SCOPE_MODEL = {"study": Study, "specimen": Specimen, "report": Report}
# 대상에 접근할 수 있는지는 §15 매트릭스로 본다.
SCOPE_RESOURCE = {"study": "study", "specimen": "specimen_pathology",
                  "report": "report"}


def object_key_prefix(scope_kind, scope_id):
    """검사 하나로 좁힌 접두사.

    Go 는 이 접두사 아래만 읽고 쓰게 한다 — 이게 권한 경계다. 넓게 잡으면
    (study/) 그 아래가 전부 열린다.
    경로에 환자번호를 넣지 않는다 (명세 19-1).
    """
    return "%s/%s" % (scope_kind, scope_id)


def issue(purpose, scope_kind, scope_id, patient_id=None, content_type=None,
          max_bytes=None):
    """서명된 티켓 하나. 권한은 보지 않는다 — 부르는 쪽이 이미 봤다.

    Celery 처럼 사람 토큰이 없는 곳에서도 이 함수를 직접 쓴다.
    """
    key = settings.TICKET_KEY
    if not key:
        logger.error("TICKET_KEY 가 비어 있다 — 티켓을 낼 수 없다")
        raise ApiError("INTERNAL_ERROR", "티켓 설정이 되어 있지 않습니다.")

    ttl = settings.TICKET_TTL_SEC[purpose]
    cap = settings.TICKET_MAX_BYTES.get(purpose, 0)
    if max_bytes:
        # 클라이언트는 더 작게만 요청할 수 있다. 크게 부르면 상한으로 자른다.
        max_bytes = min(int(max_bytes), cap) if cap else int(max_bytes)
    else:
        max_bytes = cap

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    claims = {
        "purpose": purpose,
        "patient_id": str(patient_id or ""),
        "scope_id": str(scope_id),
        "object_key_prefix": object_key_prefix(scope_kind, scope_id),
        "exp": int(expires_at.timestamp()),
        "nonce": uuid.uuid4().hex,
    }
    if max_bytes:
        claims["max_bytes"] = int(max_bytes)
    if content_type:
        claims["content_type"] = content_type

    token = jwt.encode(claims, key, algorithm="HS256")
    return token, claims, expires_at


class TicketView(APIView):
    """POST /api/v1/tickets

        {"purpose": "dicom_upload", "scope_id": 201}
        {"purpose": "tile", "scope_kind": "specimen", "scope_id": 801}
    """

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="issue_ticket",
        summary="전송 티켓 발급",
        description="Go 파일 계층에 낼 단기 티켓. 유효기간은 purpose 마다 다르다.",
        request={"application/json": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string", "enum": sorted(PURPOSE_SCOPES)},
                "scope_kind": {"type": "string", "enum": sorted(SCOPE_MODEL)},
                "scope_id": {"type": "integer"},
                "content_type": {"type": "string"},
                "max_bytes": {"type": "integer"},
            },
            "required": ["purpose", "scope_id"],
        }},
        responses={200: {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
                "expires_at": {"type": "string", "format": "date-time"},
                "object_key_prefix": {"type": "string"},
                "max_bytes": {"type": "integer"},
            },
        }},
    )
    def post(self, request):
        account = request.user
        purpose = request.data.get("purpose")
        scope_id = request.data.get("scope_id")

        if purpose in UNSUPPORTED_PURPOSES:
            logger.warning("[ticket] 아직 못 내주는 purpose=%s account=%s",
                           purpose, account.account_id)
            raise ApiError("UNSUPPORTED_PURPOSE", details={"purpose": purpose})
        if purpose not in PURPOSE_SCOPES:
            raise ApiError("VALIDATION_ERROR", "모르는 purpose 입니다.",
                           details={"purpose": purpose,
                                    "allowed": sorted(PURPOSE_SCOPES)})
        if not scope_id:
            raise ApiError("VALIDATION_ERROR", "필수 값이 없습니다.",
                           details={"missing": ["scope_id"]})

        if account.role not in PURPOSE_ROLES[purpose]:
            # derived_upload 는 아무 역할도 못 낸다 — Celery 가 issue() 를 직접 쓴다.
            raise ApiError("ROLE_FORBIDDEN",
                           details={"purpose": purpose, "role": account.role})

        scope_kind = self._scope_kind(purpose, request.data.get("scope_kind"))
        target = self._target(scope_kind, scope_id)
        self._may_touch(account, scope_kind, target)

        token, claims, expires_at = issue(
            purpose=purpose, scope_kind=scope_kind, scope_id=target.pk,
            patient_id=self._patient_id(target),
            content_type=request.data.get("content_type"),
            max_bytes=request.data.get("max_bytes"))

        # 발급 이력. 지금은 표를 만들지 않고 로그로 남긴다 — nonce 로 Go 로그와
        # 이어붙일 수 있다.
        logger.info("[ticket] 발급 trace=%s account=%s purpose=%s scope=%s/%s "
                    "nonce=%s exp=%s",
                    get_trace_id(), account.account_id, purpose, scope_kind,
                    target.pk, claims["nonce"], claims["exp"])

        return Response({
            "token": token,
            "expires_at": expires_at.isoformat(),
            "object_key_prefix": claims["object_key_prefix"],
            "max_bytes": claims.get("max_bytes"),
            "purpose": purpose,
            "scope_kind": scope_kind,
            "scope_id": str(target.pk),
        })

    @staticmethod
    def _scope_kind(purpose, given):
        allowed = PURPOSE_SCOPES[purpose]
        if len(allowed) == 1:
            return allowed[0]           # 요청이 뭘 보내든 purpose 가 정한다
        if given not in allowed:
            raise ApiError("VALIDATION_ERROR", "scope_kind 를 정해야 합니다.",
                           details={"scope_kind": given, "allowed": list(allowed)})
        return given

    @staticmethod
    def _target(scope_kind, scope_id):
        model = SCOPE_MODEL[scope_kind]
        try:
            return model.objects.get(pk=int(scope_id))
        except (model.DoesNotExist, TypeError, ValueError):
            raise ApiError("TARGET_NOT_FOUND",
                           details={"target": scope_kind, "id": scope_id}) from None

    @staticmethod
    def _patient_id(target):
        return getattr(target, "patient_id", None)

    @staticmethod
    def _may_touch(account, scope_kind, target):
        """그 대상을 볼 수 있는 사람인가 — §15 매트릭스 R + 환자는 본인 것만.

        역할만 보면 「영상의학이면 아무 검사에나 티켓을 낸다」가 된다.
        """
        rule = rule_for(SCOPE_RESOURCE[scope_kind], account.role)
        if not rule.allows("R"):
            raise ApiError("ROLE_FORBIDDEN",
                           details={"resource": SCOPE_RESOURCE[scope_kind]})
        if rule.own_only and getattr(target, "patient", None) is not None:
            if target.patient.account_id != account.account_id:
                raise ApiError("ROLE_FORBIDDEN", details={"reason": "본인 것이 아님"})
