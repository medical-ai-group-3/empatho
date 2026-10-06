# -*- coding: utf-8 -*-
"""계정 승인 — 사이드바가 승인 큐로 가고, 누른 기록이 남는가.

승인 화면을 따로 만들지 않고 Account 목록에 필터 둘을 걸어 쓴다. 그러니
「필터가 실제로 승인 대기 직원만 세우는가」가 곧 화면 시험이다.

approved_by 는 못 채운다 — staff 를 가리키는 칸인데 admin 은 auth_user 로
로그인한다. 그래서 LogEntry 가 「누가 눌렀나」의 유일한 기록이고, 그것이
실제로 남는지까지 본다.
"""

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.adminsite import NAV
from core.models import Account, Staff


def _account(login_id, role="nursing", status="pending"):
    a = Account.objects.create(login_id=login_id, role=role,
                               account_status=status, is_active=False)
    Staff.objects.create(account=a, full_name="아무개", staff_number="S-" + login_id)
    return a


class AccountApproveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        cls.waiting = _account("nurse_wait")
        cls.done = _account("nurse_done", status="active")
        cls.patient = Account.objects.create(
            login_id="p1", role="patient", account_status="pending")

    def setUp(self):
        self.client.force_login(self.boss)
        self.url = reverse("admin:core_account_changelist")

    def _act(self, name, accounts):
        # 액션은 **그 화면에 보이는 것**에만 걸린다 — 필터를 안 풀면 환자가
        # 목록에 없어서 골라도 아무 일이 안 일어난다
        return self.client.post(self.url + "?approval=all&kind=all", {
            "action": name,
            "_selected_action": [str(a.pk) for a in accounts],
        }, follow=True)

    # ── 사이드바 ────────────────────────────────────────────────
    def test_사이드바가_승인_큐로_간다(self):
        """빈 화면이 아니라 필터 걸린 목록으로 보낸다."""
        key, label, name, query = next(n for n in NAV if n[0] == "accounts")

        self.assertEqual(label, "계정 승인")
        self.assertEqual(reverse(name), self.url)
        self.assertEqual(query, "approval=pending&kind=staff")

    def test_기본_필터가_승인_대기_직원만_세운다(self):
        res = self.client.get(self.url + "?approval=pending&kind=staff")
        shown = {a.login_id for a in res.context["cl"].queryset}

        self.assertEqual(shown, {"nurse_wait"},
                         "승인 대기 직원만 나와야 한다")

    # ── 승인 · 거절 ─────────────────────────────────────────────
    def test_승인하면_로그인할_수_있게_된다(self):
        """상태만 바꾸고 is_active 를 안 켜면 승인해도 못 들어온다 —
        인증(auth.py)은 is_active 만 본다."""
        self._act("approve", [self.waiting])

        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.account_status, "active")
        self.assertTrue(self.waiting.is_active)
        self.assertIsNotNone(self.waiting.staff.approved_at)

    def test_거절하면_막힌다(self):
        self._act("reject", [self.waiting])

        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.account_status, "rejected")
        self.assertFalse(self.waiting.is_active)

    def test_환자는_건너뛴다(self):
        """환자는 가입하면 바로 쓴다. 승인 대상이 아니다."""
        res = self._act("approve", [self.patient])

        self.patient.refresh_from_db()
        self.assertEqual(self.patient.account_status, "pending")
        self.assertContains(res, "건너뛰었습니다")

    # ── 감사 기록 ───────────────────────────────────────────────
    def test_누가_눌렀는지_남는다(self):
        self._act("approve", [self.waiting])

        entry = LogEntry.objects.filter(
            object_id=str(self.waiting.pk)).latest("action_time")
        self.assertEqual(entry.user_id, self.boss.pk)
        self.assertIn("승인", entry.change_message)

    def test_건너뛴_계정에는_기록이_안_남는다(self):
        """안 바꿨는데 로그가 남으면 그 기록이 거짓이 된다."""
        self._act("approve", [self.patient])

        self.assertFalse(
            LogEntry.objects.filter(object_id=str(self.patient.pk)).exists())
