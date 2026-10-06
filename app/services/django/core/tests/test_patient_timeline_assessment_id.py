# -*- coding: utf-8 -*-
"""09-18 정은님 지적: 환자 상세(timeline)에 assessment_id 가 없어
DecisionForm 이 PATCH /assessments/{id}/decision 에 쓸 id 를 못 찾았다.
판독 이벤트에 assessment_id 를 실어준다."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, ExamOrder, Patient, PatientPii, Staff, Study


class PatientTimelineAssessmentIdTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="surgery-timeline-test",
            role="surgery",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="S-003", full_name="유방외과 테스트3",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

        self.patient = Patient.objects.create(patient_number="P-TIMELINE-001")
        PatientPii.objects.create(
            patient=self.patient, name="타임라인환자", birth_date=date(1990, 1, 1),
            phone="010-7777-7777",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient,
            order_status="ordered",
            modality="mammo",
            exam_purpose="screening",
            ordered_by=self.account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        from core.models import Assessment

        self.assessment = Assessment.objects.create(
            study=self.study, read_stage="final", category="4a",
        )

    def test_timeline_reading_event_includes_assessment_id(self):
        response = self.client.get(f"/api/v1/patients/{self.patient.pk}/timeline")
        self.assertEqual(response.status_code, 200)
        events = response.json()["data"]
        reading_events = [e for e in events if e["type"] == "판독"]
        self.assertEqual(len(reading_events), 1)
        self.assertEqual(reading_events[0]["assessment_id"], self.assessment.assessment_id)
