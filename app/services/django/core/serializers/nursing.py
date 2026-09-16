"""간호과(nursing) serializer."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class FollowupSerializer(serializers.ModelSerializer):
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