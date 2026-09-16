"""병리과(pathology) serializer — 2026-09-14 화면명세 기준."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class SpecimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Specimen
        exclude = AUDIT_FIELDS


class AiResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AiResult
        exclude = AUDIT_FIELDS


# ── 워크플로 액션 전용 ──────────────────────────────────

class SpecimenDraftSerializer(serializers.Serializer):
    """PUT /specimens/{id}/draft — 임시저장(덮어쓰기)."""

    b_category = serializers.ChoiceField(choices=models.as_choices(models.B_CATEGORY), required=False, allow_null=True)
    diagnosis = serializers.ChoiceField(choices=models.as_choices(models.DIAGNOSIS), required=False, allow_null=True)
    finding_note = serializers.CharField(required=False, allow_blank=True)


class SpecimenFinalizeSerializer(serializers.Serializer):
    """PATCH /specimens/{id}/finalize — 확진 확정."""

    b_category = serializers.ChoiceField(choices=models.as_choices(models.B_CATEGORY))
    diagnosis = serializers.ChoiceField(choices=models.as_choices(models.DIAGNOSIS))
    finding_note = serializers.CharField(required=False, allow_blank=True)
    
class SpecimenAmendSerializer(serializers.Serializer):
    """POST /specimens/{id}/amend — 판독 정정."""

    diagnosis = serializers.ChoiceField(choices=models.as_choices(models.DIAGNOSIS))
    b_category = serializers.ChoiceField(choices=models.as_choices(models.B_CATEGORY))
    finding_note = serializers.CharField(required=False, allow_blank=True)
    amend_reason = serializers.CharField()

    def validate_amend_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("정정 사유는 필수입니다.")
        return value
    