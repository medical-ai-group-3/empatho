"""core API 라우팅.

cdss_backend/urls.py 에서 path("api/v1/", include("core.urls")) 로 물린다.

전체 경로 맵 (라우터 인계 문서)
──────────────────────────────────────────────────────────────
  reception  GET/POST  api/v1/patients/            PatientViewSet
             GET       api/v1/patients/{id}/
             POST      api/v1/reservations/         ReservationViewSet

  nursing    GET/POST  api/v1/visits/today/         VisitTodayViewSet
             GET/POST  api/v1/followups/            FollowupViewSet
             PATCH     api/v1/followups/{id}/
             PATCH     api/v1/patients/{id}/questionnaire/   QuestionnaireView

  radiology  (2단계)   api/v1/read/worklist/ , api/v1/studies/{id}/upload/ ,
                       .../read/first/ , .../read/ai-compare/ , .../read/assessment/ ,
                       .../final/ , api/v1/lesions/{id}/specimen/
  pathology  (2단계)   api/v1/pathology/worklist/ , api/v1/specimens/{id}/accession/ ,
                       .../slides/ , api/v1/pathology-results/{id}/ai-review|diagnosis|finalize/
  surgery    (2단계)   api/v1/patients/{id}/timeline|report|surgery-explain/ ,
                       api/v1/lesions/{id}/decision|discordance/
  admin      (2단계)   api/v1/admin/approvals/ , api/v1/admin/accounts/{id}/role/
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"patients", views.PatientViewSet, basename="patient")
router.register(r"reservations", views.ReservationViewSet, basename="reservation")
router.register(r"visits/today", views.VisitTodayViewSet, basename="visit-today")
router.register(r"followups", views.FollowupViewSet, basename="followup")

urlpatterns = [
    path("", include(router.urls)),
    # 라우터에 안 맞는 중첩 경로는 명시적으로.
    path(
        "patients/<int:pk>/questionnaire/",
        views.QuestionnaireView.as_view({"patch": "partial_update"}),
        name="patient-questionnaire",
    ),
]
