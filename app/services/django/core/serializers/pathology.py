"""병리과(pathology) serializer — 2026-09-14 화면명세 기준.

SpecimenSerializer 는 여기 안 둔다 — core/serializers/__init__.py 가
surgery.py 의 SpecimenSerializer 만 재수출해서, 여기 따로 정의하면
`serializers.SpecimenSerializer` 를 쓰는 코드엔 하나도 안 닿는 죽은
클래스가 된다(09-18 발견 — 처음엔 여기 뒀다가 테스트로 이걸 잡았다).
"""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


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
    
class StorageObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.StorageObject
        exclude = ("created_at", "created_by", "updated_at", "updated_by")