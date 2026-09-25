"""Django admin — 관리자가 실제로 일할 수 있게 꾸민다.

우리는 관리자 화면을 따로 짓지 않고 Django admin 을 쓴다. 프론트의
[관리자 화면 열기] 가 POST /api/v1/admin-session 으로 세션을 받아 여기로
보낸다 (core/api/admin_session.py).

관리자가 여기서 하는 가장 중요한 일은 **계정 승인**이다. 직원이 가입하면
account_status='pending' · is_active=False 로 서고 로그인이 막힌다. 누군가
풀어 주지 않으면 아무도 못 들어온다.

⚠ **admin 으로 넣거나 고친 행은 created_by · updated_by 가 NULL 이다.**
  그 두 칸은 account 를 가리키는데 admin 은 auth_user 로 로그인해서 지금
  누구인지 account 로 옮길 수가 없다. 빈 것이 정상이고, API 로 들어온 행만
  채워진다.
"""

import logging

from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone

from .perms import PermissionGrid
# 주요 표 일곱을 등록한다. @admin.register 가 불러오는 순간 붙으므로 모듈만
# 들여오면 된다 — 아래 「나머지 모델」 반복문보다 먼저 와야 그쪽이 안 덮는다.
from ..models import Account, Staff

logger = logging.getLogger(__name__)


#: 상태 탭 — 시안 차례. **「모두」는 안 쓴다**: 그건 매개변수를 지우는 줄이라
#: 기본값(승인 대기)으로 되돌아온다. 「전체」가 값 있는 선택지다.
STATUS_TABS = (
    ("pending", "승인 대기"),
    ("active", "승인됨"),
    ("rejected", "거절됨"),
    ("suspended", "정지됨"),
    ("all", "전체"),
)

#: 구분 토글. 시안은 둘뿐이다 — 「전체」는 역할 고르개가 대신한다.
KIND_TABS = (("staff", "직원"), ("patient", "환자"))

#: 액션 넷이 옮기는 자리. (상태, 로그인 가능, 사람이 읽는 말, approved_at)
#:
#: 정지·복구가 approved_at 을 안 건드리는(keep) 이유 — 그 칸은 「승인된 적이
#: 있나」를 남긴다. 정지는 승인을 무르는 것이 아니라 잠시 막는 것이라,
#: 지웠다가 복구하면 승인 이력이 사라진다.
TRANSITIONS = {
    "approve": ("active", True, "승인", "set"),
    "reject": ("rejected", False, "거절", "clear"),
    "suspend": ("suspended", False, "정지", "keep"),
    "restore": ("active", True, "복구", "keep"),
}


def _link(request, **changes):
    """지금 주소에서 **자기 매개변수만** 바꾼 주소.

    서로의 조건을 지키는 것이 요점이다 — 상태 탭을 눌렀다고 역할이나 검색이
    풀리면, 좁혀 놓고 하나만 바꾸는 일을 매번 처음부터 해야 한다.

    쪽(p)은 버린다. 3쪽을 보다가 조건을 바꾸면 그 조건에 3쪽이 없어서 빈
    화면이 나온다.
    """
    params = request.GET.copy()
    params.pop("p", None)
    for key, value in changes.items():
        params[key] = value
    return "?" + params.urlencode()


def _keep(request, *drop):
    """GET 폼이 들고 갈 숨은 칸. 폼은 자기 칸만 보내서 나머지가 날아간다."""
    params = request.GET.copy()
    params.pop("p", None)
    for key in drop:
        params.pop(key, None)
    return [{"name": k, "value": v} for k in params for v in params.getlist(k)]


def _without_all_row(spec, changelist):
    """Django 가 맨 앞에 붙이는 「모두」 줄을 뺀다.

    우리 세 필터는 「전체」를 **값 있는 선택지**로 따로 갖고 있다. 두 줄이
    같이 있으면 뜻이 갈린다 — 「모두」는 그 매개변수를 **지우는** 주소라
    기본값(승인 대기 · 직원)으로 되돌아오고, 「전체」는 정말 전부를 본다.

    ⚠ **query_string == "?" 로 가려내면 안 된다.** 다른 필터가 하나라도
      걸려 있으면 「모두」의 주소가 "?kind=staff" 가 되어 그 비교가 빗나간다.
      내비 링크(?approval=pending&kind=staff)가 바로 그 경우라, 화면에
      「모두」가 남고 눌러도 전체가 안 나왔다 (2026-09-25 확인).
      골라낼 기준은 「이 매개변수를 지운 주소인가」다.

    덤으로, 아무것도 안 골랐을 때 **기본값 칩에 표를 세운다.** 목록은 이미
    그 값으로 걸러져 있는데 칩이 하나도 안 밝으면 「필터가 없다」로 읽힌다.
    """
    drop = changelist.get_query_string(remove=[spec.parameter_name])
    default = changelist.get_query_string({spec.parameter_name: spec.default_value})

    rows = [c for c in admin.SimpleListFilter.choices(spec, changelist)
            if c["query_string"] != drop]
    if not any(c["selected"] for c in rows):
        for c in rows:
            c["selected"] = c["query_string"] == default
    return rows


# ── 목록을 「승인 대기」로 먼저 보여주는 필터 ──────────────────────────
#
# 관리자가 이 화면에 오는 이유는 거의 언제나 «승인할 것이 있나» 다. 전체
# 목록을 먼저 보여주면 매번 손으로 걸러야 한다.
#
# 기본값을 리다이렉트로 넣지 않고 필터가 직접 정한다 — 리다이렉트로 하면
# 「필터 지우기」가 빈 주소로 돌아가고 그게 다시 기본값으로 튕겨서 전체를
# 볼 방법이 없어진다. 여기서는 「전체」가 값을 가진 선택지라 그런 일이 없다.
class ApprovalFilter(admin.SimpleListFilter):
    # 시안(Approvals.dc.html)의 첫 줄 이름이다
    title = "상태"
    parameter_name = "approval"
    #: 안 고르면 이 값으로 걸러진다(아래 queryset). 칩 표시도 이걸 본다
    default_value = "pending"

    def lookups(self, request, model_admin):
        return (
            ("pending", "승인 대기"),
            ("active", "승인됨"),
            ("rejected", "거절됨"),
            ("suspended", "정지됨"),
            ("all", "전체"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value in (None, "pending"):          # 안 고르면 승인 대기
            return queryset.filter(account_status="pending")
        if value == "all":
            return queryset
        return queryset.filter(account_status=value)

    def choices(self, changelist):
        return _without_all_row(self, changelist)


class KindFilter(admin.SimpleListFilter):
    """환자는 승인 대상이 아니다 — 가입하면 바로 active 다.

    기본으로 빼 둔다. 안 빼면 환자 계정이 목록을 채워서 승인할 직원이 묻힌다.
    """

    title = "구분"
    parameter_name = "kind"
    default_value = "staff"

    def lookups(self, request, model_admin):
        return (("staff", "직원"), ("patient", "환자"), ("all", "전체"))

    def queryset(self, request, queryset):
        value = self.value()
        if value in (None, "staff"):
            return queryset.exclude(role="patient")
        if value == "patient":
            return queryset.filter(role="patient")
        return queryset

    def choices(self, changelist):
        return _without_all_row(self, changelist)


class RoleFilter(admin.SimpleListFilter):
    """역할 — 시안의 셋째 줄.

    기본 FieldListFilter 를 안 쓰는 이유 둘.
      ① 제목이 칸 이름(role)으로 나온다. 시안은 「역할」이다.
      ② 값이 DB 에 적힌 영문 그대로 나온다(as_choices 가 (v, v) 다).
         칩에 「nursing」이 뜨면 화면의 다른 자리와 말이 어긋난다.
    """

    title = "역할"
    parameter_name = "role"
    default_value = "all"

    @staticmethod
    def role_choices():
        """역할 고르개에 담을 (값, 이름). 툴바와 필터가 같은 목록을 쓴다.

        ⚠ 환자를 뺀다 — 「구분」 토글이 이미 가르는 값이라, 여기 또 두면
          둘이 서로 싸운다(역할=환자 + 구분=직원 → 늘 빈 목록).

        이름은 짧은 쪽(ROLE_NAMES)이다. 표 칸의 「부서」는 정식 명칭
        (DEPT_NAMES, 「간호과」)을 쓴다 — 자리가 달라 길이도 다르다.
        """
        from .views import ROLE_NAMES, ROLE_ORDER
        return (("all", "전체"),) + tuple(
            (r, ROLE_NAMES[r]) for r in ROLE_ORDER if r != "patient")

    def lookups(self, request, model_admin):
        return self.role_choices()

    def queryset(self, request, queryset):
        value = self.value()
        if value in (None, "all"):
            return queryset
        return queryset.filter(role=value)

    def choices(self, changelist):
        return _without_all_row(self, changelist)


# ── 계정 안에서 신원을 같이 본다 ──────────────────────────────────────
#
# account 와 staff 가 1:1 인데 표가 나뉘어 있다. 승인하려면 「누구인지」를
# 봐야 하는데 이름과 사번이 staff 에 있어서, 따로 보면 창을 오가게 된다.
class StaffInline(admin.StackedInline):
    model = Staff
    # staff 는 account 를 세 번 가리킨다 — 본인(account)과 감사 칸
    # 둘(created_by · updated_by, AuditBase). 어느 것으로 묶을지 밝혀야 한다
    fk_name = "account"
    can_delete = False
    extra = 0
    verbose_name = "직원 신원"
    verbose_name_plural = "직원 신원"
    fields = ("full_name", "staff_number", "extra_permissions",
              "approved_by", "approved_at")
    # 승인 기록은 손으로 고치지 않는다. 아래 승인 액션이 찍는다
    readonly_fields = ("approved_by", "approved_at")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    # 시안(admin-redesign/Approvals.dc.html)의 다섯 칸이다: 이름 · 사번 ·
    # 부서 · 신청 일시 · 처리. 「처리」는 list_display 가 아니라 줄마다 단추라
    # 템플릿이 그린다(admin/change_list_results.html 의 account 갈래).
    #
    # ⚠ login_id 를 뺐다. 시안에 없고, 목록에 로그인 아이디가 줄줄이 있으면
    #   화면을 찍는 것만으로 계정 목록이 새어 나간다. 검색으로는 계속 찾힌다
    #   (아래 search_fields).
    list_display = ("staff_name", "staff_number", "dept", "signed_up",
                    "status_label")
    # 링크 칸을 이름으로 옮긴다. 안 옮기면 첫 칸(이름)이 링크가 되는 것은
    # 같지만, 나중에 칸 차례를 바꿀 때 조용히 딴 칸으로 옮겨간다.
    list_display_links = ("staff_name",)
    # 시안의 칩 석 줄: 상태 · 구분 · 역할.
    # is_active 를 뺐다 — 「상태」와 겹쳐 보이고(승인됨 ≈ 활성) 줄만 늘어난다.
    list_filter = (ApprovalFilter, KindFilter, RoleFilter)
    search_fields = ("login_id", "staff__full_name", "staff__staff_number")
    ordering = ("-created_at",)
    list_select_related = ("staff",)
    inlines = [StaffInline]

    # password_hash 를 읽기 전용으로 둔다 — 여기서 고치면 해시가 아닌 값이
    # 들어가 그 계정이 영영 로그인 못 한다. 비밀번호 재설정은 따로 만든다.
    readonly_fields = ("password_hash", "last_login_at",
                       "created_at", "updated_at", "created_by", "updated_by")

    actions = ("approve", "reject", "suspend", "restore")

    @admin.display(description="이름", ordering="staff__full_name")
    def staff_name(self, obj):
        staff = getattr(obj, "staff", None)
        return staff.full_name if staff else "—"

    @admin.display(description="사번", ordering="staff__staff_number")
    def staff_number(self, obj):
        staff = getattr(obj, "staff", None)
        return staff.staff_number if staff else "—"

    @admin.display(description="부서", ordering="role")
    def dept(self, obj):
        return dict(DEPT_NAMES).get(obj.role, obj.role)

    @admin.display(description="신청 일시", ordering="created_at")
    def signed_up(self, obj):
        return timezone.localtime(obj.created_at).strftime("%Y-%m-%d %H:%M")

    # 목록의 「상태」 칸은 템플릿이 알약으로 그린다. 이 함수는 **머리글과
    # 정렬 링크**를 얻으려고 둔다 — list_display 에 없으면 그 칸을 눌러
    # 정렬할 수가 없다.
    @admin.display(description="상태", ordering="account_status")
    def status_label(self, obj):
        return dict(STATUS_TABS).get(obj.account_status, obj.account_status)

    # ── 승인 · 거절 ────────────────────────────────────────────────
    #
    # 두 칸을 함께 옮긴다. account_status 는 「가입 흐름의 어디인가」이고
    # is_active 는 「로그인이 되는가」다. 인증(core/api/auth.py)은 is_active
    # 만 보므로, 상태만 바꾸고 is_active 를 안 켜면 승인해도 못 들어온다.
    #
    # ⚠ **approved_by 를 못 채운다.** 그 칸은 staff 를 가리키는데 admin 은
    #   auth_user 로 로그인해서 지금 누구인지 staff 로 옮길 수가 없다.
    #   억지로 아무 staff 나 넣으면 「그 사람이 승인했다」는 거짓이 남는다.
    #   그래서 시각만 찍고 사람은 비운다 — 누가 들어왔는지는 admin-session
    #   로그가 남긴다 (core/api/admin_session.py). 둘을 시각으로 맞춰 본다.
    @admin.action(description="선택한 계정 승인 — 로그인할 수 있게 한다")
    def approve(self, request, queryset):
        self._set_status(request, queryset, "approve")

    @admin.action(description="선택한 계정 거절 — 로그인을 막는다")
    def reject(self, request, queryset):
        self._set_status(request, queryset, "reject")

    @admin.action(description="선택한 계정 정지 — 로그인을 잠시 막는다")
    def suspend(self, request, queryset):
        self._set_status(request, queryset, "suspend")

    @admin.action(description="선택한 계정 복구 — 정지를 푼다")
    def restore(self, request, queryset):
        self._set_status(request, queryset, "restore")

    def _set_status(self, request, queryset, action):
        status, active, word, approved_at = TRANSITIONS[action]
        now = timezone.now()

        # 환자는 승인 대상이 아니다. 골라 왔으면 건너뛰고 그렇다고 알린다 —
        # 조용히 넘기면 「눌렀는데 안 됐다」가 된다
        patients = queryset.filter(role="patient")
        targets = queryset.exclude(role="patient")

        done = 0
        for account in targets:
            account.account_status = status
            account.is_active = active
            account.save(update_fields=["account_status", "is_active", "updated_at"])

            # approved_at 은 「승인된 적이 있나」를 남기는 칸이라 정지·복구는
            # 안 건드린다 — 정지는 승인을 무르는 것이 아니라 잠시 막는 것이다.
            staff = getattr(account, "staff", None)
            if staff is not None and approved_at != "keep":
                staff.approved_at = now if approved_at == "set" else None
                staff.save(update_fields=["approved_at", "updated_at"])
            done += 1

            # approved_by 를 못 채우는 대신 여기가 「누가 눌렀나」를 남긴다.
            # LogEntry 는 auth_user 로 찍히고 그 화면에서 바로 보인다.
            #
            # 메시지를 손으로 만든다 — log_change 는 기본으로 폼이 바꾼 칸을
            # 적는데, 액션은 폼을 안 거쳐서 그대로 두면 빈 줄이 남는다.
            self.log_change(
                request, account,
                "%s — account_status=%s · is_active=%s"
                % (word, status, active))

            # ⚠ login_id 를 로그에 안 찍는다. 계정 값이라, 로그만 모아도
            #   누가 있는지가 드러난다. 행 번호면 되짚기에 충분하다.
            logger.info("admin %s account_id=%s role=%s → %s",
                        word, account.account_id, account.role, status)

        if done:
            self.message_user(request, f"{done}건을 {word}했습니다.",
                              messages.SUCCESS)
        if patients.exists():
            self.message_user(
                request,
                f"환자 계정 {patients.count()}건은 건너뛰었습니다 — "
                "환자는 승인 없이 바로 쓸 수 있습니다.",
                messages.WARNING)

    # ── 툴바에 넘길 값 ────────────────────────────────────────────
    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request, {**(extra_context or {}), **self.toolbar(request)})

    def toolbar(self, request):
        """상태 탭 · 구분 토글 · 역할 고르개 · 검색에 필요한 것 전부."""
        counts = self.status_counts(request)
        approval = request.GET.get("approval") or ApprovalFilter.default_value
        kind = request.GET.get("kind") or KindFilter.default_value
        role = request.GET.get("role") or RoleFilter.default_value

        return {
            "e_tabs": [{
                "label": label,
                "url": _link(request, approval=value),
                "on": approval == value,
                # 「전체」는 나머지를 더한다 — 표를 또 세지 않는다
                "count": (sum(counts.values()) if value == "all"
                          else counts.get(value, 0)),
            } for value, label in STATUS_TABS],
            "e_kinds": [{"label": label, "url": _link(request, kind=value),
                         "on": kind == value}
                        for value, label in KIND_TABS],
            "e_roles": [{"value": value, "label": label, "on": role == value}
                        for value, label in RoleFilter.role_choices()],
            # GET 폼이 다른 조건을 잃지 않게 숨은 칸으로 들고 간다
            "e_role_keep": _keep(request, "role"),
            "e_search_keep": _keep(request, "q"),
            "e_q": request.GET.get("q", ""),
            "e_summary": " · ".join([
                dict(KIND_TABS).get(kind, kind),
                dict(STATUS_TABS).get(approval, approval),
            ]),
        }

    def status_counts(self, request):
        """상태별 건수. **상태만 빼고** 지금 걸린 조건을 그대로 반영한다.

        조건을 손으로 다시 짜지 않고 ChangeList 를 한 번 더 세운다 — 검색과
        구분·역할 규칙이 두 벌이 되면 탭의 숫자와 목록이 어긋난다.

        ⚠ approval 을 지우기만 하면 기본값(승인 대기)으로 걸러져 전부 그
          숫자가 된다. 「전체」를 명시해야 상태를 안 거른 기준이 나온다.

        ⚠ **order_by() 로 정렬을 먼저 비운다.** 안 비우면 ordering 의
          created_at 이 GROUP BY 에 딸려 들어가서 같은 상태가 시각마다 따로
          세어진다 — 승인 대기 둘이 「1, 1」로 갈라져 나오고, 아래 dict 가
          그중 하나만 남겨 탭에 1 이 뜬다 (2026-09-25 확인).
        """
        original = request.GET
        params = original.copy()
        params["approval"] = "all"
        params.pop("p", None)          # 쪽은 건수와 무관하다
        request.GET = params
        try:
            changelist = self.get_changelist_instance(request)
            rows = (changelist.get_queryset(request).order_by()
                    .values("account_status").annotate(n=Count("pk")))
            return {r["account_status"]: r["n"] for r in rows}
        except Exception:               # 필터 값이 엉터리면 탭만 0 으로 둔다
            logger.info("admin 상태 건수를 못 셌다 — 탭을 0 으로 둔다")
            return {}
        finally:
            request.GET = original


DEPT_NAMES = (
    ("admin", "관리자"), ("reception", "원무과"), ("nursing", "간호과"),
    ("radiology", "영상의학과"), ("surgery", "유방외과"),
    ("pathology", "병리과"), ("patient", "환자"),
)


# ── 직원 신원과 개인 추가 권한 ────────────────────────────────────────
class StaffForm(forms.ModelForm):
    """extra_permissions 를 체크박스 격자로 바꾼다.

    격자는 **그 사람의 역할을 알아야** 그린다 — 역할이 이미 주는 칸을 회색으로
    잠가야 해서다. 역할은 staff 가 아니라 account 에 있으므로 여기서 꺼내
    위젯에 넘긴다.
    """

    class Meta:
        model = Staff
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("extra_permissions")
        if field is None:
            return
        account = getattr(self.instance, "account", None)
        field.widget = PermissionGrid(role=getattr(account, "role", None))
        field.required = False
        # JSONField 의 기본 검증은 «문자열이 JSON 인가» 를 본다. 격자는 이미
        # dict 를 주므로 그대로 통과시킨다
        field.clean = lambda value: value


class ExtraPermFilter(admin.SimpleListFilter):
    """개인 추가 권한을 가진 사람만 추려 본다.

    권한을 개인에게 더하면 역할만 보고는 누가 무엇을 할 수 있는지 알 수 없다.
    「누구에게 더 줬더라」를 찾는 자리가 있어야 한다.
    """

    title = "추가 권한"
    parameter_name = "extra"

    def lookups(self, request, model_admin):
        return (("yes", "있음"), ("no", "없음"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            # NULL 과 빈 dict 를 둘 다 「없음」으로 본다 — 격자가 빈 것을
            # NULL 로 저장하지만 옛 행에 {} 가 남아 있을 수 있다
            return queryset.exclude(extra_permissions__isnull=True).exclude(
                extra_permissions={})
        if self.value() == "no":
            return queryset.filter(extra_permissions__isnull=True) | \
                queryset.filter(extra_permissions={})
        return queryset


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    form = StaffForm
    list_display = ("full_name", "staff_number", "dept", "has_extra", "approved_at")
    list_filter = ("account__role", ExtraPermFilter)
    search_fields = ("full_name", "staff_number", "account__login_id")
    ordering = ("full_name",)
    list_select_related = ("account",)
    readonly_fields = ("approved_by", "approved_at",
                       "created_at", "updated_at", "created_by", "updated_by")

    @admin.display(description="부서", ordering="account__role")
    def dept(self, obj):
        return dict(DEPT_NAMES).get(obj.account.role, obj.account.role)

    @admin.display(description="추가 권한", boolean=True)
    def has_extra(self, obj):
        return bool(obj.extra_permissions)


from django.contrib import admin
from ..models import (
    AiResult, DiscordanceFlag, ExamOrder, Patient, Report, Specimen, Study,
)


# ──────────────────────── 주요 표 일곱 ────────────────────────
#
# patient · exam_order · study · ai_result · specimen · discordance_flag · report
#
# 여기는 **고치는 자리가 아니라 찾는 자리**다. 관리자가 「그 환자 검사가 어디까지
# 갔나」 · 「AI 가 실패한 건이 몇 개인가」를 볼 수 있어야 한다. 그래서 세 가지를
# 공통으로 맞춘다.
#
#   list_display    한 줄로 무엇인지 알 수 있는 칸들
#   list_filter     큐를 가르는 상태 칸
#   search_fields   환자번호 · 이름으로 닿는 길
#
# ── 검색은 환자번호와 이름으로 ──────────────────────────────────────
# 관리자가 들고 오는 것은 거의 언제나 환자번호나 이름이다. 표마다 환자로 가는
# 길이 달라서(study → patient, specimen → patient) 각 표에서 그 경로를 적어 준다.
#
# ⚠ 이름은 patient_pii 에 있다. 개인정보라 목록 칸으로는 안 내보내고
#   **검색으로만** 닿게 한다 — 목록을 열면 전부 보이는 것과, 아는 이름을
#   쳐서 찾는 것은 다르다.
#
# ⚠ **admin 으로 고친 행은 updated_by 가 NULL 이다.** 그 칸은 account 를
#   가리키는데 admin 은 auth_user 로 로그인해서 옮길 수가 없다.

# 전 표 공통. 감사 칸은 손으로 고치는 것이 아니다
AUDIT_RO = ("created_at", "created_by", "updated_at", "updated_by")


class ReadMostly(admin.ModelAdmin):
    """찾는 자리의 공통 뼈대.

    지우기를 막는다 — 이 표들은 전부 PROTECT 로 얽혀 있어서 한 줄을 지우면
    어디가 끊길지 admin 화면에서는 안 보인다. 그리고 임상 기록은 지우는 것이
    아니라 상태로 물린다(cancelled · superseded).
    """

    list_per_page = 50
    readonly_fields = AUDIT_RO

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Patient)
class PatientAdmin(ReadMostly):
    list_display = ("patient_number", "name", "sex", "birth_year",
                    "allergy", "first_visited_at", "primary_staff")
    list_filter = ("sex", "has_allergy")
    search_fields = ("patient_number", "pii__name", "pii__phone")
    list_select_related = ("pii", "primary_staff")
    ordering = ("-created_at",)

    @admin.display(description="이름", ordering="pii__name")
    def name(self, obj):
        pii = getattr(obj, "pii", None)
        return pii.name if pii else "—"

    # 조영제 알레르기는 촬영 전에 반드시 보여야 하는 값이라 목록에 세운다
    @admin.display(description="알레르기", boolean=True)
    def allergy(self, obj):
        return bool(obj.has_allergy)


@admin.register(ExamOrder)
class ExamOrderAdmin(ReadMostly):
    list_display = ("exam_order_id", "patient_number", "order_status",
                    "modality", "exam_purpose", "scheduled_at", "visited_at",
                    "assigned_to")
    list_filter = ("order_status", "modality", "exam_purpose")
    search_fields = ("patient__patient_number", "patient__pii__name")
    list_select_related = ("patient", "assigned_to")
    date_hierarchy = "scheduled_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(Study)
class StudyAdmin(ReadMostly):
    list_display = ("study_id", "patient_number", "modality", "read_status",
                    "quality_status", "density_category", "performed_at")
    list_filter = ("modality", "read_status", "quality_status",
                   "density_category")
    # study_uid 로도 찾게 둔다 — PACS 쪽에서 그 값을 들고 문의가 온다
    search_fields = ("patient__patient_number", "patient__pii__name",
                     "study_uid", "orthanc_study_id")
    list_select_related = ("patient",)
    date_hierarchy = "performed_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(AiResult)
class AiResultAdmin(ReadMostly):
    list_display = ("ai_result_id", "patient_number", "requested_socket_id",
                    "run_status", "abstained", "model", "elapsed_sec",
                    "analyzed_at")
    list_filter = ("run_status", "abstained", "requested_socket_id", "model")
    search_fields = ("patient__patient_number", "patient__pii__name")
    list_select_related = ("patient", "model")
    date_hierarchy = "analyzed_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(Specimen)
class SpecimenAdmin(ReadMostly):
    list_display = ("specimen_label", "patient_number", "accession_status",
                    "specimen_type", "b_category", "diagnosis_code",
                    "collected_at", "finalized_at")
    list_filter = ("accession_status", "specimen_type", "guidance_route",
                   "b_category")
    search_fields = ("specimen_label", "patient__patient_number",
                     "patient__pii__name")
    list_select_related = ("patient",)
    date_hierarchy = "collected_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(DiscordanceFlag)
class DiscordanceFlagAdmin(ReadMostly):
    """영상 판정과 병리 확진이 갈린 건. **미처리로 남으면 안 되는 표다.**

    그래서 flag_status 가 맨 앞에 오고 기본 정렬이 오래된 순이다 — 늦게 들어온
    것이 위에 쌓이면 오래 묵은 건이 아래로 밀려 안 보인다.
    """

    list_display = ("discordance_flag_id", "flag_status", "violated_rule",
                    "disposition_type", "flagged_at", "reviewed_by",
                    "closed_at")
    list_filter = ("flag_status", "violated_rule", "disposition_type")
    search_fields = ("specimen__patient__patient_number",
                     "specimen__patient__pii__name",
                     "specimen__specimen_label")
    list_select_related = ("specimen", "reviewed_by")
    date_hierarchy = "flagged_at"
    ordering = ("flagged_at",)          # 오래된 것이 위


#: 상세 화면에서 감추는 칸. 소견문 본문과 그 부속이다.
#: 표는 그대로 보이고 나머지 20칸도 그대로 보인다 — 값만 안 보인다.
REPORT_HIDDEN = ("narrative_text", "content_json", "evidence_links",
                 "dropped_sentences", "notes", "unlock_reason")


@admin.register(Report)
class ReportAdmin(ReadMostly):
    """환자 소견문. **본문은 admin 에서 안 보인다.**

    관리자는 서버를 보는 사람이지 진료 기록을 읽는 사람이 아니다. 리포트가
    제때 나갔는지 · 잠겼는지 · 몇 번 열렸는지는 보여야 하지만 환자에게 나가는
    글 자체는 볼 이유가 없다. perms.py 에서 admin 만 report.view.all 을 빼
    프론트를 막았고(다희님, 8b6d892), 여기가 그 나머지 반쪽이다 — 둘 다
    해야 말이 된다.
    """

    list_display = ("report_id", "patient_number", "report_type", "audience",
                    "socket_id", "lock_status", "patient_confirmed",
                    "view_count", "last_viewed_at")
    list_filter = ("report_type", "audience", "lock_status",
                   "patient_confirmed", "socket_id")
    search_fields = ("patient__patient_number", "patient__pii__name")
    list_select_related = ("patient",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    # 남기는 20칸. 누가 · 언제 · 어디까지 갔는지는 다 보인다.
    fields = (
        "study", "patient", "report_type", "audience", "socket_id",
        "prompt_version", "fallback",
        "lock_status", "unlocked_by", "unlocked_at",
        "issued_by", "pdf_bucket", "pdf_object_key",
        "explained_by", "explained_at", "explain_method", "patient_confirmed",
        "last_viewed_at", "last_viewed_by", "view_count",
    ) + AUDIT_RO

    # lock_status — 잠금 해제는 유방외과 단독이다(§11.5). 뷰에 CanUnlockReport
    #   를 걸어 놓고 admin 에서 손으로 풀 수 있으면 그 잠금이 무의미하다.
    # 열람 3칸 — 서버가 찍는 값이라 손으로 고치면 감사 기록이 거짓이 된다.
    readonly_fields = AUDIT_RO + ("lock_status", "last_viewed_at",
                                  "last_viewed_by", "view_count")

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


# ── 나머지 모델 ───────────────────────────────────────────────────────
# 위에서 손으로 꾸민 것은 건너뛰고 남은 것만 기본 모양으로 등록한다.
# 주요 표(patient · exam_order · study · ai_result · specimen ·
# discordance_flag · report)는 뒤에서 하나씩 꾸민다.
for model in apps.get_app_config("core").get_models():
    if admin.site.is_registered(model):
        continue
    admin.site.register(model)
