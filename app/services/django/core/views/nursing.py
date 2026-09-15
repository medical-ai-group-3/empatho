"""간호과(nursing) view."""

from rest_framework import viewsets, status
from rest_framework.response import Response

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

    def list(self, request, *args, **kwargs):
        existing = self.get_queryset()
        existing_data = serializers.FollowupSerializer(existing, many=True).data
        result = list(existing_data)

        if request.query_params.get("include_candidates") == "1":
            tracked_patient_ids = set(existing.values_list("patient_id", flat=True))
            candidates = models.Assessment.objects.filter(
                category="3", read_stage="final"
            ).exclude(lesion__patient_id__in=tracked_patient_ids).select_related("lesion__patient")

            for a in candidates:
                if a.lesion and a.lesion.patient_id not in tracked_patient_ids:
                    result.append({
                        "followup_id": None,
                        "patient": a.lesion.patient_id,
                        "status": "candidate",
                        "round_no": 0,
                    })
                    tracked_patient_ids.add(a.lesion.patient_id)

        return Response(result)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data

        if "closed_reason" in data:
            instance.status = data.get("status", "resolved")
            instance.closed_at = timezone.now()
            instance.closed_reason = data["closed_reason"]
        else:
            instance.call_result = data.get("call_result")
            instance.call_note = data.get("call_note")
            instance.called_by = self._current_account()
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
        patient = models.Patient.objects.get(pk=pk)
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
        followup = models.Followup.objects.get(pk=pk)
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


class PrimaryStaffAssignView(AuditMixin, viewsets.ViewSet):
    """§1 PATCH /patients/{id} — 주치의 지정.

    PatientViewSet.partial_update 가 이미 있으면 그쪽으로 흡수해도 된다.
    """

    resource = "patient"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        patient = models.Patient.objects.get(pk=pk)
        serializer = serializers.PrimaryStaffAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        patient.primary_staff_id = serializer.validated_data["primary_staff"]
        patient.updated_by = self._current_account()
        patient.save()

        out = serializers.PatientDetailSerializer(patient)
        return Response(out.data)