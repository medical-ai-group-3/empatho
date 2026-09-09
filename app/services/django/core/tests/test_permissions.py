# -*- coding: utf-8 -*-
"""권한 매트릭스(§15)와 단독 권한."""

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from core.api import permissions as perm
from core.api.errors import ApiError


class _StaffStub:
    def __init__(self, extra_permissions):
        self.extra_permissions = extra_permissions


class _Stub:
    """인증을 통과한 Account 대신. DB 를 쓰지 않으려고 둔다."""

    is_authenticated = True

    def __init__(self, role, extra=None, has_staff=True):
        self.role = role
        self.account_id = 1
        if has_staff:
            self.staff = _StaffStub(extra)


class MatrixTests(SimpleTestCase):
    def test_문서에_있던_행이_그대로_있다(self):
        for resource in ("patient", "reservation", "questionnaire", "exam_order",
                         "study", "ai_result", "lesion", "assessment",
                         "specimen_pathology", "discordance_review", "followup",
                         "clinical_decision", "report"):
            self.assertIn(resource, perm.MATRIX, resource)

    def test_v10_에_없는_리소스는_뺐다(self):
        self.assertNotIn("prescription", perm.MATRIX)
        self.assertNotIn("audit_metric", perm.MATRIX)

    def test_인계문서_화면이_쓰는_리소스가_있다(self):
        for resource in ("storage_object", "patient_pii", "notification", "consent"):
            self.assertIn(resource, perm.MATRIX, resource)


class V10ScreenTests(SimpleTestCase):
    """v10 에서 컬럼이 신설되거나 표가 흡수되며 §15 가 못 따라간 U 권한.

    셋 다 라우터 인계 문서에 정상 업무로 적혀 있다.
    """

    def test_영상의학은_병변을_고칠_수_있다(self):
        # §2-4 오탐 표시(is_false_positive) · 캘리퍼 측정(measured_size_*)
        self.assertTrue(perm.rule_for("lesion", perm.RADIOLOGY).allows("U"))

    def test_유방외과는_리포트를_고칠_수_있다(self):
        # §4-5 대면 설명 기록 — result_explanation 이 report 에 흡수됐다
        self.assertTrue(perm.rule_for("report", perm.SURGERY).allows("U"))

    def test_간호는_오더를_고칠_수_있다(self):
        # §6-1 내원 확인 — reservation.visited_at 이 exam_order 로 옮겨졌다
        self.assertTrue(perm.rule_for("exam_order", perm.NURSING).allows("U"))


class NewResourceTests(SimpleTestCase):
    def test_업로드하는_부서만_원본을_올린다(self):
        for role in (perm.RADIOLOGY, perm.PATHOLOGY, perm.NURSING):
            self.assertTrue(perm.rule_for("storage_object", role).allows("C"), role)
        for role in (perm.RECEPTION, perm.SURGERY, perm.PATIENT):
            self.assertFalse(perm.rule_for("storage_object", role).allows("C"), role)

    def test_원본은_아무도_지우지_못한다(self):
        # 지우는 대신 deleted_at 을 찍는다
        for role in perm.MATRIX["storage_object"]:
            self.assertFalse(perm.rule_for("storage_object", role).allows("D"), role)

    def test_유방외과는_영상을_읽지만_올리지는_못한다(self):
        # §4-1 타임라인 검사 카드 · 3D 병변 보기
        rule = perm.rule_for("storage_object", perm.SURGERY)
        self.assertTrue(rule.allows("R"))
        self.assertFalse(rule.allows("C"))

    def test_병리도_영상을_읽는다(self):
        # §7.7 영상 참조 패널 — CR 에 이미 포함돼 있다
        self.assertTrue(perm.rule_for("storage_object", perm.PATHOLOGY).allows("R"))

    def test_개인정보는_원무가_쓰고_환자는_자기_것만_읽는다(self):
        self.assertEqual(perm.rule_for("patient_pii", perm.RECEPTION).actions, "CRU")
        patient = perm.rule_for("patient_pii", perm.PATIENT)
        self.assertEqual(patient.actions, "R")      # /me/profile
        self.assertTrue(patient.own_only)
        for role in (perm.NURSING, perm.RADIOLOGY, perm.PATHOLOGY, perm.SURGERY):
            self.assertEqual(perm.rule_for("patient_pii", role).actions, "", role)

    def test_알림은_본인_것만_읽고_확인한다(self):
        for role in perm.MATRIX["notification"]:
            rule = perm.rule_for("notification", role)
            self.assertEqual(rule.actions, "RU", role)
            self.assertTrue(rule.own_only, role)

    def test_알림은_사람이_만들지_못한다(self):
        # 생성은 시스템(Go I-3)
        for role in perm.MATRIX["notification"]:
            self.assertFalse(perm.rule_for("notification", role).allows("C"), role)

    def test_원무는_환자를_CRUD_한다(self):
        rule = perm.rule_for("patient", perm.RECEPTION)
        for action in "CRUD":
            self.assertTrue(rule.allows(action), action)

    def test_영상의학은_환자를_읽기만_한다(self):
        rule = perm.rule_for("patient", perm.RADIOLOGY)
        self.assertTrue(rule.allows("R"))
        for action in "CUD":
            self.assertFalse(rule.allows(action), action)

    def test_환자는_자기_것만(self):
        self.assertTrue(perm.rule_for("patient", perm.PATIENT).own_only)
        self.assertTrue(perm.rule_for("report", perm.PATIENT).own_only)
        self.assertFalse(perm.rule_for("patient", perm.RECEPTION).own_only)

    def test_환자는_임상_오더에_손대지_못한다(self):
        rule = perm.rule_for("exam_order", perm.PATIENT)
        self.assertEqual(rule.actions, "")
        # 예약은 자기 것을 잡을 수 있다 — 같은 exam_order 표를 건드리지만 권한이 다르다
        self.assertTrue(perm.rule_for("reservation", perm.PATIENT).allows("C"))

    def test_해소_처분은_매트릭스에_없다(self):
        # 단독 권한이라 표에 섞지 않는다
        self.assertNotIn("discordance_disposition", perm.MATRIX)
        self.assertNotIn("report_unlock", perm.MATRIX)

    def test_admin_은_매트릭스로는_아무것도_못_한다(self):
        self.assertFalse(perm.ADMIN_IN_MATRIX)
        self.assertEqual(perm.rule_for("patient", perm.ADMIN).actions, "")

    def test_매트릭스에_없는_리소스는_막힌다(self):
        with self.assertRaises(KeyError):
            perm.rule_for("없는리소스", perm.RECEPTION)

    def test_메서드가_행위로_옮겨진다(self):
        self.assertEqual(perm.action_for("GET"), "R")
        self.assertEqual(perm.action_for("POST"), "C")
        self.assertEqual(perm.action_for("PATCH"), "U")
        self.assertEqual(perm.action_for("PUT"), "U")
        self.assertEqual(perm.action_for("DELETE"), "D")


class SoleAuthorityTests(SimpleTestCase):
    def _check(self, klass, role):
        request = type("R", (), {"user": _Stub(role), "method": "POST"})()
        return klass().has_permission(request, None)

    def test_검체_바인딩은_간호와_유방외과다(self):
        for role in (perm.NURSING, perm.SURGERY):
            self.assertTrue(self._check(perm.CanBindSpecimen, role), role)

    def test_영상의학은_검체를_만지지_못한다(self):
        with self.assertRaises(ApiError) as caught:
            self._check(perm.CanBindSpecimen, perm.RADIOLOGY)
        self.assertEqual(caught.exception.code, "BINDING_ROLE_FORBIDDEN")
        self.assertEqual(caught.exception.status_code, 403)

    def test_해소_처분은_유방외과만(self):
        self.assertTrue(self._check(perm.CanDisposeDiscordance, perm.SURGERY))
        with self.assertRaises(ApiError) as caught:
            self._check(perm.CanDisposeDiscordance, perm.RADIOLOGY)
        self.assertEqual(caught.exception.code, "DISPOSITION_ROLE_ONLY_SURGERY")

    def test_잠금_해제는_유방외과만(self):
        self.assertTrue(self._check(perm.CanUnlockReport, perm.SURGERY))
        with self.assertRaises(ApiError) as caught:
            self._check(perm.CanUnlockReport, perm.PATHOLOGY)
        self.assertEqual(caught.exception.code, "UNLOCK_ROLE_ONLY_SURGERY")


# ── 뷰에 걸었을 때 ───────────────────────────────────────────────────────
class _View:
    """resource 만 선언한 뷰 흉내. 권한 클래스가 보는 것은 이게 전부다."""

    def __init__(self, resource=None, owner=None):
        if resource is not None:
            self.resource = resource
        if owner is not None:
            self.is_owned_by = owner


def _request(role, method="GET", extra=None, has_staff=True):
    account = _Stub(role, extra=extra, has_staff=has_staff)
    return type("R", (), {"user": account, "method": method})()


class MatrixPermissionTests(SimpleTestCase):
    def setUp(self):
        self.permission = perm.MatrixPermission()

    def test_영상의학은_검사를_만들_수_있다(self):
        self.assertTrue(self.permission.has_permission(
            _request(perm.RADIOLOGY, "POST"), _View("study")))

    def test_원무는_검사에_손대지_못한다(self):
        with self.assertRaises(ApiError) as caught:
            self.permission.has_permission(_request(perm.RECEPTION), _View("study"))
        self.assertEqual(caught.exception.code, "ROLE_FORBIDDEN")
        self.assertEqual(caught.exception.status_code, 403)

    def test_병리는_검사를_읽지만_만들지_못한다(self):
        self.assertTrue(self.permission.has_permission(
            _request(perm.PATHOLOGY), _View("study")))
        with self.assertRaises(ApiError):
            self.permission.has_permission(
                _request(perm.PATHOLOGY, "POST"), _View("study"))

    def test_인증이_안_됐으면_401(self):
        request = type("R", (), {"user": None, "method": "GET"})()
        with self.assertRaises(ApiError) as caught:
            self.permission.has_permission(request, _View("study"))
        self.assertEqual(caught.exception.code, "UNAUTHENTICATED")

    def test_리소스를_선언하지_않은_뷰는_막힌다(self):
        with self.assertRaises(ImproperlyConfigured):
            self.permission.has_permission(_request(perm.RADIOLOGY), _View())

    def test_소유_판정이_없으면_본인_권한이_열리지_않는다(self):
        # report 는 환자에게 own_only 다. 뷰가 is_owned_by 를 안 주면 막는다 —
        # 소유 판정을 빠뜨린 채 열리는 것보다 낫다.
        with self.assertRaises(ImproperlyConfigured):
            self.permission.has_object_permission(
                _request(perm.PATIENT), _View("report"), object())

    def test_남의_것이면_거부된다(self):
        view = _View("report", owner=lambda obj, account: False)
        with self.assertRaises(ApiError) as caught:
            self.permission.has_object_permission(
                _request(perm.PATIENT), view, object())
        self.assertEqual(caught.exception.code, "ROLE_FORBIDDEN")

    def test_자기_것이면_통과한다(self):
        view = _View("report", owner=lambda obj, account: True)
        self.assertTrue(self.permission.has_object_permission(
            _request(perm.PATIENT), view, object()))

    def test_own_only_가_아닌_역할은_소유_판정을_거치지_않는다(self):
        # 영상의학은 report 에 own_only 가 아니라 is_owned_by 가 없어도 통과한다
        self.assertTrue(self.permission.has_object_permission(
            _request(perm.RADIOLOGY), _View("report"), object()))


class OwnedOnlyMixinTests(SimpleTestCase):
    """목록 단계의 「본인」 권한. 권한 클래스가 못 막는 자리다."""

    class _Base:
        def __init__(self, role):
            self.request = _request(role)

        def get_queryset(self):
            return ["남의 것", "내 것"]

    def _view(self, role, resource, owned=None):
        body = {"resource": resource}
        if owned is not None:
            body["owned_queryset"] = owned
        klass = type("V", (perm.OwnedOnlyMixin, self._Base), body)
        return klass(role)

    def test_본인_권한이면_걸러진다(self):
        view = self._view(perm.PATIENT, "patient_pii",
                          owned=lambda self, qs, account: ["내 것"])
        self.assertEqual(view.get_queryset(), ["내 것"])

    def test_본인_권한이_아니면_그대로_둔다(self):
        view = self._view(perm.RECEPTION, "patient_pii")
        self.assertEqual(view.get_queryset(), ["남의 것", "내 것"])

    def test_거르는_법을_안_주면_막힌다(self):
        view = self._view(perm.PATIENT, "patient_pii")
        with self.assertRaises(ImproperlyConfigured):
            view.get_queryset()


class ExtraPermissionTests(SimpleTestCase):
    """staff.extra_permissions — 역할 기본 권한에 개인별로 더한다."""

    def setUp(self):
        self.permission = perm.MatrixPermission()

    def test_개인_추가_권한이_더해진다(self):
        # 원무는 매트릭스로 study 에 아무 권한이 없다
        with self.assertRaises(ApiError):
            self.permission.has_permission(_request(perm.RECEPTION), _View("study"))
        # 개인에게 R 을 주면 열린다
        request = _request(perm.RECEPTION, extra={"study": ["R"]})
        self.assertTrue(self.permission.has_permission(request, _View("study")))

    def test_준_행위만_열린다(self):
        request = _request(perm.RECEPTION, "POST", extra={"study": ["R"]})
        with self.assertRaises(ApiError):
            self.permission.has_permission(request, _View("study"))

    def test_다른_리소스는_안_열린다(self):
        request = _request(perm.RECEPTION, extra={"assessment": ["R"]})
        with self.assertRaises(ApiError):
            self.permission.has_permission(request, _View("study"))

    def test_역할_기본_권한은_그대로_남는다(self):
        # 영상의학은 매트릭스로 study CRU. 엉뚱한 개인 권한이 있어도 안 잃는다.
        request = _request(perm.RADIOLOGY, "POST", extra={"report": ["R"]})
        self.assertTrue(self.permission.has_permission(request, _View("study")))

    def test_단독_권한은_개인_추가로_안_열린다(self):
        for klass, code in ((perm.CanBindSpecimen, "BINDING_ROLE_FORBIDDEN"),
                            (perm.CanDisposeDiscordance, "DISPOSITION_ROLE_ONLY_SURGERY"),
                            (perm.CanUnlockReport, "UNLOCK_ROLE_ONLY_SURGERY")):
            request = _request(perm.RADIOLOGY, "POST",
                               extra={"specimen_binding": ["C"], "report": ["U"],
                                      "discordance_disposition": ["C", "U"]})
            with self.assertRaises(ApiError) as caught:
                klass().has_permission(request, None)
            self.assertEqual(caught.exception.code, code)

    def test_값이_없거나_망가져도_열리지_않는다(self):
        for extra in (None, {}, {"study": None}, {"study": "R"}, {"study": []},
                      {"study": ["X"]}, {"study": [1, None]}, {"study": ["CR"]},
                      "이건 dict 가 아니다", ["study"]):
            request = _request(perm.RECEPTION, extra=extra)
            with self.assertRaises(ApiError, msg=repr(extra)):
                self.permission.has_permission(request, _View("study"))

    def test_staff_행이_없는_계정은_추가_권한이_없다(self):
        request = _request(perm.PATIENT, has_staff=False)
        with self.assertRaises(ApiError):
            self.permission.has_permission(request, _View("study"))

    def test_extra_actions_for_가_아는_행위만_추린다(self):
        account = _Stub(perm.RECEPTION, extra={"study": ["R", "X", "C", 1, None]})
        self.assertEqual(sorted(perm.extra_actions_for(account, "study")), ["C", "R"])
