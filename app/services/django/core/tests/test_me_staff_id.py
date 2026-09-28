"""GET /me 가 의료진에게 staff_id 를 준다 — 목록 응답의 assigned_to ·
assessed_by · primary_staff 가 전부 staff 번호라 화면이 「내 것」을 이 번호로
가른다(09-28). 환자 응답은 그대로다."""

from django.test import TestCase

from core.tests.test_flow_0928_surgery_nursing import _client, _staff


class MeStaffIdTest(TestCase):
    def test_의료진은_staff_id_를_받는다(self):
        acc, staff = _staff("rad_me", "radiology")
        r = _client(acc).get("/api/v1/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["staff_id"], staff.staff_id)
