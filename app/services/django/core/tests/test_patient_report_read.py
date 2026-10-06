"""환자가 안내문을 열면 홈의 「새 안내문」과 「결과 도착」 알림이 함께 꺼진다."""
from rest_framework.test import APITestCase

from core import models
from core.api.auth import issue_access


class PatientReportReadTests(APITestCase):
    def setUp(self):
        self.account = models.Account.objects.create(
            login_id="readme1", role="patient", account_status="active", is_active=True)
        self.patient = models.Patient.objects.create(
            patient_number="P-READ-1", account=self.account)
        self.report = models.Report.objects.create(
            patient=self.patient, report_type="final", audience="patient",
            lock_status="unlocked", narrative_text="안내")
        self.note = models.Notification.objects.create(
            patient=self.patient, notification_type="report_ready", channel="app",
            message="검사 결과가 도착했습니다.", ref_type="report", ref_id=self.report.pk)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

    def _new_ids(self):
        return [r["report_id"] for r in self.client.get("/api/v1/home").json()["data"]["new_reports"]]

    def test_열면_홈과_알림에서_새_표시가_꺼진다(self):
        self.assertEqual(self._new_ids(), [self.report.pk])
        self.assertEqual(self.client.get(f"/api/v1/reports/{self.report.pk}/").status_code, 200)
        self.assertEqual(self._new_ids(), [])
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.acknowledged_at)
