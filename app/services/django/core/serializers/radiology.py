"""영상의학과(radiology) serializer — 2026-09-11 화면명세 기준."""

from rest_framework import serializers
from django.utils import timezone

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


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
    image_count = serializers.SerializerMethodField()

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