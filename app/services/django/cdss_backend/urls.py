"""URL 라우팅.

    /api/v1/     공개 API — 명세서 §1-1 의 Base URL
    /api/schema/ OpenAPI 문서 (Swagger 가 읽는 원본)
    /api/docs/   Swagger UI
    /admin/      Django admin — 인증 주체가 API 와 다르다 (auth_user)

Go 계층의 /svc/v1 과 내부 콜백 /internal/v1 은 여기 없다. 다른 서비스이거나
내부망 한정이라 공개 라우팅에 섞지 않는다.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
