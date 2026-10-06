# -*- coding: utf-8 -*-
"""유방외과 리포트의 modality별 부분 저장 회귀 테스트."""

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, ExamOrder, Patient, Report, Staff


class SurgeryReportMergeTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="surgery-report-merge-test",
            role="surgery",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account,
            staff_number="SUR-REPORT-MERGE-001",
            full_name="유방외과 리포트 테스트",
        )
        self.patient = Patient.objects.create(
            account=self.account,
            patient_number="P-REPORT-MERGE-001",
        )
        self.report = Report.objects.create(
            patient=self.patient,
            report_type="final",
            audience="clinician",
            lock_status="unlocked",
            content_json={},
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION="Bearer " + issue_access(self.account)
        )

    def test_modality_updates_keep_previous_values(self):
        url = f"/api/v1/reports/{self.report.report_id}/"

        first = self.client.put(
            url,
            {"content_json": {
                "doctor_summary": "초음파 요약",
                "by_modality": {"us": "초음파 소견"},
            }},
            format="json",
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.put(
            url,
            {"content_json": {
                "doctor_summary": "맘모그래피 반영 요약",
                "by_modality": {"mammo": "맘모그래피 소견"},
            }},
            format="json",
        )
        self.assertEqual(second.status_code, 200)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.json()["data"]["content_json"]
        self.assertEqual(content["doctor_summary"], "맘모그래피 반영 요약")
        self.assertEqual(content["by_modality"], {
            "us": "초음파 소견",
            "mammo": "맘모그래피 소견",
        })


class CompleteExamOrderPermissionTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(patient_number="P-COMPLETE-001")
        self.ordering_account = Account.objects.create(
            login_id="ordering-staff-complete-test",
            role="surgery",
            account_status="active",
            is_active=True,
        )
        self.ordering_staff = Staff.objects.create(
            account=self.ordering_account,
            staff_number="SUR-ORDER-COMPLETE-001",
            full_name="오더 생성 테스트",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient,
            order_status="ordered",
            modality="mammo",
            exam_purpose="screening",
            ordered_by=self.ordering_staff,
        )

    def _client(self, login_id, role, staff_number):
        account = Account.objects.create(
            login_id=login_id,
            role=role,
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=account,
            staff_number=staff_number,
            full_name=login_id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
        return client

    def test_surgery_can_complete_without_opening_exam_order_update_matrix(self):
        client = self._client("surgery-complete-test", "surgery", "SUR-COMPLETE-001")

        response = client.patch(f"/api/v1/exam-orders/{self.order.pk}/complete")

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_status, "completed")

    def test_pathology_cannot_use_the_complete_action(self):
        client = self._client("pathology-complete-test", "pathology", "PATH-COMPLETE-001")

        response = client.patch(f"/api/v1/exam-orders/{self.order.pk}/complete")

        self.assertEqual(response.status_code, 403)
