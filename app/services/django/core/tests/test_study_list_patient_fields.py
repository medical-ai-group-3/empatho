# -*- coding: utf-8 -*-
"""09-18 프론트 확인: Queue·List 크래시는 잡혔는데 GET /studies 가
patient_name 등을 안 줘서 List 화면 행이 undefined/undefined 로 떴다.
ExamOrderSerializer 와 같은 계산 필드를 StudySerializer 에도 둔다."""
from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, ExamOrder, Patient, PatientPii, Staff, Study


class StudyListPatientFieldsTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="radiology-study-fields-test",
            role="radiology",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="RAD-002", full_name="영상 테스트2",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

        self.patient = Patient.objects.create(patient_number="P-STUDYFIELD-001", sex="female")
        PatientPii.objects.create(
            patient=self.patient, name="스터디필드환자", birth_date=date(1990, 6, 1),
            phone="010-3333-2222",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
            performed_at=datetime(2020, 6, 1, tzinfo=dt_timezone.utc),
        )

    def test_study_list_includes_patient_name_age_sex(self):
        response = self.client.get("/api/v1/studies/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["results"]
        row = next(r for r in rows if r["study_id"] == self.study.pk)
        self.assertEqual(row["patient_name"], "스터디필드환자")
        self.assertEqual(row["age"], 30)
        self.assertEqual(row["sex"], "female")

    def test_patient_studies_includes_patient_name_age_sex(self):
        response = self.client.get(f"/api/v1/patients/{self.patient.pk}/studies")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["results"]
        self.assertEqual(rows[0]["patient_name"], "스터디필드환자")
        self.assertEqual(rows[0]["age"], 30)
        self.assertEqual(rows[0]["sex"], "female")
