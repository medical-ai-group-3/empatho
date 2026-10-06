"""JWT 발급 · 검증과 인증 — account 기준.

Django 의 auth_user 가 아니라 core.Account 를 주체로 삼는다. 인증을 통과하면
request.user 가 Account 인스턴스다. admin 은 계속 auth_user 를 쓴다 — 09-08
감사 컬럼 결정 (a)와 같은 구조다. 그래서 admin 으로 넣은 행은 created_by 가
NULL 이고 API 로 넣은 행만 채워진다.

djangorestframework-simplejwt 를 쓰지 않는 이유
    ① 그쪽은 AUTH_USER_MODEL 을 전제로 돈다. 우리 주체는 Account 다.
    ② 로그아웃(블랙리스트)이 DB 테이블을 새로 만든다. 매핑표 2.4 는
       「토큰 저장소(Redis) — DB 미사용」이라 18 개로 잠근 스키마에 표가 붙으면 안 된다.

이번 판은 발급과 검증까지다. 재발급(2.4)과 로그아웃(2.5)은 Redis 가 들어올 때
붙인다 — refresh 를 어디에 두는지가 정해져야 폐기가 성립한다.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from ..models import Account
from .errors import ApiError
from .permissions import PATIENT, extra_depts_of

ACCESS = "access"
REFRESH = "refresh"

SCOPE_PATIENT = "patient"
SCOPE_STAFF = "staff"

KEYWORD = "Bearer"


class TokenError(Exception):
    """토큰이 유효하지 않다. 인증 계층이 UNAUTHENTICATED 로 바꾼다."""


# ── 발급 · 검증 ──────────────────────────────────────────────────────────
def scope_for(role):
    """명세 §1-1 — 직원 토큰과 환자 토큰의 스코프를 절대 섞지 않는다.

    role 에서 유도하므로 발급하는 쪽이 임의로 정할 수 없다.
    """
    return SCOPE_PATIENT if role == PATIENT else SCOPE_STAFF


def _cfg():
    return settings.JWT


def _encode(account, token_type, lifetime):
    now = datetime.now(timezone.utc)
    cfg = _cfg()
    payload = {
        "sub": str(account.account_id),
        "typ": token_type,
        "scope": scope_for(account.role),
        "role": account.role,
        # 발급 당시의 추가 과. role 과 같은 이유로 싣는다 — 권한 판정이
        # 이 값으로도 돌기 때문에, 관리자가 과를 빼도 옛 토큰이 계속 쓰이면
        # 뺀 과가 그대로 열린다. 아래 _account_for 가 매 요청 견준다.
        "depts": extra_depts_of(account),
        "iss": cfg["ISSUER"],
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, cfg["SECRET"], algorithm=cfg["ALGORITHM"])


def issue_access(account):
    return _encode(account, ACCESS, timedelta(minutes=_cfg()["ACCESS_TTL_MIN"]))


def issue_refresh(account):
    return _encode(account, REFRESH, timedelta(days=_cfg()["REFRESH_TTL_DAYS"]))


def issue_pair(account):
    return {"access": issue_access(account), "refresh": issue_refresh(account)}


def decode(token, expected_type=ACCESS):
    """검증 후 payload. 어긋나면 TokenError.

    종류를 검증하는 이유 — refresh 로 API 를 호출할 수 있으면 유효기간 14 일짜리
    액세스 토큰을 준 것과 같다.
    """
    cfg = _cfg()
    try:
        payload = jwt.decode(
            token,
            cfg["SECRET"],
            algorithms=[cfg["ALGORITHM"]],
            issuer=cfg["ISSUER"],
            options={"require": ["exp", "iat", "sub", "typ", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("토큰이 만료되었다") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("토큰이 유효하지 않다") from exc

    if payload.get("typ") != expected_type:
        raise TokenError("토큰 종류가 %r 이 아니다" % expected_type)
    return payload


# ── 인증 ─────────────────────────────────────────────────────────────────
class AccountJWTAuthentication(BaseAuthentication):
    """Authorization: Bearer {access_token} 를 읽어 Account 를 붙인다.

    헤더가 아예 없으면 인증을 시도하지 않는다(None). 그래야 AllowAny 인
    엔드포인트가 익명으로도 열린다. 헤더가 있는데 틀린 경우에만 401 이다.
    """

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != KEYWORD.lower().encode():
            return None
        if len(header) != 2:
            raise ApiError("UNAUTHENTICATED", "Authorization 헤더 형식이 올바르지 않습니다.")

        try:
            token = header[1].decode()
        except UnicodeError:
            raise ApiError("UNAUTHENTICATED", "토큰을 읽을 수 없습니다.") from None

        try:
            payload = decode(token, expected_type=ACCESS)
        except TokenError:
            raise ApiError("UNAUTHENTICATED") from None

        return self._account_for(payload), payload

    def _account_for(self, payload):
        try:
            # staff 를 같이 읽는다 — 권한 판정이 staff.extra_permissions 를 본다.
            account = Account.objects.select_related("staff").get(pk=int(payload["sub"]))
        except (Account.DoesNotExist, KeyError, TypeError, ValueError):
            raise ApiError("UNAUTHENTICATED") from None

        # is_active 는 nullable 이다. NULL 을 활성으로 보지 않는다.
        if account.is_active is not True:
            raise ApiError("UNAUTHENTICATED", "사용할 수 없는 계정입니다.")

        # 토큰 발급 뒤에 역할이 바뀌었으면 그 토큰은 더 못 쓴다 — 권한 판정이
        # 전부 role 로 도는데 토큰 안의 role 이 낡으면 뚫린다.
        if payload.get("role") != account.role:
            raise ApiError("UNAUTHENTICATED", "권한이 변경되었습니다. 다시 로그인해야 합니다.")

        # 추가 과도 같다 — role 과 같은 무게의 값이다.
        #
        # ⚠ 클레임이 **없는** 옛 토큰은 「추가 과 없음」으로 읽는다. 없는 것을
        #   불일치로 보면 이 판을 올리는 순간 모두가 튕긴다. 추가 과가 실제로
        #   있는 사람만 다시 로그인하면 된다.
        if list(payload.get("depts") or []) != extra_depts_of(account):
            raise ApiError("UNAUTHENTICATED", "권한이 변경되었습니다. 다시 로그인해야 합니다.")

        return account

    def authenticate_header(self, request):
        return KEYWORD
