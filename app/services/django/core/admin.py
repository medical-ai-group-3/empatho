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
from django.utils import timezone

from .admin_perms import PermissionGrid
# 주요 표 일곱을 등록한다. @admin.register 가 불러오는 순간 붙으므로 모듈만
# 들여오면 된다 — 아래 「나머지 모델」 반복문보다 먼저 와야 그쪽이 안 덮는다.
from . import admin_tables  # noqa: F401
from .models import Account, Staff

logger = logging.getLogger(__name__)


# ── 목록을 「승인 대기」로 먼저 보여주는 필터 ──────────────────────────
#
# 관리자가 이 화면에 오는 이유는 거의 언제나 «승인할 것이 있나» 다. 전체
# 목록을 먼저 보여주면 매번 손으로 걸러야 한다.
#
# 기본값을 리다이렉트로 넣지 않고 필터가 직접 정한다 — 리다이렉트로 하면
# 「필터 지우기」가 빈 주소로 돌아가고 그게 다시 기본값으로 튕겨서 전체를
# 볼 방법이 없어진다. 여기서는 「전체」가 값을 가진 선택지라 그런 일이 없다.
class ApprovalFilter(admin.SimpleListFilter):
    title = "승인"
    parameter_name = "approval"

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
        """「모두」 줄을 없앤다 — 기본이 승인 대기라 그 줄이 거짓말이 된다."""
        for choice in super().choices(changelist):
            if choice["query_string"] == "?":   # SimpleListFilter 가 넣는 「모두」
                continue
            yield choice


class KindFilter(admin.SimpleListFilter):
    """환자는 승인 대상이 아니다 — 가입하면 바로 active 다.

    기본으로 빼 둔다. 안 빼면 환자 계정이 목록을 채워서 승인할 직원이 묻힌다.
    """

    title = "구분"
    parameter_name = "kind"

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
        for choice in super().choices(changelist):
            if choice["query_string"] == "?":
                continue
            yield choice


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
    list_display = ("login_id", "staff_name", "dept", "signed_up",
                    "account_status", "is_active", "last_login_at")
    list_filter = (ApprovalFilter, KindFilter, "role", "is_active")
    search_fields = ("login_id", "staff__full_name", "staff__staff_number")
    ordering = ("-created_at",)
    list_select_related = ("staff",)
    inlines = [StaffInline]

    # password_hash 를 읽기 전용으로 둔다 — 여기서 고치면 해시가 아닌 값이
    # 들어가 그 계정이 영영 로그인 못 한다. 비밀번호 재설정은 따로 만든다.
    readonly_fields = ("password_hash", "last_login_at",
                       "created_at", "updated_at", "created_by", "updated_by")

    actions = ("approve", "reject")

    @admin.display(description="이름", ordering="staff__full_name")
    def staff_name(self, obj):
        staff = getattr(obj, "staff", None)
        return staff.full_name if staff else "—"

    @admin.display(description="부서", ordering="role")
    def dept(self, obj):
        return dict(DEPT_NAMES).get(obj.role, obj.role)

    @admin.display(description="신청일", ordering="created_at")
    def signed_up(self, obj):
        return timezone.localtime(obj.created_at).strftime("%Y-%m-%d %H:%M")

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
        self._decide(request, queryset, approved=True)

    @admin.action(description="선택한 계정 거절 — 로그인을 막는다")
    def reject(self, request, queryset):
        self._decide(request, queryset, approved=False)

    def _decide(self, request, queryset, approved):
        now = timezone.now()
        status = "active" if approved else "rejected"
        word = "승인" if approved else "거절"

        # 환자는 승인 대상이 아니다. 골라 왔으면 건너뛰고 그렇다고 알린다 —
        # 조용히 넘기면 「눌렀는데 안 됐다」가 된다
        patients = queryset.filter(role="patient")
        targets = queryset.exclude(role="patient")

        done = 0
        for account in targets:
            account.account_status = status
            account.is_active = approved
            account.save(update_fields=["account_status", "is_active", "updated_at"])

            staff = getattr(account, "staff", None)
            if staff is not None:
                staff.approved_at = now if approved else None
                staff.save(update_fields=["approved_at", "updated_at"])
            done += 1

            logger.info(
                "admin %s account_id=%s login_id=%s role=%s → %s",
                word, account.account_id, account.login_id, account.role, status)

        if done:
            self.message_user(request, f"{done}건을 {word}했습니다.",
                              messages.SUCCESS)
        if patients.exists():
            self.message_user(
                request,
                f"환자 계정 {patients.count()}건은 건너뛰었습니다 — "
                "환자는 승인 없이 바로 쓸 수 있습니다.",
                messages.WARNING)


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


# ── 나머지 모델 ───────────────────────────────────────────────────────
# 위에서 손으로 꾸민 것은 건너뛰고 남은 것만 기본 모양으로 등록한다.
# 주요 표(patient · exam_order · study · ai_result · specimen ·
# discordance_flag · report)는 뒤에서 하나씩 꾸민다.
for model in apps.get_app_config("core").get_models():
    if admin.site.is_registered(model):
        continue
    admin.site.register(model)
