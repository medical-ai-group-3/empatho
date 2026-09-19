"""유방외과(surgery) view — 2026-09-14 화면명세 기준."""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.db.models import Q
from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin, CanDisposeDiscordance
from core.api.errors import ApiError
from core.api.permissions import CanBindSpecimen, CanDecideAssessment, CanUnlockReport


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
            order_note = data.get("order_note", ""),
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
            events.append({
                "at": assessment.created_at, "type": "판독", "detail": assessment.category,
                "assessment_id": assessment.assessment_id,
            })

        for specimen in models.Specimen.objects.filter(patient=patient):
            if specimen.collected_at:
                events.append({"at": specimen.collected_at, "type": "검체 채취", "detail": specimen.specimen_label})
            if specimen.finalized_at:
                events.append({"at": specimen.finalized_at, "type": "병리 확진", "detail": specimen.diagnosis})

        events.sort(key=lambda e: e["at"])
        return Response(events)


class SurgeryReportViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """§2·§3 GET/PUT /reports/{id}, GET /reports?patient=&type=final."""

    resource = "report"
    permission_classes = [MatrixPermission]
    queryset = models.Report.objects.all()
    serializer_class = serializers.ReportSerializer
    
    def owned_queryset(self, queryset, account):
        return queryset.filter(patient__account=account, lock_status="unlocked")
    
    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id

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
        incoming = request.data.get("content_json")
        if incoming is not None:
            if not isinstance(incoming, dict):
                raise ApiError("VALIDATION_ERROR", "content_json은 객체여야 합니다.")

            current = report.content_json if isinstance(report.content_json, dict) else {}
            merged = {**current, **incoming}
            current_by_modality = current.get("by_modality")
            incoming_by_modality = incoming.get("by_modality")
            if isinstance(current_by_modality, dict) or isinstance(incoming_by_modality, dict):
                merged["by_modality"] = {
                    **(current_by_modality if isinstance(current_by_modality, dict) else {}),
                    **(incoming_by_modality if isinstance(incoming_by_modality, dict) else {}),
                }
            report.content_json = merged
        report.updated_by = self._current_account()
        report.save()
        out = serializers.ReportSerializer(report)
        return Response(out.data)
    
    def retrieve(self, request, *args, **kwargs):
        report = self.get_object()
        if report.last_viewed_at is None:
            report.last_viewed_at = timezone.now()
            report.last_viewed_by = getattr(request.user, "staff", None)
            report.view_count = (report.view_count or 0) + 1
            report.save()
        else:
            report.view_count = (report.view_count or 0) + 1
            report.last_viewed_at = timezone.now()
            report.save()
        out = serializers.ReportSerializer(report)
        return Response(out.data)


class SurgeryDecisionView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /assessments/{id}/decision — 수술 여부·사유(decision_*)."""

    permission_classes = [CanDecideAssessment]

    def partial_update(self, request, pk=None):
        serializer = serializers.SurgeryDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            assessment = models.Assessment.objects.get(pk=pk)
        except models.Assessment.DoesNotExist:
            raise ApiError("NOT_FOUND")

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
    permission_classes = [MatrixPermission, CanUnlockReport]

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
        
        from .. import notify
        notify.send(
            patient=report.patient, 
            type="report_ready",
            message="검사 결과가 도착했습니다. 앱에서 확인해 주세요.", 
            ref_type="report",
            ref_id=report.pk
        )

        out = serializers.ReportSerializer(report)
        return Response(out.data)



class SpecimenBindViewSet(AuditMixin, viewsets.ViewSet):
    """§4 POST /specimens — 검체 바인딩.
    §4(병리과) GET /specimens — 전체 목록 + 필터/정렬.
    """

    resource = "specimen_pathology"

    def get_permissions(self):
        if self.action == "create":
            return [CanBindSpecimen()]
        return [MatrixPermission()]
    
    def list(self, request):
        qs = models.Specimen.objects.select_related("patient__pii").all()
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
    
    def retrieve(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)

class SpecimenUploadListView(viewsets.ViewSet):
    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        objects = models.StorageObject.objects.filter(specimen=specimen)
        out = serializers.StorageObjectSerializer(objects, many=True)
        return Response({"specimen_id": specimen.specimen_id, "uploads": out.data})

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
