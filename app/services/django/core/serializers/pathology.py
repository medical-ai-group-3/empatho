"""병리과(pathology) serializer — 2026-09-14 화면명세 기준.

SpecimenSerializer 는 여기 안 둔다 — core/serializers/__init__.py 가
surgery.py 의 SpecimenSerializer 만 재수출해서, 여기 따로 정의하면
`serializers.SpecimenSerializer` 를 쓰는 코드엔 하나도 안 닿는 죽은
클래스가 된다(09-18 발견 — 처음엔 여기 뒀다가 테스트로 이걸 잡았다).
"""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")

# 09-28 — 병리 보고 칸(조직형 · 등급 · 수용체 · Ki-67). 모델 칸은 choices 없는
# CharField 라 값 집합은 여기서만 거른다(모델에 두면 마이그레이션이 생긴다).
HISTOLOGIC_TYPE = ["idc_nst", "ilc", "dcis", "lcis", "mucinous", "tubular",
                   "papillary", "metaplastic", "fibroadenoma", "phyllodes",
                   "fibrocystic", "other"]
RECEPTOR_STATUS = ["positive", "negative", "low_positive"]   # ER · PR
HER2_STATUS = ["negative", "low", "equivocal", "positive"]


def _choices(values):
    return [(v, v) for v in values]


class _PathologyMarkersMixin(serializers.Serializer):
    """draft · finalize 가 똑같이 받는 선택 칸. 안 보내면 안 건드린다."""

    histologic_type = serializers.ChoiceField(
        choices=_choices(HISTOLOGIC_TYPE), required=False, allow_null=True)
    nottingham_grade = serializers.IntegerField(
        min_value=1, max_value=3, required=False, allow_null=True)
    er_status = serializers.ChoiceField(
        choices=_choices(RECEPTOR_STATUS), required=False, allow_null=True)
    pr_status = serializers.ChoiceField(
        choices=_choices(RECEPTOR_STATUS), required=False, allow_null=True)
    her2_status = serializers.ChoiceField(
        choices=_choices(HER2_STATUS), required=False, allow_null=True)
    ki67_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100,
        required=False, allow_null=True)


MARKER_FIELDS = ("histologic_type", "nottingham_grade", "er_status",
                 "pr_status", "her2_status", "ki67_percent")


class AiResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AiResult
        exclude = AUDIT_FIELDS


# ── 워크플로 액션 전용 ──────────────────────────────────

class SpecimenDraftSerializer(_PathologyMarkersMixin):
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


class SpecimenFinalizeSerializer(_PathologyMarkersMixin):
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