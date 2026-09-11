# -*- coding: utf-8 -*-
"""봉투 · trace_id · 페이지네이션. 실제 요청을 태워서 확인한다.

이 모듈 자체를 ROOT_URLCONF 로 쓴다 — 검사용 뷰를 공개 라우팅에 넣지 않으려고.
"""

from django.test import SimpleTestCase, override_settings
from django.urls import path
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.envelope import KEYS
from core.api.errors import ApiError
from core.api.trace import HEADER


class _Base(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class _Ok(_Base):
    def get(self, request):
        return Response({"hello": "world"})


class _Paged(_Base):
    def get(self, request):
        return Response({"count": 2, "next": None, "previous": None,
                         "results": [{"id": 1}, {"id": 2}]})


class _ApiErrorView(_Base):
    def get(self, request):
        raise ApiError("REPORT_LOCKED")


class _ValidationView(_Base):
    def get(self, request):
        raise ValidationError({"patient_number": ["필수 항목입니다."]})


class _NotFoundView(_Base):
    def get(self, request):
        raise NotFound()


class _BoomView(_Base):
    def get(self, request):
        raise RuntimeError("예상하지 못한 것")


urlpatterns = [
    path("ok", _Ok.as_view()),
    path("paged", _Paged.as_view()),
    path("api-error", _ApiErrorView.as_view()),
    path("validation", _ValidationView.as_view()),
    path("not-found", _NotFoundView.as_view()),
    path("boom", _BoomView.as_view()),
]


@override_settings(ROOT_URLCONF=__name__)
class EnvelopeTests(SimpleTestCase):
    def test_성공_응답에_봉투가_씌워진다(self):
        body = self.client.get("/ok").json()
        self.assertEqual(set(body), KEYS)
        self.assertTrue(body["success"])
        self.assertEqual(body["data"], {"hello": "world"})
        self.assertIsNone(body["error"])

    def test_페이지네이션_덩어리는_data_안에_들어간다(self):
        body = self.client.get("/paged").json()
        self.assertEqual(set(body["data"]), {"count", "next", "previous", "results"})
        self.assertNotIn("results", body)      # 봉투와 나란히가 아니다

    def test_ApiError_는_코드와_상태가_함께_나온다(self):
        response = self.client.get("/api-error")
        body = response.json()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(set(body), KEYS)
        self.assertFalse(body["success"])
        self.assertIsNone(body["data"])
        self.assertEqual(body["error"]["code"], "REPORT_LOCKED")

    def test_DRF_검증오류는_VALIDATION_ERROR_로_옮겨진다(self):
        response = self.client.get("/validation")
        body = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        # 필드별 사유는 details 로 남는다
        self.assertIn("patient_number", body["error"]["details"])

    def test_404_도_봉투다(self):
        response = self.client.get("/not-found")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_잡히지_않은_예외도_봉투를_유지한다(self):
        with self.assertLogs("core.api.envelope", level="ERROR"):
            response = self.client.get("/boom")
        body = response.json()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(set(body), KEYS)
        self.assertEqual(body["error"]["code"], "INTERNAL_ERROR")


@override_settings(ROOT_URLCONF=__name__)
class TraceIdTests(SimpleTestCase):
    def test_봉투와_응답헤더의_trace_id_가_같다(self):
        response = self.client.get("/ok")
        self.assertEqual(response.json()["trace_id"], response[HEADER])
        self.assertTrue(response[HEADER])

    def test_요청마다_다른_값이다(self):
        first = self.client.get("/ok")[HEADER]
        second = self.client.get("/ok")[HEADER]
        self.assertNotEqual(first, second)

    def test_들어온_trace_id_를_이어받는다(self):
        given = "abcdef0123456789"
        response = self.client.get("/ok", headers={"x-trace-id": given})
        self.assertEqual(response[HEADER], given)
        self.assertEqual(response.json()["trace_id"], given)

    def test_모양이_이상하면_새로_만든다(self):
        response = self.client.get("/ok", headers={"x-trace-id": "너무짧음"})
        self.assertNotEqual(response[HEADER], "너무짧음")

    def test_실패_응답에도_trace_id_가_있다(self):
        response = self.client.get("/api-error")
        self.assertEqual(response.json()["trace_id"], response[HEADER])


class ApiNotFoundTests(SimpleTestCase):
    """/api/v1 아래 없는 경로도 봉투로 돌아온다 — 실제 라우팅으로 확인."""

    def test_없는_경로가_NOT_FOUND_봉투다(self):
        response = self.client.get("/api/v1/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["content-type"], "application/json")
        body = response.json()
        self.assertEqual(set(body), KEYS)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

    def test_메서드가_달라도_봉투다(self):
        response = self.client.post("/api/v1/nope/deeper")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_health_는_그대로_동작한다(self):
        # catch-all 이 앞선 경로를 잡아먹지 않는다
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
