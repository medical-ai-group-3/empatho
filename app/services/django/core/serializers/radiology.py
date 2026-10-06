"""영상의학과(radiology) serializer — 2026-09-11 화면명세 기준."""

from rest_framework import serializers
from django.utils import timezone

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")

# 판독 권고(assessment.recommendation). ACR BI-RADS 관리 권고를 따른다 —
#   0 → additional_imaging · 1·2 → routine_screening · 3 → short_interval_followup
#   4·5 → biopsy · 6 → surgical_excision
# 모델 칸은 choices 없는 CharField(100)라 여기서만 거른다.
RECOMMENDATION = ["routine_screening", "short_interval_followup",
                  "additional_imaging", "biopsy", "surgical_excision"]


class StudySerializer(serializers.ModelSerializer):
    """GET /studies 목록·단건 — 프론트가 행마다 exam_order 를 따로 조회해
    환자 이름·나이·성별을 채우던(N+1) 걸 막으려고 ExamOrderSerializer 와
    같은 계산 필드를 여기도 둔다(09-18 프론트 확인 — Queue·List 크래시는
    잡혔지만 patient_name 등이 없어 행이 undefined 로 떴다)."""

    patient_name = serializers.CharField(
        source="patient.pii.name", read_only=True, default=None
    )
    age = serializers.SerializerMethodField()
    sex = serializers.CharField(source="patient.sex", read_only=True, allow_null=True)
    # 09-28 — 판독 목록 · 판독 화면이 행마다 환자 · 오더를 따로 부르던(N+1)
    # 것을 걷어 내려고 오더의 의뢰 문구 · 검사 목적과 환자번호를 같이 싣는다.
    # density_category · density_percent 는 모델 칸이라 원래부터 실린다.
    patient_number = serializers.CharField(
        source="patient.patient_number", read_only=True, default=None)
    order_note = serializers.CharField(
        source="exam_order.order_note", read_only=True, default=None, allow_null=True)
    exam_purpose = serializers.CharField(
        source="exam_order.exam_purpose", read_only=True, default=None, allow_null=True)
    # 「유방외과 열람」 — 목록 쿼리셋이 얹는 값(core/viewed.py). 얹지 않은
    # 자리에서는 None 이다
    viewed_at = serializers.DateTimeField(read_only=True, default=None)
    image_count = serializers.SerializerMethodField()
    # 가장 최근 AI 실행 상태 — 목록은 views/radiology.py 의 _latest_ai_status
    # 가 얹어 온다. 단건처럼 안 실려 온 자리에서는 그때 한 번 본다
    ai_status = serializers.SerializerMethodField()

    def get_ai_status(self, obj):
        if hasattr(obj, "ai_status"):
            return obj.ai_status
        last = obj.ai_results.order_by("-created_at", "-ai_result_id").first()
        return last.run_status if last else None

    def get_image_count(self, obj) -> int:
        """올라온 영상 파일 수. **0 이면 아직 촬영 전이다.**

        검사는 「촬영 시작」에 만들어지므로 파일이 한 장도 없는 채로
        read_status="pending" 인 시간이 있다. 그 동안 판독 화면을 열면
        409 STUDY_NOT_READ_READY 다 — 그런데 목록 행에는 그것을 가릴
        칸이 하나도 없어서, 부르는 쪽이 판독으로 보낼지 업로드로 보낼지
        정할 수가 없었다(09-23). 그 칸을 여기서 준다.

        목록은 queryset 에서 annotate 해 오므로 행마다 세지 않는다.
        단건 조회처럼 안 실려 온 자리에서만 그때 센다.
        """
        counted = getattr(obj, "image_count", None)
        if counted is not None:
            return counted
        return obj.storage_objects.filter(deleted_at__isnull=True).count()

    def get_age(self, obj) -> int | None:
        pii = getattr(obj.patient, "pii", None)
        birth_date = getattr(pii, "birth_date", None)
        if birth_date is None:
            return None

        reference = obj.performed_at or timezone.now()
        reference_date = reference.date()
        return reference_date.year - birth_date.year - (
            (reference_date.month, reference_date.day)
            < (birth_date.month, birth_date.day)
        )

    class Meta:
        model = models.Study
        exclude = AUDIT_FIELDS


class LesionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Lesion
        exclude = AUDIT_FIELDS + ("malignancy_p",)


class AssessmentSerializer(serializers.ModelSerializer):
    # 09-28 — 「오늘 내가 확정한 판독」(GET /assessments?assessed_by=me) 은
    # ?study 없이 여러 검사를 섞어 주므로, 행마다 누구 · 무슨 검사인지 싣는다.
    patient_id = serializers.IntegerField(source="study.patient_id", read_only=True)
    patient_name = serializers.CharField(
        source="study.patient.pii.name", read_only=True, default=None)
    patient_number = serializers.CharField(
        source="study.patient.patient_number", read_only=True, default=None)
    modality = serializers.CharField(source="study.modality", read_only=True, default=None)

    class Meta:
        model = models.Assessment
        exclude = AUDIT_FIELDS


class AiResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AiResult
        exclude = AUDIT_FIELDS


class StorageObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.StorageObject
        exclude = AUDIT_FIELDS


# ── 워크플로 액션 전용 ──────────────────────────────────

class AssessmentDraftSerializer(serializers.Serializer):
    """PUT /studies/{id}/assessment/draft — 임시저장(덮어쓰기)."""

    lesion_id = serializers.IntegerField(required=False, allow_null=True)
    finding_note = serializers.CharField(required=False, allow_blank=True)
    category = serializers.CharField(required=False, allow_null=True)
    # 09-28 — 권고 · 권고 사유. 모델 칸은 있었는데 받는 자리가 없었다.
    # 값 집합은 여기 둔다(모델 choices 로 두면 마이그레이션이 생긴다) —
    # RECOMMENDATION 참고.
    recommendation = serializers.ChoiceField(
        choices=[(v, v) for v in RECOMMENDATION], required=False, allow_null=True)
    recommendation_reason = serializers.CharField(
        max_length=250, required=False, allow_blank=True, allow_null=True)


class LesionCreateSerializer(serializers.Serializer):
    """POST /lesions — 의사가 직접 그린 병변(lesion_source=manual)."""

    study_id = serializers.IntegerField()
    detail = serializers.JSONField(required=False)


class LesionFalsePositiveSerializer(serializers.Serializer):
    """PATCH /lesions/{id} — 오탐 표시."""

    is_false_positive = serializers.BooleanField()


class StudyUploadReviewSerializer(serializers.Serializer):
    """PATCH /radiology/studies/{id}/upload — 업로드 품질 승인/반려."""

    quality_status = serializers.ChoiceField(choices=models.QUALITY_STATUS)


class AssessmentAmendSerializer(serializers.Serializer):
    """POST /assessments/{id}/amend — 판독 정정. 새 행 생성 + 옛 행 superseded_by."""

    decision_reason = serializers.CharField(max_length=250)
    category = serializers.CharField()
    finding_note = serializers.CharField(max_length=1000)