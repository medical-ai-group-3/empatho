# -*- coding: utf-8 -*-
"""POST /api/v1/admin-session — 우리 로그인을 Django admin 세션으로 바꾼다."""

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase, override_settings

from core.api import auth
from core.models import Account

URL = "/api/v1/admin-session"
ADMIN_USER = "cdss_admin"


def _account(role, login_id=None, is_active=True):
    return Account.objects.create(login_id=login_id or ("u_" + role),
                                  role=role, is_active=is_active)


def _auth_user(name=ADMIN_USER, **kwargs):
    model = get_user_model()
    return model.objects.create_user(
        username=name, password="x",
        is_staff=kwargs.pop("is_staff", True),
        is_active=kwargs.pop("is_active", True),
        **kwargs)


@override_settings(ADMIN_AUTH_USER=ADMIN_USER)
class AdminSessionTests(TestCase):
    def _post(self, account):
        token = auth.issue_access(account)
        return self.client.post(URL, HTTP_AUTHORIZATION="Bearer " + token)

    # ── 되는 길 ─────────────────────────────────────────────────
    def test_admin_이면_세션이_생긴다(self):
        user = _auth_user()
        res = self._post(_account("admin"))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["admin_url"], "/admin/")
        # 진짜로 세션이 심겼나 — 쿠키만 보고 넘어가면 빈 세션도 통과한다
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.pk)

    def test_세션이_생기면_admin_이_열린다(self):
        """이 엔드포인트의 목적이 그것이다. 세션만 만들고 admin 이 안 열리면 소용없다."""
        _auth_user()
        self._post(_account("admin"))

        res = self.client.get("/admin/", follow=False)
        # 로그인 화면으로 튕기지 않는다
        self.assertEqual(res.status_code, 200)

    # ── 막는 길 ─────────────────────────────────────────────────
    def test_admin_이_아니면_403(self):
        _auth_user()
        for role in ("reception", "nursing", "radiology", "pathology",
                     "surgery", "patient"):
            with self.subTest(role=role):
                res = self._post(_account(role, login_id="u_" + role))
                self.assertEqual(res.status_code, 403)
                self.assertEqual(res.json()["error"]["code"], "ROLE_FORBIDDEN")
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_토큰_없으면_401(self):
        _auth_user()
        res = self.client.post(URL)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"]["code"], "UNAUTHENTICATED")

    # ── auth_user 쪽이 준비 안 됐을 때 ───────────────────────────
    def test_auth_user_가_없으면_500_이고_세션은_안_생긴다(self):
        res = self._post(_account("admin"))
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_is_staff_가_아니면_막는다(self):
        """admin 에 못 들어가는 사용자로 세션을 만들면 /admin/ 이 로그인 화면을 준다.
        그 상태는 「열렸다」고 200 을 준 것과 어긋나므로 여기서 막는다."""
        _auth_user(is_staff=False)
        res = self._post(_account("admin"))
        self.assertEqual(res.status_code, 500)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_꺼진_auth_user_면_막는다(self):
        _auth_user(is_active=False)
        res = self._post(_account("admin"))
        self.assertEqual(res.status_code, 500)
        self.assertNotIn(SESSION_KEY, self.client.session)

    # ── 로그 ────────────────────────────────────────────────────
    def test_누가_언제_들어왔는지_로그가_남는다(self):
        """admin 의 LogEntry 는 전부 cdss_admin 으로 남아 사람을 못 가린다.
        그것을 대신하는 로그라서, 계정을 짚을 수 있는 값이 들어가야 한다."""
        _auth_user()
        account = _account("admin", login_id="boss")

        with self.assertLogs("core.api.admin_session", level="INFO") as caught:
            self._post(account)

        line = "\n".join(caught.output)
        self.assertIn("account_id=%s" % account.account_id, line)
        self.assertIn("login_id=boss", line)
        self.assertIn("trace_id=", line)
