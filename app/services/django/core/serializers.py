"""DRF serializer.

원칙
  - 읽기용은 ModelSerializer 기본형. 목록/상세에서 그대로 쓴다.
  - 쓰기(워크플로 액션)는 액션 전용 serializer 를 따로 만든다 — 모델
    필드를 통째로 열지 않는다.
  - 감사 컬럼(created_by/updated_by/created_at/updated_at)은 응답에서 뺀다.

여기 있는 것은 1단계 골격(reception·nursing 범위)뿐이다.
radiology 이후 모델 serializer 는 각 단계에서 추가한다.
"""

from rest_framework import serializers

from . import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class PatientPiiSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.PatientPii
        exclude = AUDIT_FIELDS


class PatientSerializer(serializers.ModelSerializer):
    """목록용. 개인정보(pii)는 필요할 때 PatientDetailSerializer 로."""

    class Meta:
        model = models.Patient
        exclude = AUDIT_FIELDS


class PatientDetailSerializer(PatientSerializer):
    pii = PatientPiiSerializer(read_only=True)


class ExamOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ExamOrder
        exclude = AUDIT_FIELDS


class FollowupSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Followup
        exclude = AUDIT_FIELDS


# ── 워크플로 액션 전용 (쓰기) ──────────────────────────────────
# 예시 하나만 둔다. 나머지는 각 ViewSet @action 옆에 두거나 여기에 모은다.

class PatientCreateSerializer(serializers.Serializer):
    """POST /patients/ — patient + patient_pii 를 한 번에 받는다(§5-2)."""

    # patient
    patient_number = serializers.CharField(max_length=50)
    sex = serializers.ChoiceField(choices=models.as_choices(["female", "male"]),
                                  required=False, allow_null=True)
    birth_year = serializers.IntegerField(required=False, allow_null=True)
    has_allergy = serializers.BooleanField(required=False)
    allergy_note = serializers.CharField(max_length=250, required=False,
                                         allow_blank=True)
    # patient_pii
    name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    birth_date = serializers.DateField(required=False, allow_null=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)

    # TODO: create() 에서 transaction.atomic 으로 Patient → PatientPii 순서로 insert
