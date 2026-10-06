"""유방외과(surgery) serializer — 2026-09-14 화면명세 기준."""

from rest_framework import serializers
from django.utils import timezone

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class ReportSerializer(serializers.ModelSerializer):
    # 환자 앱 안내문에 찍는 의사는 **주치의**다. 발급한 사람(issued_by)은
    # 판독의라서, 이름만 주면 앱이 판독의를 담당 의사로 보여 줬다(09-29).
    primary_staff_name = serializers.CharField(
        source="patient.primary_staff.full_name", read_only=True, default=None)
    primary_staff_dept = serializers.CharField(
        source="patient.primary_staff.account.role", read_only=True, default=None)

    class Meta:
        model = models.Report
        exclude = AUDIT_FIELDS


class DiscordanceFlagSerializer(serializers.ModelSerializer):
    # ⚠ 화면은 discordance_id 로 링크를 만든다(go.breast.discordance). PK 의
    #   진짜 이름은 discordance_flag_id 라, 그대로 두면 주소에 undefined 가
    #   박혀 「처분하기」가 아무 데도 안 갔다(09-23 확인).
    discordance_id = serializers.IntegerField(
        source="discordance_flag_id", read_only=True)

    class Meta:
        model = models.DiscordanceFlag
        exclude = AUDIT_FIELDS


def _flag_patient(obj):
    """플래그에는 환자 칸이 없다 — 병변으로 찾고, 병변이 빈 플래그는 검체로 받친다."""
    if obj.lesion_id is not None and obj.lesion is not None:
        return obj.lesion.patient
    if obj.specimen_id is not None and obj.specimen is not None:
        return obj.specimen.patient
    return None


class DiscordanceListSerializer(DiscordanceFlagSerializer):
    """GET /discordances 목록 한 줄. 09-28 — 영상의학 「내 판독의 불일치」 화면이
    행마다 환자 · 판독 · 검체를 따로 부르지 않게 납작한 읽기 전용 칸을 얹는다.
    뷰(DiscordanceListView)가 select_related 로 한 번에 붙여 온다.

    기존 칸(discordance_id · violated_rule · flag_status · disposition_type ·
    flagged_at · closed_at …)은 DiscordanceFlagSerializer 그대로다.
    """

    patient_id = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    patient_number = serializers.SerializerMethodField()
    modality = serializers.SerializerMethodField()
    category = serializers.CharField(source="assessment.category", read_only=True, default=None)
    assessed_by = serializers.IntegerField(source="assessment.assessed_by_id",
                                           read_only=True, default=None)
    b_category = serializers.CharField(source="specimen.b_category", read_only=True, default=None)

    def get_patient_id(self, obj):
        p = _flag_patient(obj)
        return p.patient_id if p is not None else None

    def get_patient_name(self, obj):
        p = _flag_patient(obj)
        return getattr(getattr(p, "pii", None), "name", None) if p is not None else None

    def get_patient_number(self, obj):
        p = _flag_patient(obj)
        return p.patient_number if p is not None else None

    def get_modality(self, obj):
        # 판독한 검사의 모달리티가 먼저, 판독이 빈 플래그는 병변 것
        a = obj.assessment
        if a is not None and a.study_id is not None:
            return a.study.modality
        return obj.lesion.modality if obj.lesion is not None else None


def _staff_name(staff):
    return getattr(staff, "full_name", None) if staff else None


class DiscordanceDetailSerializer(DiscordanceFlagSerializer):
    """§5 상세 — **두 판독을 나란히 놓는 자리다.**

    ⚠ 지금까지 이 경로도 얕은 것(FK 번호만)을 돌려줬다. 화면은
      `radiology_reading` · `pathology_reading` · `patient` · `lesion` 을
      읽는데 그런 칸이 하나도 없어서, 판정 불일치 화면이 양쪽 다
      「아직 없습니다」로 떴다(09-23 확인). 엇갈린 것을 보고 처분하라는
      화면인데 정작 무엇이 엇갈렸는지가 안 보였다.

    ⚠ 목록(DiscordanceListView)은 얕은 채로 둔다 — 거기는 건수와 처분
      여부만 보면 되고, 행마다 이걸 펴면 목록이 무거워진다.
    """

    patient = serializers.SerializerMethodField()
    lesion = serializers.SerializerMethodField()
    radiology_reading = serializers.SerializerMethodField()
    pathology_reading = serializers.SerializerMethodField()

    def get_patient(self, obj):
        patient = getattr(obj.lesion, "patient", None) if obj.lesion else None
        if patient is None:
            return None
        pii = getattr(patient, "pii", None)
        return {
            "patient_id": patient.patient_id,
            "patient_no": patient.patient_number,
            "patient_name": getattr(pii, "name", None),
            "sex": patient.sex,
            "age": patient.birth_year and (timezone.now().year - patient.birth_year),
        }

    def get_lesion(self, obj):
        les = obj.lesion
        if les is None:
            return None
        # 잰 값이 먼저다. AI 값은 사람이 확인하기 전의 값이라 뒤에 온다.
        size = les.measured_size_mm if les.measured_size_mm is not None else les.ai_size_mm
        return {
            "lesion_id": les.lesion_id,
            "site": les.label,
            "size_mm": size,
        }

    def get_radiology_reading(self, obj):
        a = obj.assessment
        if a is None:
            return None
        return {
            "assessment": a.category,          # BI-RADS
            "finding": a.finding_note,
            "read_at": a.finalized_at,
            "assessor": _staff_name(a.assessed_by),
        }

    def get_pathology_reading(self, obj):
        sp = obj.specimen
        if sp is None:
            return None
        return {
            "assessment": sp.b_category,       # B 분류
            "finding": sp.diagnosis,
            "read_at": sp.finalized_at,
            "assessor": _staff_name(sp.assigned_to),
        }


class SpecimenSerializer(serializers.ModelSerializer):
    """serializers.SpecimenSerializer 로 패키지 전체(병리·유방외과)가 쓴다
    — core/serializers/__init__.py 가 이 클래스만 재수출한다. 병리 판독
    화면(toRead)이 환자 이름·나이·성별을 따로 조회하지 않게 StudySerializer
    와 같은 계산 필드를 둔다(09-18 백엔드 대조 ③)."""

    patient_name = serializers.CharField(
        source="patient.pii.name", read_only=True, default=None
    )
    age = serializers.SerializerMethodField()
    sex = serializers.CharField(source="patient.sex", read_only=True, allow_null=True)
    # 09-28 — 병리 목록이 행마다 환자 · 직원을 따로 부르지 않게
    patient_number = serializers.CharField(
        source="patient.patient_number", read_only=True, default=None)
    bound_by_name = serializers.CharField(
        source="bound_by.full_name", read_only=True, default=None, allow_null=True)
    # 09-28 — 이 검체를 집은 병리의. 오더 쪽과 같은 사정이다(assigned_to 가
    # FK 라 번호로만 나가서 목록의 담당자 칸이 비어 있었다).
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default=None, allow_null=True)
    # 「유방외과 열람」 — 목록 쿼리셋이 얹는 값(core/viewed.py)
    viewed_at = serializers.DateTimeField(read_only=True, default=None)

    def get_age(self, obj) -> int | None:
        pii = getattr(obj.patient, "pii", None)
        birth_date = getattr(pii, "birth_date", None)
        if birth_date is None:
            return None

        reference = obj.collected_at or timezone.now()
        reference_date = reference.date()
        return reference_date.year - birth_date.year - (
            (reference_date.month, reference_date.day)
            < (birth_date.month, birth_date.day)
        )

    class Meta:
        model = models.Specimen
        exclude = AUDIT_FIELDS


class LesionSerializer(serializers.ModelSerializer):
    # 병변 3D 메시(JSON) 위치 — 화면이 파생물 티켓으로 받는다. 없으면 None
    mesh = serializers.SerializerMethodField()

    class Meta:
        model = models.Lesion
        # malignancy_p(악성 확률)는 화면 비노출 — core.serializers 가 이 클래스를
        # 재수출하므로(radiology 것을 덮는다) 여기서도 반드시 뺀다
        exclude = AUDIT_FIELDS + ("malignancy_p",)

    # 검체 바인딩 목록에서 「어느 검사의 병변인지」를 보인다(09-28)
    study_date = serializers.SerializerMethodField()

    def get_study_date(self, obj):
        st = obj.study
        when = st.performed_at or st.created_at if st else None
        return timezone.localdate(when).isoformat() if when else None

    def get_mesh(self, obj):
        img = (obj.images.filter(kind="mesh_lesion", deleted_at__isnull=True)
               .order_by("-image_id").first())
        return mesh_spec(img, obj.study_id)


def mesh_spec(img, study_id):
    """화면 files.js 가 받는 파생물 주소 모양"""
    if not img or not img.object_key:
        return None
    return {"key": img.object_key, "derived": True, "study_id": study_id}


# ── 워크플로 액션 전용 ──────────────────────────────────

class ExamOrderRequestSerializer(serializers.Serializer):
    """POST /exam-orders — §1 촬영 요청 팝업."""

    patient_id = serializers.IntegerField()
    modality = serializers.ChoiceField(choices=models.as_choices(models.MODALITY))
    exam_purpose = serializers.ChoiceField(choices=models.as_choices(models.EXAM_PURPOSE))
    order_note = serializers.CharField(required=False, allow_blank=True)


class SurgeryDecisionSerializer(serializers.Serializer):
    """PATCH /assessments/{id}/decision — §3 수술 여부·사유. assessment.decision_* 사용."""

    decision_type = serializers.ChoiceField(choices=models.as_choices(models.DECISION_TYPE))
    decision_value = serializers.ChoiceField(choices=models.as_choices(models.DECISION_VALUE))
    decision_reason = serializers.CharField(required=False, allow_blank=True)


class ReportExplainSerializer(serializers.Serializer):
    """PATCH /reports/{id}/explain — §3 환자 설명 기록."""

    explain_method = serializers.ChoiceField(choices=models.as_choices(models.EXPLAIN_METHOD))
    patient_confirmed = serializers.BooleanField()
    # 09-28 — 화면이 보내던 설명 내용. 모델 칸이 없어 content_json 에 둔다
    explain_content = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class SpecimenBindSerializer(serializers.Serializer):
    """POST /specimens — §4 검체 바인딩. lesion_id NOT NULL."""

    lesion_id = serializers.IntegerField()
    # 09-28 — 비우면 서버가 만든다(views/surgery.py specimen_label_for). 사람마다
    # 다르게 적어 같은 검체가 다른 이름이 되던 것을 막는다. 적어 보내면 그대로 쓴다
    specimen_label = serializers.CharField(max_length=50, required=False, allow_blank=True)
    specimen_type = serializers.ChoiceField(choices=models.as_choices(models.SPECIMEN_TYPE))
    guidance_route = serializers.ChoiceField(choices=models.as_choices(models.GUIDANCE_ROUTE))
    collected_at = serializers.DateTimeField()
    # 09-28 — 유방외과 의뢰 문구(선택). 모델 칸 specimen.clinical_note
    clinical_note = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_specimen_label(self, value):
        if value and models.Specimen.objects.filter(specimen_label=value).exists():
            raise serializers.ValidationError("이미 사용 중인 검체 라벨입니다.")
        return value

    def validate_lesion_id(self, value):
        if not models.Lesion.objects.filter(pk=value).exists():
            raise serializers.ValidationError("존재하지 않는 병변입니다.")
        return value


class DiscordanceDisposeSerializer(serializers.Serializer):
    """PATCH /discordances/{id}/dispose — §5 불일치 처분."""

    disposition_type = serializers.ChoiceField(choices=models.as_choices(models.DISPOSITION_TYPE))
    disposition_reason = serializers.CharField()

    def validate_disposition_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("처분 사유는 필수입니다.")
        return value


class PrescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Prescription
        exclude = AUDIT_FIELDS


class PrescriptionCreateSerializer(serializers.Serializer):
    """POST /patients/{id}/prescriptions — 처방 생성.

    exam_order_id · report_id 중 **정확히 하나**만 받는다 — Prescription
    의 owner CHECK(exam_order/report 중 하나)과 짝이다. 어느 환자 것인지는
    URL 의 patient pk 로 이미 정해지므로 여기서는 안 받는다 — 뷰가 그
    오더/리포트가 실제로 이 환자 것인지 대조한다."""

    exam_order_id = serializers.IntegerField(required=False)
    report_id = serializers.IntegerField(required=False)
    content = serializers.JSONField(required=False)

    def validate(self, attrs):
        has_order = attrs.get("exam_order_id") is not None
        has_report = attrs.get("report_id") is not None
        if has_order == has_report:
            raise serializers.ValidationError(
                "exam_order_id 또는 report_id 중 하나만 지정해야 합니다.")
        return attrs