# -*- coding: utf-8 -*-
"""CanRegisterPatient — POST /patients/register 에 간호 역할을 추가로 연다.

patient 매트릭스(원무 CRUD, 간호 RU)는 그대로 둔다. 정식 등록
POST /patients/(PatientViewSet, router)는 여전히 원무 단독이어야 한다.
CanCompleteExamOrder 와 같은 패턴 — 매트릭스 칸을 안 건드리고 이
endpoint 하나에서만 역할을 추가한다."""
from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, Staff


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class PatientRegisterPermissionTests(TestCase):
    def setUp(self):
        self.nursing_account = Account.objects.create(
            login_id="rp-nursing-test", role="nursing",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.nursing_account, staff_number="NUR-RP-001", full_name="등록권한 테스트(간호)",
        )
        self.reception_account = Account.objects.create(
            login_id="rp-reception-test", role="reception",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.reception_account, staff_number="REC-RP-001", full_name="등록권한 테스트(원무)",
        )
        self.radiology_account = Account.objects.create(
            login_id="rp-radiology-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-RP-001", full_name="등록권한 테스트(영상)",
        )
        self.nursing_client = _client_for(self.nursing_account)
        self.reception_client = _client_for(self.reception_account)
        self.radiology_client = _client_for(self.radiology_account)

    def test_nursing_can_use_simplified_register(self):
        response = self.nursing_client.post(
            "/api/v1/patients/register",
            {"name": "간호등록환자", "birth_date": "1991-01-01", "phone": "010-4444-1111"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["data"]["created"])

    def test_nursing_cannot_use_full_registration(self):
        # POST /patients/ (router, PatientViewSet) — 정식 등록은 여전히
        # 원무 단독이다. 권한 체크가 바디 검증보다 먼저 걸리므로 빈 바디로도
        # 403 여부를 확인할 수 있다.
        response = self.nursing_client.post("/api/v1/patients/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_reception_still_has_full_registration(self):
        # 기존 원무과 권한(patient:CRUD)은 그대로다 — 매트릭스를 안 건드렸다.
        response = self.reception_client.post(
            "/api/v1/patients/register",
            {"name": "원무등록환자", "birth_date": "1992-02-02", "phone": "010-4444-2222"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_other_roles_still_cannot_register(self):
        # 간호에게만 연 것이지 아무나 여는 게 아니다.
        response = self.radiology_client.post(
            "/api/v1/patients/register",
            {"name": "영상등록시도", "birth_date": "1993-03-03", "phone": "010-4444-3333"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
