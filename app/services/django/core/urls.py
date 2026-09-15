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

  radiology  GET       api/v1/radiology/queue                     ExamOrderQueueView
             POST      api/v1/radiology/queue/{exam_order_id}/start-study   StudyStartView
             GET/PATCH api/v1/radiology/studies/{id}/upload        StudyUploadView
             GET       api/v1/radiology/studies/{id}/read          StudyReadView
             (기존)    api/v1/studies/{id}/ai-results , api/v1/ai-results ,
                       api/v1/studies/{id}/assessment/draft , api/v1/studies/{id}/finalize ,
                       api/v1/assessments , api/v1/assessments/{id}/amend ,
                       api/v1/lesions/{id}/specimen/
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
router.register(r"me/reservation-requests", views.ReservationRequestViewSet, basename="reservation-request")
router.register(r"lesions", views.LesionViewSet, basename="lesion")
router.register(r"specimens", views.SpecimenBindViewSet, basename="specimen")
router.register(r"reports", views.SurgeryReportViewSet, basename="report")



urlpatterns = [
    path("", include(router.urls)),
    path(
        "reservation-requests",
        views.ReservationRequestQueueView.as_view(),
        name="reservation-request-queue",
    ),
    path("exam-orders", views.ExamOrderQueryView.as_view(), name="exam-order-query"),
    path(
        "exam-orders/<int:pk>/confirm",
        views.ExamOrderConfirmView.as_view({"patch": "partial_update"}),
        name = "exam-order-confirm",
    ),
    path("patients/today-status", views.PatientTodayStatusView.as_view({"get": "list"}), name = "patient-today-status"),
    path(
        "patients/<int:pk>/questionnaire/",
        views.QuestionnaireView.as_view({"patch": "partial_update"}),
        name="patient-questionnaire",
    ),
    path("radiology/queue", views.ExamOrderQueueView.as_view(), name="radiology-queue"),
    path(
        "radiology/queue/<int:pk>/start-study",
        views.StudyStartView.as_view({"post": "create"}),
        name="radiology-queue-start-study",
    ),
    path(
        "radiology/studies/<int:pk>/upload",
        views.StudyUploadView.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="radiology-study-upload",
    ),
    path(
        "radiology/studies/<int:pk>/read",
        views.StudyReadView.as_view({"get": "retrieve"}),
        name="radiology-study-read",
    ),
    path("studies/<int:pk>/ai-results", views.AiResultQueueView.as_view({"post": "start"}), name="study-ai-results-start"),
    path("ai-results", views.AiResultListView.as_view({"get": "list"}), name="ai-results-list"),
    path("studies/<int:pk>/assessment/draft", views.AssessmentDraftView.as_view({"put": "update"}), name="study-assessment-draft"),
    path("studies/<int:pk>/finalize", views.StudyFinalizeView.as_view({"patch": "partial_update"}), name="study-finalize"),
    path("assessments", views.AssessmentHistoryView.as_view(), name="assessment-history"),
    path("assessments/<int:pk>/amend", views.AssessmentAmendView.as_view({"post": "create"}), name="assessment-amend"),
    path("patients/<int:pk>/timeline", views.PatientTimelineView.as_view({"get": "retrieve"}), name="patient-timeline"),
    path("reports/<int:pk>/explain", views.ReportExplainView.as_view({"patch": "partial_update"}), name="report-explain"),
    path("reports/<int:pk>/unlock-status", views.ReportUnlockStatusView.as_view({"get": "retrieve"}), name="report-unlock-status"),
    path("reports/<int:pk>/unlock", views.ReportUnlockView.as_view({"patch": "partial_update"}), name="report-unlock"),
    path("discordances", views.DiscordanceListView.as_view(), name="discordance-list"),
    path("discordances/<int:pk>", views.DiscordanceDisposeView.as_view({"get": "retrieve", "patch": "partial_update"}), name="discordance-detail"),
    path("exam-orders", views.ExamOrderRequestView.as_view({"post": "create"}), name="exam-order-request"),
    path("specimens/queue", views.SpecimenQueueView.as_view(), name="specimen-queue"),
    path("specimens/<int:pk>/assign", views.SpecimenAssignView.as_view({"patch": "partial_update"}), name="specimen-assign"),
    path("specimens/<int:pk>/ai-results", views.SpecimenAiResultView.as_view({"post": "start"}), name="specimen-ai-results-start"),
    path("specimens/<int:pk>/draft", views.SpecimenDraftView.as_view({"put": "update"}), name="specimen-draft"),
    path("specimens/<int:pk>/finalize", views.SpecimenFinalizeView.as_view({"patch": "partial_update"}), name="specimen-finalize"),
    path("admin/approvals", views.StaffApprovalListView.as_view(), name="admin-approvals-list"),
    path("admin/approvals/<int:pk>", views.StaffApproveView.as_view({"patch": "partial_update"}), name="admin-approval-approve"),
    path("admin/accounts/<int:pk>/role", views.AccountRoleView.as_view({"patch": "partial_update"}), name="admin-account-role"),
    path("staff",views.StaffListView.as_view(), name ="staff-list"),
    path("followups/new", views.FollowupCreateView.as_view({"post": "create"}), name="followup-create"),
    path("followups/<int:pk>/call", views.FollowupCallView.as_view({"patch": "partial_update"}), name="followup-call"),
    path("patients/register", views.PatientRegisterView.as_view({"post": "create"}), name="patient-register"),
    path("exam-orders/checkin", views.CheckInView.as_view({"post": "create"}), name="exam-order-checkin"),
    path("exam-orders/schedule", views.ExamOrderScheduleView.as_view({"post": "create"}), name="exam-order-schedule"),
]

