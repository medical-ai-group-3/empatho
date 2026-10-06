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
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.urls import reverse

from core.models import Account, Staff

URL = "/admin/core/account/"
LOGIN_URL = "/api/v1/login"
#: 시험용 비밀번호. 실제 계정 값이 아니다 — 여기서 만들고 여기서만 쓴다
PASSWORD = "test-only-pw-be919ae0"


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

    def _act(self, action, account, query="?approval=all&kind=all"):
        """줄 단추를 누른 것과 같은 요청.

        ⚠ **query 를 반드시 준다.** 액션은 지금 걸린 changelist 의 결과에만
          닿는다 — 기본값(승인 대기)인 맨 주소로 보내면 이미 승인된 계정은
          그 목록에 없어서 조용히 아무 일도 안 일어난다. 화면에서는 단추가
          form action="" 로 «지금 주소»를 그대로 쓰기 때문에 이 문제가 없다.
        """
        return self.client.post(URL + query,
                                {"action": action,
                                 "_selected_action": str(account.pk)})

    def _login(self, login_id):
        """진짜 로그인 문을 두드린다 — 정지가 먹는지는 여기서만 알 수 있다.

        admin 세션과 섞이지 않게 새 client 로 친다. 돌려주는 것은 상태 코드
        뿐이다 — 토큰도 본문도 안 들여다본다.
        """
        from django.test import Client

        res = Client().post(LOGIN_URL,
                            {"login_id": login_id, "password": PASSWORD},
                            content_type="application/json")
        return res.status_code

    # ── ① 시안이 요구하는 것 ────────────────────────────────────
    def test_머리와_한_줄_툴바가_뜬다(self):
        res = self._list()

        self.assertContains(res, "계정 · 직원 가입 승인")
        self.assertContains(res, "계정 승인")
        # 툴바 네 자리: 상태 탭 · 구분 토글 · 역할 고르개 · 검색
        self.assertContains(res, 'class="e-toolbar"')
        self.assertContains(res, 'aria-label="상태"')
        self.assertContains(res, 'aria-label="구분"')
        self.assertContains(res, 'name="role"')
        self.assertContains(res, 'id="searchbar"')

    def test_칩이_비어_있지_않다(self):
        """spec.choices 를 템플릿에서 그냥 부르면 오류 없이 칩만 사라진다."""
        res = self._list()

        for label in ("승인 대기", "직원", "간호", "영상의학"):
            self.assertContains(res, label)

    def test_오른쪽_세로_필터_칸이_없다(self):
        """툴바로 옮긴 것이라 둘 다 있으면 같은 필터가 두 벌이 된다."""
        res = self._list()

        self.assertNotContains(res, 'id="changelist-filter"')

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

    def test_고른_탭에_표가_선다(self):
        res = self._list("?approval=pending&kind=staff")

        self.assertContains(res, "e-seg-item on")

    def test_정렬_중인_칸에_화살표가_붙는다(self):
        """머리줄 배경으로 알리면 칸 하나만 색이 다른 네모가 되어 깨져 보인다."""
        _pending("sortme")

        res = self._list("?o=2")

        self.assertContains(res, 'class="e-sort"')

    def test_탭을_눌러도_다른_조건이_남는다(self):
        """상태만 바꾸려다 검색과 역할이 풀리면 좁히는 일을 매번 다시 한다."""
        res = self._list("?approval=pending&kind=patient&role=nursing&q=김")
        urls = [t["url"] for t in res.context["e_tabs"]]

        self.assertTrue(all("kind=patient" in u for u in urls), urls)
        self.assertTrue(all("role=nursing" in u for u in urls), urls)
        self.assertTrue(all("q=%EA%B9%80" in u for u in urls), urls)

    def test_조건을_바꾸면_쪽은_버린다(self):
        """3쪽을 보다 조건을 바꾸면 그 조건에 3쪽이 없어 빈 화면이 된다."""
        res = self._list("?approval=pending&p=3")

        self.assertTrue(all("p=3" not in t["url"] for t in res.context["e_tabs"]))

    def test_검색_폼이_다른_조건을_들고_간다(self):
        """폼은 자기 칸만 보낸다 — 숨은 칸이 없으면 검색하는 순간 필터가 풀린다."""
        res = self._list("?approval=rejected&kind=patient")
        keep = {h["name"]: h["value"] for h in res.context["e_search_keep"]}

        self.assertEqual(keep, {"approval": "rejected", "kind": "patient"})
        # 자기 칸은 숨은 칸으로 또 넣지 않는다 — 넣으면 q 가 둘이 된다
        self.assertNotIn("q", keep)

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

    def test_상태마다_놓이는_단추가_다르다(self):
        """이미 승인된 줄에 [승인]이 또 있으면 무엇을 눌러야 할지가 안 보인다."""
        waiting = _pending("row_wait")
        done = Account.objects.create(login_id="row_done", role="reception",
                                      account_status="active", is_active=True)
        held = Account.objects.create(login_id="row_held", role="reception",
                                      account_status="suspended",
                                      is_active=False)

        res = self._list("?approval=all&kind=all")
        html = res.content.decode()

        self.assertIn('form="row-approve-%d"' % waiting.pk, html)
        self.assertNotIn('form="row-suspend-%d"' % waiting.pk, html)
        self.assertIn('form="row-suspend-%d"' % done.pk, html)
        self.assertNotIn('form="row-approve-%d"' % done.pk, html)
        self.assertIn('form="row-restore-%d"' % held.pk, html)

    def test_상세는_상태와_상관없이_늘_있다(self):
        """[상세] 자리가 줄마다 움직이면 눈이 오른쪽 끝을 찾아 헤맨다."""
        _pending("always_wait")
        Account.objects.create(login_id="always_done", role="reception",
                               account_status="active", is_active=True)

        res = self._list("?approval=all&kind=all")
        rows = res.context["cl"].result_list
        html = res.content.decode()

        for account in rows:
            with self.subTest(account.pk):
                self.assertIn(
                    reverse("admin:core_account_change", args=[account.pk]),
                    html)

    def test_표에_시안의_일곱_칸이_다_있다(self):
        _pending("cells1", name="김간호")

        res = self._list()

        for mark in ("action-select", "e-avatar-sm", "e-no", "e-dept",
                     "e-at", "e-state-pill", "e-approve-act"):
            with self.subTest(mark):
                self.assertContains(res, mark)

    def test_부서색_열쇠가_역할에서_온다(self):
        """색을 파이썬이 정하면 색을 바꿀 때 파이썬을 고치게 된다."""
        _pending("tone1", role="radiology")

        res = self._list()

        self.assertContains(res, "d-radiology")

    def test_신청_일시_서식이_목록_칸과_같다(self):
        """두 벌로 짜 두면 한쪽만 고쳐 놓고 한참 뒤에 어긋난 걸 본다."""
        from core.admin.edit import AccountAdmin

        account = _pending("when1")
        res = self._list()
        row = res.context["cl"].result_list[0]

        self.assertContains(
            res, AccountAdmin.signed_up(None, account))
        self.assertEqual(row.pk, account.pk)

    # ── 상태별 건수 ─────────────────────────────────────────────
    def test_탭_숫자가_실제와_맞는다(self):
        _pending("cnt1")
        _pending("cnt2")
        Account.objects.create(login_id="cnt3", role="reception",
                               account_status="active", is_active=True)

        tabs = {t["label"]: t["count"] for t in self._list().context["e_tabs"]}

        self.assertEqual(tabs["승인 대기"], 2)
        self.assertEqual(tabs["승인됨"], 1)
        self.assertEqual(tabs["거절됨"], 0)

    def test_전체_탭은_나머지를_더한_수다(self):
        _pending("sum1")
        Account.objects.create(login_id="sum2", role="reception",
                               account_status="active", is_active=True)

        tabs = {t["label"]: t["count"] for t in self._list().context["e_tabs"]}

        self.assertEqual(tabs["전체"],
                         sum(v for k, v in tabs.items() if k != "전체"))

    def test_숫자가_지금_걸린_다른_조건을_따른다(self):
        """「거절됨 3」을 보고 눌렀는데 0 이면 숫자가 거짓말이 된다."""
        _pending("mine1", name="김간호")
        _pending("mine2", name="박영상", role="radiology")

        tabs = {t["label"]: t["count"]
                for t in self._list("?q=김간호").context["e_tabs"]}

        self.assertEqual(tabs["승인 대기"], 1)

    def test_상태_탭_숫자는_상태에_안_걸린다(self):
        """승인 대기만 보는 중에도 「승인됨 1」이 보여야 거기 갈 생각을 한다."""
        _pending("both1")
        Account.objects.create(login_id="both2", role="reception",
                               account_status="active", is_active=True)

        tabs = {t["label"]: t["count"]
                for t in self._list("?approval=pending").context["e_tabs"]}

        self.assertEqual(tabs["승인됨"], 1)

    def test_환자를_보고_있으면_직원은_안_센다(self):
        """구분은 그대로 지킨다 — 상태만 빼고 세는 것이 규칙이다."""
        _pending("only_staff")
        Account.objects.create(login_id="only_pat", role="patient",
                               account_status="active", is_active=True)

        tabs = {t["label"]: t["count"]
                for t in self._list("?kind=patient").context["e_tabs"]}

        self.assertEqual(tabs["전체"], 1)

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

    # ── 정지 · 복구 ─────────────────────────────────────────────
    def test_정지가_로그인을_막는다(self):
        """이 화면의 존재 이유다 — 상태만 바꾸고 is_active 를 안 끄면
        「정지됨」이라고 써 놓고 그 사람은 계속 들어온다."""
        account = _pending("hold_me")
        account.password_hash = make_password(PASSWORD)
        account.account_status = "active"
        account.is_active = True
        account.save()
        self.assertEqual(self._login("hold_me"), 200, "정지 전에는 들어와야 한다")

        self._act("suspend", account)

        account.refresh_from_db()
        self.assertEqual(account.account_status, "suspended")
        self.assertFalse(account.is_active)
        self.assertEqual(self._login("hold_me"), 401)

    def test_복구가_다시_들여보낸다(self):
        account = _pending("back_me")
        account.password_hash = make_password(PASSWORD)
        account.account_status = "suspended"
        account.is_active = False
        account.save()
        self.assertEqual(self._login("back_me"), 401)

        self._act("restore", account)

        account.refresh_from_db()
        self.assertEqual(account.account_status, "active")
        self.assertEqual(self._login("back_me"), 200)

    def test_정지는_승인_이력을_안_지운다(self):
        """정지는 승인을 무르는 것이 아니라 잠시 막는 것이다 — 지웠다가
        복구하면 「승인된 적이 있나」가 사라진다."""
        account = _pending("keep_hist")
        self._act("approve", account)
        approved_at = Staff.objects.get(account=account).approved_at
        self.assertIsNotNone(approved_at)

        self._act("suspend", account)
        self._act("restore", account)

        self.assertEqual(Staff.objects.get(account=account).approved_at,
                         approved_at)

    def test_거절은_승인_이력을_지운다(self):
        """거절은 「승인한 적 없음」으로 되돌리는 것이라 정지와 다르다."""
        account = _pending("drop_hist")
        self._act("approve", account)
        self._act("reject", account)

        self.assertIsNone(Staff.objects.get(account=account).approved_at)

    def test_정지도_감사_기록을_남긴다(self):
        account = _pending("hold_log")

        self.client.post(URL, {"action": "suspend",
                               "_selected_action": str(account.pk)})

        entry = LogEntry.objects.filter(object_id=str(account.pk)).latest("id")
        self.assertIn("정지", entry.change_message)

    # ── 일괄 단추는 지금 탭에서 할 수 있는 것만 ──────────────────
    def test_탭마다_내놓는_일괄_단추가_다르다(self):
        """승인됨만 보는 중에 [선택 승인]이 있으면 눌러도 아무 일이 안
        일어나고, 눌러 본 사람은 고장인 줄 안다."""
        want = {
            "?approval=pending": {"approve", "reject"},
            "?approval=active": {"suspend"},
            "?approval=rejected": {"approve"},
            "?approval=suspended": {"restore"},
            "?approval=all": {"approve", "reject", "suspend", "restore"},
        }
        for query, actions in want.items():
            with self.subTest(query):
                res = self._list(query)
                shown = {b["action"] for b in res.context["e_bulk"]}
                self.assertEqual(shown, actions)

    def test_일괄_단추가_화면에_그려진다(self):
        """컨텍스트만 맞고 템플릿이 안 그리면 아무도 못 누른다."""
        Account.objects.create(login_id="bulk_hold", role="reception",
                               account_status="active", is_active=True)

        res = self._list("?approval=active")

        # 줄마다 숨은 폼에도 value="approve" 가 있다 — 일괄 단추만 본다
        self.assertContains(res, "선택 정지")
        self.assertNotContains(res, "선택 승인")
        self.assertNotContains(res, "선택 거절")

    def test_일괄_단추를_흐리게_할_스크립트가_붙는다(self):
        """0건인데 눌리면 한 번 헛걸음을 시킨다."""
        res = self._list()

        self.assertContains(res, "empatho/approvals.js")

    def test_그_스크립트는_계정_표에만_붙는다(self):
        """base_site 에 넣으면 스물두 표가 다 받는다."""
        from core.models import Patient

        Patient.objects.create(patient_number="P-JS-1", sex="F")

        res = self.client.get(reverse("admin:core_patient_changelist"))

        self.assertNotContains(res, "empatho/approvals.js")

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
