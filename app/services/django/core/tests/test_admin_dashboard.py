# -*- coding: utf-8 -*-
"""대시보드 — 시안(admin-redesign/Main.dc.html)이 요구하는 값.

⚠ 숫자만 낸다. 환자 이름도 소견도 여기 안 나온다 — 관리자는 시스템 관리자다.
  그 경계가 깨지는지도 같이 본다.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.admin import views
from core.models import (
    Account, ExamOrder, Patient, PatientPii, Staff,
)

SECRET_NAME = "홍길동"


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")

        cls.patient = Patient.objects.create(patient_number="P-DASH-1", sex="F")
        PatientPii.objects.create(patient=cls.patient, name=SECRET_NAME,
                                  phone="010-0000-0000")
        # 승인 대기 직원 하나 + 승인 대기 환자 하나(환자는 안 세야 한다)
        staff_account = Account.objects.create(
            login_id="wait_staff", role="nursing", account_status="pending")
        Staff.objects.create(account=staff_account, full_name="대기",
                             staff_number="S-DASH-1")
        Account.objects.create(login_id="wait_patient", role="patient",
                               account_status="pending")

        for _ in range(3):
            ExamOrder.objects.create(patient=cls.patient,
                                     order_status="requested")

    def setUp(self):
        self.client.force_login(self.boss)
        views.probe_cache_clear()
        self.addCleanup(views.probe_cache_clear)

    def _dash(self):
        res = self.client.get(reverse("admin:empatho_dashboard"))
        self.assertEqual(res.status_code, 200)
        return res

    # ── 핵심 지표 넉 장 ─────────────────────────────────────────
    def test_승인_대기_직원은_사이드바_배지와_같은_수다(self):
        """한 화면에 같은 것을 세는 수가 둘이면 어느 쪽이 맞는지 모른다."""
        from core.adminsite import _pending

        self.assertEqual(views._pending_staff(), _pending())
        self.assertEqual(views._pending_staff(), 1, "환자는 승인 대상이 아니다")

    def test_넉_장의_숫자가_실제와_맞는다(self):
        dash = self._dash().context["dash"]

        self.assertEqual(dash["pending_staff"], 1)
        self.assertEqual(dash["orders"], 3)
        self.assertEqual(dash["ai_results"], 0)
        self.assertEqual(dash["lesions"], 0)
        self.assertEqual(dash["assessments"], 0)
        self.assertEqual(dash["open_flags"], 0)

    def test_날짜에_한글_요일이_붙는다(self):
        label = self._dash().context["dash"]["date_label"]

        self.assertTrue(label.endswith(")"), label)
        self.assertIn(label[-2], views.WEEKDAYS)

    # ── 검사 오더 잔무늬 ────────────────────────────────────────
    def test_잔무늬는_다섯_칸이다(self):
        spark = self._dash().context["dash"]["order_spark"]

        self.assertEqual(len(spark), views.SPARK_DAYS)

    def test_오늘_넣은_것이_마지막_칸에_센다(self):
        spark = self._dash().context["dash"]["order_spark"]

        self.assertEqual(spark[-1]["n"], 3)

    def test_0_인_날도_자국을_남긴다(self):
        """칸이 아예 없으면 그 날이 빠진 줄 안다."""
        spark = self._dash().context["dash"]["order_spark"]

        self.assertTrue(all(d["pct"] > 0 for d in spark), spark)

    def test_오래된_오더는_잔무늬에_안_센다(self):
        old = ExamOrder.objects.create(patient=self.patient,
                                       order_status="requested")
        ExamOrder.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=views.SPARK_DAYS + 2))

        spark = self._dash().context["dash"]["order_spark"]

        self.assertEqual(sum(d["n"] for d in spark), 3)

    # ── 진료 흐름 ───────────────────────────────────────────────
    def test_흐름은_시안_차례_일곱_줄이다(self):
        """개수 순으로 정렬하지 않는다 — 진료가 흐르는 차례가 곧 뜻이다."""
        flow = self._dash().context["dash"]["flow"]

        self.assertEqual([r["label"] for r in flow],
                         ["검사 오더", "알림", "AI 결과", "병변",
                          "영상 파일", "환자", "추적 관찰"])

    def test_막대는_제일_큰_것을_100_으로_본다(self):
        flow = {r["label"]: r for r in self._dash().context["dash"]["flow"]}

        self.assertEqual(flow["검사 오더"]["n"], 3)
        self.assertEqual(flow["검사 오더"]["pct"], 100)
        self.assertEqual(flow["환자"]["pct"], 33)     # 1/3
        self.assertEqual(flow["추적 관찰"]["pct"], 0)

    def test_줄마다_색이_고정이다(self):
        """개수에 따라 색이 바뀌면 색이 뜻을 잃는다."""
        flow = {r["label"]: r["tone"] for r in self._dash().context["dash"]["flow"]}

        self.assertEqual(flow["검사 오더"], "cyan")
        self.assertEqual(flow["영상 파일"], "amber")

    # ── 서비스 고리 ─────────────────────────────────────────────
    def test_고리는_상태_화면과_같은_값을_쓴다(self):
        """따로 찌르면 admin 첫 화면에 최대 4초가 붙는다."""
        ok = [views._result("a", True, "", 0.01),
              views._result("b", True, "", 0.01)]

        with patch.object(views, "probe_all", return_value=ok) as spy:
            self.client.get(reverse("admin:empatho_dashboard"))
            self.client.get(reverse("admin:empatho_status"))

        self.assertEqual(spy.call_count, 1)

    def test_고리_길이가_정상_비율만큼이다(self):
        probes = [views._result("a", True, "", 0.01),
                  views._result("b", True, "", 0.01),
                  views._result("c", False, "죽음", None),
                  views._result("d", False, "죽음", None)]

        with patch.object(views, "probe_all", return_value=probes):
            dash = self._dash().context["dash"]

        self.assertEqual(dash["service"]["ok"], 2)
        self.assertEqual(dash["service"]["ring"], round(views.RING * 2 / 4))

    def test_하나도_못_찌르면_고리가_0_이고_안_터진다(self):
        with patch.object(views, "probe_all", return_value=[]):
            dash = self._dash().context["dash"]

        self.assertEqual(dash["service"]["ring"], 0)

    # ── 역할별 칩 ───────────────────────────────────────────────
    def test_일곱_역할이_시안_차례로_늘_나온다(self):
        """0 명인 과도 자리를 지킨다 — 칩이 사라지면 과가 없어진 줄 안다."""
        roles = self._dash().context["dash"]["roles"]

        self.assertEqual([r["label"] for r in roles],
                         ["관리자", "원무", "간호", "영상의학",
                          "유방외과", "병리", "환자"])

    def test_칩의_수가_실제와_맞는다(self):
        roles = {r["label"]: r["n"] for r in self._dash().context["dash"]["roles"]}

        self.assertEqual(roles["간호"], 1)
        self.assertEqual(roles["환자"], 1)
        self.assertEqual(roles["병리"], 0)

    def test_계정_합계가_나온다(self):
        self.assertEqual(self._dash().context["dash"]["accounts_total"],
                         Account.objects.count())

    # ── 경계 ────────────────────────────────────────────────────
    def test_환자_이름이_대시보드에_안_나온다(self):
        self.assertNotContains(self._dash(), SECRET_NAME)

    def test_로그아웃이_아바타에_붙어_있다(self):
        """머리띠를 걷어서 이 화면 말고는 나갈 길이 없다."""
        res = self._dash()

        self.assertContains(res, reverse("admin:logout"))
        self.assertContains(res, "e-avatar")
