"""앱 환자 가입 — 본인인증(포트원 · KG이니시스 통합인증) → 아이디 정하기.

  POST /signup/identity   인증 결과를 포트원에 직접 물어 확인한다
  GET  /signup/check-id   아이디 중복 확인
  POST /signup/link       계정을 만들고 환자에 잇는다

⚠ 앱이 보내는 「인증 성공」은 믿지 않는다. 포트원 API 로 다시 묻는다.
⚠ 입력값과 인증 결과가 하나라도 다르면 거절한다 — 조용히 인증값으로 바꾸면
  잘못 넣은 줄 모른 채 가입이 끝난다.
⚠ 이름+생년월일+휴대폰이 모두 같을 때만 기존 환자로 본다. 동명이인을 가를
  칸(주소 등)이 없어 번호가 바뀐 기존 환자는 두 번 등록된다. 알고 둔 것이다.
⚠ 환자는 link 에서만 만든다. identity 에서 만들면 중간에 그만둔 사람이 남는다.
"""
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core import signing
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core import models
from core.serializers import PatientRegisterSerializer
from .auth import issue_pair
from .errors import ApiError

logger = logging.getLogger(__name__)

SALT = "signup-identity"
TOKEN_AGE_SEC = 10 * 60
LOGIN_ID = re.compile(r"^[A-Za-z0-9]{4,50}$")
SEX = ("female", "male")
# ⚠ 임시로 False — signup_identity 의 「임시」 주석 참고. 운영 전에 True 로.
MATCH_CHECK = False


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _fetch(ivid):
    """포트원 본인인증 단건 조회."""
    if not settings.PORTONE_API_SECRET:
        logger.error("[signup] PORTONE_API_SECRET 이 비어 있다")
        raise ApiError("UPSTREAM_IDENTITY_UNAVAILABLE")
    url = "%s/identity-verifications/%s" % (
        settings.PORTONE_API_BASE.rstrip("/"), urllib.parse.quote(ivid, safe=""))
    req = urllib.request.Request(
        url, headers={"Authorization": "PortOne " + settings.PORTONE_API_SECRET})
    try:
        with urllib.request.urlopen(req, timeout=settings.PORTONE_TIMEOUT_SEC) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ApiError("VALIDATION_ERROR", "본인인증 내역을 찾을 수 없습니다.")
        logger.error("[signup] 포트원 조회 실패 HTTP %s", e.code)
        raise ApiError("UPSTREAM_IDENTITY_UNAVAILABLE")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        logger.error("[signup] 포트원에 못 닿았다: %s", e)
        raise ApiError("UPSTREAM_IDENTITY_UNAVAILABLE")


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_identity(request):
    d = request.data
    ivid = d.get("identity_verification_id")
    typed = {
        "name": (d.get("name") or "").strip(),
        "birth_date": d.get("birth_date") or "",
        "sex": d.get("sex"),
        "phone": _digits(d.get("phone")),
    }
    try:
        date.fromisoformat(typed["birth_date"])
    except ValueError:
        raise ApiError("VALIDATION_ERROR", "생년월일 형식이 올바르지 않습니다.")
    if not (ivid and typed["name"] and typed["phone"] and typed["sex"] in SEX):
        raise ApiError("VALIDATION_ERROR", "이름 · 생년월일 · 성별 · 휴대폰이 필요합니다.")

    iv = _fetch(ivid)
    if iv.get("status") != "VERIFIED":
        raise ApiError("VALIDATION_ERROR", "본인인증이 끝나지 않았습니다.")
    who = iv.get("verifiedCustomer") or {}
    got = {
        "name": (who.get("name") or "").strip(),
        "birth_date": who.get("birthDate") or "",
        "sex": (who.get("gender") or "").lower(),
        "phone": _digits(who.get("phoneNumber")),
    }
    # ⚠ 임시(2026-09-27) — 입력값을 인증 결과와 대조하지 않는다. 인증에만
    #   성공하면 통과하고 **입력한 값**을 저장한다. 테스트 환자를 아무 값으로
    #   여럿 만들고, 인증만 본인 폰으로 하려고 풀었다.
    #   되돌릴 때는 MATCH_CHECK 를 True 로 — 그러면 넷 다 대조하고 인증된
    #   값을 저장한다. 푼 동안 번호가 인증과 다르면 phone_verified 는 False.
    if MATCH_CHECK:
        wrong = [k for k in typed if typed[k] != got[k]]
        if wrong:
            raise ApiError("VALIDATION_ERROR",
                           "입력하신 정보가 본인인증 결과와 다릅니다. 다시 입력해 주세요.",
                           details={"fields": wrong})
    who = {**typed, "phone_verified": typed["phone"] == got["phone"]}

    # 아이디를 궁리하기 전에 알려 준다. link 에서도 다시 막는다.
    if models.Patient.objects.filter(
            pii__name=who["name"], pii__birth_date=who["birth_date"],
            pii__phone=who["phone"], account__isnull=False).exists():
        raise ApiError("VALIDATION_ERROR", "이미 가입된 분입니다. 로그인해 주세요.")

    return Response({"verify_token": signing.dumps(who, salt=SALT),
                     "detail": "본인 확인이 끝났습니다"})


@api_view(["GET"])
@permission_classes([AllowAny])
def signup_check_id(request):
    v = request.query_params.get("value") or ""
    if not LOGIN_ID.match(v):
        raise ApiError("VALIDATION_ERROR", "아이디는 영문 · 숫자 4자 이상입니다.")
    free = not models.Account.objects.filter(login_id=v).exists()
    return Response({"available": free,
                     "detail": "쓸 수 있는 아이디입니다" if free else "이미 쓰이고 있는 아이디입니다"})


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_link(request):
    d = request.data
    try:
        who = signing.loads(d.get("verify_token") or "", salt=SALT, max_age=TOKEN_AGE_SEC)
    except signing.BadSignature:          # 만료(SignatureExpired)도 여기로 온다
        raise ApiError("VALIDATION_ERROR", "본인인증이 만료됐습니다. 처음부터 다시 해 주세요.")
    login_id = d.get("username") or ""
    password = d.get("password") or ""
    if not LOGIN_ID.match(login_id) or len(password) < 8:
        raise ApiError("VALIDATION_ERROR", "아이디는 영문 · 숫자 4자 이상, 비밀번호는 8자 이상입니다.")

    with transaction.atomic():
        if models.Account.objects.filter(login_id=login_id).exists():
            raise ApiError("VALIDATION_ERROR", "이미 사용 중인 아이디입니다.")
        # ⚠ 대조를 끈 동안(MATCH_CHECK=False)은 기존 환자에 잇지 않는다.
        #   입력값이 인증과 무관하니, 잇게 두면 본인 폰으로 인증만 하고 남의
        #   이름 · 생년월일 · 번호를 넣어 그 사람 진료 기록에 들어갈 수 있다.
        #   새 환자만 만든다(번호가 겹치면 아래 시리얼라이저가 막는다).
        if not MATCH_CHECK and models.PatientPii.objects.filter(
                name=who["name"], birth_date=who["birth_date"], phone=who["phone"]).exists():
            raise ApiError("VALIDATION_ERROR",
                           "지금은 기존 환자 기록에 연결할 수 없습니다. 병원에 문의해 주세요.")
        s = PatientRegisterSerializer(data={k: who[k] for k in ("name", "birth_date", "phone")})
        s.is_valid(raise_exception=True)
        # 가입 단추를 두 번 눌러도 계정이 둘 생기지 않게 잠근다
        patient = models.Patient.objects.select_for_update().get(pk=s.save().pk)
        if patient.account_id:
            raise ApiError("VALIDATION_ERROR", "이미 가입된 분입니다. 로그인해 주세요.")
        account = models.Account.objects.create(
            login_id=login_id, password_hash=make_password(password),
            role="patient", account_status="active", is_active=True,
            phone_verified=who.get("phone_verified", True))
        patient.account = account
        patient.sex = who["sex"]
        patient.birth_year = int(who["birth_date"][:4])
        patient.save(update_fields=["account", "sex", "birth_year"])

    # 로그인과 같은 모양 — 앱은 refresh 를 본문에서, 웹은 쿠키에서 쓴다
    tokens = issue_pair(account)
    res = Response({"access": tokens["access"], "refresh": tokens["refresh"]}, status=201)
    res.set_cookie("refresh_token", tokens["refresh"], httponly=True, secure=True,
                   samesite="None", max_age=60 * 60 * 24 * 14)
    return res
