# -*- coding: utf-8 -*-
"""GET /radiology/studies/{id}/read — 품질 반려된 Study 는 409 STUDY_REJECTED.

SYS-6. 재촬영 경로(POST /exam-orders/{id}/retake)로 가야 한다 — 반려본을
그대로 판독 화면에서 열 수 없다."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account,
    ExamOrder,
    Patient,
    PatientPii,
    Staff,
    StorageObject,
    Study,
)


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class StudyReadRejectedTests(TestCase):
    def setUp(self):
        self.radiology_account = Account.objects.create(
            login_id="read-rejected-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-READ-001",
            full_name="반려판독 테스트",
        )

        self.patient = Patient.objects.create(patient_number="P-READ-REJECTED-001")
        PatientPii.objects.create(
            patient=self.patient, name="반려판독테스트환자", birth_date=date(1994, 4, 4),
            phone="010-7777-8888",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.radiology_account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        StorageObject.objects.create(study=self.study, bucket="b", object_key="rk1")
        self.client = _client_for(self.radiology_account)

    def test_rejected_study_read_is_409(self):
        self.study.quality_status = "rejected"
        self.study.save()

        response = self.client.get(f"/api/v1/radiology/studies/{self.study.pk}/read")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "STUDY_REJECTED")

    def test_accepted_study_read_still_works(self):
        self.study.quality_status = "accepted"
        self.study.save()

        response = self.client.get(f"/api/v1/radiology/studies/{self.study.pk}/read")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["study"]["study_id"], self.study.pk)

    def test_no_quality_status_yet_still_works(self):
        # 아직 품질 승인/반려를 안 거친 상태(quality_status=None) — 반려가
        # 아니니 막히면 안 된다.
        response = self.client.get(f"/api/v1/radiology/studies/{self.study.pk}/read")
        self.assertEqual(response.status_code, 200)
