"""AdminSite — 제목 · CSS · 사이드바 · 우리 화면 주소.

병원 웹에서 [관리자 화면 열기] 로 넘어오는 자리라 같은 인상이어야 한다.
색은 empatho-view/hospital/tokens.css 에서 가져왔다
(core/static/empatho/admin.css).

  제목       AdminSite 속성 셋
  CSS        base_site.html 이 한 장 얹는다
  사이드바    Django 기본은 껐다. 우리 내비를 base_site.html 에 넣는다
             (항목은 이 파일 아래 _nav)
  묶음       get_app_list 를 덮어 열여덟 표를 다섯으로
  우리 화면   get_urls 로 /admin/ 안에 끼운다 (화면 본체는 views.py)

⚠ **템플릿은 base_site.html 하나만 덮는다.** 그 파일은 블록 둘뿐이라 옮겨
  적을 것이 적다. 나머지는 Django 것을 물려받는다.
"""

from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import reverse

# ── 사이드바 묶음 ────────────────────────────────────────────────────
#
# **승인 큐가 맨 위다.** 관리자가 이 화면에 오는 이유가 거의 언제나 그것이다.
# 안에서도 Account 가 먼저다 — 승인은 계정에서 한다.
#
# 여기 없는 모델은 맨 아래 「그 밖에」로 모인다. 표를 새로 만들어도 사이드바에서
# 사라지지 않게 하려는 것이다 — 빠뜨린 것이 안 보이면 없는 줄 안다.
GROUPS = [
    ("계정", ["Account", "Staff", "Consent"]),
    ("환자", ["Patient", "PatientPii", "Followup", "Notification"]),
    ("검사", ["ExamOrder", "Study", "Image", "StorageObject"]),
    ("판독", ["AiModel", "AiResult", "Lesion", "Assessment", "Report"]),
    ("병리", ["Specimen", "DiscordanceFlag"]),
]
REST = "그 밖에"


class EmpathoAdminSite(AdminSite):
    site_title = "EMPATHO CDSS"
    index_title = "관리자"
    # 병원 웹으로 돌아가는 길. admin 은 기본이 "/" 인데 그건 환자 앱이다
    site_url = "/hospital"

    # 사이드바 자리는 그대로 쓰고 **내용만 우리 것으로 바꾼다**
    # (templates/admin/nav_sidebar.html). 끄면 그 자리의 레이아웃까지 사라져서
    # 내비가 본문 위로 눕는다 — 왼쪽 칸이 있는 편이 훑기 좋다.
    enable_nav_sidebar = True

    @property
    def site_header(self):
        """머리띠 제목. EMPATHO 만 시안으로 세운다(empatho.css 의 .e-mark).

        ⚠ AdminSite 가 이 값을 그대로 넣으므로 **마크업이 들어간다.** 사람이
          입력하는 값이 아니라 여기 박힌 문자열이라 안전하다.
        """
        from django.utils.safestring import mark_safe
        return mark_safe('<span class="e-mark">EMPATHO</span> CDSS')

    # CSS 를 얹는 자리.
    #
    # ⚠ AdminSite 에는 «모든 화면에 CSS 한 장» 후크가 없다. base.html 의
    #   {% block extrastyle %} 이 유일한 자리이고 그건 템플릿이다. 그래서
    #   Django 것을 **물려받는** 템플릿 둘을 두고 여기서 가리킨다.
    #   표 화면은 템플릿이 필요 없다 — ModelAdmin.Media 가 붙인다(admin.py).
    login_template = "admin/empatho/login.html"
    # /admin/ 은 표 목록이다. 대시보드는 /admin/dashboard/ 에 따로 있다
    index_template = "admin/empatho/index.html"

    def each_context(self, request):
        """전 화면 공통 값. 사이드바가 여기서 나온다.

        ⚠ 커스텀 뷰에서도 **이걸 컨텍스트에 넣어야** 껍데기가 붙는다.
          아래 _page() 가 그 일을 한다.
        """
        context = super().each_context(request)
        context["e_nav"] = _nav(getattr(request, "_e_nav_key", None))
        context["e_hospital_url"] = self.site_url
        return context

    # ── 우리가 만든 화면들 ────────────────────────────────────────
    #
    # ⚠ **권한은 admin 전용이다.** is_staff 만 보면 다른 앱이 만든 staff
    #   사용자도 들어온다. admin_view() 가 로그인·is_staff 를 보고, 그 위에
    #   is_superuser 를 더 본다 — 이 화면들은 계정을 승인하고 서버를 찔러
    #   보는 자리라 아무 직원에게나 열면 안 된다.
    def get_urls(self):
        from django.urls import path

        from .admin import views as v

        mine = [
            path("dashboard/", self._guard(v.dashboard),
                 name="empatho_dashboard"),
            path("status/", self._guard(v.status),
                 name="empatho_status"),
            path("accounts/", self._guard(v.accounts),
                 name="empatho_accounts"),
            path("db/", self._guard(v.db_index), name="empatho_db"),
        ]
        # 우리 것이 앞이다 — 뒤에 두면 Django 의 catch-all 이 먼저 잡는다
        return mine + super().get_urls()

    def _guard(self, view):
        """로그인 + is_staff + is_superuser 를 본 뒤에야 들여보낸다."""
        def inner(request, *args, **kwargs):
            if not request.user.is_superuser:
                raise PermissionDenied("관리자만 볼 수 있습니다.")
            return view(self, request, *args, **kwargs)
        return self.admin_view(inner)

    def page(self, request, template, nav_key, title, context=None):
        """커스텀 화면 한 장.

        ⚠ **each_context 를 반드시 넣는다.** 빠지면 머리띠도 사이드바도 없는
          맨 화면이 나온다 — Django admin 의 껍데기가 그 값으로 그려진다.
        """
        request._e_nav_key = nav_key
        return TemplateResponse(request, template, {
            **self.each_context(request),
            "title": title,
            **(context or {}),
        })

    def get_app_list(self, request, app_label=None):
        """열여덟 표를 다섯 묶음으로 나눈다.

        한 모델의 상세 화면에 들어가면 app_label 이 오는데, 그때는 Django 가
        그 앱 하나만 그린다. 거기서도 묶어 두면 사이드바가 갑자기 달라 보이므로
        같은 규칙으로 나눈다.
        """
        apps = super().get_app_list(request, app_label)

        # 모델을 이름으로 찾을 수 있게 펼친다
        by_name = {}
        for app in apps:
            for model in app["models"]:
                by_name[model["object_name"]] = model

        out, used = [], set()
        for title, names in GROUPS:
            models = [by_name[n] for n in names if n in by_name]
            if not models:
                continue
            used.update(m["object_name"] for m in models)
            out.append(self._group(title, models))

        leftover = [m for n, m in by_name.items() if n not in used]
        if leftover:
            leftover.sort(key=lambda m: m["name"])
            out.append(self._group(REST, leftover))
        return out

    @staticmethod
    def _group(title, models):
        """사이드바 한 덩어리. Django 가 app 하나처럼 다룬다.

        app_url 을 비워 두는 이유 — 묶음은 앱이 아니라서 갈 곳이 없다. 값을
        넣으면 제목이 링크가 되고, 눌러도 아무 데도 안 간다.
        """
        return {
            "name": title,
            "app_label": "core",
            "app_url": "",
            "has_module_perms": True,
            "models": models,
        }


# ── 사이드바 ──────────────────────────────────────────────────────────
#
# Django 기본 사이드바는 껐다. 앱·모델을 기계적으로 늘어놓을 뿐이라
# 「지금 할 일」이 안 보인다.
#
# 배지는 **대기 건수 하나뿐**이다. 숫자를 여기저기 달면 어느 것이 급한지
# 안 보인다. 승인이 안 되면 그 사람이 아예 못 들어오므로 그것만 세운다.

# (열쇠, 라벨, 주소 이름)
NAV = [
    ("dashboard", "대시보드", "admin:empatho_dashboard"),
    ("status", "서버 상태", "admin:empatho_status"),
    ("accounts", "계정 승인", "admin:empatho_accounts"),
    ("db", "DB 조회", "admin:empatho_db"),
    ("models", "DB 수정", "admin:index"),
]


def _pending():
    """승인 대기 계정. 환자는 승인 대상이 아니라 뺀다."""
    from .models import Account
    return Account.objects.filter(account_status="pending").exclude(
        role="patient").count()


def _nav(current=None):
    waiting = _pending()
    out = []
    for key, label, name in NAV:
        out.append({
            "label": label,
            "url": reverse(name),
            "on": key == current,
            # 0 이면 배지를 안 단다 — 「0」이 붙어 있으면 눈이 그것도 읽는다
            "badge": waiting if key == "accounts" and waiting else None,
        })
    return out


class EmpathoAdminConfig(AdminConfig):
    """admin.site 를 위 클래스로 바꾼다.

    settings.py 의 INSTALLED_APPS 에서 "django.contrib.admin" 대신 쓴다.

    ⚠ **이 파일은 core/admin/ 패키지 밖이어야 한다.** 안에 두면 default_site
      를 푸는 동안 그 패키지의 __init__ 이 돌고, 거기서 @admin.register 가
      **아직 만들어지는 중인 admin.site** 에 등록된다. 바깥 setup 이 끝나며
      진짜 객체로 갈아치우면 그 등록이 통째로 버려진다 — 표가 하나도 안 뜬다.
    """

    default_site = "core.adminsite.EmpathoAdminSite"
