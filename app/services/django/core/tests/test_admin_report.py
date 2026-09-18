# -*- coding: utf-8 -*-
"""admin 의 리포트 상세에 소견문 본문이 안 보이는가.

관리자는 서버를 보는 사람이지 진료 기록을 읽는 사람이 아니다. 프론트는
perms.py 가 admin 에게 report.view.all 을 안 줘서 막히는데, Django admin 은
그 권한 체계를 안 거친다 — 여기를 따로 막아야 반쪽이 안 된다.

⚠ **fields 목록만 보고 끝내지 않는다.** 화면을 실제로 열어 본문 문장이
  응답에 없는지까지 본다. 목록을 맞게 적어도 fieldsets 나 inline 으로
  새어나갈 수 있다.
"""

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.admin.edit import REPORT_HIDDEN
from core.models import Patient, Report

SECRET = "왼쪽 유방 상외측에 2.1cm 종괴가 보입니다"


class ReportAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        cls.patient = Patient.objects.create(patient_number="P-REPORT-1")
        cls.report = Report.objects.create(
            patient=cls.patient, narrative_text=SECRET,
            content_json={"impression": SECRET}, notes={"memo": SECRET},
            unlock_reason=SECRET, lock_status="locked")

    def setUp(self):
        self.client.force_login(self.boss)

    def _url(self):
        return reverse("admin:core_report_change", args=[self.report.pk])

    def test_본문_칸이_상세_화면에_없다(self):
        fields = site._registry[Report].get_fields(None, self.report)
        for name in REPORT_HIDDEN:
            self.assertNotIn(name, fields)

    def test_화면을_열어도_본문_문장이_안_나온다(self):
        res = self.client.get(self._url())

        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, SECRET)

    def test_목록에도_안_나온다(self):
        res = self.client.get(reverse("admin:core_report_changelist"))

        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, SECRET)

    def test_잠금은_admin_에서_못_푼다(self):
        """§11.5 는 유방외과 단독이다. 뷰에 CanUnlockReport 를 걸어 놓고
        admin 에서 손으로 풀 수 있으면 그 잠금이 무의미하다."""
        res = self.client.post(self._url(), {
            "patient": self.patient.pk,
            "lock_status": "unlocked",
        })

        self.assertIn(res.status_code, (200, 302), res.content[:300])
        self.report.refresh_from_db()
        self.assertEqual(self.report.lock_status, "locked",
                         "admin 폼으로 잠금이 풀렸다")

    def test_감춘_칸은_저장해도_안_지워진다(self):
        """폼에 없는 칸이라 건드리지 않는다. 저장 한 번에 본문이 날아가면
        가린 것이 아니라 지운 것이다."""
        self.client.post(self._url(), {"patient": self.patient.pk})

        self.report.refresh_from_db()
        self.assertEqual(self.report.narrative_text, SECRET)
