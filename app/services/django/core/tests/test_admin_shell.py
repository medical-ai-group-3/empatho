# -*- coding: utf-8 -*-
"""admin 껍데기 — 내비와 화면 틀 (2026-09-25 admin-redesign 시안).

시안에는 머리띠도 빵부스러기도 없고 이름이 내비 로고 하나뿐이다. 그 둘을
걷는 규칙이 몸통 클래스(e-full)에 걸려 있는데, **표 화면 스물두 장은 시안에
없는 자리라 그대로 둬야 한다** — 거기 로그아웃과 빵부스러기가 있고, 전 화면에서
없애면 나갈 길이 사라진다. 그 경계가 이 파일의 주제다.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.admin import views
from core.adminsite import NAV, _nav
from core.models import Account, Staff

OURS = ["admin:empatho_dashboard", "admin:empatho_status", "admin:empatho_db"]


class NavTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")

    def setUp(self):
        self.client.force_login(self.boss)
        views.probe_cache_clear()
        self.addCleanup(views.probe_cache_clear)

    def _get(self, name):
        return self.client.get(reverse(name))

    # ── 내비 ────────────────────────────────────────────────────
    def test_다섯_항목이_시안_순서대로다(self):
        """승인 큐가 위에 있어야 한다 — 관리자가 오는 이유가 거의 그것이다."""
        self.assertEqual([i["label"] for i in _nav()],
                         ["대시보드", "서버 상태", "계정 승인", "DB 조회", "DB 수정"])

    def test_항목마다_아이콘_열쇠가_있다(self):
        """열쇠가 없으면 템플릿이 연필 아이콘(기본값)으로 떨어진다."""
        keys = [i["key"] for i in _nav()]

        self.assertEqual(keys, [k for k, _, _, _ in NAV])
        self.assertEqual(len(set(keys)), len(keys), "열쇠가 겹치면 아이콘도 겹친다")

    def test_로고와_안내_카드가_전_화면에_있다(self):
        for name in OURS:
            with self.subTest(name):
                res = self._get(name)

                self.assertContains(res, "ADMIN CONSOLE")
                self.assertContains(res, "학원 내부망 전용")
                self.assertContains(res, "외부(ts.net)에서는 열리지 않습니다")

    def test_지금_있는_자리에_표가_선다(self):
        res = self._get("admin:empatho_status")

        self.assertContains(res, 'aria-current="page"')

    # ── 배지 ────────────────────────────────────────────────────
    def test_대기가_없으면_배지를_안_단다(self):
        """「0」이 붙어 있으면 눈이 그것도 읽는다. 시안도 0 일 때로 그려져 있다."""
        self.assertIsNone(
            [i for i in _nav() if i["key"] == "accounts"][0]["badge"])

    def test_대기가_있으면_그_수가_붙는다(self):
        account = Account.objects.create(login_id="waiting", role="nursing",
                                         account_status="pending")
        Staff.objects.create(account=account, full_name="대기", staff_number="S-1")

        self.assertEqual(
            [i for i in _nav() if i["key"] == "accounts"][0]["badge"], 1)

    def test_환자는_승인_대상이_아니라_안_센다(self):
        Account.objects.create(login_id="p1", role="patient",
                               account_status="pending")

        self.assertIsNone(
            [i for i in _nav() if i["key"] == "accounts"][0]["badge"])

    # ── 껍데기 경계 ─────────────────────────────────────────────
    def test_우리_화면은_머리띠를_걷는_표를_단다(self):
        # 계정 승인도 시안 넉 장 중 하나라 같이 건다(admin/core/account/)
        for name in OURS + ["admin:core_account_changelist"]:
            with self.subTest(name):
                self.assertContains(self._get(name), "e-full")

    def test_시안에_없는_표_화면은_그_표를_안_단다(self):
        """머리띠를 같이 걷으면 로그아웃과 빵부스러기가 사라진다.

        스물한 표는 시안에 없는 자리라 Django 것을 그대로 둔다.
        """
        res = self.client.get(reverse("admin:core_patient_changelist"))

        self.assertNotContains(res, "e-full")
        self.assertContains(res, "logout-form")
