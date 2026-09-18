"""간호과(nursing) serializer."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class FollowupSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.pii.name", read_only=True, default=None
    )

    class Meta:
        model = models.Followup
        exclude = AUDIT_FIELDS


class VisitCheckInSerializer(serializers.Serializer):
    """POST /visits/today/ — 내원 확인(§6-1)."""

    exam_order_id = serializers.IntegerField()

    def validate_exam_order_id(self, value):
        if not models.ExamOrder.objects.filter(pk=value).exists():
            raise serializers.ValidationError("존재하지 않는 오더입니다.")
        return value


class ExamOrderNoteSerializer(serializers.Serializer):
    """PATCH /exam-orders/{id}/note — 간호 메모 저장."""

    note = serializers.CharField(allow_blank=True)

class FollowupCreateSerializer(serializers.Serializer):
    """POST /followups — 추적 회차 생성(§2)."""

    patient_id = serializers.IntegerField()
    round_no = serializers.IntegerField()
    due_at = serializers.DateTimeField()
    
class FollowupCallSerializer(serializers.Serializer):
    """PATCH /followups/{id}/call — 안내 콜 기록(§2)."""

    call_result = serializers.CharField()
    call_note = serializers.CharField(required=False, allow_blank=True)
    
class PrimaryStaffAssignSerializer(serializers.Serializer):
    """PATCH /patients/{id} — 주치의 지정(§1)."""

    primary_staff = serializers.IntegerField()
    
