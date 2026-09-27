# -*- coding: utf-8 -*-
"""09-27 간호(원무 통합) 백엔드 점검 — 500 · N+1 · 거르기 · 시간대.

SimpleTestCase 묶음은 DB 없이 돈다(쿼리 문자열 검증 · 시간대 · 단계 판정).
TestCase 묶음은 Postgres 가 있어야 돈다.
"""
from datetime import date, datetime, timezone as dt_tz
from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIClient

from core import models, serializers
from core.api.auth import issue_access
from core.api.errors import ApiError
from core.views import reception as rv


# ── DB 없이 ─────────────────────────────────────────────────────────────

class ParamBoundTests(SimpleTestCase):
    def test_날짜만_온_to_는_다음날_미만이다(self):
        bound, exclusive = rv._param_bound("scheduled_to", "2026-09-30", end=True)
        self.assertTrue(exclusive)
        local = timezone.localtime(bound)
        self.assertEqual((local.year, local.month, local.day, local.hour), (2026, 10, 1, 0))

    def test_날짜만_온_from_은_그날_0시_이상이다(self):
        bound, exclusive = rv._param_bound("scheduled_from", "2026-09-01")
        self.assertFalse(exclusive)
        self.assertEqual(timezone.localtime(bound).day, 1)
        self.assertEqual(timezone.localtime(bound).hour, 0)

    def test_시각이_붙으면_그대로_이하(self):
        bound, exclusive = rv._param_bound("scheduled_to", "2026-09-30T23:59:59", end=True)
        self.assertFalse(exclusive)
        self.assertTrue(timezone.is_aware(bound))
        self.assertEqual(timezone.localtime(bound).hour, 23)

    def test_틀린_값은_400(self):
        for bad in ("어제", "2026-13-01", "2026-09-31T25:00"):
            with self.assertRaises(ApiError) as cm:
                rv._param_bound("scheduled_from", bad)
            self.assertEqual(cm.exception.code, "VALIDATION_ERROR")


def _query_view(params, action="list"):
    view = rv.ExamOrderQueryView()
    view.action = action
    view.request = Request(RequestFactory().get("/api/v1/exam-orders", params))
    view.format_kwarg = None
    return view


class ExamOrderQueryParamTests(SimpleTestCase):
    """쿼리셋은 만들기만 하고 평가하지 않는다 — DB 가 필요 없다."""

    def test_모르는_정렬은_500_이_아니라_400(self):
        with self.assertRaises(ApiError) as cm:
            _query_view({"ordering": "patient__pii__name; drop"}).get_queryset()
        self.assertEqual(cm.exception.code, "VALIDATION_ERROR")

    def test_허용_정렬은_통과(self):
        for o in ("visited_at", "-scheduled_at", "exam_order_id"):
            _query_view({"ordering": o}).get_queryset()

    def test_날짜가_아닌_scheduled_on_은_400(self):
        with self.assertRaises(ApiError):
            _query_view({"scheduled_on": "내일"}).get_queryset()

    def test_숫자가_아닌_patient_는_400(self):
        with self.assertRaises(ApiError):
            _query_view({"patient": "abc"}).get_queryset()

    def test_assigned_는_none_yes_만(self):
        with self.assertRaises(ApiError):
            _query_view({"assigned": "maybe"}).get_queryset()

    def test_assigned_none_은_주치의_없는_환자만(self):
        qs = _query_view({"status": "requested", "visited": "yes",
                          "assigned": "none"}).get_queryset()
        where = str(qs.query.where)
        self.assertIn("primary_staff", where)
        self.assertIn("ISNULL", where.upper())

    def test_목록은_patient_pii_주치의를_붙여_온다(self):
        qs = _query_view({}).get_queryset()
        self.assertEqual(qs.query.select_related,
                         {"patient": {"pii": {}, "primary_staff": {}}})

    def test_단건은_목록_거르기를_안_건다(self):
        qs = _query_view({"status": "requested", "ordering": "bogus"},
                         action="retrieve").get_queryset()
        self.assertFalse(qs.query.where.children)


def _patient_view(params, user):
    view = rv.PatientViewSet()
    view.action = "list"
    req = Request(RequestFactory().get("/api/v1/patients/", params))
    req.user = user
    view.request = req
    view.format_kwarg = None
    view.kwargs = {}
    return view


class PatientListParamTests(SimpleTestCase):
    def setUp(self):
        # OwnedOnlyMixin 은 role 을 본다 — 간호(own_only 아님)
        self.user = SimpleNamespace(role="nursing", staff=SimpleNamespace(pk=7),
                                    is_authenticated=True)

    def test_날짜가_아닌_검색어에_생년월일_null_조건이_안_붙는다(self):
        qs = _patient_view({"q": "김"}, self.user).get_queryset()
        self.assertNotIn("birth_date", str(qs.query.where))

    def test_날짜_검색어는_생년월일로도_찾는다(self):
        qs = _patient_view({"q": "1980-01-02"}, self.user).get_queryset()
        self.assertIn("birth_date", str(qs.query.where))

    def test_primary_staff_me_와_status_waiting_을_함께_건다(self):
        user = SimpleNamespace(role="surgery", is_authenticated=True,
                               staff=models.Staff(staff_id=7))
        qs = _patient_view({"primary_staff": "me", "status": "waiting"}, user).get_queryset()
        where = str(qs.query.where)
        self.assertIn("primary_staff", where)
        self.assertIn("EXISTS", where.upper())

    def test_primary_staff_번호와_none(self):
        qs = _patient_view({"primary_staff": "12"}, self.user).get_queryset()
        self.assertIn("primary_staff", str(qs.query.where))
        qs = _patient_view({"primary_staff": "none"}, self.user).get_queryset()
        self.assertIn("ISNULL", str(qs.query.where).upper())

    def test_primary_staff_틀린_값은_400(self):
        with self.assertRaises(ApiError):
            _patient_view({"primary_staff": "kim"}, self.user).get_queryset()


class TodayStageTests(SimpleTestCase):
    def _o(self, status, primary=None, assigned=None, has_study=False):
        return SimpleNamespace(order_status=status, assigned_to_id=assigned,
                               has_study=has_study,
                               patient=SimpleNamespace(primary_staff_id=primary))

    def test_간호_문진과_외래_진료를_가른다(self):
        stage, code, detail = rv.PatientTodayStatusView._stage(self._o("requested"))
        self.assertEqual((stage, code, detail), ("접수 대기", "nursing", "간호·문진"))
        stage, code, detail = rv.PatientTodayStatusView._stage(self._o("requested", primary=3))
        # stage 는 예전 글자 그대로 — 화면 STAGE 표가 이것으로 찾는다
        self.assertEqual((stage, code, detail), ("접수 대기", "outpatient", "외래 진료"))

    def test_영상_단계는_예전_글자_그대로(self):
        S = rv.PatientTodayStatusView._stage
        self.assertEqual(S(self._o("ordered"))[0], "영상의학과 대기")
        self.assertEqual(S(self._o("accepted", assigned=1))[0], "영상의학과 촬영중")
        self.assertEqual(S(self._o("in_progress", assigned=1, has_study=True))[0], "AI 분석중")

    def test_취소된_오더는_촬영중이_아니다(self):
        self.assertEqual(rv.PatientTodayStatusView._stage(
            self._o("cancelled", assigned=1))[1], "cancelled")


class ExamOrderSerializerTests(SimpleTestCase):
    def _order(self, visited_at, birth):
        patient = models.Patient(patient_id=1, patient_number="P1")
        models.PatientPii(patient=patient, name="홍길동", birth_date=birth)
        return models.ExamOrder(exam_order_id=1, patient=patient,
                                order_status="requested", visited_at=visited_at)

    def test_나이는_한국_날짜로_센다(self):
        # 09-27 01:00 KST = 09-26 16:00 UTC. 생일이 09-27 이면 이미 한 살 더 먹었다.
        visited = datetime(2026, 9, 26, 16, 0, tzinfo=dt_tz.utc)
        data = serializers.ExamOrderSerializer(self._order(visited, date(1980, 9, 27))).data
        self.assertEqual(data["age"], 46)

    def test_주치의_칸이_있다(self):
        data = serializers.ExamOrderSerializer(
            self._order(timezone.now(), date(1980, 1, 1))).data
        self.assertIn("primary_staff", data)
        self.assertIn("primary_staff_name", data)
        self.assertIsNone(data["primary_staff"])

    def test_환자_목록에도_주치의_칸이_있다(self):
        fields = serializers.PatientListSerializer().fields
        self.assertIn("primary_staff", fields)
        self.assertIn("primary_staff_name", fields)


class FollowupSerializerValidationTests(SimpleTestCase):
    def test_통화_결과는_정해진_값만(self):
        s = serializers.FollowupCallSerializer(data={"call_result": "아무거나"})
        self.assertFalse(s.is_valid())
        self.assertIn("call_result", s.errors)

    def test_통화_메모는_250자까지(self):
        s = serializers.FollowupCallSerializer(data={"call_result": "연결", "call_note": "가" * 251})
        self.assertFalse(s.is_valid())

    def test_범용_patch_의_status_는_정해진_값만(self):
        s = serializers.FollowupUpdateSerializer(data={"status": "done", "closed_reason": "x"})
        self.assertFalse(s.is_valid())
        s = serializers.FollowupUpdateSerializer(data={"status": "resolved", "closed_reason": "x"})
        self.assertTrue(s.is_valid(), s.errors)

    def test_회차는_1_이상(self):
        s = serializers.FollowupCreateSerializer(
            data={"patient_id": 1, "round_no": 0, "due_at": "2026-12-01T00:00:00Z"})
        with mock.patch.object(models.Patient.objects, "filter") as f:
            f.return_value.exists.return_value = True
            self.assertFalse(s.is_valid())
        self.assertIn("round_no", s.errors)


# ── DB 필요 (Postgres) ─────────────────────────────────────────────────

def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class NursingEndpointTests(TestCase):
    def setUp(self):
        self.account = models.Account.objects.create(
            login_id="nur-0927", role="nursing", account_status="active", is_active=True)
        self.staff = models.Staff.objects.create(
            account=self.account, staff_number="NUR-0927", full_name="간호 테스트")
        self.surgeon = models.Staff.objects.create(
            account=models.Account.objects.create(
                login_id="sur-0927", role="surgery", account_status="active", is_active=True),
            staff_number="SUR-0927", full_name="김서연")
        self.patient = models.Patient.objects.create(patient_number="P-0927-1")
        models.PatientPii.objects.create(patient=self.patient, name="환자일",
                                         birth_date=date(1970, 1, 1), phone="010-0927-0001")
        self.c = _client_for(self.account)

    def test_접수를_두_번_눌러도_한_줄(self):
        r1 = self.c.post("/api/v1/exam-orders/checkin", {"patient_id": self.patient.pk}, format="json")
        r2 = self.c.post("/api/v1/exam-orders/checkin", {"patient_id": self.patient.pk}, format="json")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["data"]["exam_order_id"], r2.json()["data"]["exam_order_id"])

    def test_없는_환자_접수는_400(self):
        r = self.c.post("/api/v1/exam-orders/checkin", {"patient_id": 999999}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_없는_환자_예약은_400(self):
        r = self.c.post("/api/v1/exam-orders/schedule",
                        {"patient_id": 999999, "scheduled_at": "2026-10-01T10:00:00+09:00"},
                        format="json")
        self.assertEqual(r.status_code, 400)

    def test_배정된_환자는_assigned_none_에서_빠진다(self):
        self.c.post("/api/v1/exam-orders/checkin", {"patient_id": self.patient.pk}, format="json")
        q = "/api/v1/exam-orders?status=requested&visited=yes&assigned=none"
        self.assertEqual(self.c.get(q).json()["data"]["count"], 1)
        r = self.c.patch(f"/api/v1/patients/{self.patient.pk}/",
                         {"primary_staff": self.surgeon.pk}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get(q).json()["data"]["count"], 0)
        row = self.c.get("/api/v1/exam-orders?assigned=yes").json()["data"]["results"][0]
        self.assertEqual(row["primary_staff"], self.surgeon.pk)
        self.assertEqual(row["primary_staff_name"], "김서연")

    def test_오늘_현황이_외래_진료를_가른다(self):
        self.c.post("/api/v1/exam-orders/checkin", {"patient_id": self.patient.pk}, format="json")
        rows = self.c.get("/api/v1/patients/today-status").json()["data"]
        self.assertEqual(rows[0]["stage_code"], "nursing")
        self.patient.primary_staff = self.surgeon
        self.patient.save()
        rows = self.c.get("/api/v1/patients/today-status").json()["data"]
        self.assertEqual(rows[0]["stage"], "접수 대기")
        self.assertEqual(rows[0]["stage_code"], "outpatient")
        self.assertEqual(rows[0]["stage_detail"], "외래 진료")

    def test_달력_끝날_날짜만_보내도_그날_예약이_온다(self):
        at = timezone.make_aware(datetime(2026, 9, 30, 15, 0))
        models.ExamOrder.objects.create(patient=self.patient, order_status="scheduled",
                                        scheduled_at=at)
        r = self.c.get("/api/v1/exam-orders?scheduled_from=2026-09-01"
                       "&scheduled_to=2026-09-30&ordering=scheduled_at")
        self.assertEqual(r.json()["data"]["count"], 1)

    def test_잘못된_쿼리는_400(self):
        for q in ("ordering=nope", "scheduled_on=abc", "patient=x", "scheduled_from=zz"):
            r = self.c.get("/api/v1/exam-orders?" + q)
            self.assertEqual(r.status_code, 400, q)

    def test_없는_번호는_404(self):
        self.assertEqual(self.c.patch("/api/v1/exam-orders/999999/note",
                                      {"note": "x"}, format="json").status_code, 404)
        self.assertEqual(self.c.patch("/api/v1/exam-orders/999999/confirm",
                                      {"scheduled_at": "2026-10-01T10:00:00+09:00"},
                                      format="json").status_code, 404)
        self.assertEqual(self.c.patch("/api/v1/followups/999999/call",
                                      {"call_result": "연결"}, format="json").status_code, 404)
        self.assertEqual(self.c.patch("/api/v1/patients/999999/questionnaire/",
                                      {}, format="json").status_code, 404)

    def test_등록_동시_충돌은_500_이_아니라_400(self):
        from django.db import IntegrityError
        with mock.patch.object(serializers.PatientRegisterSerializer, "create",
                               side_effect=IntegrityError("dup")):
            r = self.c.post("/api/v1/patients/register",
                            {"name": "새환자", "birth_date": "1990-01-01",
                             "phone": "010-0927-9999"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.json()["error"]["details"])

    def test_생년월일_없는_환자가_엉뚱한_검색에_안_걸린다(self):
        p = models.Patient.objects.create(patient_number="P-0927-NB")
        models.PatientPii.objects.create(patient=p, name="무생일", phone="010-0927-0002")
        rows = self.c.get("/api/v1/patients/?q=환자일").json()["data"]["results"]
        self.assertEqual([r["patient_id"] for r in rows], [self.patient.pk])

    def test_범용_followup_patch_에_모르는_status_는_400(self):
        f = models.Followup.objects.create(patient=self.patient, round_no=1, status="open")
        r = self.c.patch(f"/api/v1/followups/{f.pk}/",
                         {"status": "done", "closed_reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_내원_확인을_다시_눌러도_처음_시각을_지킨다(self):
        o = models.ExamOrder.objects.create(patient=self.patient, order_status="scheduled",
                                            scheduled_at=timezone.now())
        self.c.post("/api/v1/visits/today/", {"exam_order_id": o.pk}, format="json")
        o.refresh_from_db()
        first = o.visited_at
        self.c.post("/api/v1/visits/today/", {"exam_order_id": o.pk}, format="json")
        o.refresh_from_db()
        self.assertEqual(o.visited_at, first)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.first_visited_at, first)
