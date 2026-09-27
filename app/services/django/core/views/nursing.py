"""간호과(nursing) view."""

from rest_framework import viewsets, status
from rest_framework.response import Response

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin
from core.api import questionnaire as questionnaire_module


class VisitTodayViewSet(AuditMixin, viewsets.ViewSet):
    """§6-1 오늘 방문.

    GET  /visits/today/            오늘 scheduled_at 인 exam_order 목록 + 내원상태
    POST /visits/today/            {exam_order_id} → visited_at = now()
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def list(self, request):
        today = timezone.localdate()
        # 줄마다 patient · pii · 주치의를 따로 읽지 않게(N+1)
        qs = (models.ExamOrder.objects
              .filter(scheduled_at__date=today)
              .select_related("patient__pii", "patient__primary_staff")
              .order_by("scheduled_at", "exam_order_id"))
        out = serializers.ExamOrderSerializer(qs, many=True)
        return Response(out.data)

    def create(self, request):
        serializer = serializers.VisitCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        with transaction.atomic():
            order = (models.ExamOrder.objects.select_for_update()
                     .select_related("patient").get(pk=serializer.validated_data["exam_order_id"]))
            # 이미 내원 확인한 오더를 다시 누르면 처음 온 시각이 덮여 대기
            # 순서가 뒤로 밀렸다. 처음 값을 지킨다.
            if order.visited_at is None:
                order.visited_at = now
                order.updated_by = self._current_account()
                order.save(update_fields=["visited_at", "updated_by", "updated_at"])
                # 초진 시각 — 접수(CheckInView)와 같은 규칙. 예약으로 온 첫 방문이
                # 여기서 안 찍혀 visit_type 이 계속 「초진」으로 남았다.
                patient = order.patient
                if not patient.first_visited_at:
                    patient.first_visited_at = now
                    patient.updated_by = self._current_account()
                    patient.save(update_fields=["first_visited_at", "updated_by", "updated_at"])
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_200_OK)


class FollowupViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """§6-3 추적 관리."""

    resource = "followup"
    permission_classes = [MatrixPermission]
    # patient_name 이 patient.pii 를 읽는다 — pii 까지 붙여야 줄마다 안 쏜다(N+1)
    queryset = models.Followup.objects.select_related("patient__pii").order_by("due_at", "followup_id")
    serializer_class = serializers.FollowupSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def list(self, request, *args, **kwargs):
        existing = self.get_queryset()
        existing_data = serializers.FollowupSerializer(existing, many=True).data
        result = list(existing_data)

        if request.query_params.get("include_candidates") == "1" and getattr(request.user, "staff", None) is not None:
            tracked_patient_ids = set(existing.values_list("patient_id", flat=True))
            candidates = models.Assessment.objects.filter(
                category="3", read_stage="final"
            ).exclude(lesion__patient_id__in=tracked_patient_ids).select_related("lesion__patient__pii")

            for a in candidates:
                if a.lesion and a.lesion.patient_id not in tracked_patient_ids:
                    pii = getattr(a.lesion.patient, "pii", None)
                    result.append({
                        "followup_id": None,
                        "patient": a.lesion.patient_id,
                        "patient_name": pii.name if pii else None,
                        "status": "candidate",
                        "round_no": 0,
                    })
                    tracked_patient_ids.add(a.lesion.patient_id)

        return Response(result)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        # 예전에는 request.data 를 그대로 모델에 넣었다 — status 에 모르는 값이
        # 오면 CHECK 위반(IntegrityError)으로, 긴 메모는 DataError 로 500 이었다.
        serializer = serializers.FollowupUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "closed_reason" in data:
            instance.status = data.get("status", "resolved")
            instance.closed_at = timezone.now()
            instance.closed_reason = data["closed_reason"]
        else:
            instance.call_result = data.get("call_result")
            instance.call_note = data.get("call_note")
            instance.called_by = getattr(request.user, "staff", None)
            instance.called_at = timezone.now()

        instance.updated_by = self._current_account()
        instance.save()

        out = serializers.FollowupSerializer(instance)
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
        # 없는 환자면 DoesNotExist 로 500 이었다 → 404
        patient = get_object_or_404(models.Patient, pk=pk)
        validated = questionnaire_module.validate(request.data)
        patient.questionnaire = validated
        patient.updated_by = self._current_account()
        patient.save()
        out = serializers.PatientDetailSerializer(patient)
        return Response(out.data)
    

class FollowupCreateView(AuditMixin, viewsets.ViewSet):
    """§2 POST /followups — 회차 생성."""

    resource = "followup"
    permission_classes = [MatrixPermission]

    def create(self, request):
        serializer = serializers.FollowupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        followup = models.Followup.objects.create(
            patient_id=data["patient_id"],
            round_no=data["round_no"],
            status="open",
            started_at=timezone.now(),
            due_at=data["due_at"],
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.FollowupSerializer(followup)
        return Response(out.data, status=status.HTTP_201_CREATED)


class FollowupCallView(AuditMixin, viewsets.ViewSet):
    """§2 PATCH /followups/{id}/call — 안내 콜 기록."""

    resource = "followup"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        # 없는 번호면 DoesNotExist 로 500 이었다 → 404
        followup = get_object_or_404(models.Followup, pk=pk)
        serializer = serializers.FollowupCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        followup.call_result = data["call_result"]
        followup.call_note = data.get("call_note", "")
        followup.called_by = getattr(request.user, "staff", None)
        followup.called_at = timezone.now()
        followup.updated_by = self._current_account()
        followup.save()

        out = serializers.FollowupSerializer(followup)
        return Response(out.data)


class ExamOrderNoteView(AuditMixin, viewsets.ViewSet):
    """PATCH /exam-orders/{id}/note — 내원 메모 저장."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderNoteSerializer

    def partial_update(self, request, pk=None):
        # 없는 번호면 DoesNotExist 로 500 이었다 → 404
        order = get_object_or_404(
            models.ExamOrder.objects.select_related("patient__pii", "patient__primary_staff"),
            pk=pk)
        serializer = serializers.ExamOrderNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order.order_note = serializer.validated_data["note"]
        order.updated_by = self._current_account()
        order.save(update_fields=["order_note", "updated_by", "updated_at"])

        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)
