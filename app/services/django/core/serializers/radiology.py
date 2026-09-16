"""영상의학과(radiology) serializer — 2026-09-11 화면명세 기준."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class StudySerializer(serializers.ModelSerializer):
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