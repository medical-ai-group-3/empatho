"""원무과(reception) view."""

from rest_framework import viewsets, status, generics, mixins as drf_mixins
from rest_framework.response import Response

from django.db.models import Q
from django.utils import timezone 

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin, IsAuthenticatedAccount
from core.api.errors import ApiError

def _is_date(value):
    from datetime import date
    try:
        date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False
    
    
class PatientViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):

    resource = "patient"
    permission_classes = [MatrixPermission]
    queryset = models.Patient.objects.select_related("pii", "primary_staff").all()

    def get_queryset(self):
        qs = super().get_queryset()

        # retrieve · update · partial_update · destroy 는 pk 로 단건을
        # 찾는다 — 목록 유출 방지용 필터(q/status 없으면 빈 쿼리셋)를 걸면
        # 안 된다. 그 필터는 list 에서 「전체 환자를 실수로 긁는 것」을
        # 막으려는 것이라 list 에만 건다.
        if self.action != "list":
            return qs

        primary_staff_param = self.request.query_params.get("primary_staff")
        if primary_staff_param == "me":
            staff = getattr(self.request.user, "staff", None)
            if staff is None:
                return qs.none()
            return qs.filter(primary_staff=staff)

        q = self.request.query_params.get("q", "").strip()
        status_param = self.request.query_params.get("status")

        if not q and not status_param:
            return qs.none()

        result = qs
        if q:
            result = result.filter(
                Q(patient_number=q) |
                Q(pii__name__icontains=q) |
                Q(pii__phone__icontains=q) |
                Q(pii__birth_date=q if _is_date(q) else None)
            )
        return result
    
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
        patient = getattr(request.user, "patient", None)
        payload = request.data
        if patient is not None:
            payload = {**request.data, "patient_id": patient.patient_id}
        serializer = serializers.ReservationCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        rows = serializer.instance
        out_serializer_class = (
            serializers.PatientExamOrderSerializer if patient is not None
            else serializers.ExamOrderSerializer
        )
        if rows :
            from .. import notify 
            when = timezone.localtime(rows[0].scheduled_at)
            notify.send(
                patient=rows[0].patient, 
                type="reservation_created",
                message=f"{when:%m월 %d일 %H시} 검사 예약이 확정되었습니다.", 
                ref_type="exam_order",
                ref_id=rows[0].pk,
                severity="normal",
            )
        out = out_serializer_class(rows, many=True)
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
        out = serializers.PatientExamOrderSerializer(serializer.instance)
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
    """§7 원무 확정 — 날짜만 정한다.

    검사 종류(modality·exam_purpose·ordered_by)는 원무가 아니라 유방외과가
    나중에 정한다 — 0015 로 order_status='scheduled' 가 생겨(09-17 팀 확정),
    원무는 requested → scheduled 로만 옮긴다. ordered 전환은 별도 경로(유방외과)
    가 맡는다.

    PATCH /exam-orders/{id}/confirm   {scheduled_at}
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        from django.db import transaction

        with transaction.atomic():
            order = models.ExamOrder.objects.select_for_update().get(pk=pk)

            if order.order_status != "requested":
                raise ApiError("ALREADY_CONFIRMED")

            serializer = serializers.ExamOrderConfirmSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            order.scheduled_at = serializer.validated_data["scheduled_at"]
            order.order_status = "scheduled"
            order.updated_by = self._current_account()
            order.save()

        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_200_OK)

class ExamOrderQueryView(
    drf_mixins.ListModelMixin,
    drf_mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """GET /exam-orders — 여러 화면이 공유하는 유연한 목록 조회.
    GET /exam-orders/{id} — 단건 조회.

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
        ).select_related("patient__pii", "assigned_to")

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
            pii = getattr(o.patient, "pii", None)
            result.append({
                "exam_order_id": o.exam_order_id,
                "patient_id": o.patient_id,
                "patient_name": pii.name if pii else None,
                "stage": stage,
            })
        return Response(result)
    
class PatientRegisterView(AuditMixin, viewsets.ViewSet):
    """§1 [+] 등록 — POST /patients. (기존 PatientCreateSerializer 와 별개 — 간소화된 접수용)"""
    resource = "patient"
    permission_classes = [MatrixPermission]
    
    def create(self, request):
        serializer = serializers.PatientRegisterSerializer(data = request.data)
        serializer.is_valid(raise_exception=True)
        patient = serializer.save(
            created_by = self._current_account(),
            updated_by=self._current_account(),
        )
        created = serializer.created
        out = serializers.PatientDetailSerializer(patient)
        data = {**out.data, "created": created}
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
class CheckInView(AuditMixin, viewsets.ViewSet):
    """§1 [접수하기] — POST /exam-orders (requested + visited_at)."""
    
    resource = "exam_order"
    permission_classes = [MatrixPermission]
    
    def create(self, request):
        serializer = serializers.CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient_id = serializer.validated_data["patient_id"]
        
        order = models.ExamOrder.objects.create(
            patient_id=patient_id,
            order_status="requested",
            visited_at=timezone.now(),
            created_by=self._current_account(),
            updated_by=self._current_account()
        )
        
        patient = models.Patient.objects.get(pk=patient_id)
        if not patient.first_visited_at:
            patient.first_visited_at = timezone.now()
            patient.updated_by = self._current_account()
            patient.save()
        
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status= status.HTTP_201_CREATED)
    
class ExamOrderScheduleView(AuditMixin, viewsets.ViewSet):
    """§3 [예약 완료] — POST /exam-orders (원무가 날짜만 정함, 검사종류는 안 정함)."""
    resource = "exam_order"
    permission_classes = [MatrixPermission]
    
    def create(self, request):
        serializer = serializers.ExamOrderScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        order = models.ExamOrder.objects.create(
            patient_id=data["patient_id"],
            scheduled_at = data["scheduled_at"],
            order_status= "requested",
            ordered_at = timezone.now(),
            created_by = self._current_account(),
            updated_by = self._current_account(),
        )
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status = status.HTTP_201_CREATED)
    
class MeView(viewsets.ViewSet):
    """GET /me"""

    permission_classes = [IsAuthenticatedAccount]  # core.api.permissions 에서 import

    def list(self, request):
        out = serializers.MeSerializer(request.user)
        return Response(out.data)