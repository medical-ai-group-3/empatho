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
        self.assertContains(res, "학원 내부망 전용")

    def test_표_묶음_다섯이_그대로다(self):
        self.client.force_login(self.boss)

        res = self.client.get(reverse("admin:index"))

        for group in ("계정", "환자", "검사", "판독", "병리"):
            self.assertContains(res, group)
