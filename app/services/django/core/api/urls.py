"""/api/v1 아래 경로. 명세서 §1-1 의 Base URL 이고, 라우팅의 주인은 이 파일이다.

cdss_backend/urls.py 는 여기 하나만 물린다. 업무 엔드포인트(core/urls.py)도
여기서 물어 순서를 한 곳에서 통제한다 — catch-all 이 맨 끝에 있어야 하는데,
cdss_backend 에서 include 를 두 줄로 나누면 순서가 갈려 위쪽이 전부 잡아먹는다.

catch-all 은 반드시 맨 끝. 새 경로는 그 위에 넣는다.
"""



from importlib.util import find_spec

from django.urls import include, path, re_path

from .tickets import TicketView
from .views import (
    HealthView, NotFoundView, login, refresh_token, logout,
    signup_staff, signup_patient,
)

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("tickets", TicketView.as_view(), name="ticket-issue"),
    path("login", login, name = "login"),
    path("token/refresh", refresh_token, name="token-refresh"),
    path("logout", logout, name="logout"),
    path("signup/staff", signup_staff, name="signup-staff"),
    path("signup/patient", signup_patient, name="signup-patient"),
]

# ── 나중에 붙은 경로들 ──────────────────────────────────────────────
#
# ⚠ 위 리터럴 안에도, 맨 위 import 묶음에도 넣지 않는다. 그 두 자리
#   (`from .tickets` 바로 위 · `path("login" …)` 바로 아래)는 여러 브랜치가
#   **동시에** 줄을 넣는 곳이라 머지할 때마다 충돌이 난다. 실제로 겪었다.
#
#   append 는 이 파일이 아래에서 이미 쓰는 방식이고 붙는 순서도 같다 —
#   core.urls 와 catch-all 보다 앞이다. 새 경로도 여기에 넣을 것.
#
#   import 도 같은 이유로 여기 둔다. 맨 위 묶음이 경합 중이다.
from .admin_session import AdminSessionView  # noqa: E402 — 위 참고
from .chat import ChatView  # noqa: E402
from .drugs import DrugDetailView, DrugSearchView  # noqa: E402

# 우리 로그인 → Django admin 세션. 관리자가 로그인을 두 번 하지 않게 한다
urlpatterns.append(
    path("admin-session", AdminSessionView.as_view(), name="admin-session"))
# 안내 챗봇. 화면(empatho-view)의 src/api.js 가 이 경로를 쓴다.
urlpatterns.append(path("chat", ChatView.as_view(), name="chat"))
# 약 정보 찾기. 식약처 공공데이터를 그대로 옮겨 주는 사전이고, 처방전의
# 복약 설명과는 다른 자리다 — core/api/drugs.py 의 머리말 참고.
# ⚠ 목록(`drugs`)을 상세(`drugs/<…>`)보다 **먼저** 둔다. 순서가 반대라도
#   지금은 맞지만, 뒤에 `drugs/<str:…>` 같은 것이 늘면 목록을 가로챈다.
urlpatterns.append(path("drugs", DrugSearchView.as_view(), name="drug-search"))
urlpatterns.append(
    path("drugs/<str:item_seq>", DrugDetailView.as_view(), name="drug-detail"))

# 업무 엔드포인트는 다른 브랜치에서 오는 중이다. 들어오면 자동으로 물린다.
if find_spec("core.urls") is not None:
    urlpatterns.append(path("", include("core.urls")))

# 어디에도 안 걸린 요청. Django 의 리졸버 404 는 HTML 이라 클라이언트가 봉투와
# HTML 두 갈래를 처리해야 한다.
urlpatterns.append(re_path(r"^.*$", NotFoundView.as_view(), name="api-not-found"))
