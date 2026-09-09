"""/api/v1 아래 경로. 명세서 §1-1 의 Base URL 이다.

지금은 health 뿐이다. 엔드포인트 100 개는 화면 설계가 나온 뒤에 여기 붙는다.
catch-all 은 반드시 맨 끝에 둔다 — 위에 있으면 전부 잡아먹는다.
"""

from django.urls import path, re_path

from .views import HealthView, NotFoundView

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    re_path(r"^.*$", NotFoundView.as_view(), name="api-not-found"),
]
