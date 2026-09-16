"""
EMPATHO CDSS 데이터 모델 — v10 · 18개 테이블.

기준 문서 — DB_스키마_v10_20260908.docx

"""

from django.db import models
from django.db.models import Func, IntegerField, Q
from django.db.models.lookups import Exact


class NumNonNulls(Func):
    """비어 있지 않은 칸이 몇 개인가. Postgres 의 num_nonnulls().

    「셋 중 정확히 하나」를 Q 로 쓰면 3 갈래 × 3 항이 된다. 주인이 넷째로
    늘면 4 × 4 로 불어난다.
    """

    function = 'num_nonnulls'
    output_field = IntegerField()


def as_choices(values):
    return [(v, v) for v in values]


# CHECK 으로 거는 값 집합
ROLE = ["admin", "reception", "nursing", "radiology", "surgery", "pathology", "patient"]
DOC_TYPE = ["terms", "privacy", "sensitive_health", "marketing"]
FOLLOWUP_STATUS = ["open", "resolved", "escalated", "declined", "overdue"]
EXAM_PURPOSE = ["screening", "diagnostic"]
MODALITY = ["mammo", "us", "mri"]
# requested — 환자가 날짜·시간만 넣고 신청한 상태. 원무가 확정하면 ordered 다.
ORDER_STATUS = ["requested", "ordered", "accepted", "in_progress", "completed",
                "cancelled"]
# 가입 승인 흐름. 로그인 가능 여부는 account.is_active 가 따로 답한다 —
# 둘을 한 칸에 담으면 「승인 대기」와 「정지」가 같은 값이 된다.
ACCOUNT_STATUS = ["pending", "active", "rejected", "suspended"]
# 1차 판독 게이트가 팀 결정으로 없어져 중간 둘(first_locked · ai_revealed)이
# 빠지고, 임시저장을 담는 draft 가 들어왔다.
READ_STATUS = ["pending", "draft", "finalized"]
# mesh 가 넷인 이유 — MRI 는 유방 전체 · 치밀부위 · 몸통 · 병변 네 종류를 낸다.
# 앞의 셋은 검사당 1개라 lesion 이 null 이고 병변 메시만 병변당 1개라 lesion 이 필수다.
# 한 kind 로 두면 그 차이를 DB 가 못 걸고, lesion 이 null 인 행들이 구분도 안 된다.
# mesh_body 는 2026-09-16 조영 전 · 후 두 볼륨 판독에서 확인했다 — 응답의
# result.tumor.body_mesh(약 2.5MB)다. 조영 전만 보내면 나오지 않는다.
IMAGE_KIND = ["mask", "overlay", "mesh_breast", "mesh_dense", "mesh_lesion",
              "mesh_body", "heatmap", "thumbnail"]
READ_STAGE = ["draft", "final"]
ACCESSION_STATUS = ["unbound", "bound", "accessioned"]
DIAGNOSIS = ["benign", "malignant"]
B_CATEGORY = ["b1", "b2", "b3", "b4", "b5"]
NOTIFICATION_TYPE = ["followup", "discordance", "report_ready",
                     "reservation_requested", "reservation_created",
                     "reservation_changed"]
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
# rule3(석회 표적 대조)은 쓰지 않기로 해서 뺐다 — 대조는 4 종이다.
VIOLATED_RULE = ["rule1", "rule2", "rule4", "rule5"]
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
    # 가입 승인 흐름. 환자는 승인이 없어 가입 엔드포인트가 'active' 를 명시한다.
    account_status = models.CharField(max_length=20,
                                      choices=as_choices(ACCOUNT_STATUS),
                                      default='pending', db_default='pending')
    # 로그인 가능 여부. 인증(core/api/auth.py)은 이 칸만 본다 —
    # 승인 흐름을 거기 섞으면 상태가 늘 때마다 인증 코드를 고쳐야 한다.
    # 기본이 False 인 것은 빠뜨렸을 때 닫히는 쪽이 맞아서다. 가입 엔드포인트가
    # 직원이면 False, 환자면 True 로 명시한다.
    is_active = models.BooleanField(default=False, db_default=False,
                                    blank=True, null=True)
    phone_verified = models.BooleanField(blank=True, null=True)
    push_token = models.CharField(max_length=255, blank=True, null=True)
    last_login_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'account'
        constraints = [
            models.CheckConstraint(condition=Q(role__in=ROLE), name='account_role_ck'),
            models.CheckConstraint(condition=Q(account_status__in=ACCOUNT_STATUS),
                                   name='account_status_ck'),
        ]

    # DRF 가 request.user 에서 보는 것들. 인증 주체가 auth_user 가 아니라 이
    # 표라서 직접 준다. 파이썬 속성이라 컬럼도 마이그레이션도 생기지 않는다.
    # 여기까지 온 Account 는 인증을 통과한 것이다 — is_active 검사는
    # core/api/auth.py 가 먼저 한다.
    is_authenticated = True
    is_anonymous = False

    def __str__(self):
        return "%s(%s)" % (self.login_id or self.account_id, self.role)


class Staff(AuditBase):
    """의료진 신원. 계정과 권한(role)은 account 에, 여기는 이름 · 직원번호 · 승인 기록."""

    staff_id = models.BigAutoField(primary_key=True)
    account = models.OneToOneField(Account, models.PROTECT, related_name='staff')
    staff_number = models.CharField(unique=True, max_length=50, blank=True, null=True)
    full_name = models.CharField(max_length=50, blank=True, null=True)
    # 역할 기본 권한에 개인별로 더하는 권한. {"assessment": ["R"], "report": ["R"]}
    # 더하기만 한다 — 역할이 준 권한을 개인이 잃지 않는다.
    extra_permissions = models.JSONField(blank=True, null=True)
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
    # 초진 · 재진 판단. 원무가 처음 접수할 때 찍는다 — 앱을 먼저 가입하고
    # 나중에 오는 경우가 있어 created_at 으로는 어긋난다.
    first_visited_at = models.DateTimeField(blank=True, null=True)
    has_allergy = models.BooleanField(blank=True, null=True)
    allergy_note = models.CharField(max_length=250, blank=True, null=True)
    # 최신 1건 캐시. **진실은 exam_order.questionnaire 다** — 문진은 방문 때
    # 받는 것이라 방문마다 한 벌이고, 여기는 조회 편의로 마지막 것을 둔다.
    # 앱은 한 벌로 보내고 서버가 한 트랜잭션에서 양쪽에 담는다 — 화면이 나눠
    # 보내면 한쪽만 저장되는 경우가 생긴다.
    questionnaire = models.JSONField(blank=True, null=True)
    # 주치의. 간호과가 환자를 배정할 때 지정한다.
    # related_name 은 유방외과의 「내 환자 목록」이 staff.primary_patients 로
    # 바로 도는 자리다.
    primary_staff = models.ForeignKey('Staff', models.PROTECT, blank=True, null=True,
                                      related_name='primary_patients')

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
    """검사 오더. 예약 신청 · 확정 · 재촬영 연결을 함께 갖는다.

    환자가 날짜·시간만 넣고 신청하면 order_status='requested' 로 행이 하나 선다.
    원무가 확정하면서 modality · exam_purpose · ordered_by 를 채우고 'ordered'
    로 옮긴다.

    진실은 이 표다. notification 은 통지일 뿐이라 원무 큐는 알림이 아니라
    order_status='requested' 로 뽑는다 — 알림이 안 갔거나 지워져도 신청은 남는다.

    원무의 거절도 cancelled 다 — rejected 를 따로 두지 않는다. 누가 물렸는지는
    notification.staff_id 로 갈린다: 거절이면 채워지고, 환자 취소면 null 이다.
    """

    exam_order_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='exam_orders')
    # 신청 단계에선 비어 있다. 확정하면서 채운다 — 아래 CHECK 이 강제한다.
    exam_purpose = models.CharField(max_length=20, choices=as_choices(EXAM_PURPOSE),
                                    blank=True, null=True)
    modality = models.CharField(max_length=20, choices=as_choices(MODALITY),
                                blank=True, null=True)
    order_status = models.CharField(max_length=20, choices=as_choices(ORDER_STATUS))
    # 검사를 지시한 의료진. created_by(행을 만든 계정)와 다른 값이다 —
    # 원무가 의사 지시를 대신 입력하면 둘이 갈린다.
    ordered_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                   related_name='+', db_column='ordered_by')
    # 촬영 · 판독을 맡은 영상의학과 의사. 대기 큐에서 집으면 채워진다 —
    # 비어 있는 것이 「아직 아무도 안 집음」이라 큐의 조건이 된다.
    assigned_to = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='assigned_orders',
                                    db_column='assigned_to')
    # 유방외과가 촬영을 요청할 때 쓰는 의견서. 촬영부위는 받지 않는다.
    order_note = models.TextField(blank=True, null=True)
    ordered_at = models.DateTimeField(blank=True, null=True)
    # requested 일 때는 환자의 희망 시각, ordered 부터는 확정 시각이다.
    # 원무가 다른 시간으로 확정하면 희망 시각이 덮여 사라지므로, 확정 알림에
    # 「9월 22일 오전 신청 → 14:00 확정」처럼 둘을 같이 적는다.
    scheduled_at = models.DateTimeField(blank=True, null=True)
    visited_at = models.DateTimeField(blank=True, null=True)   # null = 노쇼
    parent_order = models.ForeignKey('self', models.SET_NULL, blank=True, null=True,
                                     related_name='+', db_column='parent_order_id')
    followup = models.ForeignKey(Followup, models.PROTECT, blank=True, null=True,
                                 related_name='exam_orders')
    # 이 방문에서 받은 문진. 진실은 이쪽이고 patient.questionnaire 는 캐시다.
    # 방문마다 한 벌이라 이력이 자연히 남는다.
    # {"form_version": "v1", "answers": {"문항code": "선택지id"}}
    questionnaire = models.JSONField(blank=True, null=True)
    # 물린 사유. 영상의학과가 협진 요청을 돌려보낼 때 유방외과가 「왜 거절됐나」를
    # 봐야 해서 알림이 아니라 여기 남긴다 — 알림이 안 갔거나 지워져도 사유는 남는다.
    cancel_reason = models.CharField(max_length=250, blank=True, null=True)
    # 물린 사람. null = 환자 본인 취소.
    # 역할은 cancelled_by.account.role 로 나온다 — 원무 거절과 영상의학 거절이
    # 갈린다. notification.staff_id 로 가르던 방식은 거절 주체가 둘이 되면서 깨졌다.
    cancelled_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                     related_name='+', db_column='cancelled_by')

    class Meta:
        db_table = 'exam_order'
        constraints = [
            models.CheckConstraint(
                condition=Q(exam_purpose__in=EXAM_PURPOSE)
                | Q(exam_purpose__isnull=True),
                name='exam_order_purpose_ck'),
            models.CheckConstraint(
                condition=Q(modality__in=MODALITY) | Q(modality__isnull=True),
                name='exam_order_modality_ck'),
            models.CheckConstraint(condition=Q(order_status__in=ORDER_STATUS),
                                   name='exam_order_status_ck'),
            # 신청 · 취소일 때만 검사 종류 · 목적 · 지시자가 비어도 된다.
            # 확정 전에 물린 신청은 requested → cancelled 로 가는데 세 칸이 비어
            # 있고, PROTECT 정책이라 행을 지울 수도 없다. 확정 후 취소는 세 칸이
            # 이미 차 있어 느슨해지는 것이 없다.
            # API 계층이 아니라 DB 로 막는다 — Celery 나 admin 으로 들어오는 행은
            # API 검증을 거치지 않는다.
            models.CheckConstraint(
                condition=Q(order_status__in=['requested', 'cancelled'])
                | (Q(modality__isnull=False) & Q(exam_purpose__isnull=False)
                   & Q(ordered_by__isnull=False)),
                name='exam_order_requested_fields_ck'),
            # 의료진이 물렸으면 사유가 반드시 남는다. 「왜 거절됐나」를 유방외과가
            # 봐야 하는데 API 검증만으로는 admin · Celery 로 들어오는 행을 못 막는다.
            models.CheckConstraint(
                condition=Q(cancelled_by__isnull=True)
                | Q(cancel_reason__isnull=False),
                name='exam_order_cancel_reason_ck'),
            # 사유는 물린 행에만. 살아 있는 오더에 사유가 붙어 있으면 안 된다.
            models.CheckConstraint(
                condition=Q(cancel_reason__isnull=True)
                | Q(order_status='cancelled'),
                name='exam_order_cancel_status_ck'),
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
    """원본 파일 1개. 주소와 촬영 정보.

    파일 단위다 — Go 가 파일(SOP instance) 하나마다 I-1 콜백을 부르고, 파일마다
    object_key 와 checksum 이 달라 한 행에 담기지 않는다. 같은 시리즈의 파일
    여럿이 같은 series_uid 를 갖는다.
    """

    storage_object_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey(Study, models.PROTECT, blank=True, null=True,
                              related_name='storage_objects')      # 영상
    specimen = models.ForeignKey('Specimen', models.PROTECT, blank=True, null=True,
                                 related_name='storage_objects')   # 병리
    report = models.ForeignKey('Report', models.PROTECT, blank=True, null=True,
                               related_name='storage_objects')     # 발급 PDF
    # 속한 시리즈의 DICOM UID. 같은 시리즈의 파일들이 같은 값을 가진다.
    # 이름은 DICOM SeriesInstanceUID 그대로 둔다 — 바꾸면 Go · Orthanc 과의
    # 대응이 끊긴다.
    series_uid = models.CharField(max_length=100, blank=True, null=True,
                                  db_index=True)
    # 이 파일의 DICOM UID. DICOM 이 아닌 파일(병리 PNG 등)은 비어 있다.
    # UNIQUE 를 걸지 않는다 — I-1 이 먼저 오고 그때는 이 칸이 NULL 이라 INSERT 를
    # 못 막는다. I-2 가 UPDATE 할 때 터지는데 그땐 이미 행이 두 개다.
    sop_instance_uid = models.CharField(max_length=100, blank=True, null=True,
                                        db_index=True)
    series_role = models.CharField(max_length=30, blank=True, null=True)
    orthanc_series_id = models.CharField(max_length=100, blank=True, null=True)
    bucket = models.CharField(max_length=100, blank=True, null=True)
    # UUID 만 쓴다. 경로에 환자번호를 넣지 않는다.
    # 유일성은 (bucket, object_key) 짝으로 본다 — 아래 UK.
    object_key = models.CharField(max_length=255, blank=True, null=True)
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
            # 주소가 적어도 하나는 있어야 한다.
            # DICOM 은 Orthanc 에, 나머지는 Garage 에 둔다. DICOM 도 I-1 때는
            # Garage 에 있다가, I-2 로 Orthanc 저장이 확인되면 주소가 그쪽으로
            # 옮겨가고 Garage 키가 비워진다 (사본은 Go 가 지운다).
            # 「정확히 하나」로 조이지 않는 것은 전송이 실패해 Orthanc ID 가
            # 없으면 Garage 키를 남겨야 해서다 — 그 파일은 Garage 에만 있다.
            models.CheckConstraint(
                condition=Q(orthanc_series_id__isnull=False)
                | Q(object_key__isnull=False),
                name='storage_object_address_ck'),
            # 영상 · 병리 · 리포트 중 정확히 하나에 매달린다.
            # 티켓 purpose 가 dicom_upload · wsi_upload · report_pdf 로 갈린다.
            # prescription_pdf · derived_upload 는 아직 미정이라 자리가 없다.
            models.CheckConstraint(
                condition=Exact(NumNonNulls('study', 'specimen', 'report'), 1),
                name='storage_object_owner_ck'),
            # I-1 의 멱등키. I-1 시점에 확정된다 — Go 의 멱등키
            # obj:<object_key> 와 같은 자리다.
            # Orthanc 로 옮겨간 뒤에는 둘 다 NULL 이 되는데, Postgres 가 NULL 을
            # UNIQUE 에서 빼므로 그런 행이 여럿이어도 서로 안 부딪힌다.
            models.UniqueConstraint(fields=['bucket', 'object_key'],
                                    name='storage_object_bucket_object_key_uk'),
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
    # 파생물의 바이트 주소. storage_object 를 거치지 않고 Garage 를 바로 가리킨다 —
    # 파생물은 Orthanc 에 안 가고 empatho-derived 에만 있어서 주소가 하나다.
    # source_object 는 「어디서 왔나」이고 이쪽이 「바이트가 어디 있나」다.
    bucket = models.CharField(max_length=100, blank=True, null=True)
    object_key = models.CharField(max_length=255, blank=True, null=True)
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
            # storage_object 와 같은 자리. object_key 만 UNIQUE 로 두면
            # empatho-original 과 empatho-derived 에 같은 키를 못 쓴다.
            models.UniqueConstraint(fields=['bucket', 'object_key'],
                                    name='image_bucket_object_key_uk'),
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
    # 주인은 검사 아니면 검체, 정확히 하나다 — 아래 CHECK 이 강제한다.
    # 병리는 study 가 없다. 크롭 여러 장이면 장마다 한 행이고 specimen 이 묶는다.
    study = models.ForeignKey(Study, models.PROTECT, blank=True, null=True,
                              related_name='ai_results')
    specimen = models.ForeignKey('Specimen', models.PROTECT, blank=True, null=True,
                                 related_name='ai_results')
    # 맘모 · 초음파는 필수, MRI 는 null 또는 조영 전 시리즈
    source_object = models.ForeignKey(StorageObject, models.PROTECT,
                                      blank=True, null=True,
                                      related_name='ai_results',
                                      db_column='source_object_id')
    model = models.ForeignKey(AiModel, models.PROTECT, blank=True, null=True,
                              related_name='ai_results')
    # 요청한 소켓. 실제 처리한 소켓은 model.socket_id 다 — 4→5 처럼 재배치되면
    # 둘이 달라지고, 그 차이 자체가 재배치 기록이다. 하나만 두면 흔적이 사라진다.
    requested_socket_id = models.CharField(max_length=5, choices=as_choices(SOCKET_ID),
                                           blank=True, null=True)
    # MRI 메시는 여기 없다. 응답의 99.98% 가 메시라 core/mesh.py 가 걷어내
    # Garage 로 보내고, 자리에는 (bucket, object_key) 스텁만 남는다.
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
        constraints = [
            # storage_object_owner_ck 와 같은 모양이다.
            models.CheckConstraint(
                condition=Exact(NumNonNulls('study', 'specimen'), 1),
                name='ai_result_owner_ck'),
        ]


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
        constraints = [
            # v10 에서 빠져 있던 것. choices 는 폼 검증이라 DB 는 아무 문자열이나
            # 받았다. 병리는 여기 없다 — 검체가 병변에 붙지 병변이 병리에서 나지 않는다.
            models.CheckConstraint(
                condition=Q(modality__in=MODALITY) | Q(modality__isnull=True),
                name='lesion_modality_ck'),
        ]


class Assessment(AuditBase):
    """판독의의 판정. 1차와 최종을 각각 행으로 보존한다."""

    assessment_id = models.BigAutoField(primary_key=True)
    study = models.ForeignKey(Study, models.PROTECT, related_name='assessments')
    lesion = models.ForeignKey(Lesion, models.PROTECT, blank=True, null=True,
                               related_name='assessments')  # null = study 전체
    # 임시저장이 먼저다. 확정은 final 로 올린다.
    read_stage = models.CharField(max_length=20, choices=as_choices(READ_STAGE),
                                  default='draft', db_default='draft')
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
    # 검체를 집은 병리의. exam_order.assigned_to 와 같은 구조 —
    # 비어 있는 것이 「아직 아무도 안 집음」이라 접수 대기 큐의 조건이 된다.
    assigned_to = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                    related_name='assigned_specimens',
                                    db_column='assigned_to')
    # 유방외과 의뢰 문구. "좌측 상외측 유방에 만져지는 종괴로 조직검사 의뢰합니다"
    clinical_note = models.TextField(blank=True, null=True)
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
    # 판독 정정 이력. 영상의학은 새 assessment 행을 만들고 옛 행이 superseded_by
    # 로 가리키는데, 검체는 물건이라 행을 늘릴 수 없다 — specimen_label 이 UK 고
    # discordance_flag 가 옛 행을 가리킨 채 남는다. 그래서 옛 값을 배열에 민다.
    # [{diagnosis, b_category, finding_note, reported_by, finalized_at,
    #   amend_reason, amended_at}, …]
    amend_history = models.JSONField(blank=True, null=True)

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
    # 유방외과 열람. 화면은 「열람 / 미열람」과 정렬에만 쓴다 —
    # 자동 기록이라 「확인했다」가 아니다.
    last_viewed_at = models.DateTimeField(blank=True, null=True)
    last_viewed_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                       related_name='+', db_column='last_viewed_by')
    # nullable 이면 F('view_count') + 1 이 NULL 에 더해져 계속 NULL 이다.
    view_count = models.IntegerField(default=0, db_default=0)

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
