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

  radiology  GET       api/v1/exam-orders/queue                     ExamOrderQueueView
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
  admin      Django admin(/admin/) + POST api/v1/admin-session 로 세션 다리.
                       REST 엔드포인트 없음 — core/api/admin_session.py, core/admin.py 참고.
"""

from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt
from rest_framework.routers import DefaultRouter

from . import views

# 같은 경로 문자열로 path() 를 두 번 등록하면 Django 는 메서드와 상관없이
# 목록의 첫 항목만 매칭한다 — 뒤에 등록한 메서드는 항상 405 로 막힌다.
# GET/POST 를 같은 경로에서 서로 다른 뷰가 나눠 맡는 곳은 여기서 메서드로
# 직접 갈라 둘 다 실제로 닿게 한다.
@csrf_exempt
def _exam_orders_dispatch(request, *args, **kwargs):
    if request.method == "POST":
        return views.ExamOrderRequestView.as_view({"post": "create"})(request, *args, **kwargs)
    return views.ExamOrderQueryView.as_view({"get": "list"})(request, *args, **kwargs)


router = DefaultRouter()
router.register(r"patients", views.PatientViewSet, basename="patient")
router.register(r"reservations", views.ReservationViewSet, basename="reservation")
router.register(r"visits/today", views.VisitTodayViewSet, basename="visit-today")
router.register(r"followups", views.FollowupViewSet, basename="followup")
router.register(r"me/reservation-requests", views.ReservationRequestViewSet, basename="reservation-request")
router.register(r"lesions", views.LesionViewSet, basename="lesion")
router.register(r"specimens", views.SpecimenBindViewSet, basename="specimen")
router.register(r"reports", views.SurgeryReportViewSet, basename="report")
router.register(r"studies", views.StudyViewSet, basename="study")
router.register(r"notifications", views.NotificationViewSet, basename="notification")



urlpatterns = [
    path("", include(router.urls)),
    path(
        "reservation-requests",
        views.ReservationRequestQueueView.as_view(),
        name="reservation-request-queue",
    ),
    path("exam-orders", _exam_orders_dispatch, name="exam-order-query"),
    path(
        "exam-orders/<int:pk>",
        views.ExamOrderQueryView.as_view({"get": "retrieve"}),
        name="exam-order-detail",
    ),
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
    path(
        "patients/<int:pk>/studies",
        views.PatientStudiesView.as_view(),
        name="patient-studies",
    ),
    path(
        "exam-orders/<int:pk>/note",
        views.ExamOrderNoteView.as_view({"patch": "partial_update"}),
        name="exam-order-note",
    ),
    path("radiology/queue", views.ExamOrderQueueView.as_view(), name="exam-order-queue"),
    path("exam-orders/queue", views.ExamOrderQueueView.as_view(), name="exam-order-queue-alias"),
    path(
        "exam-orders/<int:pk>/complete",
        views.ExamOrderCompleteView.as_view({"patch": "partial_update"}),
        name="exam-order-complete",
    ),
    path(
        "radiology/queue/<int:pk>/start-study",
        views.StudyStartView.as_view({"post": "create"}),
        name="radiology-queue-start-study",
    ),
    path(
        "exam-orders/<int:pk>/start-study",
        views.StudyStartView.as_view({"post": "create"}),
        name="exam-order-start-study",
    ),
    path(
        "radiology/studies/<int:pk>/upload",
        views.StudyUploadView.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="radiology-study-upload",
    ),
    path(
        "studies/<int:pk>/upload",
        views.StudyUploadView.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="study-upload",
    ),
    path(
        "radiology/studies/<int:pk>/read",
        views.StudyReadView.as_view({"get": "retrieve"}),
        name="radiology-study-read",
    ),
    path(
        "studies/<int:pk>/read",
        views.StudyReadView.as_view({"get": "retrieve"}),
        name="study-read",
    ),
    path("studies/<int:pk>/ai-results", views.AiResultQueueView.as_view({"post": "start"}), name="study-ai-results-start"),
    path("ai-results", views.AiResultListView.as_view({"get": "list"}), name="ai-results-list"),
    path("studies/<int:pk>/assessment/draft", views.AssessmentDraftView.as_view({"put": "update"}), name="study-assessment-draft"),
    path("studies/<int:pk>/finalize", views.StudyFinalizeView.as_view({"patch": "partial_update"}), name="study-finalize"),
    path("assessments", views.AssessmentHistoryView.as_view(), name="assessment-history"),
    path("assessments/<int:pk>/amend", views.AssessmentAmendView.as_view({"post": "create"}), name="assessment-amend"),
    path(
        "assessments/<int:pk>/decision",
        views.SurgeryDecisionView.as_view({"patch": "partial_update"}),
        name="assessment-decision",
    ),
    path("patients/<int:pk>/timeline", views.PatientTimelineView.as_view({"get": "retrieve"}), name="patient-timeline"),
    path("reports/<int:pk>/explain", views.ReportExplainView.as_view({"patch": "partial_update"}), name="report-explain"),
    path("reports/<int:pk>/unlock-status", views.ReportUnlockStatusView.as_view({"get": "retrieve"}), name="report-unlock-status"),
    path("reports/<int:pk>/unlock", views.ReportUnlockView.as_view({"patch": "partial_update"}), name="report-unlock"),
    path("reports/final", views.FinalReportView.as_view({"post": "create"}), name="report-final"),
    path("discordances", views.DiscordanceListView.as_view(), name="discordance-list"),
    path("discordances/<int:pk>", views.DiscordanceDisposeView.as_view({"get": "retrieve", "patch": "partial_update"}), name="discordance-detail"),
    path("discordances/<int:pk>/dispose", views.DiscordanceDisposeView.as_view({"get": "retrieve", "patch": "partial_update"}), name="discordance-dispose"),
    path("specimens/queue", views.SpecimenQueueView.as_view(), name="specimen-queue"),
    path("specimens/<int:pk>/assign", views.SpecimenAssignView.as_view({"patch": "partial_update"}), name="specimen-assign"),
    path("specimens/<int:pk>/ai-results", views.SpecimenAiResultView.as_view({"post": "start"}), name="specimen-ai-results-start"),
    path("specimens/<int:pk>/draft", views.SpecimenDraftView.as_view({"put": "update"}), name="specimen-draft"),
    path("specimens/<int:pk>/finalize", views.SpecimenFinalizeView.as_view({"patch": "partial_update"}), name="specimen-finalize"),
    path("specimens/<int:pk>/upload", views.SpecimenUploadListView.as_view({"get": "retrieve"}), name="specimen-upload"),
    path("staff",views.StaffListView.as_view(), name ="staff-list"),
    path("followups/new", views.FollowupCreateView.as_view({"post": "create"}), name="followup-create"),
    path("followups/<int:pk>/call", views.FollowupCallView.as_view({"patch": "partial_update"}), name="followup-call"),
    path("patients/register", views.PatientRegisterView.as_view({"post": "create"}), name="patient-register"),
    path("exam-orders/checkin", views.CheckInView.as_view({"post": "create"}), name="exam-order-checkin"),
    path("exam-orders/schedule", views.ExamOrderScheduleView.as_view({"post": "create"}), name="exam-order-schedule"),
    path("exam-orders/<int:pk>/assign", views.ExamOrderAssignView.as_view({"patch": "partial_update"}), name="exam-order-assign"),
    path("me", views.MeView.as_view({"get": "list"}), name="me"),
    path("me/push-token", views.PushTokenView.as_view({"patch": "partial_update"}), name="me-push-token"),
]

