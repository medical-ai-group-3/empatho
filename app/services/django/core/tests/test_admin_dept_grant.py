# -*- coding: utf-8 -*-
"""계정 상세에서 권한을 줬을 때 실제로 저장되는가.

두 가지를 본다.

    개인 추가 권한   리소스 × CRUD 격자 (staff.extra_permissions)
    과별 권한        과 한 벌 (staff.extra_depts)

⚠ StaffAdmin 단독 폼은 test_admin_perms 가 본다. 여기는 **계정 상세 안의
  인라인** 경로다 — 관리자가 실제로 쓰는 자리가 이쪽이고, 09-29 「권한을
  줘도 저장이 안 된다」가 나온 화면이다.
"""

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.admin.perms import ACTIONS
from core.api.perms import ROLE_PERMS
from core.api.permissions import rule_for
from core.models import Account, Staff

FIELD = "extra_permissions"
DEPTS = "extra_depts"
PREFIX = "staff"          # OneToOneField(related_name='staff') 의 폼셋 앞머리


def _missing(role, resource):
    granted = rule_for(resource, role).actions
    return [a for a, _ in ACTIONS if a not in granted]


class InlineSaveTests(TestCase):
    def setUp(self):
        self.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        self.client.force_login(self.boss)

        self.account = Account.objects.create(
            login_id="nur1", role="nursing",
            account_status="active", is_active=True)
        self.staff = Staff.objects.create(
            account=self.account, full_name="아무개", staff_number="S-1")

    def _url(self):
        return reverse("admin:core_account_change", args=[self.account.pk])

    def _payload(self, depts=(), **checked):
        """계정 상세가 보내는 것 전부 — 계정 칸 + 인라인 관리 폼 + 격자."""
        data = {
            # AccountForm
            "login_id": self.account.login_id,
            "role": self.account.role,
            "account_status": self.account.account_status,
            "is_active": "on",
            # 인라인 관리 폼
            f"{PREFIX}-TOTAL_FORMS": "1",
            f"{PREFIX}-INITIAL_FORMS": "1",
            f"{PREFIX}-MIN_NUM_FORMS": "0",
            f"{PREFIX}-MAX_NUM_FORMS": "1",
            # ⚠ pk 는 staff_id 다 — 숨은 칸 이름도 그것이다(`-0-id` 가 아니다).
            #   틀리면 폼셋이 「새 직원」으로 보고 account · staff_number 가
            #   중복이라며 조용히 막는다
            f"{PREFIX}-0-staff_id": str(self.staff.pk),
            f"{PREFIX}-0-full_name": self.staff.full_name,
            f"{PREFIX}-0-staff_number": self.staff.staff_number,
            "_continue": "저장하고 계속 편집",
        }
        for resource, actions in checked.items():
            for action in actions:
                data[f"{PREFIX}-0-{FIELD}__{resource}__{action}"] = "on"
        for dept in depts:
            data[f"{PREFIX}-0-{DEPTS}__{dept}"] = "on"
        return data

    def test_상세_화면에_격자_둘이_다_뜬다(self):
        res = self.client.get(self._url())

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "deptgrid")
        self.assertContains(res, "permgrid")

    def test_CRUD_격자는_접혀_있다(self):
        """스물몇 리소스 × 네 칸이 늘 펼쳐져 있으면 자주 쓰는 과별 권한이
        화면 아래로 밀린다. **지우지 않고** 접는다."""
        res = self.client.get(self._url())

        self.assertContains(res, "세부 권한 (고급)")
        self.assertContains(res, "collapse")

    def test_격자에서_체크한_권한이_저장된다(self):
        action = _missing("nursing", "report")[0]

        res = self.client.post(self._url(), self._payload(report=[action]))

        self.assertIn(res.status_code, (200, 302), res.status_code)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.extra_permissions, {"report": [action]})

    def test_체크를_풀면_지워진다(self):
        self.staff.extra_permissions = {"report": ["D"]}
        self.staff.save(update_fields=["extra_permissions", "updated_at"])

        self.client.post(self._url(), self._payload())

        self.staff.refresh_from_db()
        self.assertIsNone(self.staff.extra_permissions)

    def test_저장한_뒤_다시_열면_체크되어_있다(self):
        """⚠ 09-29 「권한을 줘도 저장이 안 된다」의 정체.

        DB 에는 들어가 있었다. JSONField.prepare_value 가 값을 json.dumps 로
        **문자열**로 만들어 격자에 넘겨서, 격자가 빈 것으로 보고 체크를 다
        풀어 그렸다 — 관리자 눈에는 저장이 안 된 것과 똑같다."""
        action = _missing("nursing", "report")[0]
        self.staff.extra_permissions = {"report": [action]}
        self.staff.extra_depts = ["radiology"]
        self.staff.save(update_fields=["extra_permissions", "extra_depts",
                                       "updated_at"])

        res = self.client.get(self._url())

        self.assertContains(res, f'name="{PREFIX}-0-{DEPTS}__radiology" checked')
        self.assertContains(
            res, f'name="{PREFIX}-0-{FIELD}__report__{action}" checked')

    # ── 여기부터 과별 권한 ────────────────────────────────────────
    def test_과를_주면_저장된다(self):
        res = self.client.post(self._url(), self._payload(depts=["radiology"]))

        self.assertIn(res.status_code, (200, 302), res.status_code)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.extra_depts, ["radiology"])

    def test_두_과를_한꺼번에_준다(self):
        self.client.post(self._url(),
                         self._payload(depts=["radiology", "surgery"]))

        self.staff.refresh_from_db()
        self.assertEqual(sorted(self.staff.extra_depts), ["radiology", "surgery"])

    def test_과를_빼면_지워진다(self):
        self.staff.extra_depts = ["radiology"]
        self.staff.save(update_fields=["extra_depts", "updated_at"])

        self.client.post(self._url(), self._payload())

        self.staff.refresh_from_db()
        self.assertIsNone(self.staff.extra_depts)

    def test_준_과의_화면_권한이_실제로_열린다(self):
        """저장까지만 보면 반쪽이다 — /me 가 그 과의 화면 권한 키를
        내려줘야 병원 웹에 과 탭이 뜬다."""
        from core.api.perms import perms_for

        self.client.post(self._url(), self._payload(depts=["radiology"]))

        account = Account.objects.select_related("staff").get(pk=self.account.pk)
        self.assertTrue(set(ROLE_PERMS["radiology"]) <= set(perms_for(account)))

    def test_관리자는_격자에_아예_없다(self):
        """체크할 칸이 없어야 한다 — 있으면 눌러 놓고 「왜 안 되지」가 된다."""
        res = self.client.get(self._url())

        self.assertNotContains(res, f"{DEPTS}__admin")

    def test_관리자를_손으로_보내도_안_들어간다(self):
        """격자에 칸이 없어도 요청은 손으로 만들 수 있다."""
        data = self._payload()
        data[f"{PREFIX}-0-{DEPTS}__admin"] = "on"

        self.client.post(self._url(), data)

        self.staff.refresh_from_db()
        self.assertIsNone(self.staff.extra_depts)

    def test_제_소속은_잠겨_있다(self):
        """간호과 사람에게 간호과를 또 주는 칸은 없다 — 소속은 위의
        「부서」로 바꾼다.

        ⚠ 앞머리까지 붙여서 본다. 화면에는 줄을 더할 때 쓰는 빈 폼
          (staff-__prefix__-…)도 같이 실리는데, 그쪽은 아직 계정이 없어
          역할을 몰라 네 과가 다 그려진다."""
        res = self.client.get(self._url())

        self.assertNotContains(res, f"{PREFIX}-0-{DEPTS}__nursing")
        self.assertContains(res, f"{PREFIX}-0-{DEPTS}__radiology")
        self.assertContains(res, "소속")

    def test_바꾸면_이력에_남는다(self):
        """「누가 언제 이 사람에게 영상의학과를 열어 줬나」."""
        self.client.post(self._url(), self._payload(depts=["radiology"]))

        entry = LogEntry.objects.filter(user=self.boss).last()
        self.assertIsNotNone(entry)
        self.assertIn("과별 권한", entry.change_message)
        self.assertIn("영상의학과", entry.change_message)

    def test_뺀_것도_이력에_남는다(self):
        self.staff.extra_depts = ["radiology"]
        self.staff.save(update_fields=["extra_depts", "updated_at"])

        self.client.post(self._url(), self._payload())

        entry = LogEntry.objects.filter(user=self.boss).last()
        self.assertIn("뺌: 영상의학과", entry.change_message)

    def test_안_바꿨으면_이력이_안_늘어난다(self):
        """저장할 때마다 줄이 쌓이면 진짜 바뀐 때를 못 찾는다."""
        grant = self._payload(depts=["radiology"])
        self.client.post(self._url(), grant)
        once = self._dept_logs()

        self.client.post(self._url(), grant)        # 같은 것을 또 저장

        self.assertEqual(once, 1)
        self.assertEqual(self._dept_logs(), 1)

    def _dept_logs(self):
        return LogEntry.objects.filter(change_message__contains="과별 권한").count()


class RebindRenderTests(TestCase):
    """⚠ 09-29 회귀 — 폼이 **바인딩된 채 다시 그려질 때** 500 이 났다.

    forms.JSONField.bound_data 가 json.loads(dict) 를 부르면 TypeError 다
    (JSONDecodeError 가 아니라서 Django 가 못 받아낸다). 계정 상세의 다른
    칸이 하나라도 틀리면 오류 표시 대신 500 이 떴다 — 관리자 눈에는
    「저장이 안 된다」로 보인다.
    """

    def setUp(self):
        self.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        self.client.force_login(self.boss)
        self.account = Account.objects.create(
            login_id="nur1", role="nursing",
            account_status="active", is_active=True)
        self.staff = Staff.objects.create(
            account=self.account, full_name="아무개", staff_number="S-1")

    def test_계정_칸이_틀려도_오류_화면이_뜬다(self):
        """이미 있는 로그인 아이디를 넣어 폼을 일부러 깨뜨린다.

        (login_id 를 비우는 것으로는 안 깨진다 — 그 칸은 null 을 받는다.)"""
        Account.objects.create(login_id="taken", role="radiology",
                               account_status="active", is_active=True)

        url = reverse("admin:core_account_change", args=[self.account.pk])
        res = self.client.post(url, {
            "login_id": "taken",                # unique — 여기서 깨진다
            "role": "nursing",
            "account_status": "active",
            "is_active": "on",
            f"{PREFIX}-TOTAL_FORMS": "1",
            f"{PREFIX}-INITIAL_FORMS": "1",
            f"{PREFIX}-MIN_NUM_FORMS": "0",
            f"{PREFIX}-MAX_NUM_FORMS": "1",
            f"{PREFIX}-0-staff_id": str(self.staff.pk),
            f"{PREFIX}-0-full_name": "아무개",
            f"{PREFIX}-0-staff_number": "S-1",
            f"{PREFIX}-0-{DEPTS}__radiology": "on",
            f"{PREFIX}-0-{FIELD}__report__D": "on",
        })

        self.assertEqual(res.status_code, 200)      # 500 이 아니다
        self.assertContains(res, "deptgrid")
        # 고르던 값이 그대로 남아 있어야 한다 — 다시 체크하게 만들지 않는다
        self.assertContains(res, f'name="{PREFIX}-0-{DEPTS}__radiology" checked')
        self.staff.refresh_from_db()
        self.assertIsNone(self.staff.extra_depts)   # 저장은 안 됐다
