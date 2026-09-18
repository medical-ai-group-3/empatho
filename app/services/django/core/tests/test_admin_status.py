# -*- coding: utf-8 -*-
"""서버 상태 — 죽은 서비스가 있어도 화면이 뜨는가.

이 화면의 쓸모는 「무엇이 죽었나」를 보는 것이다. 그러니 **죽어 있을 때
제대로 그려지는 것**이 정상일 때보다 중요하다. 한 줄이 예외를 내서 화면이
통째로 500 이 나면, 정작 봐야 할 때 못 본다.

⚠ 여기서 실제 서비스를 찌르지 않는다. 시험이 도커망 유무에 따라 달라지면
  그건 시험이 아니다 — 찌르는 함수만 갈아끼워 그 위를 본다.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.admin import views

PROBES = {"file-gateway": "http://file-gateway:8091",
          "orthanc (PACS)": "http://orthanc:8042"}


class StatusPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")

    def setUp(self):
        self.client.force_login(self.boss)
        self.url = reverse("admin:empatho_status")

    # ── 화면 ────────────────────────────────────────────────────
    @override_settings(ADMIN_PROBES=PROBES)
    def test_전부_죽어_있어도_화면이_뜬다(self):
        dead = views._result("x", False, "연결 거부", None)
        with patch.object(views, "probe_db", return_value=dead), \
             patch.object(views, "probe_worker", return_value=dead), \
             patch.object(views, "probe_tcp", return_value=dead):
            res = self.client.get(self.url)

        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertContains(res, "실패")

    @override_settings(ADMIN_PROBES=PROBES)
    def test_settings_에_적은_것만_찌른다(self):
        """주소를 코드에 박으면 배포처마다 화면이 거짓말을 한다."""
        with patch.object(views, "probe_db") as db, \
             patch.object(views, "probe_worker") as worker, \
             patch.object(views, "probe_tcp") as tcp:
            db.return_value = worker.return_value = tcp.return_value = \
                views._result("x", True, "", 0.001)
            views.probe_all()

        self.assertEqual([c.args[0] for c in tcp.call_args_list],
                         list(PROBES))

    # ── 찌르는 함수 ─────────────────────────────────────────────
    def test_DB_는_실제로_질의를_던진다(self):
        """연결만 보면 권한 · 인증 문제가 안 드러난다."""
        out = views.probe_db()

        self.assertTrue(out["ok"], out)
        self.assertIsNotNone(out["ms"])

    def test_닫힌_포트는_실패로_돌아온다(self):
        """예외가 새어 나가면 화면이 통째로 500 이 된다."""
        # 0 번 포트는 어디에도 안 열린다
        out = views.probe_tcp("없는곳", "http://127.0.0.1:1")

        self.assertFalse(out["ok"])
        self.assertIsNone(out["ms"])
        self.assertTrue(out["detail"], "왜 실패했는지 한 줄은 있어야 한다")

    def test_주소를_못_읽으면_그렇다고_한다(self):
        """env 를 잘못 넣으면 조용히 빠지는 게 아니라 눈에 보여야 한다."""
        out = views.probe_tcp("엉터리", "http://")

        self.assertFalse(out["ok"])
        self.assertIn("주소", out["detail"])

    @override_settings(ADMIN_PROBE_TIMEOUT_SEC=0.01)
    def test_타임아웃을_settings_에서_읽는다(self):
        """죽은 서비스를 기다리느라 화면이 같이 멎으면 안 된다."""
        with patch.object(views.socket, "create_connection") as conn:
            views.probe_tcp("느린곳", "http://10.255.255.1:9")

        self.assertEqual(conn.call_args.kwargs["timeout"], 0.01)
