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

class ExamOrderQueryView(generics.ListAPIView):
    """GET /exam-orders — 여러 화면이 공유하는 유연한 목록 조회.

    지원 쿼리:
      status, visited(yes/none), scheduled_on(today/YYYY-MM-DD),
      scheduled_from, scheduled_to, patient, ordering
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderSerializer

    def get_queryset(self):
        qs = models.ExamOrder.objects.all()
        p = self.request.query_params

        if p.get("status"):
            qs = qs.filter(order_status=p["status"])

        visited = p.get("visited")
        if visited == "yes":
            qs = qs.filter(visited_at__isnull=False)
        elif visited == "none":
            qs = qs.filter(visited_at__isnull=True)

        scheduled_on = p.get("scheduled_on")
        if scheduled_on == "today":
            qs = qs.filter(scheduled_at__date=timezone.localdate())
        elif scheduled_on:
            qs = qs.filter(scheduled_at__date=scheduled_on)

        if p.get("scheduled_from"):
            qs = qs.filter(scheduled_at__gte=p["scheduled_from"])
        if p.get("scheduled_to"):
            qs = qs.filter(scheduled_at__lte=p["scheduled_to"])

        if p.get("patient"):
            qs = qs.filter(patient_id=p["patient"])

        ordering = p.get("ordering", "visited_at")
        qs = qs.order_by(ordering)
        return qs


class StaffListView(generics.ListAPIView):
    """GET /staff?role= — 배정 팝업용 직원 목록."""

    resource = "patient"  # 별도 리소스 없어 patient 권한으로 간주(간호가 조회)
    permission_classes = [MatrixPermission]
    serializer_class = serializers.StaffSerializer

    def get_queryset(self):
        qs = models.Staff.objects.select_related("account").all()
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(account__role=role)
        return qs


class PatientTodayStatusView(viewsets.ViewSet):
    """GET /patients/today-status — 방문 환자 모니터링(§1)."""

    resource = "patient"
    permission_classes = [MatrixPermission]

    def list(self, request):
        today = timezone.localdate()
        orders = models.ExamOrder.objects.filter(
            visited_at__date=today
        ).select_related("patient", "assigned_to")

        result = []
        for o in orders:
            if o.order_status == "requested":
                stage = "접수 대기"
            elif o.order_status == "ordered" and not getattr(o, "assigned_to_id", None):
                stage = "영상의학과 대기"
            elif getattr(o, "assigned_to_id", None):
                has_study = models.Study.objects.filter(exam_order=o).exists()
                stage = "영상의학과 촬영중" if not has_study else "AI 분석중"
            else:
                stage = o.order_status
            result.append({"exam_order_id": o.exam_order_id, "patient_id": o.patient_id, "stage": stage})
        return Response(result)