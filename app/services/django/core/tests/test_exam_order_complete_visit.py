# -*- coding: utf-8 -*-
"""유방외과 「진료 완료」 — 방문 오더를 PATCH /exam-orders/{id}/complete 로 닫는다.

09-28 — 창구 접수 · 내원 처리된 예약은 modality · exam_purpose · ordered_by 가
빈 requested 인데, exam_order_requested_fields_ck 가 그런 행의 completed 를
막아서 진료 완료가 매번 IntegrityError → 500 이었다. 기존 테스트
(test_surgery_report_merge.CompleteExamOrderPermissionTests)는 세 칸이 찬
촬영 오더만 써서 못 잡았다.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, ExamOrder, Patient, Staff


class CompleteVisitOrderTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(patient_number="P-CLOSE-VISIT-001")
        # 주치의는 staff 를 만든 뒤 붙인다 — 유방외과 대기(primary_staff=me)에 서게
        account = Account.objects.create(
            login_id="surgery-close-visit", role="surgery",
            account_status="active", is_active=True,
        )
        self.staff = Staff.objects.create(
            account=account, staff_number="SUR-CLOSE-VISIT-001", full_name="진료 완료 테스트",
        )
        self.patient.primary_staff = self.staff
        self.patient.save(update_fields=["primary_staff"])
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))

    def _visit(self, **kw):
        # 창구 접수(CheckInView)가 만드는 모양 그대로 — 검사 칸이 비어 있다
        fields = dict(patient=self.patient, order_status="requested",
                      visited_at=timezone.now(), handed_at=timezone.now(),
                      handed_to=self.staff)
        fields.update(kw)
        return ExamOrder.objects.create(**fields)

    def _complete(self, order):
        # 화면(api.js breast.completeExamOrder)과 같이 빈 JSON 몸통으로 부른다
        return self.client.patch(f"/api/v1/exam-orders/{order.pk}/complete", {}, format="json")

    def test_walk_in_visit_without_exam_fields_can_be_completed(self):
        order = self._visit()

        response = self._complete(order)

        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.order_status, "completed")
        self.assertIsNone(order.modality)
        self.assertIsNone(order.exam_purpose)

    def test_completed_visit_leaves_the_surgery_waiting_list(self):
        order = self._visit()
        before = self.client.get("/api/v1/patients/", {"primary_staff": "me", "status": "waiting"})
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["data"]["count"], 1)

        self.assertEqual(self._complete(order).status_code, 200)

        after = self.client.get("/api/v1/patients/", {"primary_staff": "me", "status": "waiting"})
        self.assertEqual(after.json()["data"]["count"], 0)

    def test_completing_twice_is_idempotent(self):
        order = self._visit()
        self.assertEqual(self._complete(order).status_code, 200)
        self.assertEqual(self._complete(order).status_code, 200)

    def test_booking_not_yet_visited_cannot_be_completed(self):
        booking = ExamOrder.objects.create(
            patient=self.patient, order_status="scheduled",
            scheduled_at=timezone.now() + timedelta(days=1),
        )

        response = self._complete(booking)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "COMPLETE_NOT_ALLOWED")
        booking.refresh_from_db()
        self.assertEqual(booking.order_status, "scheduled")

    def test_cancelled_order_cannot_be_completed(self):
        order = self._visit(order_status="cancelled")

        response = self._complete(order)

        self.assertEqual(response.status_code, 409)

    def test_missing_order_is_404_not_500(self):
        response = self.client.patch("/api/v1/exam-orders/999999/complete", {}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_db_still_rejects_completing_an_unvisited_order_without_exam_fields(self):
        # 제약을 넓힌 것은 「온 방문」뿐이다 — 안 온 빈 오더는 DB 가 그대로 막는다
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExamOrder.objects.create(patient=self.patient, order_status="completed")
