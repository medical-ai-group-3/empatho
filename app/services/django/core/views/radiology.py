"""영상의학과(radiology) view — 라우터 인계 문서(화면 설계) 기준.

① 대기 큐, ①→② 촬영 시작, ② 업로드 조회/품질승인, ③ 판독 화면
통합조회는 아래 새 뷰들이 맡는다. ③의 하위 액션(AI 활성화/임시저장/확정)과
⑤ 정정은 기존 뷰를 그대로 재사용한다.

read_stage / study.read_status 는 DB CHECK 제약(READ_STAGE=["draft","final"],
READ_STATUS=["pending","draft","finalized"])을 따른다 —
1차판독 게이트를 안 쓰므로 임시저장은 "draft", 확정은 "final" 로 쓰고,
study.read_status 는 pending → draft → finalized 로만 옮긴다.
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


class StudyViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /studies, GET /studies/{id} — 검사(Study) 목록/단건 조회."""

    resource = "study"
    permission_classes = [MatrixPermission]
    queryset = models.Study.objects.all()
    serializer_class = serializers.StudySerializer


class PatientStudiesView(generics.ListAPIView):
    """GET /patients/{id}/studies — 환자의 검사(Study) 목록."""

    resource = "study"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.StudySerializer

    def get_queryset(self):
        return models.Study.objects.filter(
            patient_id=self.kwargs["pk"]
        ).order_by("-performed_at")


class ExamOrderQueueView(generics.ListAPIView):
    """GET /radiology/queue — ① 촬영 대기 리스트.

    order_status 가 ordered·accepted 로 확정돼 modality 까지 배정됐지만
    아직 Study 가 생성되지 않은 ExamOrder 만 뽑는다. `studies` 는
    Study.exam_order 의 related_name.
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderSerializer

    def get_queryset(self):
        qs = models.ExamOrder.objects.filter(
            modality__in=["mammo", "us", "mri"]
        ).order_by("ordered_at")
        
        status_param = self.request.query_params.get("status")
        if status_param:
            qs= qs.filter(order_status=status_param)
            
        assigned_param = self.request.query_params.get("assigned")
        if assigned_param == "none":
            qs= qs.filter(assigned_to__isnull=True)
            
        return qs


class ExamOrderCompleteView(AuditMixin, viewsets.ViewSet):
    """PATCH /exam-orders/{id}/complete — 촬영/판독 완료 처리."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        order = models.ExamOrder.objects.get(pk=pk)
        order.order_status = "completed"
        order.updated_by = self._current_account()
        order.save()
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)


class StudyStartView(AuditMixin, viewsets.ViewSet):
    """POST /radiology/queue/{exam_order_id}/start-study — ①→② 촬영 시작.

    Study 를 만들어 ExamOrder 에 매단다. 이후 파일 업로드는 Go 웹훅이
    StorageObject 를 채우는 별도 경로다.
    """

    resource = "study"
    permission_classes = [MatrixPermission]

    def create(self, request, pk=None):
        try:
            exam_order = models.ExamOrder.objects.get(pk=pk)
        except models.ExamOrder.DoesNotExist:
            raise ApiError("NOT_FOUND")

        account = self._current_account()
        study = models.Study.objects.create(
            patient=exam_order.patient,
            exam_order=exam_order,
            modality=exam_order.modality,
            created_by=account,
            updated_by=account,
        )
        out = serializers.StudySerializer(study)
        return Response(out.data, status=status.HTTP_201_CREATED)


class StudyUploadView(AuditMixin, viewsets.ViewSet):
    """GET/PATCH /radiology/studies/{id}/upload — ② 업로드 조회 · 품질 승인/반려."""

    resource = "study"
    permission_classes = [MatrixPermission]

    def _get_study(self, pk):
        try:
            return models.Study.objects.get(pk=pk)
        except models.Study.DoesNotExist:
            raise ApiError("NOT_FOUND")

    def retrieve(self, request, pk=None):
        study = self._get_study(pk)
        objects = study.storage_objects.all().order_by("series_uid")
        return Response({
            "study": serializers.StudySerializer(study).data,
            "storage_objects": serializers.StorageObjectSerializer(objects, many=True).data,
        })

    def partial_update(self, request, pk=None):
        study = self._get_study(pk)
        serializer = serializers.StudyUploadReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        study.quality_status = serializer.validated_data["quality_status"]
        study.updated_by = self._current_account()
        study.save()

        out = serializers.StudySerializer(study)
        return Response(out.data)


class StudyReadView(viewsets.ViewSet):
    """GET /radiology/studies/{id}/read — ③ 판독 화면 통합조회.

    Study + 병변 목록 + 최신 AiResult + 진행중(1차) Assessment 를 한 번에
    묶어서 준다. 업로드된 원본이 하나도 없으면(StorageObject 없음) 아직
    판독 화면을 열 수 없다 — 409.
    """

    resource = "study"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        try:
            study = models.Study.objects.get(pk=pk)
        except models.Study.DoesNotExist:
            raise ApiError("NOT_FOUND")

        if not study.storage_objects.exists():
            raise ApiError("STUDY_NOT_READ_READY")

        lesions = study.lesions.all()
        latest_ai_result = study.ai_results.order_by("-created_at").first()
        current_assessment = (
            study.assessments.filter(read_stage="draft")
            .order_by("-created_at")
            .first()
        )

        return Response({
            "study": serializers.StudySerializer(study).data,
            "images": serializers.StorageObjectSerializer(
                study.storage_objects.all(), many=True).data,
            "lesions": serializers.LesionSerializer(lesions, many=True).data,
            "latest_ai_result": (
                serializers.AiResultSerializer(latest_ai_result).data
                if latest_ai_result else None
            ),
            "current_assessment": (
                serializers.AssessmentSerializer(current_assessment).data
                if current_assessment else None
            ),
        })


class AiResultQueueView(AuditMixin, viewsets.ViewSet):
    """AI 분석 시작/조회.

    POST /studies/{id}/ai-results   분석 시작 (즉시 202 + 작업 등록)
    GET  /ai-results?study={id}     run_status 폴링

    현재 start() 는 AiResult 행만 만들고 실제 작업 대기열(Celery 등)에는
    등록하지 않는다. run_status="queued" 인 채로 행이 남는 것은 워커 연동
    전까지의 의도된 임시 상태다 — running/done/failed 로의 전이는 아직
    아무 코드도 하지 않는다.
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
        # TODO: Celery task 등록 필요 — 지금은 여기서 대기열에 넣는 코드가
        # 전혀 없어 이 행이 running 으로 못 넘어간다. 워커 연동 전까지는
        # run_status="queued" 로 남는 게 정상(의도된 상태)이다.

        out = serializers.AiResultSerializer(result)
        return Response(out.data, status=status.HTTP_202_ACCEPTED)


# views/radiology.py 의 AiResultListView 수정
class AiResultListView(viewsets.ViewSet):
    """GET /ai-results?study={id} 또는 ?specimen={id}

    검체/검사 전체의 통합 진행 상태를 하나로 돌려준다.
    {"status": "queued"|"running"|"done"|"failed", "pct": 0~100}
    """

    resource = "ai_result"
    permission_classes = [MatrixPermission]

    def list(self, request):
        qs = models.AiResult.objects.all()
        study_id = request.query_params.get("study")
        specimen_id = request.query_params.get("specimen")

        if study_id:
            qs = qs.filter(study_id=study_id)
        if specimen_id:
            qs = qs.filter(source_object__specimen_id=specimen_id)

        results = list(qs)
        if not results:
            return Response({"status": "queued", "pct": 0})

        total = len(results)
        done = sum(1 for r in results if r.run_status == "done")
        failed = sum(1 for r in results if r.run_status == "failed")
        running = sum(1 for r in results if r.run_status == "running")

        if failed > 0:
            overall = "failed"
        elif done == total:
            overall = "done"
        elif running > 0 or done > 0:
            overall = "running"
        else:
            overall = "queued"

        pct = int((done / total) * 100) if total else 0

        return Response({"status": overall, "pct": pct})


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
    
    def get_queryset(self):
        qs= super().get_queryset()
        patient_id = self.request.query_params.get("patient")
        if patient_id:
            qs = qs.filter(patient_id = patient_id)
        return qs


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
    
class ExamOrderAssignView(AuditMixin, viewsets.ViewSet):
    """PATCH /exam-orders/{id}/assign — 집기. 동시 집기는 409."""
    
    resource = "exam_order"
    permission_classes = [MatrixPermission]
    
    def partial_update(self, request, pk=None):
        staff = getattr(request.user, "staff", None)
        if staff is None:
            raise ApiError("VALIDATION_ERROR", "의료진 계정이 아닙니다")
        
        updated = models.ExamOrder.objects.filter(
            pk=pk, assigned_to__isnull=True
        ).update(assigned_to=staff, updated_by=self._current_account())
        
        if updated == 0:
            raise ApiError("ALREADY_ASSIGNED", "다른 선생님이 이미 맡았습니다.")
        
        order = models.ExamOrder.objects.get(pk=pk)
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)
    