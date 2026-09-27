# -*- coding: utf-8 -*-
"""09-27 예약 환자 내원 — 예약 오더를 내원 처리하고 간호 대기에 세운다.

DB 없이 도는 SimpleTestCase 만 둔다(save 는 mock).
"""
from datetime import datetime, timezone as dt_tz
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from core import models
from core.views import reception as rv


def _order(status, visited_at=None):
    o = models.ExamOrder(order_status=status, visited_at=visited_at)
    o.save = mock.Mock()
    return o


NOW = datetime(2026, 9, 27, 1, 0, tzinfo=dt_tz.utc)


class MarkVisitedTests(SimpleTestCase):
    def test_scheduled_는_requested_로_돌아가_간호_대기에_선다(self):
        o = _order("scheduled")
        self.assertTrue(rv.mark_visited(o, NOW, None))
        self.assertEqual(o.order_status, "requested")
        self.assertEqual(o.visited_at, NOW)
        self.assertIn("order_status", o.save.call_args.kwargs["update_fields"])

    def test_이미_온_오더는_처음_시각을_지킨다(self):
        first = datetime(2026, 9, 27, 0, 0, tzinfo=dt_tz.utc)
        o = _order("scheduled", visited_at=first)
        self.assertFalse(rv.mark_visited(o, NOW, None))
        self.assertEqual(o.visited_at, first)
        o.save.assert_not_called()

    def test_ordered_는_상태를_안_바꾼다(self):
        o = _order("ordered")
        rv.mark_visited(o, NOW, None)
        self.assertEqual(o.order_status, "ordered")
        self.assertNotIn("order_status", o.save.call_args.kwargs["update_fields"])


class QueueFilterTests(SimpleTestCase):
    def test_신청_큐는_내원한_requested_를_뺀다(self):
        sql = str(rv.ReservationRequestQueueView.queryset.query)
        self.assertIn('"visited_at" IS NULL', sql)

    def test_오늘_예약_찾기는_안_온_requested_scheduled_만(self):
        with mock.patch.object(models.ExamOrder.objects, "select_for_update") as sfu:
            rv._todays_booking(1, NOW)
        kwargs = sfu.return_value.filter.call_args.kwargs
        self.assertEqual(set(kwargs["order_status__in"]), {"requested", "scheduled"})
        self.assertTrue(kwargs["visited_at__isnull"])
        self.assertIn("scheduled_at__date", kwargs)


class PatientCancelTests(SimpleTestCase):
    def test_진행중_오더는_환자가_취소_못한다(self):
        from core.api.errors import ApiError
        order = _order("in_progress")
        req = mock.Mock()
        req.user.patient = SimpleNamespace()
        with mock.patch.object(models.ExamOrder.objects, "filter") as f:
            f.return_value.first.return_value = order
            with self.assertRaises(ApiError) as cm:
                rv.PatientReservationCancelView().post(req, pk=1)
        self.assertEqual(cm.exception.code, "RESERVATION_LOCKED")
        order.save.assert_not_called()
