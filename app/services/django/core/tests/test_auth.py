# -*- coding: utf-8 -*-
"""JWT 발급 · 검증과 account 기준 인증."""

from unittest import mock

import jwt
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import auth
from core.api.errors import ApiError
from core.models import Account


class _Who(APIView):
    """인증만 통과하면 되는 뷰. request.user 가 무엇인지 되돌려 준다."""

    def get(self, request):
        return Response({"account_id": request.user.account_id,
                         "role": request.user.role,
                         "scope": request.auth["scope"]})


urlpatterns = [path("who", _Who.as_view())]


def _account(role="radiology", **kwargs):
    return Account.objects.create(login_id=kwargs.pop("login_id", "u_" + role),
                                  role=role, is_active=True, **kwargs)


class TokenTests(TestCase):
    def test_스코프는_role_에서_유도된다(self):
        self.assertEqual(auth.scope_for("patient"), auth.SCOPE_PATIENT)
        for role in ("admin", "reception", "nursing", "radiology", "surgery", "pathology"):
            self.assertEqual(auth.scope_for(role), auth.SCOPE_STAFF, role)

    def test_발급한_토큰이_풀린다(self):
        account = _account()
        payload = auth.decode(auth.issue_access(account))
        self.assertEqual(payload["sub"], str(account.account_id))
        self.assertEqual(payload["role"], "radiology")
        self.assertEqual(payload["scope"], auth.SCOPE_STAFF)
        self.assertEqual(payload["typ"], auth.ACCESS)

    def test_refresh_로는_API_를_못_부른다(self):
        token = auth.issue_refresh(_account())
        with self.assertRaises(auth.TokenError):
            auth.decode(token, expected_type=auth.ACCESS)
        # refresh 로는 풀린다
        self.assertEqual(auth.decode(token, expected_type=auth.REFRESH)["typ"], "refresh")

    def test_만료된_토큰은_거부된다(self):
        account = _account()
        with override_settings(JWT={**self.settings_jwt(), "ACCESS_TTL_MIN": -1}):
            token = auth.issue_access(account)
        with self.assertRaises(auth.TokenError):
            auth.decode(token)

    def test_서명이_다르면_거부된다(self):
        token = auth.issue_access(_account())
        other = "다른-비밀" * 8      # HMAC-SHA256 권장 길이(32바이트) 이상
        with override_settings(JWT={**self.settings_jwt(), "SECRET": other}):
            with self.assertRaises(auth.TokenError):
                auth.decode(token)

    def test_발급자가_다르면_거부된다(self):
        with override_settings(JWT={**self.settings_jwt(), "ISSUER": "남의-서버"}):
            token = auth.issue_access(_account())
        with self.assertRaises(auth.TokenError):
            auth.decode(token)

    def test_알고리즘_none_공격을_막는다(self):
        cfg = self.settings_jwt()
        forged = jwt.encode({"sub": "1", "typ": "access", "iss": cfg["ISSUER"],
                             "iat": 0, "exp": 9999999999}, key="", algorithm="none")
        with self.assertRaises(auth.TokenError):
            auth.decode(forged)

    @staticmethod
    def settings_jwt():
        from django.conf import settings
        return dict(settings.JWT)


@override_settings(ROOT_URLCONF=__name__)
class AuthenticationTests(TestCase):
    def _get(self, token=None):
        headers = {"authorization": "Bearer " + token} if token else {}
        return self.client.get("/who", headers=headers)

    def test_유효한_토큰이면_request_user_가_Account_다(self):
        account = _account(role="surgery")
        body = self._get(auth.issue_access(account)).json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["account_id"], account.account_id)
        self.assertEqual(body["data"]["scope"], auth.SCOPE_STAFF)

    def test_환자_토큰은_스코프가_다르다(self):
        account = _account(role="patient", login_id="p1")
        body = self._get(auth.issue_access(account)).json()
        self.assertEqual(body["data"]["scope"], auth.SCOPE_PATIENT)

    def test_토큰이_없으면_401_UNAUTHENTICATED(self):
        response = self._get()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHENTICATED")

    def test_망가진_토큰도_401(self):
        response = self._get("not.a.real.token")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHENTICATED")

    def test_비활성_계정은_막힌다(self):
        account = _account(login_id="gone")
        token = auth.issue_access(account)
        Account.objects.filter(pk=account.pk).update(is_active=False)
        self.assertEqual(self._get(token).status_code, 401)

    def test_is_active_가_NULL_이면_활성으로_보지_않는다(self):
        account = _account(login_id="nullish")
        token = auth.issue_access(account)
        Account.objects.filter(pk=account.pk).update(is_active=None)
        self.assertEqual(self._get(token).status_code, 401)

    def test_역할이_바뀌면_옛_토큰은_못_쓴다(self):
        account = _account(role="reception", login_id="promoted")
        token = auth.issue_access(account)
        Account.objects.filter(pk=account.pk).update(role="admin")
        self.assertEqual(self._get(token).status_code, 401)

    def test_없는_계정을_가리키면_401(self):
        account = _account(login_id="deleted")
        token = auth.issue_access(account)
        Account.objects.filter(pk=account.pk).delete()
        self.assertEqual(self._get(token).status_code, 401)


class AuthHeaderTests(SimpleTestCase):
    """헤더 파싱만 본다. DRF 는 request.headers 에서 읽는다."""

    @staticmethod
    def _request(authorization=None):
        headers = {"authorization": authorization} if authorization is not None else {}
        return mock.Mock(headers=headers)

    def test_Bearer_가_아니면_인증을_시도하지_않는다(self):
        self.assertIsNone(
            auth.AccountJWTAuthentication().authenticate(self._request(b"Basic abc")))

    def test_헤더가_비면_인증을_시도하지_않는다(self):
        self.assertIsNone(auth.AccountJWTAuthentication().authenticate(self._request()))

    def test_Bearer_인데_조각이_모자라면_401(self):
        with self.assertRaises(ApiError) as caught:
            auth.AccountJWTAuthentication().authenticate(self._request(b"Bearer"))
        self.assertEqual(caught.exception.code, "UNAUTHENTICATED")

    def test_조각이_많아도_401(self):
        with self.assertRaises(ApiError) as caught:
            auth.AccountJWTAuthentication().authenticate(self._request(b"Bearer a b"))
        self.assertEqual(caught.exception.code, "UNAUTHENTICATED")
