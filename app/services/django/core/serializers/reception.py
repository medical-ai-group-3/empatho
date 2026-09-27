"""원무과(reception) serializer."""

from rest_framework import serializers
from django.db import transaction
from django.utils import timezone

from .. import models
from core.api.perms import perms_for_role
from ..services import discordance

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class PatientPiiSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.PatientPii
        exclude = AUDIT_FIELDS


class PatientSerializer(serializers.ModelSerializer):
    """목록용. 개인정보(pii)는 필요할 때 PatientDetailSerializer 로."""

    primary_staff_name = serializers.CharField(
        source="primary_staff.full_name", read_only=True, default=None
    )

    class Meta:
        model = models.Patient
        exclude = AUDIT_FIELDS
        read_only_fields = ("account", "patient_number")


class PatientDetailSerializer(PatientSerializer):
    pii = PatientPiiSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    open_discordance = serializers.SerializerMethodField()

    def get_open_discordance(self, patient) -> dict | None:
        """아직 처분되지 않은 영상·병리 불일치 한 건.

        유방외과 「검사 종합」 화면의 배너가 이 칸을 읽는다. **없으면 null**
        이고, 화면은 그때 「엇갈린 것이 없습니다」를 띄운다.

        ⚠ **「열림」은 상태값이 아니라 closed_at IS NULL 이다**
          (FLAG_STATUS 에 open 이 없다 — models.py:87). 목록 API 와 잠금
          해제 조건도 같은 기준으로 센다(views/surgery.py:226 · :468).
        ⚠ **lesion 으로 환자를 찾는다.** 플래그에 환자 FK 가 없다
          (models.py:811-820) — 같은 표의 다른 곳도 전부 이 경로다.
        ⚠ violated_rule 은 20자 코드라 그대로 내보내면 화면에 「rule1」이
          뜬다. 사람이 읽는 문장으로 바꿔서 같은 이름에 싣는다.
        """
        flag = (models.DiscordanceFlag.objects
                .filter(lesion__patient=patient, closed_at__isnull=True)
                .order_by("-flagged_at", "-discordance_flag_id")
                .first())
        if flag is None:
            return None
        return {
            "discordance_id": flag.pk,
            "violated_rule": discordance.describe(flag),
            "rule_code": flag.violated_rule,
            "flag_status": flag.flag_status,
            "lesion_id": flag.lesion_id,
            "specimen_id": flag.specimen_id,
            "flagged_at": flag.flagged_at,
        }

    class Meta:
        model = models.Patient
        exclude = ("created_by", "updated_at", "updated_by")


class ExamOrderSerializer(serializers.ModelSerializer):
    patient_number = serializers.CharField(
        source="patient.patient_number", read_only=True, default=None
    )
    patient_name = serializers.CharField(
        source="patient.pii.name", read_only=True, default=None
    )
    age = serializers.SerializerMethodField()
    sex = serializers.CharField(source="patient.sex", read_only=True, allow_null=True)
    visit_type = serializers.SerializerMethodField()
    # 09-27 — 환자의 주치의(유방외과 배정). 간호 「내원 대기」가 이미 유방외과로
    # 보낸 환자를 가려내려고 localStorage 에 오더 번호를 적어 두고 있었다 —
    # 응답에 이 칸이 없어서다. 오더가 아니라 환자의 값이라 읽기 전용이다.
    primary_staff = serializers.IntegerField(
        source="patient.primary_staff_id", read_only=True, default=None
    )
    primary_staff_name = serializers.CharField(
        source="patient.primary_staff.full_name", read_only=True, default=None
    )
    # 09-27 — 간호 → 유방외과 인계(handed_at · handed_to 는 모델 칸이라 저절로
    # 나간다). 이름만 얹는다.
    handed_to_name = serializers.CharField(
        source="handed_to.full_name", read_only=True, default=None
    )

    def get_age(self, obj) -> int | None:
        pii = getattr(obj.patient, "pii", None)
        birth_date = getattr(pii, "birth_date", None)
        if birth_date is None:
            return None

        reference = obj.visited_at or obj.scheduled_at or timezone.now()
        # ⚠ .date() 를 바로 부르면 UTC 날짜다 — 한국 시각 00~09시 방문은
        #   전날로 계산돼 생일 당일 나이가 하나 적게 나왔다. 현지 날짜로 본다.
        reference_date = timezone.localtime(reference).date()
        return reference_date.year - birth_date.year - (
            (reference_date.month, reference_date.day)
            < (birth_date.month, birth_date.day)
        )

    def get_visit_type(self, obj) -> str:
        first_visited_at = obj.patient.first_visited_at
        if first_visited_at is None:
            return "초진"
        if obj.visited_at is not None and obj.visited_at <= first_visited_at:
            return "초진"
        return "재진"

    class Meta:
        model = models.ExamOrder
        exclude = AUDIT_FIELDS


class PatientExamOrderSerializer(serializers.ModelSerializer):
    """환자 role 조회/응답용 — 문진 · 취소 사유 · 취소자 · 지시자는 뺀다."""

    class Meta:
        model = models.ExamOrder
        exclude = AUDIT_FIELDS + (
            "questionnaire", "cancel_reason", "cancelled_by", "ordered_by",
        )


class PatientListSerializer(serializers.ModelSerializer):
    """GET /patients/?q= 검색 결과용. pii 이름전화를 얕게 끌어온다."""

    name = serializers.CharField(source="pii.name", read_only=True)
    phone = serializers.CharField(source="pii.phone", read_only=True)
    birth_date = serializers.DateField(source="pii.birth_date", read_only=True, default=None)
    # PatientViewSet.get_queryset 이 Exists 로 얹어 준다. 목록 밖에서 이
    # serializer 를 쓰면 없을 수 있어 default 를 둔다.
    has_open_discordance = serializers.BooleanField(read_only=True, default=False)
    # 09-27 — 목록에도 주치의를 싣는다. 간호 환자 목록이 「배정됨」을 보려고
    # 행마다 상세(GET /patients/{id}/)를 다시 부르지 않게.
    primary_staff_name = serializers.CharField(
        source="primary_staff.full_name", read_only=True, default=None
    )

    class Meta:
        model = models.Patient
        fields = ("patient_id", "patient_number", "name", "phone", "birth_date",
                  "birth_year", "sex", "has_allergy", "has_open_discordance",
                  "primary_staff", "primary_staff_name")


# ── 워크플로 액션 전용 (쓰기) ──────────────────────────────────

class PatientCreateSerializer(serializers.Serializer):
    """POST /patients/ — patient + patient_pii 를 한 번에 받는다(§5-2)."""

    patient_number = serializers.CharField(max_length=50)
    sex = serializers.ChoiceField(choices=models.as_choices(["female", "male"]),
                                  required=False, allow_null=True)
    birth_year = serializers.IntegerField(required=False, allow_null=True)
    has_allergy = serializers.BooleanField(required=False)
    allergy_note = serializers.CharField(max_length=250, required=False,
                                         allow_blank=True)
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
    ordered_by = serializers.IntegerField()
    orders = ExamOrderItemSerializer(many=True, allow_empty=False)

    def validate_patient_id(self, value):
        if not models.Patient.objects.filter(pk=value).exists():
            raise serializers.ValidationError("존재하지 않는 환자입니다.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        audit = {
            "created_by": validated_data.pop("created_by", None),
            "updated_by": validated_data.pop("updated_by", None),
        }
        order_items = validated_data.pop("orders")
        ordered_by_id = validated_data.pop("ordered_by")

        rows = []
        for item in order_items:
            row = models.ExamOrder(
                patient_id=validated_data["patient_id"],
                scheduled_at=validated_data["scheduled_at"],
                exam_purpose=item["exam_purpose"],
                modality=item["modality"],
                order_status="ordered",
                ordered_at=timezone.now(),
                ordered_by_id=ordered_by_id,
                **audit,
            )
            rows.append(row)

        return models.ExamOrder.objects.bulk_create(rows)


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
        
class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Staff
        exclude = ("created_at", "created_by" , "updated_at", "updated_by")
        
class PatientRegisterSerializer(serializers.Serializer):
    """POST /patients/register — §1 [+] 등록. 이름·생년월일·전화로 중복 검사."""

    name = serializers.CharField(max_length=50)
    birth_date = serializers.DateField()
    phone = serializers.CharField(max_length=30)

    def validate(self, attrs):
        existing = models.PatientPii.objects.filter(
            name=attrs["name"], birth_date=attrs["birth_date"], phone=attrs["phone"],
        ).first()
        if existing is None:
            conflict = models.PatientPii.objects.filter(phone=attrs["phone"]).exists()
            if conflict:
                raise serializers.ValidationError(
                    {"phone": "이미 다른 환자에게 등록된 전화번호입니다."}
                )
        self._existing_pii = existing
        return attrs

    @property
    def created(self):
        return getattr(self, "_existing_pii", None) is None

    def create(self, validated_data):
        existing = self._existing_pii
        if existing:
            return existing.patient

        audit = {
            "created_by": validated_data.pop("created_by", None),
            "updated_by": validated_data.pop("updated_by", None),
        }
        import uuid
        patient = models.Patient.objects.create(
            patient_number="P" + uuid.uuid4().hex[:10].upper(),
            **audit,
        )
        models.PatientPii.objects.create(patient=patient, **validated_data, **audit)
        return patient
    
def _validate_patient_exists(value):
    # 없는 환자 번호를 그대로 create 에 넘기면 FK 위반(IntegrityError)으로
    # 500 이 났다. 여기서 400 으로 돌려준다.
    if not models.Patient.objects.filter(pk=value).exists():
        raise serializers.ValidationError("존재하지 않는 환자입니다.")
    return value


class CheckInSerializer(serializers.Serializer):
    """POST /exam-orders (§1 접수하기) — requested + visited_at."""

    patient_id = serializers.IntegerField()

    def validate_patient_id(self, value):
        return _validate_patient_exists(value)


class ExamOrderScheduleSerializer(serializers.Serializer):
    """POST /exam-orders (§3 예약 완료) — 원무가 날짜만 잡는다."""

    patient_id = serializers.IntegerField()
    scheduled_at = serializers.DateTimeField()

    def validate_patient_id(self, value):
        return _validate_patient_exists(value)


class ExamOrderConfirmSerializer(serializers.Serializer):
    """PATCH /exam-orders/{id}/confirm — 원무는 날짜만 확정한다.

    검사 종류(modality·exam_purpose·ordered_by)는 유방외과가 나중에 정한다
    (0015 · order_status='scheduled' 신설, 09-17 팀 확정).
    """

    scheduled_at = serializers.DateTimeField()


class ExamOrderHandoffSerializer(serializers.Serializer):
    """PATCH /exam-orders/{id}/handoff — 간호가 이 방문을 유방외과 선생님께 보낸다.

    받는 사람은 유방외과(surgery) 의료진이어야 한다. 다른 과 직원 번호를
    넣으면 400 — 그 사람 대기 줄에는 이 환자가 영영 안 뜬다.
    """

    staff_id = serializers.IntegerField()

    def validate_staff_id(self, value):
        staff = (models.Staff.objects.select_related("account")
                 .filter(pk=value).first())
        if staff is None:
            raise serializers.ValidationError("없는 직원 번호입니다.")
        if getattr(staff.account, "role", None) != "surgery":
            raise serializers.ValidationError("유방외과 의료진에게만 보낼 수 있습니다.")
        return value

    def validate(self, attrs):
        attrs["staff"] = models.Staff.objects.get(pk=attrs["staff_id"])
        return attrs


class MeSerializer(serializers.Serializer):
    """GET /me — 로그인한 계정 정보 + 권한 배열."""
    name = serializers.SerializerMethodField()
    role = serializers.CharField()
    dept = serializers.CharField(source="role")
    dept_name = serializers.SerializerMethodField()
    perms = serializers.SerializerMethodField()

    DEPT_NAMES = {
        "reception": "원무과", "nursing": "간호과", "radiology": "영상의학과",
        "pathology": "병리과", "surgery": "유방외과", "admin": "관리자",
        "patient": "환자",
    }

    def get_name(self, account):
        staff = getattr(account, "staff", None)
        return staff.full_name if staff else None

    def get_dept_name(self, account):
        return self.DEPT_NAMES.get(account.role, account.role)

    def get_perms(self, account):
        return perms_for_role(account.role)
    
class MePatientSerializer(serializers.Serializer):
    """GET /me — 환자용. 같은 경로에서 역할로 갈린다.

    의료진용(MeSerializer)은 권한 배열을 내는데, 환자에게는 쓸 데가 없다.
    환자 화면이 필요한 것은 「나는 누구이고 언제 왔고 문진은 어디까지 했나」다.

    경로를 /me/patient 로 따로 내지 않는 이유 — 화면이 이미 /me 를 부르고
    있고, 한 사람은 환자이거나 의료진이지 둘 다인 경우가 없다.
    """

    patient_id = serializers.IntegerField(source="patient.patient_id", default=None)
    patient_number = serializers.CharField(source="patient.patient_number", default=None)
    display_name = serializers.CharField(source="patient.pii.name", default=None)
    birth_date = serializers.DateField(source="patient.pii.birth_date", default=None)
    phone = serializers.CharField(source="patient.pii.phone", default=None)
    login_id = serializers.CharField(default=None)

    primary_staff_name = serializers.CharField(
        source="patient.primary_staff.full_name", default=None)
    primary_staff_dept = serializers.CharField(
        source="patient.primary_staff.account.role", default=None)

    last_visit_at = serializers.SerializerMethodField()
    last_visit_dept = serializers.SerializerMethodField()
    questionnaire_status = serializers.SerializerMethodField()
    questionnaire_progress = serializers.SerializerMethodField()

    def _last_order(self, account):
        """가장 최근 방문. 검사 오더의 visited_at 이 방문 시각이다."""
        patient = getattr(account, "patient", None)
        if patient is None:
            return None
        return (models.ExamOrder.objects
                .filter(patient=patient, visited_at__isnull=False)
                .order_by("-visited_at").first())

    def get_last_visit_at(self, account):
        o = self._last_order(account)
        return o.visited_at if o else None

    def get_last_visit_dept(self, account):
        o = self._last_order(account)
        # 모달리티가 곧 어느 과에 갔는지다. 없으면 접수만 하고 간 것이다.
        return "영상의학과" if (o and o.modality) else None

    def get_questionnaire_status(self, account):
        q = self._answers(account)
        if q is None:
            return "not_started"
        return "done" if q.get("_done") else "in_progress"

    def get_questionnaire_progress(self, account):
        q = self._answers(account) or {}
        answered = len([k for k in q if not k.startswith("_")])
        # 문항 수는 정의 파일이 안다. 아직 안 읽으므로 답한 수만 낸다.
        return {"answered": answered, "total": answered}

    def _answers(self, account):
        patient = getattr(account, "patient", None)
        return getattr(patient, "questionnaire", None) if patient else None

class PushTokenSerializer(serializers.Serializer):
    """FCM 기기 토큰. 앱이 켜질 때마다 보낸다 — 토큰은 조용히 바뀐다."""

    push_token = serializers.CharField(max_length=255, allow_blank=True)
    
class NotificationSerializer(serializers.ModelSerializer):
    """알림 한 건.

    AUDIT_FIELDS 를 그대로 쓰지 않는다. created_at 이 「언제 온 알림인가」라
    화면이 반드시 쓰는 값인데, 그 묶음에 들어 있어서 같이 빠진다.
    다시 선언하면 DRF 가 「exclude 에 있는 걸 또 선언했다」고 막는다 —
    빼는 목록에서 덜어내는 것이 맞다.
    """

    class Meta:
        model = models.Notification
        exclude = ("created_by", "updated_at", "updated_by")