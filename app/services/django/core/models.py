"""
EMPATHO CDSS 데이터 모델 — v10 · 18개 테이블.

기준 문서 — DB_스키마_v10_20260908.docx

"""

from django.db import models
from django.db.models import Q


def as_choices(values):
    return [(v, v) for v in values]


# CHECK 으로 거는 값 집합
ROLE = ["admin", "reception", "nursing", "radiology", "surgery", "pathology", "patient"]
DOC_TYPE = ["terms", "privacy", "sensitive_health", "marketing"]
FOLLOWUP_STATUS = ["open", "resolved", "escalated", "declined", "overdue"]
EXAM_PURPOSE = ["screening", "diagnostic"]
MODALITY = ["mammo", "us", "mri"]
ORDER_STATUS = ["ordered", "accepted", "in_progress", "completed", "cancelled"]
READ_STATUS = ["pending", "first_locked", "ai_revealed", "finalized"]
IMAGE_KIND = ["mask", "overlay", "mesh", "heatmap", "thumbnail"]
READ_STAGE = ["first", "final"]
ACCESSION_STATUS = ["unbound", "bound", "accessioned"]
DIAGNOSIS = ["benign", "malignant"]
B_CATEGORY = ["b1", "b2", "b3", "b4", "b5"]
NOTIFICATION_TYPE = ["followup", "discordance", "report_ready",
                     "reservation_created", "reservation_changed"]
DISPOSITION_TYPE = ["rebiopsy", "excision", "no_action"]

# choices 로만 두는 값 집합
CONSENT_CHANNEL = ["app", "paper", "counter"]
ROUND_RESULT = ["stable", "changed", "no_show"]
CALL_RESULT = ["연결", "부재", "거부"]
QUALITY_STATUS = ["accepted", "rejected"]
DENSITY_CATEGORY = ["a", "b", "c", "d"]
LATERALITY = ["left", "right"]
VIEW_POSITION = ["CC", "MLO"]
STAIN_TYPE = ["he", "ihc"]
SOCKET_ID = ["1", "2", "3", "4", "4b", "5", "6", "7"]
SOCKET_NAME = ["us", "mammo", "mri", "pathology"]
RUN_STATUS = ["queued", "running", "done", "failed"]
LESION_KIND = ["mass", "calcification"]
AI_OR_MANUAL = ["ai", "manual"]
GRADE_CONFIDENCE = ["높음", "보통", "낮음"]
BIRADS_CATEGORY = ["0", "1", "2", "3", "4a", "4b", "4c", "5", "6"]
PATH_AGREEMENT = ["match", "one_step", "two_step", "not_applicable"]
DECISION_TYPE = ["surgery", "biopsy", "imaging", "rebiopsy"]
DECISION_VALUE = ["yes", "no", "defer"]
SPECIMEN_TYPE = ["core_needle", "surgical"]
GUIDANCE_ROUTE = ["ultrasound", "stereotactic", "mri", "localization"]
STIL_LEVEL = ["low", "mid", "high"]
STROMA_STATUS = ["ok", "absent"]
VIOLATED_RULE = ["rule1", "rule2", "rule3", "rule4", "rule5"]
FLAG_STATUS = ["pass", "sev1", "sev2", "review", "unbindable"]
REVIEW_OPINION = ["agree", "object"]
REPORT_TYPE = ["stage", "final"]
AUDIENCE = ["clinician", "patient"]
REPORT_SOCKET_ID = ["1", "3", "4", "4b", "7"]
EXPLAIN_METHOD = ["대면", "유선", "영상"]
SEVERITY = ["sev1", "normal"]
NOTIFICATION_CHANNEL = ["app", "sms", "call_queue"]
REF_TYPE = ["assessment", "discordance_flag", "report", "exam_order"]


class AuditBase(models.Model):
    """전 테이블 공통 감사 컬럼."""

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('Account', models.PROTECT, blank=True, null=True,
                                   related_name='+', db_column='created_by')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('Account', models.PROTECT, blank=True, null=True,
                                   related_name='+', db_column='updated_by')

    class Meta:
        abstract = True


class Account(AuditBase):
    """로그인 계정. 환자와 의료진이 같은 표에 있고 role 로 갈린다."""

    account_id = models.BigAutoField(primary_key=True)
    login_id = models.CharField(unique=True, max_length=50, blank=True, null=True)
    password_hash = models.CharField(max_length=255, blank=True, null=True)
    role = models.CharField(max_length=20, choices=as_choices(ROLE))
    is_active = models.BooleanField(default=True, db_default=True,
                                    blank=True, null=True)
    phone_verified = models.BooleanField(blank=True, null=True)
    push_token = models.CharField(max_length=255, blank=True, null=True)
    last_login_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'account'
        constraints = [
            models.CheckConstraint(condition=Q(role__in=ROLE), name='account_role_ck'),
        ]


class Staff(AuditBase):
    """의료진 신원. 계정과 권한(role)은 account 에, 여기는 이름 · 직원번호 · 승인 기록."""

    staff_id = models.BigAutoField(primary_key=True)
    account = models.OneToOneField(Account, models.PROTECT, related_name='staff')
    staff_number = models.CharField(unique=True, max_length=50, blank=True, null=True)
    full_name = models.CharField(max_length=50, blank=True, null=True)
    approved_by = models.ForeignKey('self', models.PROTECT, blank=True, null=True,
                                    related_name='+', db_column='approved_by')
    approved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'staff'


class Patient(AuditBase):
    """환자. 조회의 출발점. 개인정보는 patient_pii 에, 추적 상태는 followup 에 따로."""

    patient_id = models.BigAutoField(primary_key=True)
    account = models.OneToOneField(Account, models.PROTECT, blank=True, null=True,
                                   related_name='patient')   # null = 앱 미가입
    patient_number = models.CharField(unique=True, max_length=50)
    sex = models.CharField(max_length=20, blank=True, null=True)
    birth_year = models.IntegerField(blank=True, null=True)
    has_allergy = models.BooleanField(blank=True, null=True)
    allergy_note = models.CharField(max_length=250, blank=True, null=True)
    questionnaire = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = 'patient'


class PatientPii(AuditBase):
    """이름 · 생년월일 · 전화. patient 와 1:1."""

    patient = models.OneToOneField(Patient, models.PROTECT, primary_key=True,
                                   db_column='patient_id', related_name='pii')
    name = models.CharField(max_length=50, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    phone = models.CharField(unique=True, max_length=30, blank=True, null=True)

    class Meta:
        db_table = 'patient_pii'


class Consent(AuditBase):
    """동의 1건. 어느 계정이 어느 문서의 어느 판에 언제 동의(또는 거부)했나."""

    consent_id = models.BigAutoField(primary_key=True)
    account = models.ForeignKey(Account, models.PROTECT, blank=True, null=True,
                                related_name='consents')
    doc_type = models.CharField(max_length=30, choices=as_choices(DOC_TYPE))
    doc_version = models.CharField(max_length=20)
    doc_sha256 = models.CharField(max_length=64)
    agreed = models.BooleanField()          # 거부도 기록한다
    agreed_at = models.DateTimeField()
    channel = models.CharField(max_length=20, choices=as_choices(CONSENT_CHANNEL),
                               blank=True, null=True)
    withdrawn_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'consent'
        constraints = [
            models.CheckConstraint(condition=Q(doc_type__in=DOC_TYPE),
                                   name='consent_doc_type_ck'),
            models.UniqueConstraint(fields=['account', 'doc_type', 'doc_version'],
                                    name='consent_account_doc_version_uk'),
        ]


class Followup(AuditBase):
    """BI-RADS 3 환자의 추적 회차. 회차마다 행 하나."""

    followup_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True,
                                related_name='followups')
    round_no = models.IntegerField()
    status = models.CharField(max_length=20, choices=as_choices(FOLLOWUP_STATUS))
    started_at = models.DateTimeField(blank=True, null=True)
    due_at = models.DateTimeField(blank=True, null=True, db_index=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    closed_reason = models.CharField(max_length=100, blank=True, null=True)
    round_result = models.CharField(max_length=20, choices=as_choices(ROUND_RESULT),
                                    blank=True, null=True)
    call_result = models.CharField(max_length=20, choices=as_choices(CALL_RESULT),
                                   blank=True, null=True)
    call_note = models.CharField(max_length=250, blank=True, null=True)
    called_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                  related_name='+', db_column='called_by')
    called_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'followup'
        constraints = [
            models.CheckConstraint(condition=Q(status__in=FOLLOWUP_STATUS),
                                   name='followup_status_ck'),
        ]


class ExamOrder(AuditBase):
    """검사 오더. 예약과 재촬영 연결을 함께 갖는다."""

    exam_order_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True,
                                related_name='exam_orders')
    exam_purpose = models.CharField(max_length=20, choices=as_choices(EXAM_PURPOSE))
    modality = models.CharField(max_length=20, choices=as_choices(MODALITY))
    order_status = models.CharField(max_length=20, choices=as_choices(ORDER_STATUS))
    ordered_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                   related_name='+', db_column='ordered_by')
    ordered_at = models.DateTimeField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True)
    visited_at = models.DateTimeField(blank=True, null=True)   # null = 노쇼
    parent_order = models.ForeignKey('self', models.SET_NULL, blank=True, null=True,
                                     related_name='+', db_column='parent_order_id')
    followup = models.ForeignKey(Followup, models.PROTECT, blank=True, null=True,
                                 related_name='exam_orders')

    class Meta:
        db_table = 'exam_order'
        constraints = [
            models.CheckConstraint(condition=Q(exam_purpose__in=EXAM_PURPOSE),
                                   name='exam_order_purpose_ck'),
            models.CheckConstraint(condition=Q(modality__in=MODALITY),
                                   name='exam_order_modality_ck'),
            models.CheckConstraint(condition=Q(order_status__in=ORDER_STATUS),
                                   name='exam_order_status_ck'),
        ]


class Study(AuditBase):
    """DICOM Study 1건. 한 번 촬영한 것 전체."""

    study_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='studies')
    exam_order = models.ForeignKey(ExamOrder, models.PROTECT, related_name='studies')
    modality = models.CharField(max_length=20, choices=as_choices(MODALITY))
    study_uid = models.CharField(unique=True, max_length=100, blank=True, null=True)
    orthanc_study_id = models.CharField(max_length=100, blank=True, null=True)
    device_name = models.CharField(max_length=100, blank=True, null=True)
    quality_status = models.CharField(max_length=20, choices=as_choices(QUALITY_STATUS),
                                      blank=True, null=True)
    performed_at = models.DateTimeField(blank=True, null=True)
    density_percent = models.DecimalField(max_digits=5, decimal_places=2,
                                          blank=True, null=True)
    density_category = models.CharField(max_length=10,
                                        choices=as_choices(DENSITY_CATEGORY),
                                        blank=True, null=True)
    read_status = models.CharField(max_length=20, choices=as_choices(READ_STATUS),
                                   default='pending', db_default='pending',
                                   blank=True, null=True)

    class Meta:
        db_table = 'study'
        constraints = [
            models.CheckConstraint(condition=Q(modality__in=MODALITY),
                                   name='study_modality_ck'),
            models.CheckConstraint(
                condition=Q(read_status__in=READ_STATUS) | Q(read_status__isnull=True),
                name='study_read_status_ck'),
        ]


class StorageObject(AuditBase):
    """원본 시리즈 · 파일 1개. 주소와 촬영 정보."""

    storage_object_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey(Study, models.PROTECT, blank=True, null=True,
                              related_name='storage_objects')      # 영상
    specimen = models.ForeignKey('Specimen', models.PROTECT, blank=True, null=True,
                                 related_name='storage_objects')   # 병리
    series_uid = models.CharField(unique=True, max_length=100, blank=True, null=True)
    series_role = models.CharField(max_length=30, blank=True, null=True)
    orthanc_series_id = models.CharField(max_length=100, blank=True, null=True)
    bucket = models.CharField(max_length=100, blank=True, null=True)
    object_key = models.CharField(unique=True, max_length=255, blank=True, null=True)
    laterality = models.CharField(max_length=10, choices=as_choices(LATERALITY),
                                  blank=True, null=True)
    view_position = models.CharField(max_length=20, choices=as_choices(VIEW_POSITION),
                                     blank=True, null=True)
    pixel_spacing_mm = models.DecimalField(max_digits=6, decimal_places=4,
                                           blank=True, null=True)
    width_px = models.IntegerField(blank=True, null=True)
    height_px = models.IntegerField(blank=True, null=True)
    has_geometry = models.BooleanField(blank=True, null=True)
    stain_type = models.CharField(max_length=10, choices=as_choices(STAIN_TYPE),
                                  blank=True, null=True)
    scan_magnification = models.CharField(max_length=10, blank=True, null=True)
    mpp = models.DecimalField(max_digits=6, decimal_places=4, blank=True, null=True)
    content_type = models.CharField(max_length=100, blank=True, null=True)
    byte_size = models.BigIntegerField(blank=True, null=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)   # 소프트 삭제

    class Meta:
        db_table = 'storage_object'
        constraints = [
            # 주소는 Orthanc 아니면 Garage, 정확히 하나
            models.CheckConstraint(
                condition=(Q(orthanc_series_id__isnull=False) & Q(object_key__isnull=True))
                | (Q(orthanc_series_id__isnull=True) & Q(object_key__isnull=False)),
                name='storage_object_address_ck'),
            # 영상 아니면 병리, 정확히 하나
            models.CheckConstraint(
                condition=(Q(study__isnull=False) & Q(specimen__isnull=True))
                | (Q(study__isnull=True) & Q(specimen__isnull=False)),
                name='storage_object_owner_ck'),
        ]


class Image(AuditBase):
    """모델이 낸 파일과 썸네일. 전부 Garage empatho-derived."""

    image_id = models.BigAutoField(primary_key=True)
    source_object = models.ForeignKey(StorageObject, models.PROTECT,
                                      related_name='images',
                                      db_column='source_object_id')
    ai_result = models.ForeignKey('AiResult', models.PROTECT, blank=True, null=True,
                                  related_name='images')   # 썸네일은 null
    lesion = models.ForeignKey('Lesion', models.PROTECT, blank=True, null=True,
                               related_name='images')
    kind = models.CharField(max_length=20, choices=as_choices(IMAGE_KIND))
    frame = models.CharField(max_length=30, blank=True, null=True)
    bucket = models.CharField(max_length=100, blank=True, null=True)
    object_key = models.CharField(unique=True, max_length=255, blank=True, null=True)
    width_px = models.IntegerField(blank=True, null=True)
    height_px = models.IntegerField(blank=True, null=True)
    content_type = models.CharField(max_length=100, blank=True, null=True)
    byte_size = models.BigIntegerField(blank=True, null=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'image'
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=IMAGE_KIND),
                                   name='image_kind_ck'),
        ]


class AiModel(AuditBase):
    """모델 카탈로그. 어느 소켓에 어느 이름 · 어느 판이 배포돼 있나."""

    # 클래스 이름만 AiModel 이다 — Model 은 models.Model 과 헷갈린다.
    model_id = models.BigAutoField(primary_key=True)
    socket_id = models.CharField(max_length=5, choices=as_choices(SOCKET_ID),
                                 blank=True, null=True)
    socket_name = models.CharField(max_length=20, choices=as_choices(SOCKET_NAME),
                                   blank=True, null=True)
    model_name = models.CharField(max_length=50, blank=True, null=True)
    model_version = models.CharField(max_length=100, blank=True, null=True)
    lora_version = models.CharField(max_length=100, blank=True, null=True)
    threshold_version = models.CharField(max_length=30, blank=True, null=True)
    operating_point = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(blank=True, null=True)
    registered_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'model'


class AiResult(AuditBase):
    """AI 실행 1회. 어느 원본을 어느 모델로 돌렸고 무엇이 나왔나."""

    ai_result_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='ai_results')
    study = models.ForeignKey(Study, models.PROTECT, related_name='ai_results')
    # 맘모 · 초음파는 필수, MRI 는 null 또는 조영 전 시리즈
    source_object = models.ForeignKey(StorageObject, models.PROTECT,
                                      blank=True, null=True,
                                      related_name='ai_results',
                                      db_column='source_object_id')
    model = models.ForeignKey(AiModel, models.PROTECT, blank=True, null=True,
                              related_name='ai_results')
    result = models.JSONField(blank=True, null=True)
    abstained = models.BooleanField(blank=True, null=True)      # 봉투 기권
    abstain_reason = models.CharField(max_length=100, blank=True, null=True)
    run_status = models.CharField(max_length=20, choices=as_choices(RUN_STATUS),
                                  blank=True, null=True)
    requested_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                     related_name='+', db_column='requested_by')
    analyzed_at = models.DateTimeField(blank=True, null=True)
    elapsed_sec = models.DecimalField(max_digits=8, decimal_places=3,
                                      blank=True, null=True)

    class Meta:
        db_table = 'ai_result'


class Lesion(AuditBase):
    """병변 1개. 판정 · 검체 · 대조가 모두 여기에 붙는 허브다."""

    lesion_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey(Study, models.PROTECT, related_name='lesions')
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='lesions')
    ai_result = models.ForeignKey(AiResult, models.PROTECT, blank=True, null=True,
                                  related_name='lesions')   # null = 사람이 추가
    modality = models.CharField(max_length=20, choices=as_choices(MODALITY),
                                blank=True, null=True)
    lesion_kind = models.CharField(max_length=20, choices=as_choices(LESION_KIND),
                                   blank=True, null=True)
    lesion_index = models.IntegerField(blank=True, null=True)
    label = models.CharField(max_length=50, blank=True, null=True)
    lesion_source = models.CharField(max_length=20, choices=as_choices(AI_OR_MANUAL),
                                     blank=True, null=True)
    birads_model = models.CharField(max_length=10, blank=True, null=True)
    grade_confidence = models.CharField(max_length=10,
                                        choices=as_choices(GRADE_CONFIDENCE),
                                        blank=True, null=True)
    certainty = models.DecimalField(max_digits=5, decimal_places=3,
                                    blank=True, null=True)
    malignancy_p = models.DecimalField(max_digits=4, decimal_places=3,
                                       blank=True, null=True)   # 화면 비노출
    # ai_* 는 AI 원본값이라 불변, measured_* 는 판독의 캘리퍼 측정값.
    # mm 쌍은 pixel_spacing 있는 모달리티(맘모 · MRI), px 쌍은 mm 로 못 바꾸는
    # 모달리티(초음파).
    ai_size_mm = models.DecimalField(max_digits=7, decimal_places=2,
                                     blank=True, null=True)
    measured_size_mm = models.DecimalField(max_digits=7, decimal_places=2,
                                           blank=True, null=True)
    ai_size_px = models.DecimalField(max_digits=7, decimal_places=1,
                                     blank=True, null=True)
    measured_size_px = models.DecimalField(max_digits=7, decimal_places=1,
                                           blank=True, null=True)
    # false = AI 가 mm 를 못 냈다 → 화면에 「미산출」
    ai_size_measurable = models.BooleanField(blank=True, null=True)
    mask_reliability = models.CharField(max_length=10, blank=True, null=True)
    # 판독의가 AI 병변을 「이건 아님」으로 표시
    is_false_positive = models.BooleanField(default=False, db_default=False)
    needs_additional_view = models.BooleanField(blank=True, null=True)
    additional_view_reason = models.CharField(max_length=250, blank=True, null=True)
    detail = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = 'lesion'


class Assessment(AuditBase):
    """판독의의 판정. 1차와 최종을 각각 행으로 보존한다."""

    assessment_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey(Study, models.PROTECT, related_name='assessments')
    lesion = models.ForeignKey(Lesion, models.PROTECT, blank=True, null=True,
                               related_name='assessments')  # null = study 전체
    read_stage = models.CharField(max_length=20, choices=as_choices(READ_STAGE))
    category = models.CharField(max_length=10, choices=as_choices(BIRADS_CATEGORY),
                                blank=True, null=True)
    category_model = models.CharField(max_length=10, blank=True, null=True)
    category_rule = models.CharField(max_length=10, blank=True, null=True)
    path_agreement = models.CharField(max_length=20, choices=as_choices(PATH_AGREEMENT),
                                      blank=True, null=True)
    recommendation = models.CharField(max_length=100, blank=True, null=True)
    recommendation_reason = models.CharField(max_length=250, blank=True, null=True)
    rule_table_version = models.CharField(max_length=30, blank=True, null=True)
    assessed_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='+', db_column='assessed_by')
    ai_revealed_at = models.DateTimeField(blank=True, null=True)
    finalized_at = models.DateTimeField(blank=True, null=True)
    superseded_by = models.ForeignKey('self', models.SET_NULL, blank=True, null=True,
                                      related_name='+', db_column='superseded_by')
    finding_note = models.TextField(blank=True, null=True)
    decision_type = models.CharField(max_length=20, choices=as_choices(DECISION_TYPE),
                                     blank=True, null=True)
    decision_value = models.CharField(max_length=20, choices=as_choices(DECISION_VALUE),
                                      blank=True, null=True)
    decision_reason = models.CharField(max_length=250, blank=True, null=True)
    decided_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                   related_name='+', db_column='decided_by')
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'assessment'
        constraints = [
            models.CheckConstraint(condition=Q(read_stage__in=READ_STAGE),
                                   name='assessment_read_stage_ck'),
        ]


class Specimen(AuditBase):
    """검체 1개와 그 병리 확진. 채취에서 확진까지 한 행이 자란다."""

    specimen_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='specimens')
    lesion = models.ForeignKey(Lesion, models.PROTECT, related_name='specimens')
    specimen_label = models.CharField(unique=True, max_length=50,
                                      blank=True, null=True)
    specimen_type = models.CharField(max_length=30, choices=as_choices(SPECIMEN_TYPE),
                                     blank=True, null=True)
    guidance_route = models.CharField(max_length=30, choices=as_choices(GUIDANCE_ROUTE),
                                      blank=True, null=True)
    target_snapshot = models.CharField(max_length=250, blank=True, null=True)
    accession_status = models.CharField(max_length=20,
                                        choices=as_choices(ACCESSION_STATUS))
    accessioned_at = models.DateTimeField(blank=True, null=True)
    bound_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                 related_name='+', db_column='bound_by')   # 간호
    collected_at = models.DateTimeField(blank=True, null=True)
    diagnosis = models.CharField(max_length=20, choices=as_choices(DIAGNOSIS),
                                 blank=True, null=True)
    b_category = models.CharField(max_length=10, choices=as_choices(B_CATEGORY),
                                  blank=True, null=True)
    diagnosis_code = models.CharField(max_length=20, blank=True, null=True)
    histologic_type = models.CharField(max_length=50, blank=True, null=True)
    nottingham_grade = models.IntegerField(blank=True, null=True)
    er_status = models.CharField(max_length=20, blank=True, null=True)
    pr_status = models.CharField(max_length=20, blank=True, null=True)
    her2_status = models.CharField(max_length=20, blank=True, null=True)
    ki67_percent = models.DecimalField(max_digits=5, decimal_places=2,
                                       blank=True, null=True)
    stil_nucleus = models.DecimalField(max_digits=5, decimal_places=2,
                                       blank=True, null=True)   # 화면 비노출
    stil_calibrated = models.DecimalField(max_digits=5, decimal_places=2,
                                          blank=True, null=True)
    stil_level = models.CharField(max_length=10, choices=as_choices(STIL_LEVEL),
                                  blank=True, null=True)
    stil_interval_low = models.DecimalField(max_digits=5, decimal_places=2,
                                            blank=True, null=True)
    stil_interval_high = models.DecimalField(max_digits=5, decimal_places=2,
                                             blank=True, null=True)
    stil_source = models.CharField(max_length=20, choices=as_choices(AI_OR_MANUAL),
                                   blank=True, null=True)
    stroma_status = models.CharField(max_length=10, choices=as_choices(STROMA_STATUS),
                                     blank=True, null=True)
    tsr_percent = models.DecimalField(max_digits=5, decimal_places=2,
                                      blank=True, null=True)
    cell_counts = models.JSONField(blank=True, null=True)
    reported_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='+', db_column='reported_by')
    finalized_at = models.DateTimeField(blank=True, null=True)  # 자동 대조 트리거
    finding_note = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'specimen'
        constraints = [
            models.CheckConstraint(condition=Q(accession_status__in=ACCESSION_STATUS),
                                   name='specimen_accession_status_ck'),
            models.CheckConstraint(
                condition=Q(diagnosis__in=DIAGNOSIS) | Q(diagnosis__isnull=True),
                name='specimen_diagnosis_ck'),
            models.CheckConstraint(
                condition=Q(b_category__in=B_CATEGORY) | Q(b_category__isnull=True),
                name='specimen_b_category_ck'),
        ]


class DiscordanceFlag(AuditBase):
    """영상 최종 판정과 병리 확진의 자동 대조 결과. 병변 단위."""

    discordance_flag_id = models.BigAutoField(primary_key=True)
    lesion = models.ForeignKey(Lesion, models.PROTECT, blank=True, null=True,
                               related_name='discordance_flags')
    specimen = models.ForeignKey(Specimen, models.PROTECT, blank=True, null=True,
                                 related_name='discordance_flags')
    assessment = models.ForeignKey(Assessment, models.PROTECT, blank=True, null=True,
                                   related_name='discordance_flags')   # final
    violated_rule = models.CharField(max_length=20,          # null = 일치
                                     choices=as_choices(VIOLATED_RULE),
                                     blank=True, null=True)
    flag_status = models.CharField(max_length=20, choices=as_choices(FLAG_STATUS),
                                   blank=True, null=True)
    rule_table_version = models.CharField(max_length=30, blank=True, null=True)
    flagged_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='+', db_column='reviewed_by')
    review_opinion = models.CharField(max_length=20, choices=as_choices(REVIEW_OPINION),
                                      blank=True, null=True)
    review_note = models.CharField(max_length=250, blank=True, null=True)
    disposition_type = models.CharField(max_length=20,
                                        choices=as_choices(DISPOSITION_TYPE),
                                        blank=True, null=True)
    disposition_reason = models.CharField(max_length=250, blank=True, null=True)
    disposed_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='+', db_column='disposed_by')
    closed_at = models.DateTimeField(blank=True, null=True)
    superseded_by = models.ForeignKey('self', models.SET_NULL, blank=True, null=True,
                                      related_name='+', db_column='superseded_by')

    class Meta:
        db_table = 'discordance_flag'
        constraints = [
            models.CheckConstraint(
                condition=Q(disposition_type__in=DISPOSITION_TYPE)
                | Q(disposition_type__isnull=True),
                name='discordance_flag_disposition_type_ck'),
        ]


class Report(AuditBase):
    """리포트 1건. 검사별(stage)과 종합(final), 의료진용과 환자용."""

    report_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey(Study, models.PROTECT, blank=True, null=True,
                              related_name='reports')   # 종합 리포트는 null
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='reports')
    report_type = models.CharField(max_length=20, choices=as_choices(REPORT_TYPE),
                                   blank=True, null=True)
    audience = models.CharField(max_length=20, choices=as_choices(AUDIENCE),
                                blank=True, null=True)
    socket_id = models.CharField(max_length=5, choices=as_choices(REPORT_SOCKET_ID),
                                 blank=True, null=True)
    narrative_text = models.TextField(blank=True, null=True)
    content_json = models.JSONField(blank=True, null=True)
    evidence_links = models.JSONField(blank=True, null=True)
    dropped_sentences = models.JSONField(blank=True, null=True)
    notes = models.JSONField(blank=True, null=True)
    prompt_version = models.CharField(max_length=50, blank=True, null=True)
    fallback = models.BooleanField(blank=True, null=True)     # true = 뼈대 문장
    lock_status = models.CharField(max_length=20, default='locked',
                                   db_default='locked', blank=True, null=True)
    unlocked_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='+', db_column='unlocked_by')
    unlocked_at = models.DateTimeField(blank=True, null=True)
    unlock_reason = models.CharField(max_length=250, blank=True, null=True)
    issued_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                  related_name='+', db_column='issued_by')
    pdf_bucket = models.CharField(max_length=100, blank=True, null=True)
    pdf_object_key = models.CharField(unique=True, max_length=255,
                                      blank=True, null=True)
    explained_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                     related_name='+', db_column='explained_by')
    explained_at = models.DateTimeField(blank=True, null=True)  # 잠금 해제 트리거
    explain_method = models.CharField(max_length=20, choices=as_choices(EXPLAIN_METHOD),
                                      blank=True, null=True)
    patient_confirmed = models.BooleanField(blank=True, null=True)
    last_viewed_at = models.DateTimeField(blank=True, null=True)
    view_count = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = 'report'


class Notification(AuditBase):
    """알림 발송 · 확인 이력. 환자 또는 의료진 하나가 수신자."""

    notification_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True,
                                related_name='notifications')
    staff = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                              related_name='notifications')
    notification_type = models.CharField(max_length=30,
                                         choices=as_choices(NOTIFICATION_TYPE))
    severity = models.CharField(max_length=20, choices=as_choices(SEVERITY),
                                blank=True, null=True)
    channel = models.CharField(max_length=20,
                               choices=as_choices(NOTIFICATION_CHANNEL),
                               blank=True, null=True)
    message = models.TextField()          # 보낸 문장 그대로
    ref_type = models.CharField(max_length=30, choices=as_choices(REF_TYPE),
                                blank=True, null=True)
    ref_id = models.BigIntegerField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    acknowledged_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'notification'
        constraints = [
            models.CheckConstraint(condition=Q(notification_type__in=NOTIFICATION_TYPE),
                                   name='notification_type_ck'),
            # 환자 아니면 의료진, 정확히 하나
            models.CheckConstraint(
                condition=(Q(patient__isnull=False) & Q(staff__isnull=True))
                | (Q(patient__isnull=True) & Q(staff__isnull=False)),
                name='notification_recipient_ck'),
        ]
