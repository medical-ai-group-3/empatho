from rest_framework import viewsets, status
from rest_framework.response import Response
from django.db.models import Q

from django.utils import timezone
from . import models, serializers
from .mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin

from core.api.errors import ApiError
from rest_framework import generics

from django.db import transaction
from core.api.errors import ApiError

# ── reception · 원무 ──────────────────────────────────────────
class PatientViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):

    resource = "patient"
    permission_classes = [MatrixPermission]
    queryset = models.Patient.objects.select_related("pii", "primary_staff").all()

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

class ReservationRequestViewSet(AuditMixin, viewsets.ViewSet):
    """§7 환자 예약 신청.

    POST /me/reservation-requests   {scheduled_at}
    """

    resource = "reservation"
    permission_classes = [MatrixPermission]

    def create(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")

        serializer = serializers.ReservationRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            patient=patient,
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.ExamOrderSerializer(serializer.instance)
        return Response(out.data, status=status.HTTP_201_CREATED)

# ── nursing · 간호 ───────────────────────────────────────────
class VisitTodayViewSet(AuditMixin, viewsets.ViewSet):
    """§6-1 오늘 방문.

    GET  /visits/today/            오늘 scheduled_at 인 exam_order 목록 + 내원상태
    POST /visits/today/            {exam_order_id} → visited_at = now()
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def list(self, request):
        today = timezone.localdate()
        qs = models.ExamOrder.objects.filter(
            scheduled_at__date=today
        ).order_by("scheduled_at")
        out = serializers.ExamOrderSerializer(qs, many=True)
        return Response(out.data)

    def create(self, request):
        serializer = serializers.VisitCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = models.ExamOrder.objects.get(pk=serializer.validated_data["exam_order_id"])
        order.visited_at = timezone.now()
        order.updated_by = self._current_account()
        order.save()
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_200_OK)

class FollowupViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """§6-3 추적 관리."""
    
    resource = "followup"
    permission_classes = [MatrixPermission]
    queryset = models.Followup.objects.select_related("patient").order_by("due_at")
    serializer_class = serializers.FollowupSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data
        
        if "closed_reason" in data:
            instance.status = data.get("status", "resolved")
            instance.closed_at = timezone.now()
            instance.closed_reason = data["closed_reaason"]
        else:
            instance.call_result = data.get("call_result")
            instance.call_note = data.get("claa_note")
            instance.called_by = self._current_account()
            instance.called_at = timezone.now()
            
        instance.updated_by = self._current_account()
        instance.save()
        
        out= serializers.FollowupSerializer(instance)
        return Response(out.data)


    def owned_queryset(self, queryset, account):
        return queryset.filter(patient__account=account)

    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id


class QuestionnaireView(AuditMixin, viewsets.ViewSet):
    """§6-2 문진 저장."""
    
    resource = "questionnaire"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        patient = models.Patient.objects.get(pk=pk)
        patient.questionnaire = request.data 
        patient.updated_by = self._current_account()
        patient.save()
        out = serializers.PatientDetailSerializer(patient)
        return Response(out.data)
    
    
    
class ReservationRequestViewSet(AuditMixin, viewsets.ViewSet):
    """§7 환자 예약 신청.

    POST /me/reservation-requests   {scheduled_at}
    """
    resource = "reservation"
    permission_classes = [MatrixPermission]
    
    def get_serializer_class(self):
        return serializers.ReservationRequestCreateSerializer

    def create(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")

        serializer = serializers.ReservationRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            patient=patient,
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.ExamOrderSerializer(serializer.instance)
        return Response(out.data, status=status.HTTP_201_CREATED)
    
    
class ReservationRequestQueueView(generics.ListAPIView):
    """§7 원무 큐 — order_status='requested' 만 노출.

    GET /reservation-requests
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderSerializer
    queryset = models.ExamOrder.objects.filter(order_status="requested").order_by("scheduled_at")
    
    
class ExamOrderConfirmView(AuditMixin, viewsets.ViewSet):
    """§7 원무 확정 — modality 여러 개면 parent_order_id 로 묶어 추가 생성.

    PATCH /exam-orders/{id}/confirm   {modalities: [...], exam_purpose}
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    @transaction.atomic
    def partial_update(self, request, pk=None):
        order = models.ExamOrder.objects.select_for_update().get(pk=pk)

        if order.order_status != "requested":
            raise ApiError("ALREADY_CONFIRMED")

        modalities = request.data.get("modalities") or []
        exam_purpose = request.data.get("exam_purpose")
        ordered_by_id = request.data.get("ordered_by")

        if not modalities or not exam_purpose or not ordered_by_id:
            raise ApiError("VALIDATION_ERROR", "modalities · exam_purpose · ordered_by 가 필요합니다.")

        account = self._current_account()

        # 첫 번째 modality — 기존 requested 행을 확정
        order.modality = modalities[0]
        order.exam_purpose = exam_purpose
        order.ordered_by_id = ordered_by_id
        order.order_status = "ordered"
        order.updated_by = account
        order.save()

        # 나머지 modality — 새 행 생성, parent_order_id 로 묶음
        extra_rows = [
            models.ExamOrder(
                patient=order.patient,
                scheduled_at=order.scheduled_at,
                exam_purpose=exam_purpose,
                modality=m,
                order_status="ordered",
                ordered_by_id=ordered_by_id,
                parent_order=order,
                created_by=account,
                updated_by=account,
            )
            for m in modalities[1:]
        ]
        if extra_rows:
            models.ExamOrder.objects.bulk_create(extra_rows)

        all_rows = [order] + extra_rows
        out = serializers.ExamOrderSerializer(all_rows, many=True)
        return Response(out.data, status=status.HTTP_200_OK)


