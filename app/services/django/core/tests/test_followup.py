# -*- coding: utf-8 -*-
"""§6-3 추적 관리 — 회차 생성 → 통화 기록 → 종료.

09-27 확인 — FollowupViewSet.partial_update() 의 통화 기록 분기(바디에
closed_reason 이 없을 때)가 instance.called_by 에 Account 를 넣고
있었다. Followup.called_by 는 Staff FK 라 즉시 ValueError 로 500 이
났다 — 옆의 FollowupCallView(전용 /call 엔드포인트)는 같은 자리를
request.user.staff 로 올바르게 쓰고 있었는데 여기만 안 고쳐져 있었다."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, Patient, PatientPii, Staff


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class FollowupLifecycleTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="followup-test", role="nursing",
            account_status="active", is_active=True,
        )
        self.staff = Staff.objects.create(
            account=self.account, staff_number="NUR-FU-001", full_name="추적 테스트",
        )
        self.patient = Patient.objects.create(patient_number="P-FOLLOWUP-001")
        PatientPii.objects.create(
            patient=self.patient, name="추적테스트환자", birth_date=date(1975, 1, 1),
            phone="010-5555-1111",
        )
        self.client = _client_for(self.account)

        response = self.client.post(
            "/api/v1/followups/new",
            {"patient_id": self.patient.pk, "round_no": 1, "due_at": "2026-12-01T00:00:00Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.followup_id = response.json()["data"]["followup_id"]

    def test_create_starts_open(self):
        response = self.client.get("/api/v1/followups/")
        rows = [r for r in response.json()["data"] if r["followup_id"] == self.followup_id]
        self.assertEqual(rows[0]["status"], "open")

    def test_dedicated_call_endpoint_logs_call(self):
        response = self.client.patch(
            f"/api/v1/followups/{self.followup_id}/call",
            {"call_result": "연결", "call_note": "변화 없음"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["call_result"], "연결")
        self.assertEqual(data["called_by"], self.staff.pk)

    def test_generic_patch_without_closed_reason_logs_call_not_crash(self):
        """⚠ 이게 실제로 500 이 나던 경로다 — called_by 에 Account 대신
        Staff 가 들어가야 통과한다."""
        response = self.client.patch(
            f"/api/v1/followups/{self.followup_id}/",
            {"call_result": "부재", "call_note": "다시 전화"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["call_result"], "부재")
        self.assertEqual(data["called_by"], self.staff.pk)
        self.assertEqual(data["status"], "open")   # 종료가 아니라 통화 기록일 뿐이다

    def test_generic_patch_with_closed_reason_closes(self):
        response = self.client.patch(
            f"/api/v1/followups/{self.followup_id}/",
            {"status": "resolved", "closed_reason": "경과 안정 · 추적 종료"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "resolved")
        self.assertIsNotNone(data["closed_at"])
        self.assertEqual(data["closed_reason"], "경과 안정 · 추적 종료")

    def test_full_lifecycle_create_call_close(self):
        call = self.client.patch(
            f"/api/v1/followups/{self.followup_id}/call",
            {"call_result": "연결", "call_note": "재검 권유"}, format="json",
        )
        self.assertEqual(call.status_code, 200)

        close = self.client.patch(
            f"/api/v1/followups/{self.followup_id}/",
            {"status": "resolved", "closed_reason": "재검 완료 · 정상"}, format="json",
        )
        self.assertEqual(close.status_code, 200)
        data = close.json()["data"]
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["call_result"], "연결")   # 통화 기록은 종료 뒤에도 남는다
        self.assertIsNotNone(data["closed_at"])
