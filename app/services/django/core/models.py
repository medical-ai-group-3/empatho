"""
CDSS 데이터 모델 — 35개 테이블.

DB 스키마(SQL)가 원본이고 이 파일은 그것을 Django 로 옮긴 것이다.
스키마를 바꿀 때는 SQL 과 이 파일을 함께 고치고 makemigrations 로 대조할 것.

on_delete 규칙
    PROTECT     기본. 의료 기록이라 참조가 걸린 행은 지우지 못하게 막는다.
                DO_NOTHING 과 달리 Django 단계에서 ProtectedError 로 원인을 알려준다.
    SET_NULL    자기 참조 3건(superseded_by · parent_order)만. 체인이 끊겨도 본체는 남는다.
    CASCADE     쓰지 않는다. 연쇄 삭제는 사고로 이어진다.

storage_object 는 deleted_at 을 두어 소프트 삭제가 원칙이다.
모델 순서는 FK 의존 순서(참조되는 쪽이 먼저)다.
"""

from django.db import models


# audit_metric — 감사지표 6종   [공통·선택·7컬럼]
class AuditMetric(models.Model):
    audit_metric_id = models.BigAutoField(primary_key=True)
    metric_name = models.CharField(max_length=50, blank=True, null=True)
    exam_purpose = models.CharField(max_length=20, blank=True, null=True)
    period_start = models.DateField(blank=True, null=True)
    period_end = models.DateField(blank=True, null=True)
    metric_value = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    computed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'audit_metric'

# patient — 조회의 출발점   [환자·필수·8컬럼]
class Patient(models.Model):
    patient_id = models.BigAutoField(primary_key=True)
    patient_number = models.CharField(unique=True, max_length=50)
    birth_year = models.IntegerField(blank=True, null=True)
    sex = models.CharField(max_length=20, blank=True, null=True)
    has_allergy = models.BooleanField(blank=True, null=True)
    allergy_note = models.CharField(max_length=250, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'patient'

# pharmacy — 외부 API 응답 캐시 겸 마스터 · 없어도 기능은 돈다   [처방·선택·10컬럼]
class Pharmacy(models.Model):
    pharmacy_id = models.BigAutoField(primary_key=True)
    external_key = models.CharField(unique=True, max_length=100, blank=True, null=True)
    pharmacy_name = models.CharField(max_length=100)
    address = models.CharField(max_length=250, blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    business_hours = models.TextField(blank=True, null=True)
    is_holiday_open = models.BooleanField(blank=True, null=True)
    synced_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'pharmacy'

# staff — 사용자 (user 는 예약어)   [공통·필수·10컬럼]
class Staff(models.Model):
    staff_id = models.BigAutoField(primary_key=True)
    login_name = models.CharField(unique=True, max_length=50)
    display_name = models.CharField(max_length=50, blank=True, null=True)
    department = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(blank=True, null=True)
    email = models.CharField(unique=True, max_length=100, blank=True, null=True)
    password_hash = models.CharField(max_length=255)
    staff_position = models.CharField(max_length=30, blank=True, null=True)
    account_status = models.CharField(max_length=20, blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'staff'

# storage_object — 파일 주소만 저장 · 실물은 스토리지   [영상·필수·9컬럼]
class StorageObject(models.Model):
    storage_object_id = models.BigAutoField(primary_key=True)
    bucket = models.CharField(max_length=100, blank=True, null=True)
    object_key = models.CharField(unique=True, max_length=255)
    content_type = models.CharField(max_length=100, blank=True, null=True)
    byte_size = models.BigIntegerField(blank=True, null=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, null=True)
    storage_class = models.CharField(max_length=20, blank=True, null=True)
    uploaded_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'storage_object'

# chat_session — MVP 범위 밖 권장   [챗봇·선택·6컬럼]
class ChatSession(models.Model):
    chat_session_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    channel = models.CharField(max_length=20, blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    escalated_to_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'chat_session'

# notification — 알림 · 발송 이력   [통보·선택·8컬럼]
class Notification(models.Model):
    notification_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    notification_type = models.CharField(max_length=30, blank=True, null=True)
    severity = models.CharField(max_length=20, blank=True, null=True)
    channel = models.CharField(max_length=20, blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    acknowledged_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'notification'

# patient_account — 환자 앱 로그인 · staff 와 절대 섞지 않는다   [계정·필수·8컬럼]
class PatientAccount(models.Model):
    patient_account_id = models.BigAutoField(primary_key=True)
    patient = models.OneToOneField(Patient, models.PROTECT)
    login_id = models.CharField(unique=True, max_length=50)
    password_hash = models.CharField(max_length=255)
    phone_verified = models.BooleanField(blank=True, null=True)
    push_token = models.CharField(max_length=255, blank=True, null=True)
    account_status = models.CharField(max_length=20, blank=True, null=True)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'patient_account'

# prescription — 발급된 처방전의 사본 — 내용은 우리가 만들지 않는다   [처방·필수·9컬럼]
class Prescription(models.Model):
    prescription_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True)
    prescribed_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    prescribed_at = models.DateTimeField()
    valid_until = models.DateField(blank=True, null=True)
    diagnosis_code = models.CharField(max_length=30, blank=True, null=True)
    prescription_status = models.CharField(max_length=20, blank=True, null=True)
    storage_object = models.ForeignKey('StorageObject', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'prescription'

# questionnaire — 문진 + 위험도 (별도 테이블 안 씀)   [환자·필수·12컬럼]
class Questionnaire(models.Model):
    questionnaire_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT)
    has_symptom = models.BooleanField(blank=True, null=True)
    symptom_detail = models.CharField(max_length=250, blank=True, null=True)
    family_history = models.CharField(max_length=250, blank=True, null=True)
    past_history = models.CharField(max_length=250, blank=True, null=True)
    menopause_status = models.CharField(max_length=50, blank=True, null=True)
    risk_model = models.CharField(max_length=50, blank=True, null=True)
    risk_lifetime_percent = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    risk_tier = models.CharField(max_length=50, blank=True, null=True)
    guideline_source = models.CharField(max_length=100, blank=True, null=True)
    answered_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'questionnaire'

# report — 리포트 + 열람 잠금   [리포트·필수·16컬럼]
class Report(models.Model):
    report_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True)
    report_type = models.CharField(max_length=20, blank=True, null=True)
    audience = models.CharField(max_length=20, blank=True, null=True)
    content_json = models.TextField(blank=True, null=True)
    narrative_text = models.TextField(blank=True, null=True)
    evidence_links = models.TextField(blank=True, null=True)
    dropped_sentence_log = models.TextField(blank=True, null=True)
    lock_status = models.CharField(max_length=20, blank=True, null=True)
    unlocked_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    unlocked_at = models.DateTimeField(blank=True, null=True)
    generated_at = models.DateTimeField(blank=True, null=True)
    doc_type = models.CharField(max_length=20, blank=True, null=True)
    issued_by_staff = models.ForeignKey('Staff', models.PROTECT, related_name='report_issued_by_staff_set', blank=True, null=True)
    storage_object = models.ForeignKey('StorageObject', models.PROTECT, blank=True, null=True)
    unlock_reason = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'report'

# reservation — 예약 1건 : 오더 N건 (맘모+초음파 같은 날)   [예약·필수·9컬럼]
class Reservation(models.Model):
    reservation_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT)
    scheduled_at = models.DateTimeField()
    visited_at = models.DateTimeField(blank=True, null=True)
    reservation_status = models.CharField(max_length=20, blank=True, null=True)
    requested_by = models.CharField(max_length=20, blank=True, null=True)
    cancel_reason = models.CharField(max_length=250, blank=True, null=True)
    created_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'reservation'

# chat_message — MVP 범위 밖 권장   [챗봇·선택·7컬럼]
class ChatMessage(models.Model):
    chat_message_id = models.BigAutoField(primary_key=True)
    chat_session = models.ForeignKey('ChatSession', models.PROTECT, blank=True, null=True)
    sender_type = models.CharField(max_length=20, blank=True, null=True)
    content = models.TextField(blank=True, null=True)
    cited_report = models.ForeignKey('Report', models.PROTECT, blank=True, null=True)
    needs_human = models.BooleanField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'chat_message'

# exam_order — 검사 오더 · 재촬영 연결   [환자·필수·12컬럼]
class ExamOrder(models.Model):
    exam_order_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT)
    exam_purpose = models.CharField(max_length=20)
    # 갭 G1. ordered → accepted → in_progress → completed / cancelled
    # 허용값은 DB CHECK 이 막는다. 완료 시 study 생성이 필수다.
    order_status = models.CharField(max_length=20, default='ordered')
    modality = models.CharField(max_length=20, blank=True, null=True)
    order_source = models.CharField(max_length=20, blank=True, null=True)
    followup_round_no = models.IntegerField(blank=True, null=True)
    parent_order = models.ForeignKey('self', models.SET_NULL, blank=True, null=True)
    billing_class = models.CharField(max_length=20, blank=True, null=True)
    ordered_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    ordered_at = models.DateTimeField(blank=True, null=True)
    reservation = models.ForeignKey('Reservation', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'exam_order'

# prescription_item — 약 1줄 = 1행   [처방·필수·11컬럼]
class PrescriptionItem(models.Model):
    prescription_item_id = models.BigAutoField(primary_key=True)
    prescription = models.ForeignKey(Prescription, models.PROTECT, blank=True, null=True)
    line_no = models.IntegerField(blank=True, null=True)
    drug_code = models.CharField(max_length=50)
    drug_name = models.CharField(max_length=100)
    dose_amount = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    dose_unit = models.CharField(max_length=20, blank=True, null=True)
    times_per_day = models.IntegerField(blank=True, null=True)
    duration_days = models.IntegerField(blank=True, null=True)
    route = models.CharField(max_length=20, blank=True, null=True)
    instruction = models.CharField(max_length=250, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'prescription_item'

# prescription_pharmacy — 환자가 이 처방전으로 어느 약국을 봤나 (N:M)   [처방·선택·6컬럼]
class PrescriptionPharmacy(models.Model):
    prescription_pharmacy_id = models.BigAutoField(primary_key=True)
    prescription = models.ForeignKey(Prescription, models.PROTECT, blank=True, null=True)
    pharmacy = models.ForeignKey(Pharmacy, models.PROTECT, blank=True, null=True)
    relation_type = models.CharField(max_length=20, blank=True, null=True)
    distance_meter = models.IntegerField(blank=True, null=True)
    occurred_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'prescription_pharmacy'

# report_access_log — 누가 언제 열람했나 · 잠금 통제의 증거   [리포트·선택·8컬럼]
class ReportAccessLog(models.Model):
    report_access_log_id = models.BigAutoField(primary_key=True)
    report = models.ForeignKey(Report, models.PROTECT, blank=True, null=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True)
    actor_type = models.CharField(max_length=20, blank=True, null=True)
    actor_id = models.BigIntegerField(blank=True, null=True)
    action = models.CharField(max_length=20, blank=True, null=True)
    accessed_at = models.DateTimeField(blank=True, null=True)
    client_channel = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'report_access_log'

# result_explanation — 대면 설명 · 열람잠금을 푸는 트리거   [리포트·필수·9컬럼]
class ResultExplanation(models.Model):
    result_explanation_id = models.BigAutoField(primary_key=True)
    report = models.ForeignKey(Report, models.PROTECT, blank=True, null=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True)
    explained_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    explained_at = models.DateTimeField(blank=True, null=True)
    explain_method = models.CharField(max_length=20, blank=True, null=True)
    summary_text = models.TextField(blank=True, null=True)
    patient_confirmed = models.BooleanField(blank=True, null=True)
    storage_object = models.ForeignKey('StorageObject', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'result_explanation'

# study — 검사 1건 · 모달리티는 컬럼   [영상·필수·13컬럼]
class Study(models.Model):
    study_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT)
    exam_order = models.ForeignKey(ExamOrder, models.PROTECT, blank=True, null=True)
    modality = models.CharField(max_length=20, blank=True, null=True)
    study_uid = models.CharField(unique=True, max_length=100)
    laterality = models.CharField(max_length=10, blank=True, null=True)
    view_position = models.CharField(max_length=20, blank=True, null=True)
    mri_purpose = models.CharField(max_length=30, blank=True, null=True)
    is_screen_capture = models.BooleanField(blank=True, null=True)
    device_name = models.CharField(max_length=100, blank=True, null=True)
    quality_status = models.CharField(max_length=20, blank=True, null=True)
    rejected_reason = models.CharField(max_length=250, blank=True, null=True)
    performed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'study'

# ai_result — AI 실행 1건 · 버전 테이블 안 씀   [AI·필수·14컬럼]
class AiResult(models.Model):
    ai_result_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    study = models.ForeignKey('Study', models.PROTECT, blank=True, null=True)
    # 매핑표 G2 — study_id 만으로는 7.6 슬라이드 분석 대상을 가리킬 수 없었다.
    # study 와 배타다(DB CHECK: num_nonnulls <= 1).
    pathology_slide = models.ForeignKey('PathologySlide', models.PROTECT, blank=True, null=True)
    socket_name = models.CharField(max_length=30, blank=True, null=True)
    model_name = models.CharField(max_length=50, blank=True, null=True)
    model_version = models.CharField(max_length=50, blank=True, null=True)
    lora_version = models.CharField(max_length=50, blank=True, null=True)
    threshold_version = models.CharField(max_length=50, blank=True, null=True)
    abstained = models.BooleanField(blank=True, null=True)
    abstain_signals = models.CharField(max_length=100, blank=True, null=True)
    analyzed_at = models.DateTimeField(blank=True, null=True)
    run_status = models.CharField(max_length=20, blank=True, null=True)
    requested_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ai_result'

# breast_density — 밀도 % · 등급은 판독의가 입력   [영상·선택·6컬럼]
class BreastDensity(models.Model):
    breast_density_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey('Study', models.PROTECT, blank=True, null=True)
    density_percent = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    density_category = models.CharField(max_length=10, blank=True, null=True)
    is_near_boundary = models.BooleanField(blank=True, null=True)
    measured_by = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'breast_density'

# image_series — DICOM 시리즈   [영상·필수·6컬럼]
class ImageSeries(models.Model):
    image_series_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey('Study', models.PROTECT, blank=True, null=True)
    series_uid = models.CharField(unique=True, max_length=100)
    pixel_spacing_mm = models.DecimalField(max_digits=6, decimal_places=4, blank=True, null=True)
    slice_count = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'image_series'

# image_instance — 이미지 낱장 · 파일은 스토리지   [영상·필수·7컬럼]
class ImageInstance(models.Model):
    image_instance_id = models.BigAutoField(primary_key=True)
    image_series = models.ForeignKey('ImageSeries', models.PROTECT, blank=True, null=True)
    instance_number = models.IntegerField(blank=True, null=True)
    storage_object = models.ForeignKey('StorageObject', models.PROTECT, blank=True, null=True)
    thumbnail_object = models.ForeignKey('StorageObject', models.PROTECT, related_name='imageinstance_thumbnail_object_set', blank=True, null=True)
    width_pixel = models.IntegerField(blank=True, null=True)
    height_pixel = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'image_instance'

# lesion — 병변 — 모든 판단의 단위   [AI·필수·13컬럼]
class Lesion(models.Model):
    lesion_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    study = models.ForeignKey('Study', models.PROTECT, blank=True, null=True)
    ai_result = models.ForeignKey(AiResult, models.PROTECT, blank=True, null=True)
    laterality = models.CharField(max_length=10, blank=True, null=True)
    clock_position = models.CharField(max_length=20, blank=True, null=True)
    distance_from_nipple_mm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    size_mm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    size_measurable = models.BooleanField(blank=True, null=True)
    aspect_ratio = models.DecimalField(max_digits=5, decimal_places=3, blank=True, null=True)
    area_pixel = models.IntegerField(blank=True, null=True)
    lesion_source = models.CharField(max_length=20, blank=True, null=True)
    lesion_type = models.CharField(max_length=30, blank=True, null=True)
    needs_additional_view = models.BooleanField(blank=True, null=True)
    additional_view_reason = models.CharField(max_length=250, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'lesion'

# ai_mask — AI가 그린 마스크 · XAI 1층   [AI·필수·7컬럼]
class AiMask(models.Model):
    ai_mask_id = models.BigAutoField(primary_key=True)
    ai_result = models.ForeignKey('AiResult', models.PROTECT, blank=True, null=True)
    lesion = models.ForeignKey('Lesion', models.PROTECT, blank=True, null=True)
    image_instance = models.ForeignKey('ImageInstance', models.PROTECT, blank=True, null=True)
    # 매핑표 G3 — image_instance_id 만으로는 병리 마스크(tumor·stroma·immune)를
    # 붙일 곳이 없었다. G3 제안에 배타 언급이 없어 CHECK 은 걸지 않는다.
    pathology_slide = models.ForeignKey('PathologySlide', models.PROTECT, blank=True, null=True)
    mask_type = models.CharField(max_length=30, blank=True, null=True)
    storage_object = models.ForeignKey('StorageObject', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ai_mask'

# assessment — 등급 + 권고 분리 · 1차/최종 모두 보존   [판정·필수·19컬럼]
class Assessment(models.Model):
    assessment_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    study = models.ForeignKey('Study', models.PROTECT, blank=True, null=True)
    lesion = models.ForeignKey('Lesion', models.PROTECT, blank=True, null=True)
    assessment_scope = models.CharField(max_length=20, blank=True, null=True)
    read_stage = models.CharField(max_length=20, blank=True, null=True)
    category = models.CharField(max_length=10, blank=True, null=True)
    category_rule = models.CharField(max_length=10, blank=True, null=True)
    category_model = models.CharField(max_length=10, blank=True, null=True)
    path_agreement = models.CharField(max_length=20, blank=True, null=True)
    suspicion_total_score = models.IntegerField(blank=True, null=True)
    recommendation = models.CharField(max_length=100, blank=True, null=True)
    recommendation_reason = models.CharField(max_length=250, blank=True, null=True)
    rule_table_version = models.CharField(max_length=30, blank=True, null=True)
    assessed_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    finalized_at = models.DateTimeField(blank=True, null=True)
    superseded_by = models.ForeignKey('self', models.SET_NULL, blank=True, null=True)
    finding_note = models.TextField(blank=True, null=True)
    ai_revealed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'assessment'

# lesion_descriptor — BI-RADS 서술자 · 맘모 + 초음파  [v3]   [AI·필수·8컬럼]
class LesionDescriptor(models.Model):
    lesion_descriptor_id = models.BigAutoField(primary_key=True)
    lesion = models.ForeignKey(Lesion, models.PROTECT, blank=True, null=True)
    descriptor_name = models.CharField(max_length=50, blank=True, null=True)
    descriptor_value = models.CharField(max_length=50, blank=True, null=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, blank=True, null=True)
    suspicion_score = models.IntegerField(blank=True, null=True)
    descriptor_source = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'lesion_descriptor'

# specimen — 검체 · 진행 차단 지점   [병리·필수·11컬럼]
class Specimen(models.Model):
    specimen_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, blank=True, null=True)
    lesion = models.ForeignKey(Lesion, models.PROTECT)
    # 갭 G4. unbound → bound → accessioned
    # unbound 상태로 7.3 접수를 시도하면 409 SPECIMEN_NOT_BOUND.
    accession_status = models.CharField(max_length=20, default='unbound')
    accessioned_at = models.DateTimeField(blank=True, null=True)
    specimen_label = models.CharField(unique=True, max_length=50, blank=True, null=True)
    specimen_type = models.CharField(max_length=30, blank=True, null=True)
    guidance_route = models.CharField(max_length=30, blank=True, null=True)
    target_snapshot = models.CharField(max_length=250, blank=True, null=True)
    bound_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    collected_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'specimen'

# followup_track — 등급 3 추적 · 종료 조건   [추적·필수·10컬럼]
class FollowupTrack(models.Model):
    followup_track_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    assessment = models.ForeignKey(Assessment, models.PROTECT, blank=True, null=True)
    track_status = models.CharField(max_length=20, blank=True, null=True)
    current_round_no = models.IntegerField(blank=True, null=True)
    opened_at = models.DateTimeField(blank=True, null=True)
    next_due_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    close_reason = models.CharField(max_length=250, blank=True, null=True)
    assigned_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'followup_track'

# pathology_result — 확진 · 정량 · 대조 트리거   [병리·필수·21컬럼]
class PathologyResult(models.Model):
    pathology_result_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    specimen = models.OneToOneField('Specimen', models.PROTECT, blank=True, null=True)
    diagnosis = models.CharField(max_length=20, blank=True, null=True)
    b_category = models.CharField(max_length=10, blank=True, null=True)
    diagnosis_code = models.CharField(max_length=30, blank=True, null=True)
    histologic_type = models.CharField(max_length=100, blank=True, null=True)
    nottingham_grade = models.IntegerField(blank=True, null=True)
    er_status = models.CharField(max_length=20, blank=True, null=True)
    pr_status = models.CharField(max_length=20, blank=True, null=True)
    her2_status = models.CharField(max_length=20, blank=True, null=True)
    ki67_percent = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    stil_percent = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    stil_interval_low = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    stil_interval_high = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    # 간질 ÷ (종양 + 간질). 0~100 으로 갇힌다 [Q6 확정]
    # 구간(low/high)이 없다 — 소켓 1 조직분할 모델(linear_tand)에 dropout 이
    # 없어 sTIL 처럼 MC Dropout 으로 구간을 낼 수 없다. 저장소의
    # docs/api_summary.md §0-3 에 근거를 적어 뒀다(이미지에는 들어가지 않는다).
    tsr_percent = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    stil_source = models.CharField(max_length=20, blank=True, null=True)
    has_calcification = models.BooleanField(blank=True, null=True)
    reported_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    finalized_at = models.DateTimeField(blank=True, null=True)
    finding_note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'pathology_result'

# discordance_flag — 영상 ↔ 병리 · 병변 단위   [대조·필수·18컬럼]
class DiscordanceFlag(models.Model):
    discordance_flag_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    lesion = models.ForeignKey('Lesion', models.PROTECT, blank=True, null=True)
    specimen = models.ForeignKey('Specimen', models.PROTECT, blank=True, null=True)
    pathology_result = models.ForeignKey('PathologyResult', models.PROTECT, blank=True, null=True)
    assessment = models.ForeignKey(Assessment, models.PROTECT, blank=True, null=True)
    violated_rule = models.CharField(max_length=20, blank=True, null=True)
    flag_status = models.CharField(max_length=20, blank=True, null=True)
    rule_table_version = models.CharField(max_length=30, blank=True, null=True)
    flagged_at = models.DateTimeField(blank=True, null=True)
    reviewed_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    review_opinion = models.CharField(max_length=20, blank=True, null=True)
    review_note = models.CharField(max_length=250, blank=True, null=True)
    disposition_type = models.CharField(max_length=20, blank=True, null=True)
    disposition_reason = models.CharField(max_length=250, blank=True, null=True)
    disposed_by_staff = models.ForeignKey('Staff', models.PROTECT, related_name='discordanceflag_disposed_by_staff_set', blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    superseded_by = models.ForeignKey('self', models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'discordance_flag'

# followup_round — 6 · 12 · 24개월 회차   [추적·선택·11컬럼]
class FollowupRound(models.Model):
    followup_round_id = models.BigAutoField(primary_key=True)
    followup_track = models.ForeignKey('FollowupTrack', models.PROTECT, blank=True, null=True)
    round_no = models.IntegerField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True)
    visited_at = models.DateTimeField(blank=True, null=True)
    study = models.ForeignKey('Study', models.PROTECT, blank=True, null=True)
    round_result = models.CharField(max_length=20, blank=True, null=True)
    contact_method = models.CharField(max_length=20, blank=True, null=True)
    contacted_at = models.DateTimeField(blank=True, null=True)
    contacted_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    patient_response = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'followup_round'

# pathology_slide — 조직 슬라이드 이미지 · specimen 기준으로 등록  [v3]   [병리·필수·7컬럼]
class PathologySlide(models.Model):
    pathology_slide_id = models.BigAutoField(primary_key=True)
    # v3 개정이력 "pathology_result_id → specimen_id FK 로 전환".
    # 스캔이 판독보다 먼저라 결과 초안을 기다리지 않고 붙일 수 있어야 한다.
    specimen = models.ForeignKey(Specimen, models.PROTECT, blank=True, null=True)
    storage_object = models.ForeignKey('StorageObject', models.PROTECT, blank=True, null=True)
    thumbnail_object = models.ForeignKey('StorageObject', models.PROTECT, related_name='pathologyslide_thumbnail_object_set', blank=True, null=True)
    stain_type = models.CharField(max_length=20, blank=True, null=True)
    scan_magnification = models.CharField(max_length=20, blank=True, null=True)
    mpp = models.DecimalField(max_digits=6, decimal_places=4, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'pathology_slide'

# image_pyramid — 타일 피라미드 메타 · 판독 화면이 이걸 보고 열린다   [영상·필수·13컬럼]
#
# 매핑표 G13 으로 등재됐던 신설 테이블이다. 원본 제안은 source_type/source_id
# 다형 참조였으나 배타 FK 2개로 간다 — 같은 문서가 G2 에서 배타 방식을 골랐고,
# G9 에서 한 컬럼에 담는 방식을 "FK 를 걸 수 없다"는 결함으로 등재했다.
# 소스는 병리 WSI 아니면 영상 인스턴스, 정확히 하나다(DB CHECK).
class ImagePyramid(models.Model):
    image_pyramid_id = models.BigAutoField(primary_key=True)
    pathology_slide = models.ForeignKey(PathologySlide, models.PROTECT, blank=True, null=True)
    image_instance = models.ForeignKey('ImageInstance', models.PROTECT, blank=True, null=True)
    tile_size = models.IntegerField(blank=True, null=True)
    tile_format = models.CharField(max_length=10, blank=True, null=True)
    level_count = models.IntegerField(blank=True, null=True)
    max_width = models.IntegerField(blank=True, null=True)
    max_height = models.IntegerField(blank=True, null=True)
    mpp_x = models.DecimalField(max_digits=6, decimal_places=4, blank=True, null=True)
    mpp_y = models.DecimalField(max_digits=6, decimal_places=4, blank=True, null=True)
    object_key_prefix = models.CharField(max_length=255, blank=True, null=True)
    # pending / building / ready / failed — 생성 전 뷰어 요청은 409 PYRAMID_NOT_READY
    build_status = models.CharField(max_length=20, blank=True, null=True)
    built_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'image_pyramid'

# clinical_decision — 유방외과의 결정 4종 · 불일치 해소는 discordance_flag 담당   [판정·필수·10컬럼]
class ClinicalDecision(models.Model):
    clinical_decision_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey('Patient', models.PROTECT, blank=True, null=True)
    lesion = models.ForeignKey('Lesion', models.PROTECT, blank=True, null=True)
    decision_type = models.CharField(max_length=20)
    decision_value = models.CharField(max_length=20)
    decision_reason = models.CharField(max_length=250, blank=True, null=True)
    source_assessment = models.ForeignKey(Assessment, models.PROTECT, blank=True, null=True)
    source_discordance = models.ForeignKey('DiscordanceFlag', models.PROTECT, blank=True, null=True)
    decided_by_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True)
    decided_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'clinical_decision'
