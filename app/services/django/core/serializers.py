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
from django.db import transaction
from . import models

from django.utils import timezone
from django.db import transaction


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


class PatientListSerializer(serializers.ModelSerializer):
    """GET /patients/?q= 검색 결과용. pii 이름전화를 얕게 끌어온다."""
    
    name = serializers.CharField(source="pii.name", read_only=True)
    phone = serializers.CharField(source="pii.phone", read_only=True)
    
    class Meta:
        model= models.Patient
        fields = ("patient_id", "patient_number", "name", "phone", "birth_year", "sex")
        
        

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


    def validate_patient_number(self, value):
        if models.Patient.objects.filter(patient_number=value).exists():
            raise serializers.ValidationError("이미 등록된 환자번호입니다.")
        return value
    
    def validate_phone(self, value):
        if value and models.PatientPii.objects.filter(phone=value).exists():
            raise serializers.ValidationError("이미 등록된 전화번호입니다.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        pii_fields = ("name", "birth_date", "phone")
        pii_data = {k: validated_data.pop(k) for k in pii_fields if k in validated_data}

        audit = {
            "created_by": validated_data.pop("created_by", None),
            "updated_by": validated_data.pop("updated_by", None),
        }

        patient = models.Patient.objects.create(**validated_data, **audit)
        models.PatientPii.objects.create(patient=patient, **pii_data, **audit)

        return patient
    
class ExamOrderItemSerializer(serializers.Serializer):
    exam_purpose = serializers.ChoiceField(choices=models.as_choices(models.EXAM_PURPOSE))
    modality = serializers.ChoiceField(choices=models.as_choices(models.MODALITY))
    

class ReservationCreateSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    scheduled_at = serializers.DateTimeField()
    orders = ExamOrderItemSerializer(many=True, allow_empty=False)
    
    def validate_patient_id(self, value):
        if not models.Patient.objects.filter(pk=value).exists():
            raise serializers.ValidationError("존재하지 않는 환자입니다.")
        return value
    
    @transaction.atomic
    def create(self, validated_data):
        audit = {
            "created_by" : validated_data.pop("created_by", None),
            "updated_by" : validated_data.pop("updated_by", None),
        }
        order_items = validated_data.pop("orders")
        
        rows=[]
        for item in order_items:
            row = models.ExamOrder(
                patient_id=validated_data["patient_id"],
                scheduled_at=validated_data["scheduled_at"],
                exam_purpose=item["exam_purpose"],
                modality= item["modality"],
                order_status ="ordered",
                ordered_at = timezone.now(),
                ordered_by=None,
                **audit,
            )
            rows.append(row)
        
        return models.ExamOrder.objects.bulk_create(rows)
    
  
  
  
  
  
  #=====환자 신청용======
class ReservationRequestCreateSerializer(serializers.Serializer):
    """POST /me/reservation-requests — 환자가 날짜·시간만 신청(§7).

    patient_id 는 여기서 안 받는다 — view 에서 request.user.patient 로 강제.
    """

    scheduled_at = serializers.DateTimeField()

    def create(self, validated_data):
        return models.ExamOrder.objects.create(
            patient=validated_data["patient"],
            scheduled_at=validated_data["scheduled_at"],
            order_status="requested",
            modality=None,
            exam_purpose=None,
            ordered_by=None,
            created_by=validated_data.get("created_by"),
            updated_by=validated_data.get("updated_by"),
        )