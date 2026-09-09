# -*- coding: utf-8 -*-
"""예약 신청 지원 — exam_order 의 requested 상태와 확정 제약.

흐름
    환자가 날짜·시간만 신청  → order_status='requested', 세 칸은 빈다
    원무가 확정             → modality · exam_purpose · ordered_by 를 채우고 'ordered'

세 칸을 비운 채 확정 상태로 넘어가는 것은 DB 가 막는다 — API 를 안 거치는
경로(Celery · admin)가 있어서다.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Account, ExamOrder, Patient, Staff


class ExamOrderRequestedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        account = Account.objects.create(login_id="rec1", role="reception",
                                         is_active=True)
        cls.staff = Staff.objects.create(account=account, full_name="박원무")

    def test_환자는_날짜만_넣고_신청한다(self):
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="requested",
            scheduled_at="2026-09-22T09:00:00+09:00")
        order.refresh_from_db()
        self.assertIsNone(order.modality)
        self.assertIsNone(order.exam_purpose)
        self.assertIsNone(order.ordered_by_id)

    def test_원무가_확정하면_세_칸이_찬다(self):
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="requested",
            scheduled_at="2026-09-22T09:00:00+09:00")
        order.modality = "mammo"
        order.exam_purpose = "screening"
        order.ordered_by = self.staff
        order.order_status = "ordered"
        order.scheduled_at = "2026-09-22T14:00:00+09:00"   # 다른 시간으로 확정
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.order_status, "ordered")
        self.assertEqual(order.modality, "mammo")

    def _blocked(self, **kwargs):
        base = {"patient": self.patient, "order_status": "ordered",
                "modality": "mammo", "exam_purpose": "screening",
                "ordered_by": self.staff}
        base.update(kwargs)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExamOrder.objects.create(**base)

    def test_검사종류_없이_확정하지_못한다(self):
        self._blocked(modality=None)

    def test_목적_없이_확정하지_못한다(self):
        self._blocked(exam_purpose=None)

    def test_지시자_없이_확정하지_못한다(self):
        self._blocked(ordered_by=None)

    def test_신청_아닌_다른_상태도_세_칸이_필요하다(self):
        # 'requested' 만 예외다
        for status in ("accepted", "in_progress", "completed", "cancelled"):
            self._blocked(order_status=status, modality=None)

    def test_환자_없이는_만들지_못한다(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExamOrder.objects.create(patient=None, order_status="requested")

    def test_없는_상태값은_막힌다(self):
        self._blocked(order_status="nope")


class NotificationTypeTests(TestCase):
    def test_신청_알림_종류가_있다(self):
        from core.models import NOTIFICATION_TYPE

        self.assertIn("reservation_requested", NOTIFICATION_TYPE)
        self.assertIn("reservation_created", NOTIFICATION_TYPE)

    def test_원무에게_가는_신청_알림을_만든다(self):
        from core.models import Notification

        patient = Patient.objects.create(patient_number="E_2000001")
        note = Notification.objects.create(
            patient=patient, notification_type="reservation_requested",
            message="9월 22일 오전 예약을 신청했습니다.",
            ref_type="exam_order", ref_id=1)
        self.assertEqual(note.notification_type, "reservation_requested")
