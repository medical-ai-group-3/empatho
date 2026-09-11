"""영상의학과(radiology) view — 2026-09-11 화면명세 기준.

주의: exam_order.assigned_to, report.viewed_at/viewed_by 는 마이그레이션
0013 이 와야 실제 컬럼이 생긴다. 그 전까지 assign/complete/report 열람
기록 기능은 AttributeError 가 날 수 있다.
"""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Q
from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission
from core.api.errors import ApiError


class ExamOrderQueueView(generics.ListAPIView):
    """대기 큐. GET /exam-orders?status=ordered&assigned=none"""

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderSerializer

    def get_queryset(self):
        qs = models.ExamOrder.objects.filter(
            modality__in=["mammo", "us", "mri"]
        ).order_by("ordered_at")

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(order_status=status_param)

        assigned_param = self.request.query_params.get("assigned")
        if assigned_param == "none":
            qs = qs.filter(assigned_to__isnull=True)

        return qs


class ExamOrderAssignView(AuditMixin, viewsets.ViewSet):
    """PATCH /exam-orders/{id}/assign — 집기. 동시 집기는 409."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        # 조건부 UPDATE — assigned_to 가 이미 채워진 행은 갱신 안 됨.
        staff = getattr(request.user, "staff", None)
        if staff is None:
            raise ApiError("VALIDATION_ERROR", "의료진 계정이 아닙니다.")

        updated = models.ExamOrder.objects.filter(
            pk=pk, assigned_to__isnull=True
        ).update(assigned_to=staff, updated_by=self._current_account())

        if updated == 0:
            raise ApiError("ALREADY_ASSIGNED", "다른 선생님이 이미 맡았습니다.")

        order = models.ExamOrder.objects.get(pk=pk)
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)


class ExamOrderCompleteView(AuditMixin, viewsets.ViewSet):
    """PATCH /exam-orders/{id}/complete — 영상 품질 승인 → AI 분석 시작."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        order = models.ExamOrder.objects.get(pk=pk)
        order.order_status = "completed"
        order.updated_by = self._current_account()
        order.save()

        # TODO: Celery 로 AI 분석 작업 등록 (POST /studies/{id}/ai-results 트리거)

        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)


class AiResultQueueView(AuditMixin, viewsets.ViewSet):
    """AI 분석 시작/조회.

    POST /studies/{id}/ai-results   분석 시작 (즉시 202 + 작업 등록)
    GET  /ai-results?study={id}     run_status 폴링
    """

    resource = "ai_result"
    permission_classes = [MatrixPermission]

    def start(self, request, pk=None):
        study = models.Study.objects.get(pk=pk)
        result = models.AiResult.objects.create(
            patient=study.patient,
            study=study,
            run_status="queued",
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        # TODO: Celery task 등록 — run_status 를 running → done/failed 로 갱신

        out = serializers.AiResultSerializer(result)
        return Response(out.data, status=status.HTTP_202_ACCEPTED)


class AiResultListView(generics.ListAPIView):
    """GET /ai-results?study={id}"""

    resource = "ai_result"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.AiResultSerializer

    def get_queryset(self):
        qs = models.AiResult.objects.all().order_by("-created_at")
        study_id = self.request.query_params.get("study")
        if study_id:
            qs = qs.filter(study_id=study_id)
        return qs


class StudyViewSet(AuditMixin, viewsets.ModelViewSet):
    """GET /studies, GET /studies/{id} — 목록 + 필터/정렬."""

    resource = "study"
    permission_classes = [MatrixPermission]
    queryset = models.Study.objects.select_related("patient", "exam_order").all()
    serializer_class = serializers.StudySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        ordering = self.request.query_params.get("ordering")
        allowed = {
            "patient__name": "patient__pii__name",
            "performed_at": "performed_at",
            "read_status": "read_status",
            "modality": "modality",
        }
        if ordering and ordering.lstrip("-") in allowed:
            field = allowed[ordering.lstrip("-")]
            qs = qs.order_by(("-" + field) if ordering.startswith("-") else field)
        return qs


class AssessmentDraftView(AuditMixin, viewsets.ViewSet):
    """PUT /studies/{id}/assessment/draft — 임시저장(덮어쓰기)."""

    resource = "assessment"
    permission_classes = [MatrixPermission]

    def update(self, request, pk=None):
        study = models.Study.objects.get(pk=pk)
        serializer = serializers.AssessmentDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        assessment, _ = models.Assessment.objects.update_or_create(
            study=study, read_stage="draft", lesion_id=data.get("lesion_id"),
            defaults={
                "finding_note": data.get("finding_note", ""),
                "category": data.get("category"),
                "assessed_by": getattr(request.user, "staff", None),
                "updated_by": self._current_account(),
            },
        )
        study.read_status = "draft"
        study.updated_by = self._current_account()
        study.save()

        out = serializers.AssessmentSerializer(assessment)
        return Response(out.data)


class StudyFinalizeView(AuditMixin, viewsets.ViewSet):
    """PATCH /studies/{id}/finalize — 판독 확정."""

    resource = "study"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        study = models.Study.objects.get(pk=pk)
        drafts = models.Assessment.objects.filter(study=study, read_stage="draft")

        if not drafts.exists():
            raise ApiError("VALIDATION_ERROR", "확정할 판정이 없습니다.")

        drafts.update(read_stage="final", finalized_at=timezone.now(),
                      updated_by=self._current_account())
        study.read_status = "finalized"
        study.updated_by = self._current_account()
        study.save()

        finals = models.Assessment.objects.filter(study=study, read_stage="final")
        out = serializers.AssessmentSerializer(finals, many=True)
        return Response(out.data)


class LesionViewSet(AuditMixin, viewsets.ModelViewSet):
    """POST /lesions (manual), PATCH /lesions/{id} (오탐 표시)."""

    resource = "lesion"
    permission_classes = [MatrixPermission]
    queryset = models.Lesion.objects.all()
    serializer_class = serializers.LesionSerializer

    def create(self, request, *args, **kwargs):
        serializer = serializers.LesionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        study = models.Study.objects.get(pk=serializer.validated_data["study_id"])

        lesion = models.Lesion.objects.create(
            study=study,
            patient=study.patient,
            lesion_source="manual",
            detail=serializer.validated_data.get("detail"),
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.LesionSerializer(lesion)
        return Response(out.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        lesion = self.get_object()
        serializer = serializers.LesionFalsePositiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lesion.is_false_positive = serializer.validated_data["is_false_positive"]
        lesion.updated_by = self._current_account()
        lesion.save()
        out = serializers.LesionSerializer(lesion)
        return Response(out.data)


class AssessmentHistoryView(generics.ListAPIView):
    """GET /assessments?study={id} — superseded_by 체인을 따라 이력 전체."""

    resource = "assessment"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.AssessmentSerializer

    def get_queryset(self):
        qs = models.Assessment.objects.all().order_by("-created_at")
        study_id = self.request.query_params.get("study")
        if study_id:
            qs = qs.filter(study_id=study_id)
        return qs


class AssessmentAmendView(AuditMixin, viewsets.ViewSet):
    """POST /assessments/{id}/amend — 정정. 새 행 생성 + 옛 행 superseded_by."""

    resource = "assessment"
    permission_classes = [MatrixPermission]

    def create(self, request, pk=None):
        old = models.Assessment.objects.get(pk=pk)
        serializer = serializers.AssessmentAmendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        account = self._current_account()
        new = models.Assessment.objects.create(
            study=old.study,
            lesion=old.lesion,
            read_stage="final",
            category=data["category"],
            finding_note=data["finding_note"],
            decision_reason=data["decision_reason"],
            assessed_by=getattr(request.user, "staff", None),
            finalized_at=timezone.now(),
            created_by=account,
            updated_by=account,
        )
        old.superseded_by = new
        old.updated_by = account
        old.save()

        out = serializers.AssessmentSerializer(new)
        return Response(out.data, status=status.HTTP_201_CREATED)


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /reports/{id} — 최초 열람 시 viewed_at 자동 기록."""

    resource = "report"
    permission_classes = [MatrixPermission]
    queryset = models.Report.objects.all()
    serializer_class = serializers.ReportSerializer

    def retrieve(self, request, *args, **kwargs):
        report = self.get_object()
        if report.viewed_at is None:
            report.viewed_at = timezone.now()
            report.viewed_by = getattr(request.user, "staff", None)
            report.save()
        out = serializers.ReportSerializer(report)
        return Response(out.data)