"""영상의학과(radiology) serializer."""

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
        exclude = AUDIT_FIELDS


class AssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Assessment
        exclude = AUDIT_FIELDS


class AiResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AiResult
        exclude = AUDIT_FIELDS