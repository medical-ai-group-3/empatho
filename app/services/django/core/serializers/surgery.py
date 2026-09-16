"""유방외과(surgery) serializer — 2026-09-14 화면명세 기준."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Report
        exclude = AUDIT_FIELDS


class DiscordanceFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DiscordanceFlag
        exclude = AUDIT_FIELDS


class SpecimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Specimen
        exclude = AUDIT_FIELDS


class LesionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Lesion
        exclude = AUDIT_FIELDS


# ── 워크플로 액션 전용 ──────────────────────────────────

class ExamOrderRequestSerializer(serializers.Serializer):
    """POST /exam-orders — §1 촬영 요청 팝업."""

    patient_id = serializers.IntegerField()
    modality = serializers.ChoiceField(choices=models.as_choices(models.MODALITY))
    exam_purpose = serializers.ChoiceField(choices=models.as_choices(models.EXAM_PURPOSE))
    order_note = serializers.CharField(required=False, allow_blank=True)


class SurgeryDecisionSerializer(serializers.Serializer):
    """POST /assessments — §3 수술 여부·사유. assessment.decision_* 사용."""

    lesion_id = serializers.IntegerField()
    decision_type = serializers.ChoiceField(choices=models.as_choices(models.DECISION_TYPE))
    decision_value = serializers.ChoiceField(choices=models.as_choices(models.DECISION_VALUE))
    decision_reason = serializers.CharField(required=False, allow_blank=True)


class ReportExplainSerializer(serializers.Serializer):
    """PATCH /reports/{id}/explain — §3 환자 설명 기록."""

    explain_method = serializers.ChoiceField(choices=models.as_choices(models.EXPLAIN_METHOD))
    patient_confirmed = serializers.BooleanField()


class SpecimenBindSerializer(serializers.Serializer):
    """POST /specimens — §4 검체 바인딩. lesion_id NOT NULL."""

    lesion_id = serializers.IntegerField()
    specimen_label = serializers.CharField(max_length=50)
    specimen_type = serializers.ChoiceField(choices=models.as_choices(models.SPECIMEN_TYPE))
    guidance_route = serializers.ChoiceField(choices=models.as_choices(models.GUIDANCE_ROUTE))
    collected_at = serializers.DateTimeField()

    def validate_specimen_label(self, value):
        if models.Specimen.objects.filter(specimen_label=value).exists():
            raise serializers.ValidationError("이미 사용 중인 검체 라벨입니다.")
        return value

    def validate_lesion_id(self, value):
        if not models.Lesion.objects.filter(pk=value).exists():
            raise serializers.ValidationError("존재하지 않는 병변입니다.")
        return value


class DiscordanceDisposeSerializer(serializers.Serializer):
    """PATCH /discordances/{id}/dispose — §5 불일치 처분."""

    disposition_type = serializers.ChoiceField(choices=models.as_choices(models.DISPOSITION_TYPE))
    disposition_reason = serializers.CharField()

    def validate_disposition_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("처분 사유는 필수입니다.")
        return value