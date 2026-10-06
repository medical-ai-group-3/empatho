"""POST /api/v1/admin-session — 우리 로그인으로 Django admin 세션을 받는다.

관리자가 로그인을 두 번 하지 않게 하는 자리다.

    프론트 로그인 (account · JWT)  →  [관리자 화면 열기]
                                        │
                                        ├─ 여기서 role 을 확인하고
                                        └─ auth_user 세션을 심어 준다
                                             │
                                             └─ /admin/ 이 열린다

── 왜 이런 다리가 필요한가 ────────────────────────────────────────────
Django admin 의 인증 주체는 auth_user 이고, 우리 API 의 주체는 core.Account 다
(core/api/auth.py). 둘이 다른 표라서 admin 계정으로 로그인해도 /admin/ 은
그 사람을 모른다. 그렇다고 AUTH_USER_MODEL 을 Account 로 바꾸면 18 개로 잠근
스키마에 admin 이 요구하는 칸들이 붙는다.

그래서 **권한 판정은 우리 쪽에서 하고, 세션만 admin 것으로 발급한다.**

⚠ auth_user 는 settings.ADMIN_AUTH_USER 하나뿐이다. 관리자가 여럿이어도 같이
  쓴다. 그래서 **admin 의 변경 이력(LogEntry)으로는 누가 고쳤는지 못 가린다** —
  동시에 둘이 들어와 있으면 둘 다 cdss_admin 으로 남는다. 승인 이력만은
  staff.approved_by 로 따로 남아서 가려진다.
  대신 「누가 언제 관리자로 들어왔나」는 아래 로그가 남긴다.

⚠ cdss_admin 의 비밀번호는 아무도 몰라도 된다. 이 경로를 거쳐야만 세션이
  생기므로 /admin/ 에 직접 들어가는 길이 막힌다. 다만 superuser 하나는 따로
  둬야 한다 — API 가 안 돌 때 들어갈 길이다.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login as django_login
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import ApiError
from .permissions import ADMIN, IsAuthenticatedAccount
from .trace import get_trace_id

logger = logging.getLogger(__name__)


class AdminSessionView(APIView):
    """우리 로그인을 admin 세션으로 바꿔 준다. role='admin' 만."""

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="admin_session",
        summary="Django admin 세션 발급",
        description=(
            "role 이 admin 인 계정에게 Django admin 세션 쿠키를 심는다. "
            "성공하면 /admin/ 을 새 탭으로 열면 된다."
        ),
        request=None,
        responses={200: {
            "type": "object",
            "properties": {"admin_url": {"type": "string"}},
            "required": ["admin_url"],
        }},
    )
    def post(self, request):
        account = request.user

        # ① 우리 권한으로 막는다. admin 은 §15 매트릭스에 없는 역할이라
        #    MatrixPermission 이 아니라 여기서 직접 본다.
        if account.role != ADMIN:
            raise ApiError("ROLE_FORBIDDEN", "관리자만 열 수 있습니다.")

        # ② 세션을 심을 auth_user 를 찾는다. 없으면 만들지 않는다 —
        #    여기서 만들면 그 사용자의 권한을 코드가 정하게 되는데, admin
        #    권한은 사람이 /admin/ 에서 정해야 할 값이다.
        user_model = get_user_model()
        name = settings.ADMIN_AUTH_USER
        try:
            user = user_model.objects.get(**{user_model.USERNAME_FIELD: name})
        except user_model.DoesNotExist:
            logger.error(
                "admin-session: auth_user %r 가 없다 — "
                "createsuperuser 로 만들어야 한다", name)
            raise ApiError(
                "INTERNAL_ERROR",
                "관리자 계정이 준비되지 않았습니다. 서버 담당자에게 문의하세요.",
            ) from None

        if not user.is_active or not user.is_staff:
            logger.error("admin-session: auth_user %r 가 admin 에 못 들어간다 "
                         "(is_active=%s is_staff=%s)",
                         name, user.is_active, user.is_staff)
            raise ApiError(
                "INTERNAL_ERROR",
                "관리자 계정이 준비되지 않았습니다. 서버 담당자에게 문의하세요.",
            )

        # ③ 세션 발급. backend 를 명시하는 이유 — 우리는 authenticate() 를
        #    거치지 않고 바로 로그인시키므로 Django 가 어느 백엔드로 인증됐는지
        #    모른다. 안 주면 ValueError 가 난다.
        django_login(request, user,
                     backend="django.contrib.auth.backends.ModelBackend")

        # ④ 「누가 언제 관리자로 들어왔나」. LogEntry 가 못 가리는 것을
        #    여기서 남긴다. trace_id 로 이 요청의 다른 로그와 이어진다.
        logger.info(
            "admin-session 발급 trace_id=%s account_id=%s login_id=%s "
            "role=%s auth_user=%s",
            get_trace_id(), account.account_id, account.login_id,
            account.role, name,
        )

        return Response({"admin_url": "/admin/"})
