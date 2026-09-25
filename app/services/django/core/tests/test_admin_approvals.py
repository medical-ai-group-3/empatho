# -*- coding: utf-8 -*-
"""계정 승인 화면 — 시안(admin-redesign/Approvals.dc.html).

이 화면은 Django changelist 위에 «보이는 모양»만 얹은 것이다. 그래서 시험의
주제가 둘이다.

  ① 시안이 요구하는 것이 실제로 그려지는가 (칩 석 줄 · 줄별 단추 · 빈 상태)
  ② **Django 것이 그대로 도는가** — 줄별 단추가 기존 approve/reject 액션을
     부르는지, 검색 · 정렬 · 페이지 · 감사 기록이 살아 있는지.

②가 깨지면 화면은 멀쩡해 보이는데 승인이 안 된다. 그게 제일 나쁜 고장이다.
"""

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Account, Staff

URL = "/admin/core/account/"


def _pending(login_id, name="아무개", role="nursing"):
    account = Account.objects.create(login_id=login_id, role=role,
                                     account_status="pending", is_active=False)
    Staff.objects.create(account=account, full_name=name,
                         staff_number="S-" + login_id)
    return account


class ApprovalScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")

    def setUp(self):
        self.client.force_login(self.boss)

    def _list(self, query=""):
        res = self.client.get(URL + query)
        self.assertEqual(res.status_code, 200)
        return res

    # ── ① 시안이 요구하는 것 ────────────────────────────────────
    def test_머리와_칩_석_줄이_뜬다(self):
        res = self._list()

        self.assertContains(res, "계정 · 직원 가입 승인")
        self.assertContains(res, "계정 승인")
        for title in ("상태", "구분", "역할"):
            self.assertContains(res, ">%s</span>" % title)

    def test_칩이_비어_있지_않다(self):
        """spec.choices 를 템플릿에서 그냥 부르면 오류 없이 칩만 사라진다."""
        res = self._list()

        for label in ("승인 대기", "직원", "간호", "영상의학"):
            self.assertContains(res, label)

    def test_역할_칩에_환자가_없다(self):
        """「구분」 줄이 이미 가르는 값이다 — 두 줄이 서로 싸운다."""
        from core.admin.edit import RoleFilter

        roles = [r for r, _ in RoleFilter.lookups(RoleFilter, None, None)]

        self.assertNotIn("patient", roles)
        # 「전체」가 맨 앞이다. Django 가 붙이는 「모두」는 걷어냈으므로
        # 우리가 값 있는 선택지로 직접 둔다
        self.assertEqual(roles[:2], ["all", "admin"])

    def test_모두_줄이_사라지고_전체만_남는다(self):
        """다른 필터가 걸려도 그렇다 — 내비 링크가 바로 그 경우다."""
        res = self._list("?approval=pending&kind=staff")
        chips = [c["display"] for c in
                 res.context["cl"].filter_specs[0].choices(res.context["cl"])]

        self.assertNotIn("모두", chips)
        self.assertIn("전체", chips)

    def test_아무것도_안_고르면_기본값_칩에_표가_선다(self):
        """목록은 승인 대기로 걸러져 있는데 칩이 안 밝으면 필터가 없는 줄 안다."""
        res = self._list()
        spec = res.context["cl"].filter_specs[0]
        on = [c["display"] for c in spec.choices(res.context["cl"]) if c["selected"]]

        self.assertEqual(on, ["승인 대기"])

    def test_전체를_누르면_정말_전부_나온다(self):
        _pending("waiting1")
        Account.objects.create(login_id="active1", role="reception",
                               account_status="active", is_active=True)

        res = self._list("?approval=all&kind=all")

        self.assertEqual(res.context["cl"].result_count,
                         Account.objects.count())

    def test_고른_칩에_표가_선다(self):
        res = self._list("?approval=pending&kind=staff")

        self.assertContains(res, "e-fchip on")

    def test_승인할_것이_없으면_안내가_뜬다(self):
        """「0 계정」 한 줄로 두지 않는다 — 없는 것은 좋은 소식이다."""
        res = self._list()

        self.assertContains(res, "승인을 기다리는 직원이 없습니다")
        self.assertContains(res, "승인해야 로그인할 수 있습니다")

    def test_다른_필터에서는_그_문구를_안_쓴다(self):
        """거절됨을 보는 중에 「승인을 기다리는…」이 뜨면 거짓말이다."""
        res = self._list("?approval=rejected&kind=staff")

        self.assertNotContains(res, "승인을 기다리는 직원이 없습니다")
        self.assertContains(res, "조건에 맞는 계정이 없습니다")

    def test_줄마다_승인_거절_단추가_붙는다(self):
        account = _pending("nurse1")

        res = self._list()

        self.assertContains(res, 'form="row-approve-%d"' % account.pk)
        self.assertContains(res, 'form="row-reject-%d"' % account.pk)
        self.assertContains(res, 'id="row-approve-%d"' % account.pk)

    def test_처리가_끝난_줄에는_단추_대신_상태가_뜬다(self):
        Account.objects.create(login_id="done1", role="reception",
                               account_status="active", is_active=True)

        res = self._list("?approval=all&kind=all")

        self.assertContains(res, "e-act-done")

    def test_고르개와_선택_건수_자리가_남아_있다(self):
        """actions.js 가 이 이름들을 찾는다 — 바꾸면 숫자가 0 에서 안 움직인다."""
        _pending("nurse2")

        res = self._list()

        self.assertContains(res, 'id="action-toggle"')
        self.assertContains(res, "action-select")
        self.assertContains(res, "action-counter")

    def test_로그인_아이디_칸이_목록에_없다(self):
        """화면을 찍는 것만으로 계정 목록이 새면 안 된다."""
        _pending("secret_login_id")

        res = self._list()

        self.assertNotContains(res, ">secret_login_id<")

    # ── ② Django 것이 그대로 도는가 ────────────────────────────
    def test_줄_단추가_기존_승인_액션을_부른다(self):
        account = _pending("nurse3")

        res = self.client.post(URL, {"action": "approve",
                                     "_selected_action": str(account.pk)})

        self.assertEqual(res.status_code, 302)
        account.refresh_from_db()
        self.assertEqual(account.account_status, "active")
        self.assertTrue(account.is_active, "is_active 를 안 켜면 승인해도 못 들어온다")

    def test_줄_단추가_기존_거절_액션을_부른다(self):
        account = _pending("nurse4")

        self.client.post(URL, {"action": "reject",
                               "_selected_action": str(account.pk)})

        account.refresh_from_db()
        self.assertEqual(account.account_status, "rejected")
        self.assertFalse(account.is_active)

    def test_승인이_감사_기록을_남긴다(self):
        """줄 단추가 새 경로를 팠으면 이 기록이 안 남는다."""
        account = _pending("nurse5")

        self.client.post(URL, {"action": "approve",
                               "_selected_action": str(account.pk)})

        self.assertTrue(
            LogEntry.objects.filter(object_id=str(account.pk)).exists())

    def test_여럿_고르기도_그대로_된다(self):
        a = _pending("nurse6")
        b = _pending("nurse7")

        self.client.post(URL, {"action": "approve",
                               "_selected_action": [str(a.pk), str(b.pk)]})

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual({a.account_status, b.account_status}, {"active"})

    def test_검색이_그대로_된다(self):
        _pending("nurse8", name="김간호")
        _pending("nurse9", name="박영상", role="radiology")

        res = self._list("?q=김간호")

        self.assertContains(res, "김간호")
        self.assertNotContains(res, "박영상")

    def test_로그인_아이디로도_찾힌다(self):
        """목록에서 뺐다고 검색까지 막으면 계정을 못 찾는다."""
        _pending("only_by_id", name="숨은이")

        res = self._list("?q=only_by_id")

        self.assertContains(res, "숨은이")

    def test_정렬_링크가_살아_있다(self):
        _pending("nurse10")

        res = self._list()

        self.assertContains(res, "?o=")

    def test_이름을_누르면_상세로_간다(self):
        """감사 기록이 거기 있다 — 링크가 없으면 볼 길이 사라진다."""
        account = _pending("nurse11")

        res = self._list()

        self.assertContains(
            res, reverse("admin:core_account_change", args=[account.pk]))

    def test_환자는_여전히_건너뛴다(self):
        patient = Account.objects.create(login_id="pat1", role="patient",
                                         account_status="active",
                                         is_active=True)

        self.client.post(URL, {"action": "reject",
                               "_selected_action": str(patient.pk)})

        patient.refresh_from_db()
        self.assertEqual(patient.account_status, "active")

    # ── 다른 표는 안 건드린다 ───────────────────────────────────
    def test_다른_표는_Django_기본_목록_그대로다(self):
        """change_list_results.html 은 스물두 표가 같이 쓴다."""
        from core.models import Patient

        # 행이 없으면 Django 기본 갈래가 표를 아예 안 그린다({% if results %}).
        # 빈 화면으로는 「갈래가 갈렸는지」를 못 본다.
        Patient.objects.create(patient_number="P-ADMIN-1", sex="F")

        res = self.client.get(reverse("admin:core_patient_changelist"))

        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "e-approve")
        self.assertContains(res, 'id="result_list"')
        self.assertContains(res, "P-ADMIN-1")
