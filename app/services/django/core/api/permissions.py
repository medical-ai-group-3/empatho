"""역할별 권한 — 명세서 §15 매트릭스.

판정 = 역할 기본 권한(아래 MATRIX) + 개인 추가 권한(staff.extra_permissions).
개인 쪽은 더하기만 한다 — 역할이 준 권한을 개인이 잃는 경로는 없다.

역할은 account.role 로만 본다. v10 은 staff 에 부서 컬럼을 두지 않는다 —
같은 값을 두 표에 두면 CHECK 으로 못 거는 동기화 규칙이 생긴다.

v10 에서 빠진 리소스 — 되살리면 여기 추가
    audit_metric   감사지표 표가 없다 (13.3 · 13.4)
    문서 §15 에는 이 행이 있지만 쓸 수 있는 테이블이 없어 뺐다. 못 쓰는 권한이
    표에 있으면 다음 사람이 테이블이 있는 줄 안다.
    (prescription 은 09-21 Prescription 모델과 함께 추가했다 — v10 에 없던
     것을 새로 판 것이지 문서 §15 에 있던 것을 되살린 게 아니다. 아래
     MATRIX 의 prescription 행 주석 참고)

단독 권한은 매트릭스에 섞지 않고 아래 별도 클래스로 세운다. 표 한 칸을 고쳐서
조용히 풀리면 안 되는 것들이다 — 풀리는 순간 미처리 건이 어느 큐에도 안 남는다.
개인 추가 권한으로도 열리지 않는다.
"""

from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from .errors import ApiError

# account.role — v10 CHECK 이 이미 이 7 개로 막는다.
RECEPTION = "reception"
NURSING = "nursing"
RADIOLOGY = "radiology"
PATHOLOGY = "pathology"
SURGERY = "surgery"
PATIENT = "patient"
ADMIN = "admin"

# admin 은 §15 매트릭스에 열이 없다. 매트릭스로는 아무 권한도 주지 않고,
# 관리자 전용 엔드포인트(2.7 · 2.8)에서 IsRole(ADMIN) 로 따로 연다.
# 「admin 에게 전부 열어줄 것인가」는 문서에 없어 팀 확인 대상이다.
ADMIN_IN_MATRIX = False

_METHOD_ACTION = {
    "GET": "R", "HEAD": "R", "OPTIONS": "R",
    "POST": "C",
    "PUT": "U", "PATCH": "U",
    "DELETE": "D",
}

# 한 글자짜리만 받는다. "CR" 같은 묶음이 부분 문자열로 통과하지 않게.
_ACTIONS = frozenset("CRUD")


@dataclass(frozen=True)
class Rule:
    actions: str = ""          # "CRUD" 의 부분집합
    own_only: bool = False     # 문서의 「본인」 — 자기 것에만
    note: str = ""

    def allows(self, action):
        return action in self.actions


def _r(actions, own_only=False, note=""):
    return Rule(actions=actions, own_only=own_only, note=note)


NONE = Rule()

# 문서 §15 를 그대로 옮긴 것. 행 이름은 v10 테이블에 맞췄다.
MATRIX = {
    # patient · reservation 행 중 patient 부분
    "patient": {
        RECEPTION: _r("CRUD"), NURSING: _r("RU"), RADIOLOGY: _r("R"),
        PATHOLOGY: _r("R"), SURGERY: _r("R"), PATIENT: _r("CRU", own_only=True),
    },
    # 문서의 reservation. v10 에는 표가 없고 exam_order 에 흡수됐지만 권한은
    # 따로 둔다 — 환자는 자기 예약을 잡을 수 있어도 임상 오더를 낼 수는 없다.
    "reservation": {
        RECEPTION: _r("CRUD"), NURSING: _r("RU"), RADIOLOGY: _r("R"),
        PATHOLOGY: _r("R"), SURGERY: _r("R"), PATIENT: _r("CRU", own_only=True),
        # 같은 exam_order 행을 건드린다. 뷰가 scheduled_at · visited_at 밖의
        # 칸을 환자에게 열지 않도록 직렬화 단계에서 막을 것.
    },
    "questionnaire": {
        RECEPTION: _r("R"), NURSING: _r("CRU"), RADIOLOGY: _r("R"),
        PATHOLOGY: _r("R"), SURGERY: _r("R"), PATIENT: NONE,
    },
    "exam_order": {
        RECEPTION: _r("CRU"),
        NURSING: _r("CRU", note="내원 확인 — visited_at"),
        RADIOLOGY: _r("CRU"), PATHOLOGY: _r("R"), SURGERY: _r("CR"), PATIENT: NONE,
    },
    "study": {
        RECEPTION: NONE, NURSING: _r("R"), RADIOLOGY: _r("CRU"),
        PATHOLOGY: _r("R"), SURGERY: _r("R"), PATIENT: NONE,
        # 품질 반려(4.8)도 이 행이다.
    },
    "ai_result": {
        RECEPTION: NONE, NURSING: NONE,
        RADIOLOGY: _r("CR", note="1 차 판정 잠금 후에만 R — 엔드포인트가 따로 막는다"),
        PATHOLOGY: _r("CR", note="병리 소켓"), SURGERY: _r("R"), PATIENT: NONE,
    },
    "lesion": {
        RECEPTION: NONE, NURSING: NONE,
        RADIOLOGY: _r("CRU", note="오탐 표시 · 캘리퍼 측정"),
        PATHOLOGY: _r("CR"), SURGERY: _r("R"), PATIENT: NONE,
    },
    "assessment": {
        RECEPTION: _r("R"), NURSING: _r("R"), RADIOLOGY: _r("CRU"),
        PATHOLOGY: _r("R"), SURGERY: _r("R"), PATIENT: NONE,
    },
    # 문서의 pathology_result · FINAL. v10 은 specimen 에 흡수됐다.
    "specimen_pathology": {
        RECEPTION: _r("R"), NURSING: _r("R"), RADIOLOGY: _r("R"),
        PATHOLOGY: _r("CRU"), SURGERY: _r("R"), PATIENT: NONE,
    },
    # 09-28 — 영상의학에 R 을 더한다(제품 책임자 승인). 자기 판독이 병리와
    # 어떻게 맞았는지(처분 결과)를 본다. **본인 것만** — 여기서 「본인」은
    # 환자 계정이 아니라 assessment.assessed_by 가 자기인 플래그다.
    # 목록은 DiscordanceListView.owned_queryset 이 거른다.
    "discordance_review": {
        RECEPTION: NONE, NURSING: NONE,
        RADIOLOGY: _r("CRU", own_only=True,
                      note="의견만 — 종결시키지 못한다 · 자기 판독의 불일치만 본다"),
        PATHOLOGY: _r("R"), SURGERY: _r("R"), PATIENT: NONE,
    },
    # 09-28 — 유방외과 R → CR(제품 책임자 승인). 외래에서 BI-RADS 3 환자의
    # 다음 회차를 바로 잡는다(POST /followups/new). U(통화 기록 · 종료)는
    # 간호 일이라 주지 않는다.
    "followup": {
        RECEPTION: _r("R"), NURSING: _r("CRU"), RADIOLOGY: _r("CRU"),
        PATHOLOGY: NONE, SURGERY: _r("CR", note="회차 생성 — 외래"),
        PATIENT: _r("R", own_only=True),
    },
    # 문서의 clinical_decision. v10 은 assessment.decision_* 에 흡수됐다.
    "clinical_decision": {
        RECEPTION: _r("R"), NURSING: _r("R"), RADIOLOGY: _r("R"),
        PATHOLOGY: _r("R"), SURGERY: _r("CRU"), PATIENT: NONE,
    },
    "report": {
        RECEPTION: _r("C", note="발급만"), NURSING: _r("R"), RADIOLOGY: _r("CR"),
        PATHOLOGY: _r("CR"),
        SURGERY: _r("CRU", note="대면 설명 기록 — explained_* · patient_confirmed"),
        PATIENT: _r("R", own_only=True),
    },
    # 올리는 부서만 C. D 는 아무도 — 지우는 대신 deleted_at 을 찍는다.
    "storage_object": {
        RECEPTION: NONE, NURSING: _r("CR"), RADIOLOGY: _r("CR"),
        PATHOLOGY: _r("CR", note="§7.7 영상 참조 패널"),
        SURGERY: _r("R", note="§4-1 타임라인 검사 카드 · 3D 병변 보기"),
        PATIENT: NONE,
    },
    "patient_pii": {
        RECEPTION: _r("CRU"), NURSING: NONE, RADIOLOGY: NONE,
        PATHOLOGY: NONE, SURGERY: NONE,
        PATIENT: _r("R", own_only=True, note="/me/profile"),
    },
    # 만드는 것은 시스템(Go I-3)이라 사람에게 C 가 없다. 확인 처리만 U.
    "notification": {
        RECEPTION: _r("RU", own_only=True), NURSING: _r("RU", own_only=True),
        RADIOLOGY: _r("RU", own_only=True), PATHOLOGY: _r("RU", own_only=True),
        SURGERY: _r("RU", own_only=True), PATIENT: _r("RU", own_only=True),
    },
    # v10 신설. 문서 §15 에 행이 없어 우리가 정한다 — 팀 확인 대상.
    # 09-28 — 간호 · 원무에 R(제품 책임자 승인). 창구에서 동의 여부를 확인한다
    # (GET /patients/{id}/consents). 읽기만 — 동의는 환자 본인만 한다.
    "consent": {
        RECEPTION: _r("R"), NURSING: _r("R", note="창구 동의 확인"),
        RADIOLOGY: NONE, PATHOLOGY: NONE, SURGERY: NONE,
        PATIENT: _r("CR", own_only=True),
    },
    # v10 신설 (09-21, models.py 의 Prescription 참고). 처방은 유방외과만
    # 만든다. 원무는 서류 발급 화면에서 조회만 한다 — §11 리포트 발급과
    # 같은 결이라 report 행의 RECEPTION: _r("C", note="발급만") 과 짝지어
    # 읽으면 된다(그쪽은 발급, 이쪽은 조회).
    # 09-21 — PATIENT 를 NONE 에서 R(own_only)로 연다. 환자 앱 복약 관리가
    # /me/prescriptions 로 자기 처방을 읽어야 한다. R 뿐이다 — 「먹었다」를
    # 적는 것은 아래 medication_log 행이고, 둘을 나눈 이유가 그것이다.
    # 한 행으로 두면 환자에게 C 를 줘야 하고 그러면 처방 자체를 만들 길이 열린다.
    "prescription": {
        RECEPTION: _r("R", note="서류 발급 화면 조회"), NURSING: NONE, RADIOLOGY: NONE,
        PATHOLOGY: NONE, SURGERY: _r("CR"),
        PATIENT: _r("R", own_only=True, note="/me/prescriptions"),
    },
    # 09-21 신설. 환자가 유일하게 쓰는 임상 자료다. C 와 D 만 준다 —
    # U 가 없는 이유는 고칠 것이 없기 때문이다. 잘못 눌렀으면 지운다.
    "medication_log": {
        RECEPTION: NONE, NURSING: _r("R"), RADIOLOGY: NONE,
        PATHOLOGY: NONE, SURGERY: _r("R"),
        PATIENT: _r("CRD", own_only=True),
    },
}


# 09-27 — 원무과가 간호과로 합쳐졌다(프론트 hospital/nav.js 6.1). 창구 일
# (환자 등록 · 접수 · 예약 · 인적 사항 수정)을 간호가 하므로 **간호는 원무가
# 가진 것을 다 가진다.** 행마다 손으로 옮기면 원무 칸을 고칠 때 간호 칸을
# 빠뜨리게 되므로 여기서 한 번에 더한다. 빼는 것은 없다 — 간호 고유의
# 권한(문진 · 추적 · 영상 원본)은 그대로 남는다.
def _merge_reception_into_nursing():
    for table in MATRIX.values():
        rec = table.get(RECEPTION, NONE)
        nur = table.get(NURSING, NONE)
        actions = "".join(a for a in "CRUD" if a in rec.actions or a in nur.actions)
        # 한쪽이라도 「전체」면 전체다. 빈 쪽은 따지지 않는다
        owns = [r.own_only for r in (rec, nur) if r.actions]
        table[NURSING] = Rule(
            actions=actions,
            own_only=bool(owns) and all(owns),
            note=" · ".join(n for n in (nur.note, rec.note) if n),
        )


_merge_reception_into_nursing()


def rule_for(resource, role):
    try:
        table = MATRIX[resource]
    except KeyError:
        raise KeyError(
            "리소스 %r 이 권한 매트릭스에 없다. core/api/permissions.py 에 먼저 넣을 것." % resource
        ) from None
    if role == ADMIN and not ADMIN_IN_MATRIX:
        return NONE
    return table.get(role, NONE)


def action_for(method):
    return _METHOD_ACTION.get(method.upper(), "")


def extra_actions_for(account, resource):
    """staff.extra_permissions 가 이 리소스에 더해 주는 행위.

    더하기만 한다. 역할이 준 권한을 개인이 잃는 경로는 두지 않는다.
    단독 권한 3 개는 이걸로 열리지 않는다 — 그쪽은 IsRole 계열이라 여기를 안 본다.

    값이 망가져 있어도 권한이 열리지 않게, 아는 모양이 아니면 빈 문자열이다.
    """
    staff = getattr(account, "staff", None)      # 환자 계정은 staff 행이 없다
    granted = getattr(staff, "extra_permissions", None)
    if not isinstance(granted, dict):
        return ""
    actions = granted.get(resource)
    if not isinstance(actions, (list, tuple)):
        return ""
    return "".join(a for a in actions if a in _ACTIONS)


class IsAuthenticatedAccount:
    """Account 로 인증됐는가. DRF 의 IsAuthenticated 와 같은 자리지만 코드를 우리 것으로."""

    def has_permission(self, request, view):
        account = getattr(request, "user", None)
        if account is None or not getattr(account, "is_authenticated", False):
            raise ApiError("UNAUTHENTICATED")
        return True

    def has_object_permission(self, request, view, obj):
        return True


class MatrixPermission(IsAuthenticatedAccount):
    """뷰가 선언한 resource 를 §15 매트릭스에서 찾아 판정한다.

        class StudyViewSet(...):
            resource = "study"
            permission_classes = [MatrixPermission]

    「본인」 권한(own_only)은 두 군데를 다 막아야 한다.
        한 건    뷰가 is_owned_by(obj, account) 를 정의한다. 없으면 막는다 —
                 소유 판정을 빠뜨린 채 열리는 것보다 낫다.
        목록     권한 클래스가 쿼리셋을 못 봐서 못 막는다. 뷰가 OwnedOnlyMixin
                 을 붙여 걸러야 한다. 안 붙이면 남의 행이 목록에 섞인다.
    """

    def _resource(self, view):
        resource = getattr(view, "resource", None)
        if not resource:
            raise ImproperlyConfigured(
                "%s 에 resource 가 없다. MatrixPermission 은 리소스 이름이 있어야 판정한다."
                % type(view).__name__
            )
        return resource

    def has_permission(self, request, view):
        super().has_permission(request, view)
        resource = self._resource(view)
        action = action_for(request.method)
        rule = rule_for(resource, request.user.role)
        if rule.allows(action) or action in extra_actions_for(request.user, resource):
            return True
        raise ApiError("ROLE_FORBIDDEN")

    def has_object_permission(self, request, view, obj):
        rule = rule_for(self._resource(view), request.user.role)
        if not rule.own_only:
            return True

        owned_by = getattr(view, "is_owned_by", None)
        if owned_by is None:
            raise ImproperlyConfigured(
                "%s 는 「본인」 권한이 걸린 리소스인데 is_owned_by 가 없다." % type(view).__name__
            )
        if not owned_by(obj, request.user):
            raise ApiError("ROLE_FORBIDDEN")
        return True


class OwnedOnlyMixin:
    """own_only 가 걸린 역할에게는 목록도 자기 것만 보이게 한다.

        class MyReportList(OwnedOnlyMixin, ListAPIView):
            resource = "report"

            def owned_queryset(self, queryset, account):
                return queryset.filter(patient__account=account)

    MatrixPermission 은 객체 하나는 막지만 목록은 못 막는다 — 쿼리셋을 못 보기
    때문이다. own_only 리소스를 다루는 뷰는 이 믹스인을 함께 붙인다.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        role = self.request.user.role
        if not rule_for(getattr(self, "resource", ""), role).own_only:
            return queryset
        return self.owned_queryset(queryset, self.request.user)

    def owned_queryset(self, queryset, account):
        raise ImproperlyConfigured(
            "%s 는 「본인」 권한이 걸린 리소스인데 owned_queryset 이 없다."
            % type(self).__name__
        )


class IsRole(IsAuthenticatedAccount):
    """역할을 직접 지정한다. 매트릭스에 없는 관리자 전용 경로에 쓴다.

        permission_classes = [IsRole.of(ADMIN)]
    """

    roles = frozenset()
    code = "ROLE_FORBIDDEN"

    @classmethod
    def of(cls, *roles, code="ROLE_FORBIDDEN"):
        return type("IsRole_" + "_".join(roles),
                    (cls,), {"roles": frozenset(roles), "code": code})

    def has_permission(self, request, view):
        super().has_permission(request, view)
        if request.user.role not in self.roles:
            raise ApiError(self.code)
        return True


# ── 단독 권한 ────────────────────────────────────────────────────────────
# 문서가 굵게 표시한 것들. 다른 역할에 주면 미처리 건이 어느 큐에도 남지 않는다.

#: 검체 바인딩 — 09-09 팀 확정. 유방외과가 채취하고 간호가 라벨링·바인딩한다.
#: 영상의학은 판독만 하고 검체는 만지지 않는다.
#: 문서와 다르다 — §7.1 · §15 는 「간호 단독」, 개정 이력은 「영상의학 · 유방외과 ·
#: 간호」다. 어느 쪽도 맞지 않아 문서 반영 요청 목록에 올렸다.
CanBindSpecimen = IsRole.of(NURSING, SURGERY, code="BINDING_ROLE_FORBIDDEN")

#: 수술 결정 기록 — 유방외과 단독. 다른 부서는 이 경로로 assessment를
#: 못 건드린다. 범용 PATCH /assessments/{id} 와는 분리된 경로다.
CanDecideAssessment = IsRole.of(SURGERY, code="DECISION_ROLE_ONLY_SURGERY")

#: 불일치 해소 처분 — 유방외과 단독 (§8.4)
CanDisposeDiscordance = IsRole.of(SURGERY, code="DISPOSITION_ROLE_ONLY_SURGERY")

# 촬영 완료 처리 — 기존 exam_order 매트릭스는 그대로 둔다.
# 매트릭스에서 이미 허용된 역할은 계속 통과시키고, 유방외과에는 이 endpoint
# 하나에서만 U 권한을 추가한다.
class CanCompleteExamOrder(MatrixPermission):
    def has_permission(self, request, view):
        IsAuthenticatedAccount.has_permission(self, request, view)
        if request.user.role == SURGERY:
            return True
        return super().has_permission(request, view)

#: 리포트 열람 잠금 해제 — 유방외과 단독 (§11.5)
CanUnlockReport = IsRole.of(SURGERY, code="UNLOCK_ROLE_ONLY_SURGERY")
CanIssueFinalReport = IsRole.of(SURGERY, code="FINAL_REPORT_ROLE_ONLY_SURGERY")

# 09-21 추가 — 간소 접수 등록(POST /patients/register). patient 매트릭스는
# 그대로 둔다(정식 등록 POST /patients/ 는 여전히 원무 단독 CRUD) — 간호에는
# 이 endpoint 하나에서만 C 권한을 추가한다. CanCompleteExamOrder 와 같은
# 패턴이다.
class CanRegisterPatient(MatrixPermission):
    def has_permission(self, request, view):
        IsAuthenticatedAccount.has_permission(self, request, view)
        if request.user.role == NURSING:
            return True
        return super().has_permission(request, view)

# ── 판독 확정 — 부서 자체를 잠근다 ──────────────────────────────────────
# MATRIX 는 study:U · assessment:U · specimen_pathology:U 칸으로 "이 역할이
# 이 리소스를 건드릴 수 있는가"만 표현한다. 관리자 화면에서 그 칸을 다른
# 역할에 체크해도(예: 원무에 study:U) 판독 확정까지 동시에 열리면 안 된다 —
# 그래서 MATRIX 칸과 별개로 IsRole 을 하나 더 건다. 업로드 품질승인
# (studies/{id}/upload) 과 조회(GET)는 이 칸에 안 걸린다 — 기사·타부서도
# 그대로 써야 한다.
CanFinalizeRadiologyRead = IsRole.of(RADIOLOGY, code="FINALIZE_ROLE_ONLY_RADIOLOGY")
CanFinalizePathologyRead = IsRole.of(PATHOLOGY, code="FINALIZE_ROLE_ONLY_PATHOLOGY")
