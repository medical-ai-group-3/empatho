"""간호과(nursing) serializer."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class FollowupSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.pii.name", read_only=True, default=None
    )
    # 09-28 — 추적 콜 화면이 전화할 번호 · 본인 확인용 생년월일 · 환자번호를
    # 행마다 환자 상세로 다시 부르지 않게 얹는다. 읽기 전용.
    patient_number = serializers.CharField(
        source="patient.patient_number", read_only=True, default=None
    )
    phone = serializers.CharField(
        source="patient.pii.phone", read_only=True, default=None
    )
    birth_date = serializers.DateField(
        source="patient.pii.birth_date", read_only=True, default=None
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
    round_no = serializers.IntegerField(min_value=1)
    due_at = serializers.DateTimeField()

    def validate_patient_id(self, value):
        # 없는 환자면 FK 위반으로 500 이 났다
        if not models.Patient.objects.filter(pk=value).exists():
            raise serializers.ValidationError("존재하지 않는 환자입니다.")
        return value


class FollowupCallSerializer(serializers.Serializer):
    """PATCH /followups/{id}/call — 안내 콜 기록(§2).

    call_result 는 CALL_RESULT(연결 · 부재 · 거부) 중 하나다. 아무 문자열이나
    받으면 DB 칸(varchar 20)을 넘거나 화면이 모르는 값이 쌓였다.
    call_note 는 varchar(250) — 넘치면 Postgres 가 DataError 로 500 을 냈다.
    """

    call_result = serializers.ChoiceField(choices=models.as_choices(models.CALL_RESULT))
    call_note = serializers.CharField(required=False, allow_blank=True, max_length=250)


class FollowupUpdateSerializer(serializers.Serializer):
    """PATCH /followups/{id}/ — 종료 또는 통화 기록(범용 경로).

    closed_reason 이 있으면 종료, 없으면 통화 기록이다(기존 동작 그대로).
    """

    status = serializers.ChoiceField(
        choices=models.as_choices([s for s in models.FOLLOWUP_STATUS if s != "open"]),
        required=False)
    closed_reason = serializers.CharField(required=False, allow_blank=True, max_length=100)
    call_result = serializers.ChoiceField(
        choices=models.as_choices(models.CALL_RESULT), required=False, allow_null=True)
    call_note = serializers.CharField(required=False, allow_blank=True,
                                      allow_null=True, max_length=250)
    # 09-28 — 회차 결과(stable · changed · no_show). 종료 · 통화 기록과 같이
    # 와도 되고 혼자 와도 된다 — 혼자 오면 결과만 적는다(views/nursing.py).
    round_result = serializers.ChoiceField(
        choices=models.as_choices(models.ROUND_RESULT), required=False, allow_null=True)

class PatientPiiCorrectSerializer(serializers.Serializer):
    """PATCH /patients/{id}/pii — 창구 인적 사항 정정(이름 · 전화 · 생년월일).

    보낸 칸만 고친다. 전화는 다른 환자와 겹치면 400 — 등록
    (PatientRegisterSerializer)과 같은 규칙이다.
    """

    name = serializers.CharField(max_length=50, required=False)
    phone = serializers.CharField(max_length=30, required=False)
    birth_date = serializers.DateField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("고칠 칸(name · phone · birth_date)이 없습니다.")
        return attrs


class PrimaryStaffAssignSerializer(serializers.Serializer):
    """PATCH /patients/{id} — 주치의 지정(§1)."""

    primary_staff = serializers.IntegerField()
    
