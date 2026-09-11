"""영상의학과(radiology) view."""

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action

from django.db.models import Q

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission
from core.api.errors import ApiError


class RadiologyDashboardView(viewsets.ViewSet):
    """§2-1 대시보드 — 큐 4개.

    GET /  (radiology 전용 dashboard 라우트로 등록)
    """

    resource = "study"
    permission_classes = [MatrixPermission]

    def list(self, request):
        촬영요청 = models.ExamOrder.objects.filter(
            order_status__in=["ordered", "accepted"], modality__in=["mammo", "us", "mri"]
        ).count()
        판독대기 = models.Study.objects.filter(
            read_status__in=["pending", "first_locked", "ai_revealed"]
        ).count()
        기권 = models.AiResult.objects.filter(abstained=True).count()
        불일치 = models.DiscordanceFlag.objects.filter(
            flag_status__in=["sev1", "sev2", "review"]
        ).count()

        return Response({
            "촬영요청": 촬영요청,
            "판독대기": 판독대기,
            "기권": 기권,
            "불일치": 불일치,
        })


class StudyViewSet(AuditMixin, viewsets.ModelViewSet):
    """§2-2~2-6 검사 조회/수정. read/first, read/ai-compare, read/assessment, final 은 @action."""

    resource = "study"
    permission_classes = [MatrixPermission]
    queryset = models.Study.objects.select_related("patient", "exam_order").all()
    serializer_class = serializers.StudySerializer

    @action(detail=True, methods=["post"], url_path="read/first")
    def read_first(self, request, pk=None):
        """§2-3 1차 판독(AI 숨김). 병변 추가 + 판정 저장."""
        study = self.get_object()

        lesion_data = request.data.get("lesion")
        if lesion_data:
            models.Lesion.objects.create(
                study=study,
                patient=study.patient,
                lesion_source="manual",
                created_by=self._current_account(),
                updated_by=self._current_account(),
                **lesion_data,
            )

        finding_note = request.data.get("finding_note", "")
        models.Assessment.objects.create(
            study=study,
            read_stage="first",
            finding_note=finding_note,
            assessed_by_id=request.data.get("assessed_by"),
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        study.read_status = "first_locked"
        study.updated_by = self._current_account()
        study.save()

        out = serializers.StudySerializer(study)
        return Response(out.data)

    @action(detail=True, methods=["post"], url_path="read/ai-compare")
    def reveal_ai(self, request, pk=None):
        """§2-4 AI 결과 대조 게이트 해제."""
        study = self.get_object()
        assessment = models.Assessment.objects.filter(
            study=study, read_stage="first"
        ).order_by("-created_at").first()
        if assessment is None:
            raise ApiError("VALIDATION_ERROR", "1차 판독이 먼저 필요합니다.")

        from django.utils import timezone
        assessment.ai_revealed_at = timezone.now()
        assessment.save()
        study.read_status = "ai_revealed"
        study.save()

        ai_results = models.AiResult.objects.filter(study=study)
        out = serializers.AiResultSerializer(ai_results, many=True)
        return Response(out.data)

    @action(detail=True, methods=["post"], url_path="read/assessment")
    def save_assessment(self, request, pk=None):
        """§2-5 소견·판정 저장."""
        study = self.get_object()
        lesion_id = request.data.get("lesion_id")

        assessment = models.Assessment.objects.filter(
            study=study, read_stage="first", lesion_id=lesion_id
        ).order_by("-created_at").first()
        if assessment is None:
            raise ApiError("VALIDATION_ERROR", "1차 판독 행을 찾을 수 없습니다.")

        assessment.category = request.data.get("category")
        assessment.recommendation = request.data.get("recommendation")
        assessment.updated_by = self._current_account()
        assessment.save()

        out = serializers.AssessmentSerializer(assessment)
        return Response(out.data)

    @action(detail=True, methods=["post"], url_path="final")
    def finalize(self, request, pk=None):
        """§2-6 FINAL 확정 — study 의 병변별 assessment 를 일괄 잠금."""
        from django.utils import timezone

        study = self.get_object()
        assessments = models.Assessment.objects.filter(study=study, read_stage="first")

        if not assessments.exists():
            raise ApiError("VALIDATION_ERROR", "확정할 판정이 없습니다.")

        now = timezone.now()
        assessments.update(finalized_at=now, updated_by=self._current_account())
        study.read_status = "finalized"
        study.updated_by = self._current_account()
        study.save()

        out = serializers.AssessmentSerializer(assessments, many=True)
        return Response(out.data)