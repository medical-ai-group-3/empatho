# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta, timezone

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, ExamOrder, Patient, PatientPii, Staff
from core.serializers.reception import ExamOrderSerializer


class ExamOrderNoteAndPatientFieldsTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="nursing-note-test",
            role="nursing",
            account_status="active",
            is_active=True,
        )
        self.staff = Staff.objects.create(
            account=self.account,
            staff_number="N-001",
            full_name="간호 테스트",
        )
        self.patient = Patient.objects.create(
            patient_number="P-NOTE-001",
            sex="female",
        )
        PatientPii.objects.create(
            patient=self.patient,
            name="메모 테스트 환자",
            birth_date=date(1990, 6, 1),
            phone="010-0000-0001",
        )
        self.visited_at = datetime(2020, 6, 1, tzinfo=timezone.utc)
        self.patient.first_visited_at = self.visited_at + timedelta(seconds=1)
        self.patient.save(update_fields=["first_visited_at"])
        self.order = ExamOrder.objects.create(
            patient=self.patient,
            order_status="requested",
            scheduled_at=self.visited_at,
            visited_at=self.visited_at,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

    def test_exam_order_serializer_adds_patient_fields(self):
        data = ExamOrderSerializer(self.order).data

        self.assertEqual(data["age"], 30)
        self.assertEqual(data["sex"], "female")
        self.assertEqual(data["visit_type"], "초진")

    def test_note_patch_updates_order_note(self):
        response = self.client.patch(
            f"/api/v1/exam-orders/{self.order.pk}/note",
            {"note": "간호 메모 저장 테스트"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_note, "간호 메모 저장 테스트")
        self.assertEqual(response.json()["data"]["order_note"], "간호 메모 저장 테스트")
