"""원무과(reception) view."""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.db.models import Q

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin
from core.api.errors import ApiError


class PatientViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):

    resource = "patient"
    permission_classes = [MatrixPermission]
    queryset = models.Patient.objects.select_related("pii", "primary_staff").all()

    def get_queryset(self):
        qs = super().get_queryset()
        
        primary_staff_param = self.request.query_params.get("primaty_staff")
        if primary_staff_param == "me":
            staff = getattr(self.request.user, "staff", None)
            if staff is None:
                return qs.none()
            return qs.filter(primary_staff=staff)
        
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

    def partial_update(self, request, pk=None):
        from django.db import transaction

        with transaction.atomic():
            order = models.ExamOrder.objects.select_for_update().get(pk=pk)

            if order.order_status != "requested":
                raise ApiError("ALREADY_CONFIRMED")

            modalities = request.data.get("modalities") or []
            exam_purpose = request.data.get("exam_purpose")
            ordered_by_id = request.data.get("ordered_by")

            if not modalities or not exam_purpose or not ordered_by_id:
                raise ApiError("VALIDATION_ERROR", "modalities · exam_purpose · ordered_by 가 필요합니다.")

            account = self._current_account()

            order.modality = modalities[0]
            order.exam_purpose = exam_purpose
            order.ordered_by_id = ordered_by_id
            order.order_status = "ordered"
            order.updated_by = account
            order.save()

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