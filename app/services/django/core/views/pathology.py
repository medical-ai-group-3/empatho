"""병리과(pathology) view — 2026-09-14 화면명세 기준.

확정 사양서 §8-2: 병리 결과 정정 경로를 두지 않는다 — 확정 후 오류는
새 검체로 처리한다. POST /specimens/{id}/amend 는 만들지 않는다(예전
초안엔 있었으나 무효).
"""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.utils import timezone

from ..tasks import run_inference
from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, CanFinalizePathologyRead
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

        assigned_param = self.request.query_params.get("assigned")
        if assigned_param == "none":
            qs = qs.filter(assigned_to__isnull=True)

        return qs


class SpecimenAssignView(AuditMixin, viewsets.ViewSet):
    """§1 PATCH /specimens/{id}/assign — 집기. 동시 집기는 409."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        staff = getattr(request.user, "staff", None)
        if staff is None:
            raise ApiError("VALIDATION_ERROR", "의료진 계정이 아닙니다.")

        updated = models.Specimen.objects.filter(
            pk=pk, assigned_to__isnull=True
        ).update(assigned_to=staff, updated_by=self._current_account())

        if updated == 0:
            raise ApiError("ALREADY_ASSIGNED", "다른 선생님이 이미 맡았습니다.")

        specimen = models.Specimen.objects.get(pk=pk)
        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)

class SpecimenAiResultView(AuditMixin, viewsets.ViewSet):
    """§2 POST /specimens/{id}/ai-results — 분석 시작. 올린 크롭마다 1행."""

    resource = "ai_result"
    permission_classes = [MatrixPermission]

    def start(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        results = []
        for storage_object in models.StorageObject.objects.filter(specimen=specimen):
            # 크롭 한 장이 판독 한 번이다.
            #
            # specimen 을 반드시 채운다 — ai_result_owner_ck 가 study·specimen
            # 중 **정확히 하나**를 요구한다. 둘 다 비우면 행을 만드는 순간
            # 제약 위반으로 500 이 난다. 병리는 검사가 없고 검체에 매달리며,
            # 워커도 study_id 가 비어 있으면 병리로 본다(tasks.py run_inference).
            result = models.AiResult.objects.create(
                patient=specimen.patient,
                specimen=specimen,
                source_object=storage_object,
                run_status="queued",
                created_by=self._current_account(),
                updated_by=self._current_account(),
            )
            results.append(result)
            run_inference.delay(result.pk)
        out = serializers.AiResultSerializer(results, many=True)
        return Response(out.data, status=status.HTTP_202_ACCEPTED)


class SpecimenDraftView(AuditMixin, viewsets.ViewSet):
    """§3 PUT /specimens/{id}/draft — 임시저장(덮어쓰기)."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission, CanFinalizePathologyRead]

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
    permission_classes = [MatrixPermission, CanFinalizePathologyRead]

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