# -*- coding: utf-8 -*-
"""09-28 예약 판 — 같은 사람 · 같은 날 예약이 또 서던 것, 변경 저장.

화면(간호 「예약 관리」)에서 **이미 내원한 예약**을 눌러 [예약] 을 누르면
같은 날 · 같은 시각에 새 예약이 또 섰다. ea6b2c4 의 중복 검사가 「안 온
예약」만 봐서 내원한 것은 못 막았다. 옮기기(reschedule) · 신청 확정
(confirm) · 앱 신청도 같은 날 둘을 만들 수 있었다.

TestCase 라 Postgres 가 있어야 돈다. 날짜는 오늘에서 떨어뜨려 잡는다 —
박아 둔 날짜는 그날이 지나면 뜻이 바뀐다.
"""
from datetime import datetime, time, timedelta, timezone as dt_tz

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core import models
from core.api.auth import issue_access


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


def _at(days, hh=9, mm=30):
    d = timezone.localdate() + timedelta(days=days)
    return timezone.make_aware(datetime.combine(d, time(hh, mm)))


def _iso(dt):
    return timezone.localtime(dt).isoformat()


class SameDayReservationTests(TestCase):
    def setUp(self):
        account = models.Account.objects.create(
            login_id="nur-0928", role="nursing", account_status="active", is_active=True)
        models.Staff.objects.create(account=account, staff_number="NUR-0928",
                                    full_name="간호 예약")
        self.patient = models.Patient.objects.create(patient_number="P-0928-SD")
        self.other = models.Patient.objects.create(patient_number="P-0928-OT")
        self.c = _client_for(account)

    def _book(self, when, patient=None):
        return self.c.post("/api/v1/exam-orders/schedule",
                           {"patient_id": (patient or self.patient).pk,
                            "scheduled_at": _iso(when)}, format="json")

    def _count(self):
        return (models.ExamOrder.objects.filter(patient=self.patient)
                .exclude(order_status="cancelled").count())

    # ── 새로 만들기 ────────────────────────────────────────────────
    def test_같은_날_다른_시각도_409_이고_그_예약_번호를_준다(self):
        r1 = self._book(_at(10, 9, 30))
        self.assertEqual(r1.status_code, 201)
        r2 = self._book(_at(10, 14, 0))
        self.assertEqual(r2.status_code, 409)
        err = r2.json()["error"]
        self.assertEqual(err["code"], "DUPLICATE_RESERVATION")
        self.assertEqual(err["details"]["exam_order_id"], r1.json()["data"]["exam_order_id"])
        self.assertTrue(err["details"]["editable"])
        self.assertEqual(self._count(), 1)

    def test_내원한_예약이_있는_날에도_새로_안_선다(self):
        # 화면 사고 그대로 — 내원 처리된(visited · requested 로 돌아간) 예약을
        # 눌러 같은 날 · 같은 시각으로 [예약]
        when = _at(0, 9, 30)
        models.ExamOrder.objects.create(patient=self.patient, order_status="requested",
                                        scheduled_at=when, visited_at=timezone.now())
        r = self._book(when)
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()["error"]["details"]["editable"])
        self.assertIn("내원", r.json()["error"]["message"])
        self.assertEqual(self._count(), 1)

    def test_진료가_끝난_날에도_새로_안_선다(self):
        when = _at(1)
        models.ExamOrder.objects.create(patient=self.patient, order_status="completed",
                                        scheduled_at=when, visited_at=when)
        self.assertEqual(self._book(when).status_code, 409)

    def test_취소한_예약은_막지_않는다(self):
        when = _at(10)
        models.ExamOrder.objects.create(patient=self.patient, order_status="cancelled",
                                        scheduled_at=when)
        self.assertEqual(self._book(when).status_code, 201)

    def test_다른_날_다른_사람은_된다(self):
        self.assertEqual(self._book(_at(10)).status_code, 201)
        self.assertEqual(self._book(_at(11)).status_code, 201)
        self.assertEqual(self._book(_at(10), patient=self.other).status_code, 201)

    def test_날짜는_병원_시간대로_가른다(self):
        # 같은 날 00:30 KST = 전날 15:30 UTC. UTC 로 가르면 다른 날로 보여 또 선다
        self.assertEqual(self._book(_at(10, 8, 0)).status_code, 201)
        early = _at(10, 0, 30)
        r = self.c.post("/api/v1/exam-orders/schedule",
                        {"patient_id": self.patient.pk,
                         "scheduled_at": early.astimezone(dt_tz.utc).isoformat()},
                        format="json")
        self.assertEqual(r.status_code, 409)

    # ── 변경 저장 ──────────────────────────────────────────────────
    def test_변경_저장이_날짜와_시각을_바꾼다(self):
        oid = self._book(_at(10, 9, 30)).json()["data"]["exam_order_id"]
        to = _at(12, 14, 0)
        r = self.c.patch(f"/api/v1/exam-orders/{oid}/reschedule",
                         {"scheduled_at": _iso(to)}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["exam_order_id"], oid)
        o = models.ExamOrder.objects.get(pk=oid)
        self.assertEqual(o.scheduled_at, to)
        self.assertEqual(o.order_status, "scheduled")
        self.assertEqual(self._count(), 1)
        # 판(GET /exam-orders)에도 옮긴 날에 한 줄로 뜬다
        day = to.date().isoformat()
        rows = self.c.get(f"/api/v1/exam-orders?scheduled_from={day}T00:00:00"
                          f"&scheduled_to={day}T23:59:59&ordering=scheduled_at"
                          ).json()["data"]["results"]
        self.assertEqual([x["exam_order_id"] for x in rows], [oid])

    def test_같은_날_안에서_시각만_옮기는_것은_된다(self):
        oid = self._book(_at(10, 9, 30)).json()["data"]["exam_order_id"]
        r = self.c.patch(f"/api/v1/exam-orders/{oid}/reschedule",
                         {"scheduled_at": _iso(_at(10, 15, 0))}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(timezone.localtime(
            models.ExamOrder.objects.get(pk=oid).scheduled_at).hour, 15)

    def test_다른_예약이_있는_날로는_못_옮긴다(self):
        a = self._book(_at(10)).json()["data"]["exam_order_id"]
        b = self._book(_at(11)).json()["data"]["exam_order_id"]
        r = self.c.patch(f"/api/v1/exam-orders/{b}/reschedule",
                         {"scheduled_at": _iso(_at(10, 16, 0))}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["details"]["exam_order_id"], a)
        self.assertEqual(models.ExamOrder.objects.get(pk=b).scheduled_at, _at(11))

    def test_내원한_예약은_못_고친다(self):
        o = models.ExamOrder.objects.create(patient=self.patient, order_status="requested",
                                            scheduled_at=_at(0), visited_at=timezone.now())
        r = self.c.patch(f"/api/v1/exam-orders/{o.pk}/reschedule",
                         {"scheduled_at": _iso(_at(3))}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "RESERVATION_LOCKED")

    def test_없는_예약_변경은_404(self):
        r = self.c.patch("/api/v1/exam-orders/999999/reschedule",
                         {"scheduled_at": _iso(_at(3))}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_취소하면_그날_다시_잡을_수_있다(self):
        oid = self._book(_at(10)).json()["data"]["exam_order_id"]
        self.assertEqual(self.c.post(f"/api/v1/exam-orders/{oid}/cancel", {},
                                     format="json").status_code, 200)
        self.assertEqual(self._book(_at(10, 11, 0)).status_code, 201)

    # ── 앱 신청 확정 ───────────────────────────────────────────────
    def test_신청을_다른_예약이_있는_날로_확정하면_409(self):
        self._book(_at(10))
        ask = models.ExamOrder.objects.create(patient=self.patient, order_status="requested",
                                              scheduled_at=_at(12))
        r = self.c.patch(f"/api/v1/exam-orders/{ask.pk}/confirm",
                         {"scheduled_at": _iso(_at(10, 13, 0))}, format="json")
        self.assertEqual(r.status_code, 409)
        ask.refresh_from_db()
        self.assertEqual(ask.order_status, "requested")

    def test_신청을_제_날에_확정하는_것은_된다(self):
        ask = models.ExamOrder.objects.create(patient=self.patient, order_status="requested",
                                              scheduled_at=_at(12))
        r = self.c.patch(f"/api/v1/exam-orders/{ask.pk}/confirm",
                         {"scheduled_at": _iso(_at(12, 10, 0))}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["order_status"], "scheduled")


class PatientAppSameDayTests(TestCase):
    """앱 신청(POST /me/reservation-requests)도 같은 날 둘을 안 세운다."""

    def setUp(self):
        self.account = models.Account.objects.create(
            login_id="pt-0928", role="patient", account_status="active", is_active=True)
        self.patient = models.Patient.objects.create(patient_number="P-0928-APP",
                                                     account=self.account)
        self.c = _client_for(self.account)

    def test_같은_날_두_번_신청하면_409(self):
        d = (timezone.localdate() + timedelta(days=9)).isoformat()
        r1 = self.c.post("/api/v1/me/reservation-requests/",
                         {"date": d, "time": "10:00"}, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        r2 = self.c.post("/api/v1/me/reservation-requests/",
                         {"date": d, "time": "14:00"}, format="json")
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(models.ExamOrder.objects.filter(patient=self.patient).count(), 1)
