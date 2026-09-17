# -*- coding: utf-8 -*-
"""staff.extra_permissions 체크박스 격자."""

from django.contrib.admin.sites import AdminSite
from django.test import TestCase

from core.admin import StaffAdmin, StaffForm
from core.admin_perms import ACTIONS, PermissionGrid
from core.api.permissions import MATRIX, rule_for
from core.models import Account, Staff

FIELD = "extra_permissions"


def _staff(role="nursing", extra=None):
    account = Account.objects.create(login_id="u_" + role, role=role,
                                     account_status="active", is_active=True)
    return Staff.objects.create(account=account, full_name="아무개",
                                staff_number="S-" + role, extra_permissions=extra)


def _post(**checked):
    """격자가 보내는 모양 — 체크된 칸만 키로 온다."""
    return {f"{FIELD}__{res}__{act}": "on" for res, acts in checked.items()
            for act in acts}


def _missing(role, resource):
    """그 역할이 **안 가진** 행위들. 매트릭스를 고쳐도 시험이 같이 따라간다 —
    「간호는 report R 을 가진다」를 시험에 박아 두면 그때 엉뚱한 곳이 깨진다."""
    granted = rule_for(resource, role).actions
    return [a for a, _ in ACTIONS if a not in granted]


class GridReadTests(TestCase):
    def test_체크된_칸만_모은다(self):
        """역할이 **안 가진** 행위로 고른다 — 이미 가진 것은 개인 추가로
        저장하지 않는 것이 맞고, 그건 아래에서 따로 본다."""
        role = "nursing"
        grid = PermissionGrid(role=role)
        a_new = _missing(role, "assessment")[:1]
        r_new = _missing(role, "report")[:2]

        got = grid.value_from_datadict(
            _post(assessment=a_new, report=r_new), {}, FIELD)

        self.assertEqual(sorted(got), ["assessment", "report"])
        self.assertEqual(got["assessment"], a_new)
        self.assertEqual(got["report"], r_new)

    def test_아무것도_안_고르면_NULL_이다(self):
        """빈 dict 가 아니라 NULL 이 이 칸의 「없음」이다 —
        판정(extra_actions_for)은 dict 가 아니면 빈 문자열로 떨어진다."""
        grid = PermissionGrid(role="nursing")
        self.assertIsNone(grid.value_from_datadict({}, {}, FIELD))

    def test_역할이_이미_주는_칸은_개인_추가로_저장하지_않는다(self):
        """저장하면 역할에서 그 권한을 빼도 이 사람만 계속 갖는다 —
        「역할을 고쳤는데 한 사람만 안 바뀐다」가 가장 찾기 어렵다."""
        role = "nursing"
        granted = rule_for("patient", role).actions      # 간호는 patient RU
        self.assertTrue(granted, "전제가 깨졌다 — 간호에게 patient 권한이 있어야 한다")

        grid = PermissionGrid(role=role)
        got = grid.value_from_datadict(_post(patient=list(granted)), {}, FIELD)
        self.assertIsNone(got)

    def test_역할에_없는_칸만_남는다(self):
        role = "nursing"
        granted = rule_for("study", role).actions        # 간호는 study R
        missing = [a for a, _ in ACTIONS if a not in granted]

        grid = PermissionGrid(role=role)
        got = grid.value_from_datadict(
            _post(study=list(granted) + missing[:1]), {}, FIELD)
        self.assertEqual(got, {"study": missing[:1]})

    def test_없는_리소스는_아예_안_들어간다(self):
        """손으로 JSON 을 쓰면 assesment 처럼 한 글자 틀려도 조용히 무시된다.
        격자는 MATRIX 에 있는 것만 훑으므로 그 길이 없다."""
        grid = PermissionGrid(role="nursing")
        got = grid.value_from_datadict(
            {f"{FIELD}__assesment__R": "on"}, {}, FIELD)
        self.assertIsNone(got)

    def test_한_글자가_아닌_행위는_안_들어간다(self):
        """["CR"] 로 묶어 쓰면 판정이 통째로 버린다(_ACTIONS). 격자는 C·R·U·D
        네 칸뿐이라 묶인 값이 생길 수 없다."""
        grid = PermissionGrid(role="nursing")
        got = grid.value_from_datadict({f"{FIELD}__report__CR": "on"}, {}, FIELD)
        self.assertIsNone(got)


class GridRenderTests(TestCase):
    def test_모든_리소스가_격자에_있다(self):
        html = PermissionGrid(role="nursing").render(FIELD, None)
        for resource in MATRIX:
            self.assertIn(resource, html, resource)

    def test_역할이_가진_칸은_잠겨_있다(self):
        html = PermissionGrid(role="nursing").render(FIELD, None)
        self.assertIn("disabled", html)

    def test_단독_권한_셋을_적어_둔다(self):
        """개인 추가로 못 여는 것들이라 격자에 넣으면 체크는 되는데 아무 일도
        안 일어난다. 대신 무엇이 그런지 적는다."""
        html = PermissionGrid(role="surgery").render(FIELD, None)
        for word in ("검체 바인딩", "불일치 해소 처분", "리포트 열람 잠금 해제"):
            self.assertIn(word, html, word)

    def test_이미_준_개인_권한이_체크되어_나온다(self):
        action = _missing("nursing", "report")[0]
        html = PermissionGrid(role="nursing").render(
            FIELD, {"report": [action]})
        self.assertIn(f'name="{FIELD}__report__{action}" checked', html)


class StaffFormTests(TestCase):
    def test_폼이_그_사람의_역할로_격자를_세운다(self):
        staff = _staff(role="radiology")
        form = StaffForm(instance=staff)
        self.assertEqual(form.fields[FIELD].widget.role, "radiology")

    def test_격자로_저장된다(self):
        staff = _staff(role="nursing")
        data = {
            "account": staff.account_id,
            "full_name": "아무개",
            "staff_number": staff.staff_number,
            **_post(report=["U"]),
        }
        form = StaffForm(data, instance=staff)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        staff.refresh_from_db()
        self.assertEqual(staff.extra_permissions, {"report": ["U"]})

    def test_판정이_그_값을_실제로_읽는다(self):
        """저장 모양이 판정이 읽는 모양과 같아야 한다 — 다르면 화면은
        저장됐다고 하고 권한은 안 생긴다."""
        from core.api.permissions import extra_actions_for

        staff = _staff(role="nursing")
        grid = PermissionGrid(role="nursing")
        staff.extra_permissions = grid.value_from_datadict(
            _post(report=["U"]), {}, FIELD)
        staff.save()

        account = Account.objects.select_related("staff").get(pk=staff.account_id)
        self.assertIn("U", extra_actions_for(account, "report"))


class StaffListTests(TestCase):
    def setUp(self):
        self.admin = StaffAdmin(Staff, AdminSite())

    def test_추가_권한_유무가_보인다(self):
        self.assertFalse(self.admin.has_extra(_staff(role="nursing")))
        self.assertTrue(
            self.admin.has_extra(_staff(role="surgery", extra={"report": ["R"]})))

    def test_부서가_한글로_나온다(self):
        self.assertEqual(self.admin.dept(_staff(role="radiology")), "영상의학과")
