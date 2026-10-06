"""URL 라우팅.

    /api/v1/      공개 API — 명세서 §1-1 의 Base URL
    /api/schema/  OpenAPI 문서 (Swagger 가 읽는 원본)
    /api/docs/    Swagger UI
    /admin/       Django admin — 인증 주체가 API 와 다르다 (auth_user)
    /internal/v1/ Go → Django 콜백 (명세 21장) — 서명으로만 연다

Go 계층의 /svc/v1 은 다른 서비스라 여기 없다.

/internal/v1 은 밖에서 닿으면 안 된다. compose 에서 web 은 127.0.0.1:8000 이고
conf/nginx/default.conf 가 location /internal/ 을 404 로 잘라낸다.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.api.urls")),
    path("internal/v1/", include("core.api.internal")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
