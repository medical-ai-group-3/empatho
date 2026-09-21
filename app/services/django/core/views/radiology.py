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

from ..tasks import run_inference
from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import (
    CanCompleteExamOrder,
    CanFinalizeRadiologyRead,
    MatrixPermission,
)
from core.api.errors import ApiError


class StudyViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /studies, GET /studies/{id} — 검사(Study) 목록/단건 조회.

    ?q= 로 환자 이름·환자번호 검색, ?ordering= 으로 정렬(기본 -performed_at).
    ?status= 로 quality_status 를 명시하지 않으면 반려본(rejected)은 목록
    에서 뺀다 — 반려는 재촬영 대상이라 판독 목록에 섞이면 안 된다
    (09-18 백엔드 대조 ⑨, 지금까지 get_queryset 이 없어 검색·정렬이
    전부 장식이었고 반려본도 그대로 섞여 있었다).
    """

    resource = "study"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.StudySerializer

    ORDERING_FIELDS = {
        "performed_at": "performed_at",
        "patient_name": "patient__pii__name",
        "read_status": "read_status",
    }

    def get_queryset(self):
        qs = models.Study.objects.select_related("patient__pii")

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(quality_status=status_param)
        else:
            qs = qs.exclude(quality_status="rejected")

        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(patient__pii__name__icontains=q) |
                Q(patient__patient_number__icontains=q)
            )

        ordering = self.request.query_params.get("ordering", "-performed_at")
        field = ordering.lstrip("-")
        if field in self.ORDERING_FIELDS:
            db_field = self.ORDERING_FIELDS[field]
            qs = qs.order_by(("-" + db_field) if ordering.startswith("-") else db_field)

        return qs


class PatientStudiesView(generics.ListAPIView):
    """GET /patients/{id}/studies — 환자의 검사(Study) 목록."""

    resource = "study"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.StudySerializer

    def get_queryset(self):
        return models.Study.objects.select_related("patient__pii").filter(
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
    permission_classes = [CanCompleteExamOrder]

    def partial_update(self, request, pk=None):
        order = models.ExamOrder.objects.get(pk=pk)
        order.order_status = "completed"
        order.updated_by = self._current_account()
        order.save()
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)


class ExamOrderRetakeView(AuditMixin, viewsets.ViewSet):
    """POST /exam-orders/{id}/retake — 확정 사양서 §2-3, 재촬영 오더 발행.

    자동 트리거(품질 반려 액션 안에 얹기)가 아니라 **명시적 호출**로 둔다.
    반려 사유가 늘 「다시 찍어야 함」은 아니다 — 이미 확보한 다른 시리즈로
    커버되거나, 유방외과가 판단해 그 소견으로 진행할 수도 있다. 자동으로
    오더가 하나 더 생기면 그 경우 고아 오더를 사람이 매번 취소해야 한다.
    프론트에 이미 있는 "재촬영" 버튼이 이 경로를 부른다.

    원본 오더(pk)에 quality_status="rejected" 인 Study 가 하나도 없으면
    409 — 재촬영은 반려의 결과여야 한다.

    새 오더는 원본과 같은 환자 · modality · exam_purpose · ordered_by 를
    물려받고, order_status="ordered" 로 바로 서서 ExamOrderQueueView 의
    큐(?status=ordered&assigned=none)에 다시 뜬다 — 원무를 다시 거치지
    않는다. parent_order 로 원본을 가리킨다(모델에 있던 자리인데 지금까지
    아무도 채우지 않고 있었다).
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def create(self, request, pk=None):
        try:
            original = models.ExamOrder.objects.select_related("patient").get(pk=pk)
        except models.ExamOrder.DoesNotExist:
            raise ApiError("NOT_FOUND")

        if not original.studies.filter(quality_status="rejected").exists():
            raise ApiError("RETAKE_REQUIRES_REJECTED_QUALITY")

        account = self._current_account()
        retake = models.ExamOrder.objects.create(
            patient=original.patient,
            modality=original.modality,
            exam_purpose=original.exam_purpose,
            order_status="ordered",
            ordered_by=original.ordered_by,
            ordered_at=timezone.now(),
            parent_order=original,
            created_by=account,
            updated_by=account,
        )
        out = serializers.ExamOrderSerializer(retake)
        return Response(out.data, status=status.HTTP_201_CREATED)


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
        # 취소된(soft-delete) 파일은 업로드 목록에서 뺀다.
        objects = study.storage_objects.filter(
            deleted_at__isnull=True).order_by("series_uid")
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
    판독 화면을 열 수 없다 — 409. 품질 반려된(quality_status=rejected)
    Study 도 마찬가지로 409 — SYS-6, 재촬영 경로(POST .../retake)로
    가야 한다. errors.py 에 STUDY_REJECTED 코드는 있었는데 여태 아무도
    안 던지고 있었다.
    """

    resource = "study"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        try:
            study = models.Study.objects.get(pk=pk)
        except models.Study.DoesNotExist:
            raise ApiError("NOT_FOUND")

        if study.quality_status == "rejected":
            raise ApiError("STUDY_REJECTED")

        # 취소된(soft-delete) 파일은 「업로드된 것」으로 안 친다.
        images = study.storage_objects.filter(deleted_at__isnull=True)
        if not images.exists():
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
                images, many=True).data,
            "lesions": serializers.LesionSerializer(lesions, many=True).data,
            "latest_ai_result": (
                serializers.AiResultSerializer(latest_ai_result).data
                if latest_ai_result else None
            ),
            "current_assessment": (
                serializers.AssessmentSerializer(current_assessment).data
                if current_assessment else None
            ),
            "reports": serializers.ReportSerializer(
                            study.reports.filter(report_type="stage").order_by("socket_id"), 
                            many=True
                        ).data,
        })


class AiResultQueueView(AuditMixin, viewsets.ViewSet):
    """AI 분석 시작 · 조회.

    POST /studies/{id}/ai-results   분석 시작 (202 + 대기열 투입)
    GET  /ai-results?study={id}     run_status 폴링

    ■ 판독 한 번의 단위가 모달리티마다 다르다

        초음파   영상 한 장이 판독 한 번이다. 여러 장 찍으면 행도 여러 개
        맘모     영상 넷(좌우 × CC/MLO)이 한 검진이다. 행은 하나이고,
                워커가 네 장을 돌며 판독해 결과를 합친다
        MRI     시리즈 전체가 한 판독이다. 가리킬 파일 한 장이 없어
                source_object 를 비운다 — 워커가 검사의 저장 행에서 찾는다

    ■ source_object 를 여기서 정하는 이유

        워커는 이 칸으로 보낼 파일을 고른다(tasks.py 의 _ref). 비워 두면
        초음파·맘모는 무엇을 보낼지 몰라 failed 로 끝난다.
    """

    resource = "ai_result"
    permission_classes = [MatrixPermission]

    def start(self, request, pk=None):
        study = models.Study.objects.get(pk=pk)
        account = self._current_account()
        
        # deleted_at 이 빈 행만 본다 - 지운 파일을 다시 판독하지 않는다 
        sources = list(study.storage_objects.filter(deleted_at__isnull=True).order_by("storage_object_id"))
        
        if not sources:
            raise ApiError("VALIDATION_ERROR", "판독할 영상이 없습니다.")
        
        if study.modality == "us":
            targets = sources
        else: 
            targets = [None]
            
        results = []
        for source in targets:
            result = models.AiResult.objects.create(
                patient=study.patient,
                study=study,
                source_object=source, 
                run_status="queued",
                created_by=account,
                updated_by=account,
            )
            results.append(result)
            run_inference.delay(result.pk)

        out = serializers.AiResultSerializer(results, many=True)
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
    permission_classes = [MatrixPermission, CanFinalizeRadiologyRead]

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
    permission_classes = [MatrixPermission, CanFinalizeRadiologyRead]

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
    http_method_names = ["get", "post", "patch", "head", "options"]

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
    permission_classes = [MatrixPermission, CanFinalizeRadiologyRead]

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
