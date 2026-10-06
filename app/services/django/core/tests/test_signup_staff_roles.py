"""직원 가입에서 만들 수 있는 role.

⚠ 2026-09-28 원무(reception)를 뺐다. 원무 일은 간호과가 하고(화면은
  hospital/nav.js 6.1 에서 옮겼다, 권한은 permissions.py 의
  _merge_reception_into_nursing 이 간호에 전부 준다) 여기 남겨 두면
  **간호 화면을 못 보는 계정**이 계속 새로 생긴다.

  기존 reception 계정은 지우지 않는다 — account 를 가리키는 감사 기록이
  59건이고 전부 PROTECT 다. 그래서 「가입은 막지만 role 값 자체는 살아
  있다」가 지금 상태이고, 아래 마지막 시험이 그것을 못 박는다.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core import models
from core.api.views import STAFF_SIGNUP_ROLES

URL = "/api/v1/signup/staff"


def _form(role, n):
    return {"login_id": f"u_{role}_{n}", "password": "pw-0928-test",
            "role": role, "full_name": "아무개", "staff_number": f"S-{role}-{n}"}


class StaffSignupRoleTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_원무로는_가입이_안_된다(self):
        r = self.c.post(URL, _form("reception", 1), format="json")

        self.assertEqual(r.status_code, 400)
        self.assertFalse(models.Account.objects.filter(role="reception").exists())

    def test_안내_문구에_원무가_안_남아_있다(self):
        """목록에서 뺐는데 문구에 남으면 「된다고 적혀 있는데 안 된다」가 된다."""
        body = self.c.post(URL, _form("reception", 2), format="json").json()

        self.assertNotIn("reception", str(body))

    def test_나머지_네_과는_그대로_된다(self):
        for i, role in enumerate(sorted(STAFF_SIGNUP_ROLES)):
            with self.subTest(role):
                r = self.c.post(URL, _form(role, i), format="json")
                self.assertEqual(r.status_code, 201, r.content[:200])

    def test_관리자와_환자는_이_경로로_못_만든다(self):
        for role in ("admin", "patient"):
            with self.subTest(role):
                self.assertEqual(
                    self.c.post(URL, _form(role, 9), format="json").status_code, 400)

    def test_role_값_자체는_아직_살아_있다(self):
        """가입만 막은 것이다 — 기존 원무 계정이 죽으면 감사 기록이 끊긴다."""
        self.assertIn("reception", models.ROLE)

        account = models.Account.objects.create(
            login_id="legacy_reception", role="reception",
            account_status="active", is_active=True)

        self.assertEqual(account.role, "reception")
