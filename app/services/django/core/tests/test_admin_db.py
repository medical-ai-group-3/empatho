# -*- coding: utf-8 -*-
"""DB 조회 — 구조는 보이고 값은 안 새는가.

표를 통째로 막지 않는다. 관리자가 스키마도 못 보면 일을 못 한다. 막는 것은
값 쪽이다 — 분포다.

⚠ 「민감한 표에는 분포를 안 낸다」를 목록 대조로만 보면 부족하다. 화면을 실제로
  열어 그 값이 응답에 없는지까지 본다.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.admin import views
from core.models import Account, ExamOrder, Patient, PatientPii

SECRET_NAME = "홍길동"


class DbScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        patient = Patient.objects.create(patient_number="P-DB-1", sex="F")
        PatientPii.objects.create(patient=patient, name=SECRET_NAME,
                                  phone="010-1111-2222")
        Account.objects.create(login_id="secret_login", role="nursing",
                               account_status="active")
        # 분포가 개수를 제대로 세는지 보려고 일부러 치우치게 넣는다
        for status in ("requested", "requested", "cancelled"):
            ExamOrder.objects.create(patient=patient, order_status=status)

    def setUp(self):
        self.client.force_login(self.boss)

    def _detail(self, table):
        return self.client.get(
            reverse("admin:empatho_db_detail", args=[table]))

    # ── 목록 ────────────────────────────────────────────────────
    def test_표_목록이_뜬다(self):
        res = self.client.get(reverse("admin:empatho_db"))

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "patient_pii")
        self.assertContains(res, "exam_order")

    # ── 구조는 막지 않는다 ──────────────────────────────────────
    def test_민감한_표도_구조는_보인다(self):
        """표째 가리면 관리자가 스키마를 못 본다. 막는 것은 값뿐이다."""
        res = self._detail("patient_pii")

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "phone")        # 칸 이름은 구조다
        self.assertContains(res, "name")

    def test_없는_표는_404(self):
        self.assertEqual(self._detail("no_such_table").status_code, 404)

    # ── 값은 막는다 ─────────────────────────────────────────────
    def test_민감한_표에는_분포가_없다(self):
        res = self._detail("patient_pii")

        self.assertEqual(res.context["spreads"], [])
        self.assertTrue(res.context["hidden"])
        self.assertNotContains(res, SECRET_NAME)

    def test_account_도_가린다(self):
        """로그인 아이디가 분포로 새면 계정 목록을 내주는 것과 같다."""
        res = self._detail("account")

        self.assertEqual(res.context["spreads"], [])
        self.assertNotContains(res, "secret_login")

    @override_settings(ADMIN_DB_SENSITIVE=[])
    def test_가릴_표는_settings_가_정한다(self):
        """코드에 박으면 표가 늘 때 아무도 여기를 안 고친다."""
        res = self._detail("patient_pii")

        self.assertFalse(res.context["hidden"])

    # ── 어느 칸을 내는가 ────────────────────────────────────────
    def test_상태형_칸만_분포를_낸다(self):
        """자유 텍스트는 안 낸다 — 길이 분포도 안 낸다.

        patient.sex 는 choices 가 없는 CharField 라 여기서 빠진다. 값 집합이
        코드에 없으면 자유 칸과 구분할 방법이 없다 — 막는 쪽으로 둔다.
        """
        patient = {f.column: f for f in Patient._meta.fields}
        order = {f.column: f for f in ExamOrder._meta.fields}

        self.assertTrue(views._spreadable(order["order_status"]))       # choices
        self.assertTrue(views._spreadable(patient["has_allergy"]))      # 참거짓
        self.assertFalse(views._spreadable(patient["allergy_note"]))    # 자유
        self.assertFalse(views._spreadable(patient["sex"]))             # 집합 없음
        self.assertFalse(views._spreadable(patient["patient_id"]))      # 키

    def test_외래키는_안_낸다(self):
        """값이 남의 표 행 번호라 분포가 뜻을 못 갖고, 사람을 좁힌다."""
        fk = PatientPii._meta.get_field("patient")

        self.assertFalse(views._spreadable(fk))

    def test_분포에_실제_개수가_나온다(self):
        spreads = {s["name"]: s["rows"] for s in views.db_spreads(ExamOrder)}

        self.assertEqual(spreads["order_status"],
                         [{"value": "requested", "n": 2},
                          {"value": "cancelled", "n": 1}])

    # ── 시안이 요구하는 값 (2026-09-25 admin-redesign) ──────────
    def _index(self, **params):
        return self.client.get(reverse("admin:empatho_db"), params)

    def test_요약_넉_장의_값이_실제와_맞는다(self):
        res = self._index()
        summary = res.context["summary"]

        self.assertEqual(summary["total"], len(views.db_tables()))
        self.assertEqual(summary["shown"], summary["total"])
        # 이 시험이 넣은 것 중 exam_order 가 3 행으로 제일 많다
        self.assertEqual(summary["biggest_rows"], 3)
        self.assertEqual(summary["biggest_name"], "검사 오더")

    def test_가린_표를_요약이_이름으로만_말한다(self):
        """이름을 세는 것과 안을 들여다보는 것은 다른 일이다."""
        res = self._index()

        self.assertIn("계정", res.context["summary"]["hidden"])
        self.assertNotContains(res, SECRET_NAME)
        self.assertNotContains(res, "secret_login")

    def test_비어_있는_표를_따로_센다(self):
        res = self._index()
        summary = res.context["summary"]

        empty = [t["name"] for t in views.db_tables() if not t["rows"]]
        self.assertEqual(summary["empty_count"], len(empty))
        self.assertIn("동의", summary["empty"])

    def test_이름이_많으면_줄이고_말줄임을_붙인다(self):
        """다 적으면 카드가 목록이 되고, 아래 표와 같은 말을 두 번 한다."""
        few = ["가", "나"]
        many = [str(i) for i in range(views.SUMMARY_NAMES + 3)]

        self.assertEqual(views._join_names(few), "가 · 나")
        self.assertTrue(views._join_names(many).endswith(" …"))
        self.assertEqual(views._join_names([]), "없음")

    def test_행_수_막대는_제일_큰_표를_기준으로_한다(self):
        rows = views._with_bars([{"rows": 10}, {"rows": 5}, {"rows": 0}])

        self.assertEqual([r["pct"] for r in rows], [100.0, 50.0, 0.0])

    def test_표가_하나도_없어도_막대가_안_터진다(self):
        """0 으로 나누면 화면이 통째로 500 이 된다."""
        self.assertEqual(views._with_bars([{"rows": 0}])[0]["pct"], 0.0)

    # ── ?q= 검색 ────────────────────────────────────────────────
    def test_표_이름으로_찾는다(self):
        res = self._index(q="exam_order")

        self.assertEqual(res.context["summary"]["shown"], 1)
        self.assertContains(res, "exam_order")
        self.assertNotContains(res, ">patient_pii<")

    def test_한글_이름으로도_찾는다(self):
        """화면에 한글이 보이는데 영문으로만 찾히면 아무도 못 쓴다."""
        res = self._index(q="검사 오더")

        self.assertEqual(res.context["summary"]["shown"], 1)
        self.assertEqual(res.context["tables"][0]["table"], "exam_order")

    def test_대소문자를_안_가린다(self):
        self.assertEqual(self._index(q="EXAM_ORDER").context["summary"]["shown"],
                         self._index(q="exam_order").context["summary"]["shown"])

    def test_못_찾으면_찾는_법을_알려준다(self):
        """「0 건」 한 줄로 두면 없는 것인지 잘못 친 것인지 모른다."""
        res = self._index(q="없는표이름")

        self.assertEqual(res.context["summary"]["shown"], 0)
        self.assertContains(res, "맞는 표가 없습니다")

    def test_검색해도_요약의_전체_수는_안_변한다(self):
        """「22개 중 1개 표시」가 되어야 한다 — 전체가 1 로 줄면 거짓말이다."""
        whole = self._index().context["summary"]["total"]

        summary = self._index(q="exam_order").context["summary"]

        self.assertEqual(summary["total"], whole)
        self.assertEqual(summary["shown"], 1)
