# -*- coding: utf-8 -*-
"""09-27 간호 → 유방외과 인계 — exam_order.handed_at · handed_to.

PATCH /exam-orders/{id}/handoff {staff_id} 가 오더에 인계를 남기고 환자의
primary_staff 도 바꾼다. 간호 대기(handed=none) · 방문 모니터링 stage ·
유방외과 대기(status=waiting&primary_staff=me)가 이 칸으로 갈린다.

SimpleTestCase 는 DB 없이 돈다. TestCase 는 PostgreSQL 이 있어야 돈다.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import models, serializers
from core.api.errors import ApiError
from core.views import reception as rv


class HandoffRouteTests(SimpleTestCase):
    def test_경로가_인계_뷰로_간다(self):
        url = reverse("exam-order-handoff", kwargs={"pk": 7})
        self.assertTrue(url.endswith("/exam-orders/7/handoff"))
        self.assertIs(resolve(url).func.cls, rv.ExamOrderHandoffView)

    def test_리소스와_권한은_이웃과_같다(self):
        self.assertEqual(rv.ExamOrderHandoffView.resource, "exam_order")
        self.assertEqual(rv.ExamOrderHandoffView.permission_classes,
                         rv.ExamOrderRescheduleView.permission_classes)


class HandoffSerializerTests(SimpleTestCase):
    def test_응답에_인계_칸이_실린다(self):
        fields = serializers.ExamOrderSerializer().fields
        for name in ("handed_at", "handed_to", "handed_to_name"):
            self.assertIn(name, fields)

    def test_staff_id_는_필수다(self):
        s = serializers.ExamOrderHandoffSerializer(data={})
        self.assertFalse(s.is_valid())
        self.assertIn("staff_id", s.errors)

    def test_숫자가_아니면_400(self):
        s = serializers.ExamOrderHandoffSerializer(data={"staff_id": "abc"})
        self.assertFalse(s.is_valid())
        self.assertIn("staff_id", s.errors)


class HandedParamTests(SimpleTestCase):
    def _qs(self, **params):
        view = rv.ExamOrderQueryView()
        view.action = "list"
        view.request = SimpleNamespace(query_params=params)
        return view.get_queryset()

    def test_handed_none_yes(self):
        self.assertIn('"handed_at" IS NULL', str(self._qs(handed="none").query))
        self.assertIn('"handed_at" IS NOT NULL', str(self._qs(handed="yes").query))

    def test_모르는_값은_400(self):
        with self.assertRaises(ApiError):
            self._qs(handed="maybe")


class StageTests(SimpleTestCase):
    def _o(self, handed_at=None, primary_staff_id=None, status="requested"):
        return SimpleNamespace(order_status=status, handed_at=handed_at,
                               assigned_to_id=None,
                               patient=SimpleNamespace(primary_staff_id=primary_staff_id))

    def test_주치의만_있고_안_보냈으면_간호다(self):
        # 재진 환자 — 주치의는 있지만 이번 방문은 아직 안 보냈다
        stage = rv.PatientTodayStatusView._stage(self._o(primary_staff_id=3))
        self.assertEqual(stage[1], "nursing")

    def test_보냈으면_외래_진료(self):
        stage = rv.PatientTodayStatusView._stage(self._o(handed_at=timezone.now()))
        self.assertEqual(stage[1], "outpatient")

    def test_다른_단계는_그대로(self):
        o = self._o(status="ordered", handed_at=timezone.now())
        self.assertEqual(rv.PatientTodayStatusView._stage(o)[1], "radiology_wait")
        o = self._o(status="cancelled")
        self.assertEqual(rv.PatientTodayStatusView._stage(o)[1], "cancelled")


class HandoffDbTests(TestCase):
    """PostgreSQL 이 있어야 돈다."""

    @classmethod
    def setUpTestData(cls):
        def staff(login, role, name):
            acc = models.Account.objects.create(login_id=login, role=role, is_active=True)
            return acc, models.Staff.objects.create(account=acc, full_name=name,
                                                    staff_number="S-" + login)
        cls.nurse_acc, cls.nurse = staff("hn1", "nursing", "간호")
        cls.surg_acc, cls.surgeon = staff("hs1", "surgery", "외과")
        cls.surg2_acc, cls.surgeon2 = staff("hs2", "surgery", "외과2")
        _, cls.radio = staff("hr1", "radiology", "영상")
        cls.patient = models.Patient.objects.create(patient_number="H_0001",
                                                    primary_staff=cls.surgeon)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.nurse_acc)
        self.order = models.ExamOrder.objects.create(
            patient=self.patient, order_status="requested",
            visited_at=timezone.now())

    def _handoff(self, staff_id, pk=None):
        return self.client.patch(f"/api/v1/exam-orders/{pk or self.order.pk}/handoff",
                                 {"staff_id": staff_id}, format="json")

    def test_인계가_오더와_환자에_남는다(self):
        r = self._handoff(self.surgeon2.pk)
        self.assertEqual(r.status_code, 200)
        self.order.refresh_from_db()
        self.patient.refresh_from_db()
        self.assertIsNotNone(self.order.handed_at)
        self.assertEqual(self.order.handed_to_id, self.surgeon2.pk)
        self.assertEqual(self.patient.primary_staff_id, self.surgeon2.pk)

    def test_외과가_아니면_400(self):
        self.assertEqual(self._handoff(self.radio.pk).status_code, 400)

    def test_없는_직원이면_400(self):
        self.assertEqual(self._handoff(999999).status_code, 400)

    def test_없는_오더면_404(self):
        self.assertEqual(self._handoff(self.surgeon.pk, pk=999999).status_code, 404)

    def test_취소된_오더는_409(self):
        self.order.order_status = "cancelled"
        self.order.save()
        self.assertEqual(self._handoff(self.surgeon.pk).status_code, 409)

    def test_유방외과_대기는_인계받은_것만(self):
        c = APIClient()
        c.force_authenticate(user=self.surg_acc)
        url = "/api/v1/patients/?primary_staff=me&status=waiting"
        # 주치의지만 아직 안 보냄 — 안 뜬다
        self.assertNotIn("H_0001", c.get(url).content.decode())
        self._handoff(self.surgeon.pk)
        self.assertIn("H_0001", c.get(url).content.decode())

    def test_간호_대기에서_빠진다(self):
        url = "/api/v1/exam-orders?status=requested&visited=yes&visited_on=today&handed=none"
        self.assertIn(f'"exam_order_id":{self.order.pk}',
                      self.client.get(url).content.decode().replace(" ", ""))
        self._handoff(self.surgeon.pk)
        self.assertNotIn(f'"exam_order_id":{self.order.pk}',
                         self.client.get(url).content.decode().replace(" ", ""))
