# -*- coding: utf-8 -*-
"""DB 조회 — 구조는 보이고 값은 안 새는가.

표를 통째로 막지 않는다. 관리자가 스키마도 못 보면 일을 못 한다. 막는 것은
값 쪽이다 — 분포다.

⚠ 「민감한 표에는 분포를 안 낸다」를 목록 대조로만 보면 부족하다. 화면을 실제로
  열어 그 값이 응답에 없는지까지 본다.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.admin import views
from core.models import Account, ExamOrder, Patient, PatientPii

SECRET_NAME = "홍길동"


class DbScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        patient = Patient.objects.create(patient_number="P-DB-1", sex="F")
        PatientPii.objects.create(patient=patient, name=SECRET_NAME,
                                  phone="010-1111-2222")
        Account.objects.create(login_id="secret_login", role="nursing",
                               account_status="active")
        # 분포가 개수를 제대로 세는지 보려고 일부러 치우치게 넣는다
        for status in ("requested", "requested", "cancelled"):
            ExamOrder.objects.create(patient=patient, order_status=status)

    def setUp(self):
        self.client.force_login(self.boss)

    def _detail(self, table):
        return self.client.get(
            reverse("admin:empatho_db_detail", args=[table]))

    # ── 목록 ────────────────────────────────────────────────────
    def test_표_목록이_뜬다(self):
        res = self.client.get(reverse("admin:empatho_db"))

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "patient_pii")
        self.assertContains(res, "exam_order")

    # ── 구조는 막지 않는다 ──────────────────────────────────────
    def test_민감한_표도_구조는_보인다(self):
        """표째 가리면 관리자가 스키마를 못 본다. 막는 것은 값뿐이다."""
        res = self._detail("patient_pii")

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "phone")        # 칸 이름은 구조다
        self.assertContains(res, "name")

    def test_없는_표는_404(self):
        self.assertEqual(self._detail("no_such_table").status_code, 404)

    # ── 값은 막는다 ─────────────────────────────────────────────
    def test_민감한_표에는_분포가_없다(self):
        res = self._detail("patient_pii")

        self.assertEqual(res.context["spreads"], [])
        self.assertTrue(res.context["hidden"])
        self.assertNotContains(res, SECRET_NAME)

    def test_account_도_가린다(self):
        """로그인 아이디가 분포로 새면 계정 목록을 내주는 것과 같다."""
        res = self._detail("account")

        self.assertEqual(res.context["spreads"], [])
        self.assertNotContains(res, "secret_login")

    @override_settings(ADMIN_DB_SENSITIVE=[])
    def test_가릴_표는_settings_가_정한다(self):
        """코드에 박으면 표가 늘 때 아무도 여기를 안 고친다."""
        res = self._detail("patient_pii")

        self.assertFalse(res.context["hidden"])

    # ── 어느 칸을 내는가 ────────────────────────────────────────
    def test_상태형_칸만_분포를_낸다(self):
        """자유 텍스트는 안 낸다 — 길이 분포도 안 낸다.

        patient.sex 는 choices 가 없는 CharField 라 여기서 빠진다. 값 집합이
        코드에 없으면 자유 칸과 구분할 방법이 없다 — 막는 쪽으로 둔다.
        """
        patient = {f.column: f for f in Patient._meta.fields}
        order = {f.column: f for f in ExamOrder._meta.fields}

        self.assertTrue(views._spreadable(order["order_status"]))       # choices
        self.assertTrue(views._spreadable(patient["has_allergy"]))      # 참거짓
        self.assertFalse(views._spreadable(patient["allergy_note"]))    # 자유
        self.assertFalse(views._spreadable(patient["sex"]))             # 집합 없음
        self.assertFalse(views._spreadable(patient["patient_id"]))      # 키

    def test_외래키는_안_낸다(self):
        """값이 남의 표 행 번호라 분포가 뜻을 못 갖고, 사람을 좁힌다."""
        fk = PatientPii._meta.get_field("patient")

        self.assertFalse(views._spreadable(fk))

    def test_분포에_실제_개수가_나온다(self):
        spreads = {s["name"]: s["rows"] for s in views.db_spreads(ExamOrder)}

        self.assertEqual(spreads["order_status"],
                         [{"value": "requested", "n": 2},
                          {"value": "cancelled", "n": 1}])
