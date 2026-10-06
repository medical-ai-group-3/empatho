# -*- coding: utf-8 -*-
"""09-18 프론트-백엔드 대조에서 나온 6건 중 백엔드 몫 검증."""
from datetime import date, datetime, timezone

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account,
    DiscordanceFlag,
    Lesion,
    Patient,
    PatientPii,
    Staff,
    Study,
)


def _client_for(account):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return client


class PatientRegisterCreatedFlagTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="reception-register-test",
            role="reception",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="R-001", full_name="원무 테스트",
        )
        self.client = _client_for(self.account)

    def test_new_registration_returns_201_and_created_true(self):
        response = self.client.post(
            "/api/v1/patients/register",
            {"name": "신규환자", "birth_date": "1990-01-01", "phone": "010-1111-1111"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()["data"]
        self.assertTrue(body["created"])
        self.assertIn("created_at", body)

    def test_repeat_registration_returns_200_and_created_false(self):
        payload = {"name": "재등록환자", "birth_date": "1985-05-05", "phone": "010-2222-2222"}
        first = self.client.post("/api/v1/patients/register", payload, format="json")
        self.assertEqual(first.status_code, 201)

        second = self.client.post("/api/v1/patients/register", payload, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["data"]["created"])
        self.assertEqual(second.json()["data"]["patient_id"], first.json()["data"]["patient_id"])

    def test_phone_conflict_with_different_identity_is_validation_error_not_500(self):
        self.client.post(
            "/api/v1/patients/register",
            {"name": "원래환자", "birth_date": "1970-01-01", "phone": "010-3333-3333"},
            format="json",
        )
        response = self.client.post(
            "/api/v1/patients/register",
            {"name": "다른이름", "birth_date": "1970-01-01", "phone": "010-3333-3333"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class PatientListHasAllergyTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="reception-list-test",
            role="reception",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="R-002", full_name="원무 테스트2",
        )
        self.client = _client_for(self.account)
        self.patient = Patient.objects.create(
            patient_number="P-ALLERGY-001", has_allergy=True,
        )
        PatientPii.objects.create(
            patient=self.patient, name="알레르기환자", birth_date=date(1980, 1, 1),
            phone="010-4444-4444",
        )

    def test_list_includes_has_allergy(self):
        response = self.client.get("/api/v1/patients/?q=알레르기환자")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["results"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["has_allergy"])


class PatientStudiesEndpointTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="surgery-studies-test",
            role="surgery",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="S-001", full_name="유방외과 테스트",
        )
        self.client = _client_for(self.account)
        self.patient = Patient.objects.create(patient_number="P-STUDIES-001")
        PatientPii.objects.create(
            patient=self.patient, name="검사환자", birth_date=date(1975, 3, 3),
            phone="010-5555-5555",
        )
        from core.models import ExamOrder

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

    def test_get_patient_studies(self):
        response = self.client.get(f"/api/v1/patients/{self.patient.pk}/studies")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["study_id"], self.study.study_id)


class DiscordanceDisposeAliasTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="surgery-dispose-test",
            role="surgery",
            account_status="active",
            is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="S-002", full_name="유방외과 테스트2",
        )
        self.client = _client_for(self.account)
        self.patient = Patient.objects.create(patient_number="P-DISCORD-001")
        PatientPii.objects.create(
            patient=self.patient, name="불일치환자", birth_date=date(1965, 2, 2),
            phone="010-6666-6666",
        )
        from core.models import ExamOrder

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
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)
        self.flag = DiscordanceFlag.objects.create(lesion=self.lesion)

    def test_patch_dispose_alias_route(self):
        response = self.client.patch(
            f"/api/v1/discordances/{self.flag.pk}/dispose",
            {"disposition_type": "rebiopsy", "disposition_reason": "조직검사 필요"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.disposition_type, "rebiopsy")
        self.assertIsNotNone(self.flag.closed_at)
