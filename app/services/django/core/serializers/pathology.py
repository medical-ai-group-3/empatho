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
    """PUT /specimens/{id}/draft — 임시저장(덮어쓰기).

    ⚠ 09-28 결정 — sTIL(임상 수치)은 병리의가 검체 단위로 직접 입력한다.
    AI 원시값(stil_percent)은 "sTIL"이 아니라 "AI 계측값"으로만 화면에
    쓰고, 보정계수는 안 쓴다. 여기 stil_calibrated 는 그 병리의 입력값을
    받는 자리다 — 이름은 그대로 두지만(모델 필드명이라 마이그레이션 없이
    가려면 이름을 못 바꾼다) 뜻은 "AI가 보정한 값"이 아니라 "병리의가
    입력한 sTIL"로 바뀌었다. stil_level 은 계산하지 않는다 — 여기서도
    안 채운다(뷰가 그대로 null 로 둔다)."""

    b_category = serializers.ChoiceField(choices=models.as_choices(models.B_CATEGORY), required=False, allow_null=True)
    diagnosis = serializers.ChoiceField(choices=models.as_choices(models.DIAGNOSIS), required=False, allow_null=True)
    finding_note = serializers.CharField(required=False, allow_blank=True)
    stil_calibrated = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=0, max_value=100,
        required=False, allow_null=True,
    )


class SpecimenFinalizeSerializer(serializers.Serializer):
    """PATCH /specimens/{id}/finalize — 확진 확정. stil_calibrated 설명은
    SpecimenDraftSerializer 참고 — 같은 자리다."""

    b_category = serializers.ChoiceField(choices=models.as_choices(models.B_CATEGORY))
    diagnosis = serializers.ChoiceField(choices=models.as_choices(models.DIAGNOSIS))
    finding_note = serializers.CharField(required=False, allow_blank=True)
    stil_calibrated = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=0, max_value=100,
        required=False, allow_null=True,
    )
    
class StorageObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.StorageObject
        exclude = ("created_at", "created_by", "updated_at", "updated_by")