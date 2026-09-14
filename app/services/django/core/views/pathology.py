"""병리과(pathology) view — 2026-09-14 화면명세 기준.

주의: specimen.assigned_to, specimen.clinical_note, specimen.amend_history,
report.viewed_by 는 아직 마이그레이션이 안 와서 assign/amend 는 컬럼이
생기기 전까지 AttributeError 가 날 수 있다.
"""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission
from core.api.errors import ApiError


class SpecimenQueueView(generics.ListAPIView):
    """§1 GET /specimens?status=bound&assigned=none — 접수 대기 목록."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.SpecimenSerializer

    def get_queryset(self):
        qs = models.Specimen.objects.all().order_by("collected_at")

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(accession_status=status_param)

        # TODO: specimen.assigned_to 컬럼 추가되면 활성화
        # assigned_param = self.request.query_params.get("assigned")
        # if assigned_param == "none":
        #     qs = qs.filter(assigned_to__isnull=True)

        return qs


class SpecimenAssignView(AuditMixin, viewsets.ViewSet):
    """§1 PATCH /specimens/{id}/assign — 집기. 동시 집기는 409.

    TODO: specimen.assigned_to 컬럼 마이그레이션 대기 중. 컬럼 생기면
    조건부 UPDATE 로 교체할 것 (영상의학과 ExamOrderAssignView 참고).
    """

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        raise ApiError("INTERNAL_ERROR", "assigned_to 컬럼 마이그레이션 대기 중입니다.")


class SpecimenAiResultView(AuditMixin, viewsets.ViewSet):
    """§2 POST /specimens/{id}/ai-results — 분석 시작. 올린 크롭마다 1행."""

    resource = "ai_result"
    permission_classes = [MatrixPermission]

    def start(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        results = []
        for storage_object in models.StorageObject.objects.filter(specimen=specimen):
            result = models.AiResult.objects.create(
                patient=specimen.patient,
                source_object=storage_object,
                run_status="queued",
                created_by=self._current_account(),
                updated_by=self._current_account(),
            )
            results.append(result)
            # TODO: Celery task 등록 — run_status queued → running → done/failed

        out = serializers.AiResultSerializer(results, many=True)
        return Response(out.data, status=status.HTTP_202_ACCEPTED)


class SpecimenDraftView(AuditMixin, viewsets.ViewSet):
    """§3 PUT /specimens/{id}/draft — 임시저장(덮어쓰기)."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def update(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        serializer = serializers.SpecimenDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        specimen.b_category = data.get("b_category", specimen.b_category)
        specimen.diagnosis = data.get("diagnosis", specimen.diagnosis)
        specimen.finding_note = data.get("finding_note", specimen.finding_note)
        specimen.reported_by = getattr(request.user, "staff", None)
        specimen.updated_by = self._current_account()
        specimen.save()

        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)


class SpecimenFinalizeView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /specimens/{id}/finalize — 확진 확정. finalized_at 을 찍는다."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        serializer = serializers.SpecimenFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        specimen.b_category = data["b_category"]
        specimen.diagnosis = data["diagnosis"]
        specimen.finding_note = data.get("finding_note", "")
        specimen.reported_by = getattr(request.user, "staff", None)
        specimen.finalized_at = timezone.now()
        specimen.updated_by = self._current_account()
        specimen.save()

        # TODO: 자동 대조(discordance) 로직 트리거 — 영상 최종 판정과 비교

        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)

