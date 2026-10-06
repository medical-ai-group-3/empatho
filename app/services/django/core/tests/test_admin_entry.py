# -*- coding: utf-8 -*-
"""배포 인수 조건이 찌르는 자리 — /admin/ 과 로그인 화면이 뜨는가.

deploy.yml 이 /admin/ 에 200·302 를 요구한다. 여기가 500 이면 **배포가
통째로 실패한다** — 화면 넷을 아무리 잘 만들어도 서버에 못 올라간다.

⚠ 우리 화면 넷은 각자 시험이 있는데 /admin/ 만 없었다. 내비(_nav.html)를
  고치면 이 화면도 같이 바뀌는데, 그때 여기를 안 보면 배포에서야 안다.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")

    def test_로그인_화면이_뜬다(self):
        """익명으로 열리는 유일한 자리다."""
        res = self.client.get(reverse("admin:index"), follow=True)

        self.assertEqual(res.status_code, 200)

    def test_admin_첫_화면이_뜬다(self):
        """deploy.yml 의 인수 조건이 여기를 찌른다."""
        self.client.force_login(self.boss)

        res = self.client.get(reverse("admin:index"))

        self.assertEqual(res.status_code, 200)

    def test_첫_화면에도_내비가_붙는다(self):
        """Django 의 index.html 은 nav-sidebar 블록을 비워서 따로 넣어야 한다."""
        self.client.force_login(self.boss)

        res = self.client.get(reverse("admin:index"))

        self.assertContains(res, "ADMIN CONSOLE")
        # 내비 항목이 실제로 그려졌는지까지 본다 — 로고만 보면 조각이
        # 비어 있어도 통과한다
        self.assertContains(res, "e-nav-label")

    def test_표_묶음_다섯이_그대로다(self):
        self.client.force_login(self.boss)

        res = self.client.get(reverse("admin:index"))

        for group in ("계정", "환자", "검사", "판독", "병리"):
            self.assertContains(res, group)


class NavActiveTests(TestCase):
    """사이드바의 «지금 여기».

    전에는 우리가 만든 화면 셋만 열쇠를 넘겨서, 계정 승인과 DB 수정에는
    불이 안 들어왔다 — 그 둘은 Django 의 changelist 라 우리 뷰를 안 거친다.
    이제 주소로 정한다(_nav_key).

    ⚠ **「정확히 하나」를 본다.** 하나도 안 켜지면 어디 있는지를 잃고, 둘이
      켜지면 어느 쪽이 맞는지 모른다 — 둘 다 고장이라 둘 다 잡아야 한다.
    """

    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        from core.models import Account

        cls.account = Account.objects.create(
            login_id="nav_probe", role="nursing", account_status="pending")

    def setUp(self):
        self.client.force_login(self.boss)
        from core.admin import views

        views.probe_cache_clear()
        self.addCleanup(views.probe_cache_clear)

    def _on(self, path):
        """그 화면에서 켜진 항목들의 이름. 하나여야 한다."""
        res = self.client.get(path)
        self.assertEqual(res.status_code, 200, path)
        lit = [item["label"] for item in res.context["e_nav"] if item["on"]]
        self.assertEqual(len(lit), 1, "%s → %s" % (path, lit))
        return lit[0]

    def test_우리_화면_셋은_그대로다(self):
        self.assertEqual(self._on(reverse("admin:empatho_dashboard")), "대시보드")
        self.assertEqual(self._on(reverse("admin:empatho_status")), "서버 상태")
        self.assertEqual(self._on(reverse("admin:empatho_db")), "DB 조회")

    def test_DB_조회_상세도_DB_조회다(self):
        path = reverse("admin:empatho_db_detail", args=["account"])

        self.assertEqual(self._on(path), "DB 조회")

    def test_계정_승인_목록에_불이_들어온다(self):
        self.assertEqual(
            self._on(reverse("admin:core_account_changelist")), "계정 승인")

    def test_계정_상세와_추가도_계정_승인이다(self):
        """계정 하나를 열어 보는 동안 꺼지면 어디 있는지를 잃는다."""
        detail = reverse("admin:core_account_change", args=[self.account.pk])

        self.assertEqual(self._on(detail), "계정 승인")
        self.assertEqual(self._on(reverse("admin:core_account_add")), "계정 승인")

    def test_admin_첫_화면은_DB_수정이다(self):
        self.assertEqual(self._on(reverse("admin:index")), "DB 수정")

    def test_다른_표는_DB_수정이다(self):
        """계정 말고는 전부 여기로 묶인다 — 표마다 항목을 두면 내비가 길어진다."""
        self.assertEqual(
            self._on(reverse("admin:core_patient_changelist")), "DB 수정")

    def test_계정_표는_DB_수정이_아니다(self):
        """/admin/ 이 모든 주소의 앞머리라, 차례를 잘못 두면 여기가 깨진다."""
        res = self.client.get(reverse("admin:core_account_changelist"))
        lit = [item["label"] for item in res.context["e_nav"] if item["on"]]

        self.assertNotIn("DB 수정", lit)

    def test_켜진_항목에_표시가_둘_다_붙는다(self):
        """class 만 주면 눈으로만 보이고 읽어 주는 쪽에는 안 들린다."""
        res = self.client.get(reverse("admin:core_account_changelist"))

        self.assertContains(res, 'class="on" aria-current="page"')
