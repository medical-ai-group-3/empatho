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

from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone

from ..tasks import run_inference
from .. import models, serializers, viewed
from ..serializers.surgery import mesh_spec
from ..mixins import AuditMixin
from core.api.permissions import (
    CanCompleteExamOrder,
    CanFinalizeRadiologyRead,
    MatrixPermission,
)
from core.api.errors import ApiError
from core.services import birads as birads_rules
from core.api import tickets


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
        # image_count 는 행마다 세면 N+1 이라 여기서 한 번에 얹는다.
        # 부르는 쪽이 「판독으로 보낼까 업로드로 보낼까」를 이 값으로 가른다
        # (serializers/radiology.py 의 get_image_count 참고).
        qs = models.Study.objects.select_related("patient__pii").annotate(
            image_count=Count(
                "storage_objects",
                filter=Q(storage_objects__deleted_at__isnull=True),
                distinct=True,
            ),
            ai_status=_latest_ai_status(),
            # 목록의 「유방외과 열람」 칸 — core/viewed.py
            viewed_at=viewed.last_seen("study"),
        )

        # ?patient= 은 한 환자의 검사만 본다. 없으면 조용히 전체가 나와서
        # 부르는 쪽이 남의 환자 검사를 자기 것으로 읽는다 — 09-23 에 그랬다.
        patient = self.request.query_params.get("patient")
        if patient:
            if not str(patient).isdigit():
                raise ApiError("VALIDATION_ERROR", "patient 는 숫자여야 합니다.")
            qs = qs.filter(patient_id=int(patient))

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
            desc = ordering.startswith("-")
            # ⚠ **빈 칸을 맨 앞에 두지 않는다.** Postgres 는 DESC 에서 NULL 을
            #   먼저 놓는다 — 그냥 두면 시각을 모르는 검사가 목록 맨 위에
            #   서고, 부르는 쪽은 맨 앞을 «이번 검사»로 읽는다.
            #   촬영 시작이 이 칸을 채우고 0022 가 옛 행을 백필했지만,
            #   그 전후로 손으로 들어온 행까지 보장되지는 않는다.
            expr = F(db_field).desc(nulls_last=True) if desc else F(db_field).asc(nulls_last=True)
            qs = qs.order_by(expr, "-study_id")

        return qs


class PatientStudiesView(generics.ListAPIView):
    """GET /patients/{id}/studies — 환자의 검사(Study) 목록."""

    resource = "study"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.StudySerializer

    def get_queryset(self):
        return models.Study.objects.select_related("patient__pii").annotate(
            image_count=Count(
                "storage_objects",
                filter=Q(storage_objects__deleted_at__isnull=True),
                distinct=True,
            ),
        ).filter(
            patient_id=self.kwargs["pk"]
        ).order_by(F("performed_at").desc(nulls_last=True), "-study_id")


def _latest_ai_status():
    """이 검사의 **가장 최근** AI 실행 상태(queued · running · done · failed).
    한 번도 안 돌렸으면 None. 목록에서 한 번의 서브쿼리로 얹는다 —
    줄마다 /ai-results 를 부르면 N+1 이다(09-27, 영상 홈이 「AI 분석 중」 과
    「소견 대기」를 가르려고 쓴다)."""
    latest = models.AiResult.objects.filter(study=OuterRef("pk")).order_by(
        "-created_at", "-ai_result_id").values("run_status")[:1]
    return Subquery(latest)


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
        # ⚠ **주석이 말하던 조건이 코드에 없었다**(09-23). 「아직 Study 가
        #   생성되지 않은 오더만」이라고 적혀 있는데 거르는 줄이 없어서,
        #   start-study 를 부른 오더가 큐에 그대로 남았다. start-study 는
        #   assigned_to 도 order_status 도 안 건드리기 때문에, 집기(assign)
        #   없이 촬영만 시작한 경로가 생기면 그 오더는 영영 큐에 남는다.
        #   재촬영 오더는 새 행이라 studies 가 비어 있어 그대로 올라온다.
        qs = models.ExamOrder.objects.select_related(
            "patient__pii", "patient__primary_staff", "ordered_by", "handed_to",
        ).filter(
            modality__in=["mammo", "us", "mri"]
        ).filter(studies__isnull=True).order_by("ordered_at")
        
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
        # ⚠ .get() 이면 없는 번호가 DoesNotExist → 500 이었다
        order = models.ExamOrder.objects.filter(pk=pk).first()
        if order is None:
            raise ApiError("NOT_FOUND", "오더를 찾을 수 없습니다.")
        if order.order_status == "completed":
            # 두 번 눌러도 같은 결과 — 연타 · 재시도가 오류로 떨어지지 않게
            return Response(serializers.ExamOrderSerializer(order).data)
        # 09-28 — 유방외과 「진료 완료」는 검사 칸(modality · exam_purpose ·
        # ordered_by)이 빈 **방문 오더**를 닫는다. DB 제약
        # (exam_order_requested_fields_ck)은 그런 행을 visited_at 이 있을 때만
        # completed 로 받는다 — 예전에는 여기서 걸러 주지 않아 제약 위반이
        # IntegrityError → 500 「서버에서 처리하지 못했습니다」로 떨어졌다.
        # 취소된 오더 · 안 온 예약은 닫을 대상이 아니다.
        confirmed = (order.modality and order.exam_purpose
                     and order.ordered_by_id is not None)
        if order.order_status == "cancelled" or (not confirmed and order.visited_at is None):
            raise ApiError("COMPLETE_NOT_ALLOWED")
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

        # 같은 오더로 두 번 들어오면 **있는 것을 돌려준다.**
        # 전에는 부를 때마다 행이 하나씩 더 생겼다 — 두 사람이 같이 눌렀거나
        # 새로고침으로 다시 들어오면 고아 Study 가 남고, 업로드·판독이
        # 어느 쪽 id 로 갈지가 누른 순서에 달렸다. 오더 하나에 검사 하나다
        # (다시 찍는 것은 새 오더를 만드는 /retake 경로다).
        # ⚠ **아무 거나 고르면 안 된다.** 전에 행이 여러 개 쌓인 오더가 있고,
        #   영상은 그중 한 행에만 달려 있다. 빈 행을 돌려주면 부르는 쪽이
        #   영영 업로드 화면으로만 간다 — 영상이 붙은 행을 먼저 고르고,
        #   없으면 최신 행으로 간다.
        pool = exam_order.studies.annotate(image_count=Count(
            "storage_objects",
            filter=Q(storage_objects__deleted_at__isnull=True),
            distinct=True,
        ))
        # 품질 반려된 것은 뒤로 미룬다 — 그걸 돌려주면 판독이 409
        # STUDY_REJECTED 로 떨어진다. 다만 그것밖에 없으면 그대로 준다.
        # **새로 만들지는 않는다** — 다시 찍는 것은 /retake 가 새 오더를
        # 만드는 일이고, 여기서 행을 더 만들면 고아가 쌓인다.
        existing = (pool.exclude(quality_status="rejected")
                    .order_by("-image_count", "-study_id").first()
                    or pool.order_by("-study_id").first())
        if existing is not None:
            # 만든 것이 아니라 **있던 것**이라 200 이다.
            return Response(serializers.StudySerializer(existing).data)

        account = self._current_account()
        # ⚠ **촬영 시각을 여기서 찍는다.** 이 호출이 곧 「촬영 시작」이다.
        #   아무도 안 채우고 있었다(09-23 기준 검사 36 건 전부 NULL) —
        #   읽는 곳은 넷이나 된다: 목록 정렬(-performed_at), 나이 계산,
        #   타임라인의 「촬영」 줄, 그리고 유방외과 뷰어의 모달리티 탭.
        #   비어 있으면 뷰어가 「촬영한 검사가 없습니다」로 남는다.
        study = models.Study.objects.create(
            patient=exam_order.patient,
            exam_order=exam_order,
            modality=exam_order.modality,
            performed_at=timezone.now(),
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
        # 번호순으로 준다 — 초음파 병변 이름(US-n)의 n 이 이 순서의 몇째 장이다
        images = study.storage_objects.filter(
            deleted_at__isnull=True).order_by("storage_object_id")
        if not images.exists():
            raise ApiError("STUDY_NOT_READ_READY")

        lesions = study.lesions.all()
        latest_ai_result = study.ai_results.order_by("-created_at").first()
        # 초음파는 영상 한 장이 판독 한 번이라(AiResultQueueView.start) 한
        # 검사에 AiResult 가 여럿이다. latest_ai_result 하나만 주면 마지막에
        # 끝난 장의 결과가 모든 장에 겹쳐 그려진다. 전부 준다 — 화면은
        # ai_results[].source_object 와 images[].storage_object_id 를 맞춰
        # 고른다. latest_ai_result 는 옛 화면을 위해 그대로 둔다.
        ai_results = study.ai_results.order_by("-created_at", "-ai_result_id")
        current_assessment = (
            study.assessments.filter(read_stage="draft")
            .order_by("-created_at")
            .first()
        )
        
        
        # 뷰어가 쓸 주소. DICOM 은 Orthanc 에만 있어 Garage 경로가 없다
        # (internal.py 의 「Orthanc 저장이 확인되면 키를 비운다」와 짝).
        # 모달리티마다 이름만 다르고 내용은 같다 — 시리즈 인스턴스 목록과
        # 그 인스턴스를 하나씩 받을 기준 주소다.
        extra = {}
        series_id = next((o.orthanc_series_id for o in images if o.orthanc_series_id),None)
        if series_id:
            token, _claims, _exp = tickets.issue(
                "tile", "study", study.pk, patient_id=str(study.patient_id)
            )
            manifest = f"/svc/v1/dicom/series/{series_id}/instances?ticket={token}"
            base = "/svc/v1/dicom/instances"
            if study.modality == "mri":
                extra = {"volume_manifest": manifest, "volume_base": base}
            else:
                # 맘모와 **초음파**가 같은 모양이다 — 한 시리즈를 한 장씩
                # 넘겨 보는 더미다. MRI 만 단면 재구성(volume)이 필요하다.
                #
                # ⚠ 전에는 맘모만 주소를 받았다. 초음파는 아무 것도 못 받아
                #   뷰어가 열 길이 없었고, 화면은 DICOM 원본(sop) 주소를
                #   <img> 에 그대로 넣고 있었다 — Orthanc 가 돌려주는 것은
                #   Part-10 파일이라 브라우저가 못 푼다. 그래서 초음파는
                #   어느 화면에서도 한 장도 안 떴다(09-23 확인).
                extra = {"stack_manifest": manifest, "stack_base": base}

        # MRI 3D 뷰어 왼쪽의 몸 · 유방 메시 — 최신 판독이 올린 파생물 JSON
        if study.modality == "mri" and latest_ai_result:
            imgs = {i.kind: i for i in latest_ai_result.images.filter(
                kind__in=("mesh_body", "mesh_breast"), deleted_at__isnull=True
            ).order_by("image_id")}
            extra["anatomy_meshes"] = {
                "body": mesh_spec(imgs.get("mesh_body"), study.pk),
                "breast": mesh_spec(imgs.get("mesh_breast"), study.pk),
            }

        return Response({
            "study": serializers.StudySerializer(study).data,
            "images": serializers.StorageObjectSerializer(
                images, many=True).data,
            "lesions": serializers.LesionSerializer(lesions, many=True).data,
            "latest_ai_result": (
                serializers.AiResultSerializer(latest_ai_result).data
                if latest_ai_result else None
            ),
            "ai_results": serializers.AiResultSerializer(
                ai_results, many=True).data,
            "current_assessment": (
                serializers.AssessmentSerializer(current_assessment).data
                if current_assessment else None
            ),
            "reports": serializers.ReportSerializer(
                            study.reports.filter(report_type="stage").order_by("socket_id"), 
                            many=True
                        ).data,
            **extra, 
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

        # 상태만 폴링하던 기존 응답은 병리 조직 마스크의 실제 주소를
        # 화면에 전달하지 못했다. 결과 JSON 안의 mask 스텁(object_key)을
        # 함께 내려 주되, 기존 status/pct 계약은 그대로 유지한다.
        out = serializers.AiResultSerializer(results, many=True).data
        return Response({"status": overall, "pct": pct, "results": out})


class AssessmentDraftView(AuditMixin, viewsets.ViewSet):
    """PUT /studies/{id}/assessment/draft — 임시저장(덮어쓰기)."""

    resource = "assessment"
    permission_classes = [MatrixPermission, CanFinalizeRadiologyRead]

    def update(self, request, pk=None):
        study = models.Study.objects.get(pk=pk)
        serializer = serializers.AssessmentDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # MRI 는 4 만, 맘모 · 초음파는 4a~4c 만 — services/birads.py
        birads_rules.validate_for_study(study, data.get("category"))

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
        # 규칙이 생기기 전에 저장된 임시저장(예: MRI 4b)이 그대로 final 로
        # 올라가지 않게 확정 때 한 번 더 본다
        for d in drafts:
            birads_rules.validate_for_study(study, d.category)

        drafts.update(read_stage="final", finalized_at=timezone.now(),
                      updated_by=self._current_account())
        study.read_status = "finalized"
        study.updated_by = self._current_account()
        study.save()

        finals = models.Assessment.objects.filter(study=study, read_stage="final")
        out = serializers.AssessmentSerializer(finals, many=True)
        return Response(out.data)


class LesionViewSet(AuditMixin, viewsets.ModelViewSet):
    """POST /lesions (manual), PATCH /lesions/{id} (오탐 표시),
    GET /lesions/?patient={id} · ?study={id}.

    ⚠ **?patient= 을 아무도 안 보고 있었다**(09-23 확인). 필터 백엔드도
      get_queryset 도 없어서 질의가 조용히 무시되고 표 앞쪽 스무 건이
      그대로 나갔다 — 부르는 쪽(유방외과 검사 종합 · 환자 상세)은 그것을
      «이 환자의 병변»으로 그리고 있었다. 남의 병변 위치·크기가 이 환자
      것으로 보이는 자리라 조용히 틀리면 안 된다.

    ⚠ **조건 없는 목록은 안 준다.** 환자도 검사도 안 짚으면 빈 목록이다 —
      환자 표 전체를 실수로 긁는 것을 막는다(PatientViewSet 과 같은 규칙).
    """

    resource = "lesion"
    permission_classes = [MatrixPermission]
    queryset = models.Lesion.objects.all()
    serializer_class = serializers.LesionSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action != "list":
            return qs

        patient = self.request.query_params.get("patient")
        study = self.request.query_params.get("study")
        if not patient and not study:
            return qs.none()

        if patient:
            if not str(patient).isdigit():
                raise ApiError("VALIDATION_ERROR", "patient 는 숫자여야 합니다.")
            qs = qs.filter(patient_id=int(patient))
        if study:
            if not str(study).isdigit():
                raise ApiError("VALIDATION_ERROR", "study 는 숫자여야 합니다.")
            qs = qs.filter(study_id=int(study))
        # ⚠ **순서를 못 박는다.** 안 박으면 Postgres 가 아무 순서로나 주고,
        #   부르는 쪽은 맨 앞을 「이 환자의 병변」으로 그린다 — 새로고침할
        #   때마다 다른 병변이 대표로 뜬다. 쪽 나눔 경계도 흔들린다.
        return qs.order_by("study_id", "lesion_index", "lesion_id")

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
    permission_classes = [MatrixPermission, CanFinalizeRadiologyRead]

    def create(self, request, pk=None):
        old = models.Assessment.objects.get(pk=pk)
        serializer = serializers.AssessmentAmendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        birads_rules.validate_for_study(old.study, data["category"])

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
