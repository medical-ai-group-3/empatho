"""관리자 · 계정 승인 → 상세 — 칸 이름이 한글이고 비밀번호 해시가 안 보인다."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Account, Staff


class AccountDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(username="cdss_admin", password="x")
        cls.acc = Account.objects.create(login_id="rad_new", role="radiology",
                                         password_hash="pbkdf2_sha256$secret",
                                         account_status="active", is_active=True)
        Staff.objects.create(account=cls.acc, full_name="김판독", staff_number="R-001")

    def setUp(self):
        self.client.force_login(self.boss)

    def test_한글_칸_이름과_묶음(self):
        html = self.client.get(
            reverse("admin:core_account_change", args=[self.acc.pk])).content.decode()
        for word in ("로그인 아이디", "부서", "승인 상태", "로그인 허용", "가입 신청",
                     "최근 로그인", "이름", "사번", "영상의학과", "승인됨"):
            self.assertIn(word, html)
        self.assertNotIn("pbkdf2_sha256$secret", html)
        self.assertNotIn("Password hash", html)
