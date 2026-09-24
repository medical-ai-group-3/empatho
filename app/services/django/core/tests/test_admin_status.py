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
        # 찔러 본 결과를 15초 들고 있는다. 안 버리면 이 시험이 앞 시험의
        # 값을 보고, patch 를 걸어도 소용이 없다.
        views.probe_cache_clear()
        self.addCleanup(views.probe_cache_clear)

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

    # ── 시안이 요구하는 값 (2026-09-25 admin-redesign) ──────────
    def test_부제가_이름_밑에_붙는다(self):
        """「llm-proxy 가 죽었다」만 보면 무엇이 멈추는지 모르는 사람이 있다."""
        self.assertEqual(views._result("llm-proxy", True, "", 0.01)["subtitle"],
                         "소견문 중계")
        self.assertEqual(views._result("postgres", True, "", 0.01)["subtitle"],
                         "DB")

    @override_settings(ADMIN_SLOW_MS=500)
    def test_느림은_임계값으로_가른다(self):
        """celery 2초와 나머지 10ms 가 한 화면에 같은 색이면 구별이 안 된다."""
        self.assertTrue(views._result("celery 워커", True, "", 2.1)["slow"])
        self.assertFalse(views._result("postgres", True, "", 0.01)["slow"])
        # 죽은 것은 「느림」이 아니다 — 배지가 둘 다 붙으면 뜻이 흐려진다
        self.assertFalse(views._result("postgres", False, "", None)["slow"])

    def test_요약은_가장_느린_것을_빼고_평균낸다(self):
        """같이 평균 내면 느린 하나가 나머지를 끌어올려 전부 느려 보인다."""
        probes = [views._result("a", True, "", 0.010),
                  views._result("b", True, "", 0.010),
                  views._result("c", True, "", 2.000)]

        out = views.probe_summary(probes)

        self.assertEqual(out["slowest_ms"], 2000)
        self.assertEqual(out["slowest_name"], "c")
        self.assertEqual(out["rest_avg_ms"], 10)
        self.assertEqual((out["ok"], out["total"]), (3, 3))
        self.assertTrue(out["all_ok"])

    def test_하나라도_죽으면_요약이_그렇게_말한다(self):
        probes = [views._result("a", True, "", 0.01),
                  views._result("b", False, "연결 거부", None)]

        out = views.probe_summary(probes)

        self.assertFalse(out["all_ok"])
        self.assertEqual((out["ok"], out["down"]), (1, 1))

    def test_시간을_못_잰_것만_있으면_요약이_비어도_안_터진다(self):
        out = views.probe_summary([views._result("a", False, "죽음", None)])

        self.assertIsNone(out["slowest_ms"])
        self.assertIsNone(out["rest_avg_ms"])

    @override_settings(ADMIN_PROBES=PROBES)
    def test_부른_순서를_지킨다(self):
        """끝난 순서로 두면 빠른 것이 먼저 와서 화면이 매번 뒤바뀐다."""
        with patch.object(views, "probe_db",
                          return_value=views._result("postgres", True, "", 0.5)), \
             patch.object(views, "probe_worker",
                          return_value=views._result("celery 워커", True, "", 0.001)), \
             patch.object(views, "probe_tcp",
                          side_effect=lambda name, base:
                              views._result(name, True, "", 0.001)):
            names = [p["name"] for p in views.probe_all()]

        self.assertEqual(names, ["postgres", "celery 워커"] + list(PROBES))

    # ── 15초 캐시 (대시보드와 나눠 쓴다) ────────────────────────
    @override_settings(ADMIN_PROBES=PROBES, ADMIN_PROBE_CACHE_SEC=60)
    def test_두_번_열어도_한_번만_찌른다(self):
        """대시보드는 admin 의 첫 화면이다 — 열 때마다 찌르면 admin 이 느려진다."""
        with patch.object(views, "probe_all",
                          return_value=[views._result("a", True, "", 0.01)]) as spy:
            views.probe_all_cached()
            views.probe_all_cached()

        self.assertEqual(spy.call_count, 1)

    @override_settings(ADMIN_PROBES=PROBES, ADMIN_PROBE_CACHE_SEC=60)
    def test_다시_확인은_캐시를_버린다(self):
        """고치고 나서 캐시가 풀리기를 기다리면 고쳐졌는지를 못 본다."""
        with patch.object(views, "probe_all",
                          return_value=[views._result("a", True, "", 0.01)]) as spy:
            views.probe_all_cached()
            views.probe_all_cached(force=True)

        self.assertEqual(spy.call_count, 2)

    @override_settings(ADMIN_PROBES=PROBES, ADMIN_PROBE_CACHE_SEC=60)
    def test_화면의_다시_확인_단추가_그_길로_간다(self):
        with patch.object(views, "probe_all",
                          return_value=[views._result("a", True, "", 0.01)]) as spy:
            self.client.get(self.url)
            self.client.get(self.url + "?refresh=1")

        self.assertEqual(spy.call_count, 2)
