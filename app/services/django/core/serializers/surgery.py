"""유방외과(surgery) serializer — 2026-09-14 화면명세 기준."""

from rest_framework import serializers
from django.utils import timezone

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
    """serializers.SpecimenSerializer 로 패키지 전체(병리·유방외과)가 쓴다
    — core/serializers/__init__.py 가 이 클래스만 재수출한다. 병리 판독
    화면(toRead)이 환자 이름·나이·성별을 따로 조회하지 않게 StudySerializer
    와 같은 계산 필드를 둔다(09-18 백엔드 대조 ③)."""

    patient_name = serializers.CharField(
        source="patient.pii.name", read_only=True, default=None
    )
    age = serializers.SerializerMethodField()
    sex = serializers.CharField(source="patient.sex", read_only=True, allow_null=True)

    def get_age(self, obj) -> int | None:
        pii = getattr(obj.patient, "pii", None)
        birth_date = getattr(pii, "birth_date", None)
        if birth_date is None:
            return None

        reference = obj.collected_at or timezone.now()
        reference_date = reference.date()
        return reference_date.year - birth_date.year - (
            (reference_date.month, reference_date.day)
            < (birth_date.month, birth_date.day)
        )

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
    """PATCH /assessments/{id}/decision — §3 수술 여부·사유. assessment.decision_* 사용."""

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


class PrescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Prescription
        exclude = AUDIT_FIELDS


class PrescriptionCreateSerializer(serializers.Serializer):
    """POST /patients/{id}/prescriptions — 처방 생성.

    exam_order_id · report_id 중 **정확히 하나**만 받는다 — Prescription
    의 owner CHECK(exam_order/report 중 하나)과 짝이다. 어느 환자 것인지는
    URL 의 patient pk 로 이미 정해지므로 여기서는 안 받는다 — 뷰가 그
    오더/리포트가 실제로 이 환자 것인지 대조한다."""

    exam_order_id = serializers.IntegerField(required=False)
    report_id = serializers.IntegerField(required=False)
    content = serializers.JSONField(required=False)

    def validate(self, attrs):
        has_order = attrs.get("exam_order_id") is not None
        has_report = attrs.get("report_id") is not None
        if has_order == has_report:
            raise serializers.ValidationError(
                "exam_order_id 또는 report_id 중 하나만 지정해야 합니다.")
        return attrs