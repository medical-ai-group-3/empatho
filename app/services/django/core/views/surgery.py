"""유방외과(surgery) view — 2026-09-14 화면명세 기준."""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.db.models import Q
from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin, CanDisposeDiscordance
from core.api.errors import ApiError
from core.api.permissions import CanBindSpecimen


class ExamOrderRequestView(AuditMixin, viewsets.ViewSet):
    """§1 POST /exam-orders — 촬영 요청 팝업(유방외과가 만드는 오더)."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def create(self, request):
        serializer = serializers.ExamOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = models.ExamOrder.objects.create(
            patient_id=data["patient_id"],
            modality=data["modality"],
            exam_purpose=data["exam_purpose"],
            order_status="ordered",
            ordered_at=timezone.now(),
            ordered_by=getattr(request.user, "staff", None),
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_201_CREATED)


class PatientTimelineView(AuditMixin, viewsets.ViewSet):
    """§2 GET /patients/{id}/timeline — 다섯 표 조립."""

    resource = "patient"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        patient = models.Patient.objects.get(pk=pk)

        events = []
        for study in models.Study.objects.filter(patient=patient):
            if study.performed_at:
                events.append({"at": study.performed_at, "type": "촬영", "detail": study.modality})

        for ai in models.AiResult.objects.filter(patient=patient):
            if ai.analyzed_at:
                events.append({"at": ai.analyzed_at, "type": "AI 분석 완료", "detail": None})

        for assessment in models.Assessment.objects.filter(study__patient=patient):
            events.append({"at": assessment.created_at, "type": "판독", "detail": assessment.category})

        for specimen in models.Specimen.objects.filter(patient=patient):
            if specimen.collected_at:
                events.append({"at": specimen.collected_at, "type": "검체 채취", "detail": specimen.specimen_label})
            if specimen.finalized_at:
                events.append({"at": specimen.finalized_at, "type": "병리 확진", "detail": specimen.diagnosis})

        events.sort(key=lambda e: e["at"])
        return Response(events)


class SurgeryReportViewSet(AuditMixin, viewsets.ModelViewSet):
    """§2·§3 GET/PUT /reports/{id}, GET /reports?patient=&type=final."""

    resource = "report"
    permission_classes = [MatrixPermission]
    queryset = models.Report.objects.all()
    serializer_class = serializers.ReportSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get("patient")
        report_type = self.request.query_params.get("type")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        if report_type:
            qs = qs.filter(report_type=report_type)
        return qs

    def update(self, request, *args, **kwargs):
        report = self.get_object()
        report.content_json = request.data.get("content_json", report.content_json)
        report.updated_by = self._current_account()
        report.save()
        out = serializers.ReportSerializer(report)
        return Response(out.data)


class SurgeryDecisionView(AuditMixin, viewsets.ViewSet):
    """§3 POST /assessments — 수술 여부·사유(decision_*)."""

    resource = "assessment"
    permission_classes = [MatrixPermission]

    def create(self, request):
        serializer = serializers.SurgeryDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        assessment = models.Assessment.objects.filter(
            lesion_id=data["lesion_id"], read_stage="final"
        ).order_by("-created_at").first()
        if assessment is None:
            raise ApiError("VALIDATION_ERROR", "최종 판정을 찾을 수 없습니다.")

        assessment.decision_type = data["decision_type"]
        assessment.decision_value = data["decision_value"]
        assessment.decision_reason = data.get("decision_reason", "")
        assessment.decided_by = getattr(request.user, "staff", None)
        assessment.decided_at = timezone.now()
        assessment.updated_by = self._current_account()
        assessment.save()

        out = serializers.AssessmentSerializer(assessment)
        return Response(out.data)


class ReportExplainView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /reports/{id}/explain — 환자 설명 기록."""

    resource = "report"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        report = models.Report.objects.get(pk=pk)
        serializer = serializers.ReportExplainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        report.explain_method = data["explain_method"]
        report.patient_confirmed = data["patient_confirmed"]
        report.explained_by = getattr(request.user, "staff", None)
        report.explained_at = timezone.now()
        report.updated_by = self._current_account()
        report.save()

        out = serializers.ReportSerializer(report)
        return Response(out.data)


class ReportUnlockStatusView(viewsets.ViewSet):
    """§3 GET /reports/{id}/unlock-status — 잠금 해제 세 조건 판단."""

    resource = "report"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        report = models.Report.objects.get(pk=pk)
        patient = report.patient

        records_final = not models.Study.objects.filter(
            patient=patient
        ).exclude(read_status="finalized").exists() and not models.Specimen.objects.filter(
            patient=patient, finalized_at__isnull=True
        ).exists()

        discordance_closed = not models.DiscordanceFlag.objects.filter(
            lesion__patient=patient, closed_at__isnull=True
        ).exists()

        explained = report.explained_at is not None

        conditions = [
            {"key": "records_final", "label": "전 레코드 확정", "met": records_final},
            {"key": "discordance_closed", "label": "대조 종결", "met": discordance_closed},
            {"key": "explained", "label": "대면 설명 완료", "met": explained},
        ]
        can_unlock = all(c["met"] for c in conditions)

        return Response({"conditions": conditions, "can_unlock": can_unlock})


class ReportUnlockView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /reports/{id}/unlock — 잠금 해제."""

    resource = "report"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        report = models.Report.objects.get(pk=pk)

        status_view = ReportUnlockStatusView()
        status_check = status_view.retrieve(request, pk=pk).data
        if not status_check["can_unlock"]:
            raise ApiError("VALIDATION_ERROR", "잠금 해제 조건이 충족되지 않았습니다.",
                           details=status_check["conditions"])

        report.lock_status = "unlocked"
        report.unlocked_by = getattr(request.user, "staff", None)
        report.unlocked_at = timezone.now()
        report.unlock_reason = request.data.get("unlock_reason", "")
        report.updated_by = self._current_account()
        report.save()

        out = serializers.ReportSerializer(report)
        return Response(out.data)



class SpecimenBindViewSet(AuditMixin, viewsets.ViewSet):
    """§4 POST /specimens — 검체 바인딩.
    §4(병리과) GET /specimens — 전체 목록 + 필터/정렬.
    """

    resource = "specimen"
    permission_classes = [CanBindSpecimen]
    # TODO: 단독 권한 CanBindSpecimen 적용 (간호·유방외과) — permissions import 확인 후 교체

    def list(self, request):
        qs = models.Specimen.objects.select_related("patient").all()
        ordering = request.query_params.get("ordering")
        allowed = {
            "patient__name": "patient__pii_name",
            "collected_at": "collected_at",
            "accessioned_at": "accessioned_at",
            "accession_status": "accession_status",
        }
        if ordering and ordering.lstrip("-") in allowed:
            field = allowed[ordering.lstrip("-")]
            qs = qs.order_by(("-" + field) if ordering.startswith("-") else field)
        out = serializers.SpecimenSerializer(qs, many = True)
        return Response(out.data)
    
    def create(self, request):
        serializer = serializers.SpecimenBindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        specimen = models.Specimen.objects.create(
            lesion_id=data["lesion_id"],
            patient_id=models.Lesion.objects.get(pk=data["lesion_id"]).patient_id,
            specimen_label=data["specimen_label"],
            specimen_type=data["specimen_type"],
            guidance_route=data["guidance_route"],
            collected_at=data["collected_at"],
            accession_status="bound",
            bound_by=getattr(request.user, "staff", None),
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data, status=status.HTTP_201_CREATED)


class DiscordanceListView(generics.ListAPIView):
    """§1·§5 GET /discordances?patient={id}&status=open."""

    resource = "discordance_review"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.DiscordanceFlagSerializer

    def get_queryset(self):
        qs = models.DiscordanceFlag.objects.all()
        patient_id = self.request.query_params.get("patient")
        status_param = self.request.query_params.get("status")
        if patient_id:
            qs = qs.filter(lesion__patient_id=patient_id)
        if status_param == "open":
            qs = qs.filter(closed_at__isnull=True)
        return qs


class DiscordanceDisposeView(AuditMixin, viewsets.ViewSet):
    """§5 PATCH /discordances/{id}/dispose — 처분 확정."""

    resource = "discordance_review"
    permission_classes = [CanDisposeDiscordance]

    def partial_update(self, request, pk=None):
        flag = models.DiscordanceFlag.objects.get(pk=pk)
        serializer = serializers.DiscordanceDisposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        flag.disposition_type = data["disposition_type"]
        flag.disposition_reason = data["disposition_reason"]
        flag.disposed_by = getattr(request.user, "staff", None)
        flag.closed_at = timezone.now()
        flag.updated_by = self._current_account()
        flag.save()

        out = serializers.DiscordanceFlagSerializer(flag)
        return Response(out.data)
    
    def retrieve(self, request, pk=None):
        flag = models.DiscordanceFlag.objects.get(pk=pk)
        out = serializers.DiscordanceFlagSerializer(flag)
        return Response(out.data)
    
    def partial_ipdate(self, request, pk=None):
        flag = models.DiscordanceFlag.objects.get(pk=pk)
        serializer = serializers.DiscordanceDisposeSerializer(data = request.data)
        serializer.is_valid(raise_exceptioin=True)
        data = serializer.validated_data
        
        flag.disposition_type = data["disposition_type"]
        flag.disposition_reason = data["disposition_reason"]
        flag.disposed_by = getattr(request.user, "staff", None)
        flag.closed_at = timezone.now()
        flag.updated_by = self._current_account()
        flag.save()
        
        out = serializers.DiscordanceFlagSerializer(flag)
        return Response(out.data)