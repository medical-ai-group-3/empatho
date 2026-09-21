# -*- coding: utf-8 -*-
"""POST /exam-orders/{id}/retake — 확정 사양서 §2-3, 품질 반려 재촬영 오더.

명시적 버튼 호출이다(자동 트리거 아님). 원본 오더에 quality_status=rejected
인 Study 가 있어야만 되고, 새 오더는 parent_order 로 원본을 가리킨다."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, ExamOrder, Patient, PatientPii, Staff, Study


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class ExamOrderRetakeTests(TestCase):
    def setUp(self):
        self.radiology_account = Account.objects.create(
            login_id="retake-rad-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-RETAKE-001",
            full_name="재촬영 테스트",
        )
        self.pathology_account = Account.objects.create(
            login_id="retake-path-test", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.pathology_account, staff_number="PAT-RETAKE-001",
            full_name="재촬영 테스트(병리)",
        )

        self.patient = Patient.objects.create(patient_number="P-RETAKE-001")
        PatientPii.objects.create(
            patient=self.patient, name="재촬영테스트환자", birth_date=date(1993, 3, 3),
            phone="010-5555-6666",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.radiology_account.staff,
        )
        self.client = _client_for(self.radiology_account)

    def test_retake_fails_without_rejected_study(self):
        response = self.client.post(
            f"/api/v1/exam-orders/{self.order.pk}/retake", {}, format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"],
                         "RETAKE_REQUIRES_REJECTED_QUALITY")

    def test_retake_succeeds_with_rejected_study(self):
        Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
            quality_status="rejected",
        )
        response = self.client.post(
            f"/api/v1/exam-orders/{self.order.pk}/retake", {}, format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertIn("exam_order_id", data)
        new_id = data["exam_order_id"]
        self.assertNotEqual(new_id, self.order.pk)

        new_order = ExamOrder.objects.get(pk=new_id)
        self.assertEqual(new_order.parent_order_id, self.order.pk)
        self.assertEqual(new_order.patient_id, self.patient.pk)
        self.assertEqual(new_order.modality, self.order.modality)
        self.assertEqual(new_order.exam_purpose, self.order.exam_purpose)
        self.assertEqual(new_order.order_status, "ordered")
        self.assertEqual(new_order.ordered_by_id, self.order.ordered_by_id)

    def test_retake_appears_in_radiology_queue(self):
        # ⚠ ExamOrderQueueView 의 docstring 은 "Study 가 이미 생긴 오더는
        # 큐에서 뺀다"고 적어 두었지만, get_queryset() 에 그 필터가 실제로는
        # 없다 — 원본도 여전히 큐에 남는다(기존 버그, 이 테스트 범위 밖).
        # 여기서는 새로 만든 재촬영 오더가 큐에 뜨는 것만 확인한다.
        Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
            quality_status="rejected",
        )
        self.client.post(f"/api/v1/exam-orders/{self.order.pk}/retake", {}, format="json")

        response = self.client.get("/api/v1/radiology/queue?status=ordered&assigned=none")
        self.assertEqual(response.status_code, 200)
        ids = [row["exam_order_id"] for row in response.json()["data"]["results"]]
        new_order = ExamOrder.objects.exclude(pk=self.order.pk).get(patient=self.patient)
        self.assertIn(new_order.pk, ids)

    def test_pathology_cannot_retake(self):
        Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
            quality_status="rejected",
        )
        other_client = _client_for(self.pathology_account)
        response = other_client.post(
            f"/api/v1/exam-orders/{self.order.pk}/retake", {}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_retake_of_missing_order_is_404(self):
        response = self.client.post("/api/v1/exam-orders/999999/retake", {}, format="json")
        self.assertEqual(response.status_code, 404)
