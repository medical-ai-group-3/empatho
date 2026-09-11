"""/api/v1 아래 경로. 명세서 §1-1 의 Base URL 이고, 라우팅의 주인은 이 파일이다.

cdss_backend/urls.py 는 여기 하나만 물린다. 업무 엔드포인트(core/urls.py)도
여기서 물어 순서를 한 곳에서 통제한다 — catch-all 이 맨 끝에 있어야 하는데,
cdss_backend 에서 include 를 두 줄로 나누면 순서가 갈려 위쪽이 전부 잡아먹는다.

catch-all 은 반드시 맨 끝. 새 경로는 그 위에 넣는다.
"""

from importlib.util import find_spec

from django.urls import include, path, re_path

from .tickets import TicketView
from .views import HealthView, NotFoundView

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("tickets", TicketView.as_view(), name="ticket-issue"),
]

# 업무 엔드포인트는 다른 브랜치에서 오는 중이다. 들어오면 자동으로 물린다.
if find_spec("core.urls") is not None:
    urlpatterns.append(path("", include("core.urls")))

# 어디에도 안 걸린 요청. Django 의 리졸버 404 는 HTML 이라 클라이언트가 봉투와
# HTML 두 갈래를 처리해야 한다.
urlpatterns.append(re_path(r"^.*$", NotFoundView.as_view(), name="api-not-found"))
