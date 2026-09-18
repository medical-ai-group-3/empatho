# -*- coding: utf-8 -*-
"""AccountAdmin — 승인 큐와 승인 · 거절 액션."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.admin import AccountAdmin
from core.models import Account, Staff


def _pending(login_id, role="nursing", name="아무개"):
    account = Account.objects.create(login_id=login_id, role=role,
                                     account_status="pending", is_active=False)
    Staff.objects.create(account=account, full_name=name,
                         staff_number="S-" + login_id)
    return account


class _Req:
    """메시지 프레임워크 없이 액션을 부르려고 messages 를 삼킨다."""

    def __init__(self):
        self.factory = RequestFactory()

    def get(self, query=""):
        return self.factory.get("/admin/core/account/" + query)


class ApprovalActionTests(TestCase):
    def setUp(self):
        self.admin = AccountAdmin(Account, AdminSite())
        self.messages = []
        self.admin.message_user = lambda req, msg, level=None: self.messages.append(msg)
        self.req = _Req().get()

    # ── 승인 ────────────────────────────────────────────────────
    def test_승인하면_두_칸이_함께_바뀐다(self):
        """account_status 만 바꾸고 is_active 를 안 켜면 승인해도 못 들어온다 —
        인증(core/api/auth.py)은 is_active 만 본다."""
        a = _pending("nurse1")
        self.admin.approve(self.req, Account.objects.filter(pk=a.pk))

        a.refresh_from_db()
        self.assertEqual(a.account_status, "active")
        self.assertIs(a.is_active, True)

    def test_승인하면_approved_at_이_찍힌다(self):
        a = _pending("nurse2")
        self.admin.approve(self.req, Account.objects.filter(pk=a.pk))

        staff = Staff.objects.get(account=a)
        self.assertIsNotNone(staff.approved_at)

    def test_approved_by_는_비어_있다(self):
        """admin 은 auth_user 로 로그인해서 지금 누구인지 staff 로 옮길 수 없다.
        아무 staff 나 넣으면 「그 사람이 승인했다」는 거짓이 남으므로 비운다."""
        a = _pending("nurse3")
        self.admin.approve(self.req, Account.objects.filter(pk=a.pk))

        self.assertIsNone(Staff.objects.get(account=a).approved_by_id)

    def test_여러_건을_한_번에_승인한다(self):
        for i in range(3):
            _pending("bulk%d" % i)
        self.admin.approve(self.req, Account.objects.filter(role="nursing"))

        self.assertEqual(
            Account.objects.filter(account_status="active", is_active=True).count(), 3)

    # ── 거절 ────────────────────────────────────────────────────
    def test_거절하면_로그인이_막힌_채로_남는다(self):
        a = _pending("nurse4")
        self.admin.reject(self.req, Account.objects.filter(pk=a.pk))

        a.refresh_from_db()
        self.assertEqual(a.account_status, "rejected")
        self.assertIs(a.is_active, False)
        self.assertIsNone(Staff.objects.get(account=a).approved_at)

    def test_승인했다가_거절하면_approved_at_이_지워진다(self):
        """남아 있으면 「승인된 적 있는데 지금 거절됨」과 구분이 안 된다."""
        a = _pending("nurse5")
        qs = Account.objects.filter(pk=a.pk)
        self.admin.approve(self.req, qs)
        self.admin.reject(self.req, qs)

        self.assertIsNone(Staff.objects.get(account=a).approved_at)

    # ── 환자 ────────────────────────────────────────────────────
    def test_환자는_건너뛰고_알린다(self):
        """환자는 가입하면 바로 active 다. 조용히 넘기면 「눌렀는데 안 됐다」가 된다."""
        p = Account.objects.create(login_id="pat1", role="patient",
                                   account_status="active", is_active=True)
        self.admin.reject(self.req, Account.objects.filter(pk=p.pk))

        p.refresh_from_db()
        self.assertEqual(p.account_status, "active")
        self.assertIs(p.is_active, True)
        self.assertTrue(any("환자" in m for m in self.messages))

    def test_직원과_환자를_같이_고르면_직원만_처리한다(self):
        a = _pending("nurse6")
        p = Account.objects.create(login_id="pat2", role="patient",
                                   account_status="active", is_active=True)
        self.admin.approve(self.req, Account.objects.filter(pk__in=[a.pk, p.pk]))

        a.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(a.account_status, "active")
        self.assertEqual(p.account_status, "active")   # 원래 그대로
        self.assertTrue(any("1건을 승인" in m for m in self.messages))


class QueueFilterTests(TestCase):
    """관리자가 이 화면에 오는 이유는 거의 언제나 «승인할 것이 있나» 다."""

    def setUp(self):
        self.admin = AccountAdmin(Account, AdminSite())
        self.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")
        _pending("wait1")
        Account.objects.create(login_id="done1", role="reception",
                               account_status="active", is_active=True)
        Account.objects.create(login_id="pat3", role="patient",
                               account_status="pending", is_active=False)

    def _rows(self, query=""):
        """필터를 손으로 엮지 않고 **admin 이 실제로 쓰는 길**로 뽑는다 —
        params 를 어떤 모양으로 넘기는지는 Django 판마다 다르다."""
        req = RequestFactory().get("/admin/core/account/" + query)
        req.user = self.boss
        changelist = self.admin.get_changelist_instance(req)
        return {a.login_id for a in changelist.get_queryset(req)}

    def test_기본은_승인_대기_직원만이다(self):
        self.assertEqual(self._rows(), {"wait1"})

    def test_환자는_기본에서_빠진다(self):
        """환자는 승인 대상이 아니다. 목록을 채우면 승인할 직원이 묻힌다."""
        self.assertNotIn("pat3", self._rows())

    def test_전체를_고르면_다_보인다(self):
        self.assertEqual(self._rows("?approval=all&kind=all"),
                         {"wait1", "done1", "pat3"})

    def test_승인됨만_따로_볼_수_있다(self):
        self.assertEqual(self._rows("?approval=active"), {"done1"})
