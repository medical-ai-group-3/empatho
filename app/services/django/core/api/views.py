"""GET /api/v1/health — 살아 있는지와 DB 가 붙는지.

명세에 없는 경로다. 봉투가 실제로 씌워지는지 확인할 자리가 필요하고 컨테이너
헬스체크에도 쓴다. 팀에 알린 뒤 넣었다 (09-09).

배포 판(버전)은 내보내지 않는다 — 인증 없이 열려 있어서 밖에서 어느 판이 떠
있는지 알면 취약점 탐색의 단서가 된다.

상태 코드는 항상 200 이다. DB 가 죽어도 500 · 503 을 내지 않는다 — 명세 §1-4 의
에러 코드 25 개에 「DB 가 죽었다」가 없고, 이 하나 때문에 카탈로그를 늘리고 싶지
않아서다. API 자신은 응답했으니 success 는 true 이고, DB 상태는 에러가 아니라
data 로 알린다.

    docker healthcheck 예 —
      test: ["CMD-SHELL", "curl -fsS localhost:8000/api/v1/health | grep -q '\"status\": \"ok\"'"]

상태 코드로 판정해야 하면 카탈로그에 코드를 하나 더 넣는 결정이 먼저다.
"""

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import ApiError
from .auth import decode, issue_access, issue_pair, REFRESH, TokenError

def _db_state():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return "error"
    return "ok"


class HealthView(APIView):
    """{status, db}. 인증 없이 연다 — 헬스체크는 자격증명을 들고 오지 않는다."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="health",
        summary="상태 확인",
        description="DB 가 죽어도 200 이다. 판정은 status 로 한다.",
        responses={200: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["ok", "degraded"]},
                "db": {"type": "string", "enum": ["ok", "error"]},
            },
            "required": ["status", "db"],
        }},
    )
    def get(self, request):
        db = _db_state()
        return Response({"status": "ok" if db == "ok" else "degraded", "db": db})


class NotFoundView(APIView):
    """/api/v1 아래에서 어느 경로에도 안 걸린 요청.

    Django 의 리졸버 404 는 HTML 이라 클라이언트가 봉투와 HTML 두 갈래를 처리해야
    한다. 여기로 떨어뜨려 NOT_FOUND 봉투로 돌린다.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def _not_found(self, request, *args, **kwargs):
        raise ApiError("NOT_FOUND")

    get = post = put = patch = delete = head = options = _not_found



from rest_framework.decorators import api_view, permission_classes
from django.contrib.auth.hashers import check_password, make_password

from ..models import Account, Staff
from .auth import issue_pair

# 직원 가입에서 만들 수 있는 role. admin · patient 는 이 경로로 못 만든다 —
# admin 은 운영자가 직접 부여하고, patient 는 signup_patient 가 따로 맡는다.
STAFF_SIGNUP_ROLES = {"reception", "nursing", "radiology", "surgery", "pathology"}


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    login_id = request.data.get("login_id")
    password = request.data.get("password")

    if not login_id or not password:
        raise ApiError("VALIDATION_ERROR", "login_id · password 가 필요합니다.")

    try:
        account = Account.objects.get(login_id=login_id)
    except Account.DoesNotExist:
        raise ApiError("UNAUTHENTICATED", "아이디 또는 비밀번호가 올바르지 않습니다.")

    if not account.password_hash or not check_password(password, account.password_hash):
        raise ApiError("UNAUTHENTICATED", "아이디 또는 비밀번호가 올바르지 않습니다.")

    # 비밀번호가 맞은 뒤에만 pending 을 알린다 — 비밀번호를 모르는 사람이
    # login_id 만으로 승인 대기 여부를 캐낼 수 있으면 계정 존재가 샌다.
    if account.account_status == "pending":
        raise ApiError("UNAUTHENTICATED", "관리자 승인 대기 중입니다.")

    if not account.is_active:
        raise ApiError("UNAUTHENTICATED", "아이디 또는 비밀번호가 올바르지 않습니다.")

    tokens = issue_pair(account)
    # refresh 를 쿠키와 **본문 둘 다**로 준다.
    #   웹(https)은 지금처럼 httponly 쿠키를 쓴다 — 스크립트가 못 읽는 쪽이 안전하다.
    #   앱(Capacitor/에뮬레이터)은 http·다른 출처라 브라우저가 Secure 쿠키를 버린다.
    #   그래서 앱은 본문으로 받아 저장했다가 재발급 때 실어 보낸다 — 이게 없으면
    #   액세스(30분)가 끝나는 순간 쓰던 중에 로그아웃된다.
    response = Response({"access": tokens["access"], "refresh": tokens["refresh"]})
    response.set_cookie(
        "refresh_token",
        tokens["refresh"],
        httponly=True,
        secure=True,
        samesite="None",
        max_age=60 * 60 * 24 * 14,
    )
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_staff(request):
    login_id = request.data.get("login_id")
    password = request.data.get("password")
    role = request.data.get("role")
    full_name = request.data.get("full_name")
    staff_number = request.data.get("staff_number")

    if not login_id or not password or not role or not full_name or not staff_number:
        raise ApiError(
            "VALIDATION_ERROR",
            "login_id · password · role · full_name · staff_number 가 필요합니다.",
        )

    if role not in STAFF_SIGNUP_ROLES:
        raise ApiError(
            "VALIDATION_ERROR",
            "role 은 reception · nursing · radiology · surgery · pathology 중 하나여야 합니다.",
        )

    if Account.objects.filter(login_id=login_id).exists():
        raise ApiError("VALIDATION_ERROR", "이미 사용 중인 아이디입니다.")

    if Staff.objects.filter(staff_number=staff_number).exists():
        raise ApiError("VALIDATION_ERROR", "이미 등록된 사번입니다.")

    account = Account.objects.create(
        login_id=login_id,
        password_hash=make_password(password),
        role=role,
        account_status="pending",
        is_active=False,
    )
    Staff.objects.create(account=account, full_name=full_name, staff_number=staff_number)

    return Response(
        {"message": "가입 신청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다."},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_patient(request):
    login_id = request.data.get("login_id")
    password = request.data.get("password")

    if not login_id or not password:
        raise ApiError("VALIDATION_ERROR", "login_id · password 가 필요합니다.")

    if Account.objects.filter(login_id=login_id).exists():
        raise ApiError("VALIDATION_ERROR", "이미 사용 중인 아이디입니다.")

    account = Account.objects.create(
        login_id=login_id,
        password_hash=make_password(password),
        role="patient",
        account_status="active",
        is_active=True,
    )

    tokens = issue_pair(account)
    response = Response({"access": tokens["access"]}, status=status.HTTP_201_CREATED)
    response.set_cookie(
        "refresh_token",
        tokens["refresh"],
        httponly=True,
        secure=True,
        samesite="None",
        max_age=60 * 60 * 24 * 14,
    )
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token(request):
    # 쿠키가 먼저다(웹). 앱은 Secure 쿠키가 안 실려서 본문으로 보낸다 —
    # 토큰 자체를 검증하므로 어느 길로 왔는지는 안전에 영향이 없다.
    refresh = (request.COOKIES.get("refresh_token")
               or (request.data or {}).get("refresh"))
    if not refresh:
        raise ApiError("UNAUTHENTICATED", "refresh 토큰이 없습니다.")

    try:
        payload = decode(refresh, expected_type=REFRESH)
    except TokenError:
        raise ApiError("UNAUTHENTICATED", "refresh 토큰이 유효하지 않습니다.")

    try:
        account = Account.objects.get(pk=int(payload["sub"]), is_active=True)
    except Account.DoesNotExist:
        raise ApiError("UNAUTHENTICATED", "계정을 찾을 수 없습니다.")

    return Response({"access": issue_access(account)})

@api_view(["POST"])
@permission_classes([AllowAny])
def logout(request):
    response = Response({"success": True})
    response.delete_cookie("refresh_token")
    return response