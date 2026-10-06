"""유방외과 열람 — 유방외과가 리포트 목록을 열면 영상 · 병리 목록에 열람이 뜬다."""
from rest_framework.test import APITestCase

from core import models
from core.api.auth import issue_access


def _staff(login, role):
    acc = models.Account.objects.create(login_id=login, role=role,
                                        account_status="active", is_active=True)
    models.Staff.objects.create(account=acc, full_name=login)
    return acc


class SurgeryViewedTests(APITestCase):
    def setUp(self):
        self.surgeon = _staff("surg1", "surgery")
        self.rad = _staff("rad1", "radiology")
        self.patient = models.Patient.objects.create(patient_number="P-VIEW-1")
        order = models.ExamOrder.objects.create(patient=self.patient, order_status="requested")
        self.study = models.Study.objects.create(patient=self.patient, exam_order=order,
                                                 modality="us")
        models.Report.objects.create(patient=self.patient, study=self.study,
                                     report_type="stage", narrative_text="소견")

    def _as(self, acc):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(acc))

    def _viewed(self):
        self._as(self.rad)
        rows = self.client.get(f"/api/v1/studies/?patient={self.patient.pk}").json()["data"]
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        return rows[0]["viewed_at"]

    def test_유방외과가_열기_전에는_미열람(self):
        self.assertIsNone(self._viewed())

    def test_유방외과가_목록을_열면_열람이_남는다(self):
        self._as(self.surgeon)
        self.client.get(f"/api/v1/reports/?patient={self.patient.pk}")
        self.assertIsNotNone(self._viewed())

    def test_다른_과가_열어도_열람이_아니다(self):
        self._as(self.rad)
        self.client.get(f"/api/v1/reports/?patient={self.patient.pk}")
        self.assertIsNone(self._viewed())
