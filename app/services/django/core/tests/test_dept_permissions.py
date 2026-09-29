# -*- coding: utf-8 -*-
"""과 단위 추가 권한 — staff.extra_depts.

소속 말고 한 벌로 더 보는 과. 그 과의 매트릭스 행 **과** 화면 권한 키를
같이 더한다 — 둘 중 하나만 더하면 반쪽만 열린 계정이 생긴다.

    화면 권한 키    병원 웹 메뉴 · 버튼 (api/perms.py)
    매트릭스        API 게이트 (api/permissions.py)

⚠ 여기서 역할 이름을 손으로 박지 않는다. 「간호는 study R 을 가진다」를
  시험에 적어 두면 매트릭스를 고칠 때 엉뚱한 곳이 깨진다 — 규칙을 불러서
  견준다.
"""

from django.test import RequestFactory, TestCase

from core.api import auth
from core.api.errors import ApiError
from core.api.perms import ROLE_PERMS, perms_for, perms_for_role
from core.api.permissions import (
    ADMIN, MATRIX, GRANTABLE_DEPTS, MatrixPermission, NURSING, PATHOLOGY,
    RADIOLOGY, SURGERY, effective_rule, extra_depts_of, rule_for,
)
from core.models import Account, Staff


def _staff(role=NURSING, depts=None, login="u1"):
    account = Account.objects.create(login_id=login, role=role,
                                     account_status="active", is_active=True)
    Staff.objects.create(account=account, full_name="아무개",
                         staff_number="S-" + login, extra_depts=depts)
    return Account.objects.select_related("staff").get(pk=account.pk)


class ReadTests(TestCase):
    """값을 어떻게 읽는가 — 망가진 값에 열리면 안 된다."""

    def test_준_과가_그대로_나온다(self):
        self.assertEqual(extra_depts_of(_staff(depts=[RADIOLOGY])), [RADIOLOGY])

    def test_없으면_빈_목록(self):
        for value in (None, [], {}, "radiology", 3):
            with self.subTest(repr(value)):
                self.assertEqual(extra_depts_of(_staff(depts=value,
                                                       login="u%s" % id(value))), [])

    def test_모르는_과는_버린다(self):
        got = extra_depts_of(_staff(depts=[RADIOLOGY, "wardroom", ""]))

        self.assertEqual(got, [RADIOLOGY])

    def test_관리자는_줄_수_없다(self):
        """부서가 아니라 문이다 — role='admin' 으로만 열린다."""
        self.assertNotIn(ADMIN, GRANTABLE_DEPTS)
        self.assertEqual(extra_depts_of(_staff(depts=[ADMIN])), [])

    def test_제_소속은_더할_것이_없다(self):
        self.assertEqual(extra_depts_of(_staff(role=NURSING, depts=[NURSING])), [])

    def test_환자_계정은_staff_가_없다(self):
        patient = Account.objects.create(login_id="p1", role="patient",
                                         account_status="active", is_active=True)
        self.assertEqual(extra_depts_of(patient), [])

    def test_관리자_계정은_받을_수도_없다(self):
        """ADMIN_IN_MATRIX = False 를 옆문으로 뚫지 않는다 — 매트릭스에
        열이 없기로 한 역할이 남의 열을 빌려 쓰면 안 된다."""
        self.assertEqual(extra_depts_of(_staff(role=ADMIN, depts=[RADIOLOGY],
                                               login="adm")), [])

    def test_원무_계정은_아직_받을_수_있다(self):
        """과가 아니라 간호과 일의 하나라 줄 수는 없지만, 남아 있는
        계정이 화면을 잃으면 안 된다."""
        from core.api.permissions import RECEPTION

        self.assertEqual(
            extra_depts_of(_staff(role=RECEPTION, depts=[RADIOLOGY], login="rec")),
            [RADIOLOGY])


class ScreenPermTests(TestCase):
    """화면 권한 키 — 병원 웹 메뉴가 이걸 보고 과 탭을 그린다."""

    def test_두_과의_권한이_합쳐진다(self):
        account = _staff(role=NURSING, depts=[RADIOLOGY])

        perms = set(perms_for(account))

        self.assertTrue(set(ROLE_PERMS[NURSING]) <= perms, "제 과가 빠졌다")
        self.assertTrue(set(ROLE_PERMS[RADIOLOGY]) <= perms, "더한 과가 빠졌다")

    def test_제_과의_권한이_앞에_온다(self):
        got = perms_for(_staff(role=NURSING, depts=[RADIOLOGY]))

        self.assertEqual(got[:len(ROLE_PERMS[NURSING])], ROLE_PERMS[NURSING])

    def test_겹치는_권한은_한_번만(self):
        got = perms_for(_staff(role=NURSING, depts=[SURGERY]))

        self.assertEqual(len(got), len(set(got)))

    def test_안_준_계정은_예전과_똑같다(self):
        account = _staff(role=NURSING)

        self.assertEqual(perms_for(account), perms_for_role(NURSING))

    def test_관리자_문은_안_열린다(self):
        """줄 수 있는 과에 admin 이 없으니 ADMIN_PERMS 가 섞일 길이 없다."""
        for dept in GRANTABLE_DEPTS:
            account = _staff(role=dept, depts=list(GRANTABLE_DEPTS),
                             login="adm_%s" % dept)
            self.assertNotIn("admin.console.open", perms_for(account), dept)


class MatrixTests(TestCase):
    """API 게이트 — 매트릭스 행도 같이 더해져야 한다."""

    def test_더한_과의_행위가_열린다(self):
        # 간호에 없고 영상에 있는 칸을 매트릭스에서 찾는다
        resource, action = next(
            (res, a)
            for res in MATRIX
            for a in "CRUD"
            if a in rule_for(res, RADIOLOGY).actions
            and a not in rule_for(res, NURSING).actions)

        account = _staff(role=NURSING, depts=[RADIOLOGY])

        self.assertNotIn(action, rule_for(resource, NURSING).actions)
        self.assertIn(action, effective_rule(account, resource).actions)

    def test_제_과의_행위는_그대로_남는다(self):
        account = _staff(role=NURSING, depts=[PATHOLOGY])

        for resource in MATRIX:
            with self.subTest(resource):
                mine = rule_for(resource, NURSING).actions
                got = effective_rule(account, resource).actions
                self.assertTrue(set(mine) <= set(got), resource)

    def test_한쪽이_전체를_주면_본인만이_풀린다(self):
        """own_only 는 둘 다 「본인만」일 때만 남는다 — 아니면 목록에서
        자기 것만 보이는 계정이 생긴다."""
        # notification 은 모든 역할이 own_only 다. report 는 환자만 그렇다
        account = _staff(role=NURSING, depts=[RADIOLOGY])

        self.assertFalse(effective_rule(account, "report").own_only)

    def test_안_준_계정은_역할_규칙_그대로(self):
        account = _staff(role=NURSING)

        for resource in MATRIX:
            with self.subTest(resource):
                self.assertEqual(effective_rule(account, resource),
                                 rule_for(resource, NURSING))

    def test_게이트가_그_규칙을_쓴다(self):
        """effective_rule 만 고치고 게이트가 rule_for 를 계속 보면
        「저장은 됐는데 여전히 403」이 된다."""
        resource, action, method = next(
            (res, a, m)
            for res in MATRIX
            for a, m in (("R", "GET"), ("C", "POST"), ("U", "PATCH"), ("D", "DELETE"))
            if a in rule_for(res, RADIOLOGY).actions
            and a not in rule_for(res, NURSING).actions)

        view = type("V", (), {"resource": resource})()
        request = getattr(RequestFactory(), method.lower())("/")
        request.user = _staff(role=NURSING, depts=[RADIOLOGY])

        self.assertTrue(MatrixPermission().has_permission(request, view))

    def test_안_준_계정은_여전히_막힌다(self):
        resource, action, method = next(
            (res, a, m)
            for res in MATRIX
            for a, m in (("R", "GET"), ("C", "POST"), ("U", "PATCH"), ("D", "DELETE"))
            if a in rule_for(res, RADIOLOGY).actions
            and a not in rule_for(res, NURSING).actions)

        view = type("V", (), {"resource": resource})()
        request = getattr(RequestFactory(), method.lower())("/")
        request.user = _staff(role=NURSING)

        with self.assertRaises(ApiError):
            MatrixPermission().has_permission(request, view)


class SoloPermissionTests(TestCase):
    """단독 권한 셋은 과별 권한으로도 안 열린다 — IsRole 은 role 만 본다."""

    def test_검체_바인딩은_안_열린다(self):
        from core.api.permissions import CanBindSpecimen

        request = RequestFactory().post("/")
        request.user = _staff(role=PATHOLOGY, depts=[NURSING, SURGERY])

        with self.assertRaises(ApiError):
            CanBindSpecimen().has_permission(request, object())

    def test_불일치_처분과_리포트_잠금_해제도_안_열린다(self):
        from core.api.permissions import CanDisposeDiscordance, CanUnlockReport

        request = RequestFactory().post("/")
        request.user = _staff(role=NURSING, depts=[SURGERY])

        for gate in (CanDisposeDiscordance, CanUnlockReport):
            with self.subTest(gate.__name__), self.assertRaises(ApiError):
                gate().has_permission(request, object())


class TokenTests(TestCase):
    """과를 바꾸면 쓰던 토큰은 바로 막힌다 — 역할을 바꿀 때와 같은 흐름."""

    def _auth(self, token):
        request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer " + token)
        return auth.AccountJWTAuthentication().authenticate(request)

    def test_그대로면_통과한다(self):
        account = _staff(role=NURSING, depts=[RADIOLOGY])

        got, _ = self._auth(auth.issue_access(account))

        self.assertEqual(got.pk, account.pk)

    def test_과를_빼면_막힌다(self):
        account = _staff(role=NURSING, depts=[RADIOLOGY])
        token = auth.issue_access(account)

        account.staff.extra_depts = None
        account.staff.save(update_fields=["extra_depts", "updated_at"])

        with self.assertRaises(ApiError):
            self._auth(token)

    def test_과를_더해도_막힌다(self):
        """더하는 쪽도 막는다 — 새 권한은 다시 로그인해야 받는다.
        옛 토큰이 계속 돌면 「줬는데 화면이 안 바뀐다」가 된다."""
        account = _staff(role=NURSING)
        token = auth.issue_access(account)

        account.staff.extra_depts = [RADIOLOGY]
        account.staff.save(update_fields=["extra_depts", "updated_at"])

        with self.assertRaises(ApiError):
            self._auth(token)

    def test_클레임이_없는_옛_토큰은_그대로_쓴다(self):
        """이 판을 올리는 순간 모두가 튕기면 안 된다 — 추가 과가 실제로
        있는 사람만 다시 로그인한다."""
        account = _staff(role=NURSING)
        payload = auth.decode(auth.issue_access(account))
        payload.pop("depts")

        import jwt
        from django.conf import settings
        old = jwt.encode(payload, settings.JWT["SECRET"],
                         algorithm=settings.JWT["ALGORITHM"])

        got, _ = self._auth(old)
        self.assertEqual(got.pk, account.pk)


class MeTests(TestCase):
    """GET /me — 화면이 읽는 자리. 기존 칸은 그대로 두고 더하기만 했다."""

    def test_perms_에_더한_과가_실린다(self):
        from core.serializers import MeSerializer

        data = MeSerializer(_staff(role=NURSING, depts=[RADIOLOGY])).data

        self.assertTrue(set(ROLE_PERMS[RADIOLOGY]) <= set(data["perms"]))
        self.assertEqual(data["extra_depts"], [RADIOLOGY])

    def test_기존_칸은_그대로다(self):
        from core.serializers import MeSerializer

        data = MeSerializer(_staff(role=NURSING, depts=[RADIOLOGY])).data

        # dept · role 은 **소속**이다. 더한 과로 바뀌면 첫 화면이 딴 데로 간다
        self.assertEqual(data["role"], NURSING)
        self.assertEqual(data["dept"], NURSING)
        self.assertEqual(data["dept_name"], "간호과")
