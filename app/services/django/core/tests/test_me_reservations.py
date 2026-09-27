# -*- coding: utf-8 -*-
"""환자 앱 「내 예약」 — 온 예약 · 지난 예약은 빠진다."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core import models


class MeReservationsTestCase(TestCase):
    def test_온_예약과_지난_예약은_안_뜬다(self):
        acc = models.Account.objects.create(login_id="pat9", role="patient", is_active=True)
        p = models.Patient.objects.create(patient_number="H_9009", account=acc)
        now = timezone.now()
        mk = lambda **kw: models.ExamOrder.objects.create(patient=p, **kw).pk
        upcoming = mk(order_status="scheduled", scheduled_at=now + timedelta(days=1))
        pending = mk(order_status="requested")
        mk(order_status="requested", scheduled_at=now, visited_at=now)   # 왔다
        mk(order_status="scheduled", scheduled_at=now - timedelta(days=2))  # 지났다

        c = APIClient()
        c.force_authenticate(user=acc)
        body = c.get("/api/v1/me/reservations").json()
        items = (body.get("data") or body)["items"]
        self.assertEqual(sorted(i["exam_order_id"] for i in items), sorted([upcoming, pending]))
