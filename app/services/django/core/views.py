from rest_framework import viewsets, status
from rest_framework.response import Response
from django.db.models import Q

from . import models, serializers
from .mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin


# ── reception · 원무 ──────────────────────────────────────────
class PatientViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):

    resource = "patient"
    permission_classes = [MatrixPermission]
    queryset = models.Patient.objects.select_related("pii").all()

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q", "").strip()
        if not q:
            return qs.none()
        return qs.filter(
            Q(patient_number=q) |
            Q(pii__name__icontains=q) |
            Q(pii__phone__icontains=q)
        )

    def owned_queryset(self, queryset, account):
        return queryset.filter(account=account)

    def is_owned_by(self, obj, account):
        return obj.account_id == account.account_id

    def get_serializer_class(self):
        if self.action == "create":
            return serializers.PatientCreateSerializer
        if self.action == "retrieve":
            return serializers.PatientDetailSerializer
        if self.action == "list":
            return serializers.PatientListSerializer
        return serializers.PatientSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        out = serializers.PatientDetailSerializer(serializer.instance)
        return Response(out.data, status=status.HTTP_201_CREATED)


class ReservationViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ViewSet):
    """§5-3 예약 생성. exam_order 로 1:N 생성.

    POST /reservations/   {patient_id, scheduled_at, orders: [{exam_purpose, modality}, ...]}
    """

    resource = "reservation"
    permission_classes = [MatrixPermission]

    def owned_queryset(self, queryset, account):
        return queryset.filter(patient__account=account)

    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id

    def create(self, request):
        serializer = serializers.ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        rows = serializer.instance
        out = serializers.ExamOrderSerializer(rows, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)


# ── nursing · 간호 ───────────────────────────────────────────
class VisitTodayViewSet(AuditMixin, viewsets.ViewSet):
    """§6-1 오늘 방문."""
    resource = "exam_order"
    permission_classes = [MatrixPermission]
    # own_only 없음 (exam_order 매트릭스엔 own_only 없음) — OwnedOnlyMixin 불필요


class FollowupViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    resource = "followup"
    permission_classes = [MatrixPermission]
    queryset = models.Followup.objects.select_related("patient").order_by("due_at")
    serializer_class = serializers.FollowupSerializer

    def owned_queryset(self, queryset, account):
        return queryset.filter(patient__account=account)

    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id


class QuestionnaireView(AuditMixin, viewsets.ViewSet):
    resource = "questionnaire"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        return Response(status=status.HTTP_501_NOT_IMPLEMENTED)
    
    
    
class ReservationRequestViewSet(AuditMixin, viewsets.ViewSet):
    """§7 환자 예약 신청.

    POST /me/reservation-requests   {scheduled_at}
    """
    resource = "reservation"
    permission_classes = [MatrixPermission]
    
    def create(self, request):
        patient = getattr(request.user, "patient", None)