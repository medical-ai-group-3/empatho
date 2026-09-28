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
# requested   환자가 앱에서 신청. 날짜도 검사 종류도 아직
# scheduled   원무가 날짜를 확정. **검사 종류는 아직 없다**
# ordered     유방외과가 검사 종류·목적·지시의까지 정함
ORDER_STATUS = ["requested", "scheduled", "ordered", "accepted", "in_progress",
                "completed", "cancelled"]
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
                     "reservation_changed", "reservation_reminder"]
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
# 리포트를 낸 소켓. **실재하는 배치만** 둔다 —
#   1 병리 · 3 MRI · 4b 맘모 · 5 초음파 · 7 종합
# 4 는 재배치(4→5) 전의 초음파 번호라 뺐다. 요청 번호를 담는 SOCKET_ID
# 쪽에는 4 · 2 가 그대로 있다 — 거기는 재배치 전 값이 들어오는 자리다.
REPORT_SOCKET_ID = ["1", "3", "4b", "5", "7"]
EXPLAIN_METHOD = ["대면", "유선", "영상"]
SEVERITY = ["sev1", "normal"]
# sse 는 Go notify 허브가 I-3 으로 보내는 값이다 (cmd/notify/main.go 의
# Channel: "sse"). 이미 보내고 있는데 목록에 없었다.
NOTIFICATION_CHANNEL = ["app", "sms", "call_queue", "sse"]
REF_TYPE = ["assessment", "discordance_flag", "report", "exam_order"]
# PersonalNote 용. v10 에도 §15 문서에도 없다 — 화면 쪽 임시 상태(브라우저
# 저장만 되던 할일·스티키 메모)를 서버로 옮기며 새로 판 값이다.
# handover — 인계 사항. todo · sticky 와 달리 **같은 과(역할) 전체가 본다**
# (views/personal_note.py). 09-27 브라우저 저장에서 옮겼다
NOTE_TYPE = ["todo", "sticky", "handover"]


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
        verbose_name = "계정"
        verbose_name_plural = "계정"
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
        verbose_name = "직원"
        verbose_name_plural = "직원"


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
        verbose_name = "환자"
        verbose_name_plural = "환자"


class PatientPii(AuditBase):
    """이름 · 생년월일 · 전화. patient 와 1:1."""

    patient = models.OneToOneField(Patient, models.PROTECT, primary_key=True,
                                   db_column='patient_id', related_name='pii')
    name = models.CharField(max_length=50, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    phone = models.CharField(unique=True, max_length=30, blank=True, null=True)

    class Meta:
        db_table = 'patient_pii'
        verbose_name = "환자 개인정보"
        verbose_name_plural = "환자 개인정보"


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
        verbose_name = "동의"
        verbose_name_plural = "동의"
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
        verbose_name = "추적 관찰"
        verbose_name_plural = "추적 관찰"
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
    # 간호 → 유방외과 인계. 이 방문을 어느 외과 선생님께 언제 보냈는가.
    # patient.primary_staff 는 환자의 값이라 재진 환자는 보내기 전부터 차 있다 —
    # 「이번 방문을 보냈나」는 오더에 남겨야 갈린다. 비어 있으면 아직 안 보냄.
    # ⚠ 0024 이전에 보낸 오더는 비어 있다(남은 흔적이 없어 백필하지 않는다).
    handed_at = models.DateTimeField(blank=True, null=True)
    handed_to = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                  related_name='+', db_column='handed_to')

    class Meta:
        db_table = 'exam_order'
        verbose_name = "검사 오더"
        verbose_name_plural = "검사 오더"
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
            # 신청 · 날짜확정 · 취소일 때만 검사 종류 · 목적 · 지시자가 비어도 된다.
            #
            # scheduled 가 여기 있는 이유 — **원무가 날짜만 확정하는 자리다.
            # 검사 종류는 유방외과가 정한다.**
            #
            # 확정 전에 물린 신청은 requested → cancelled 로 가는데 세 칸이 비어
            # 있고, PROTECT 정책이라 행을 지울 수도 없다. 확정 후 취소는 세 칸이
            # 이미 차 있어 느슨해지는 것이 없다.
            # API 계층이 아니라 DB 로 막는다 — Celery 나 admin 으로 들어오는 행은
            # API 검증을 거치지 않는다.
            #
            # 09-28 — **내원해서 진료만 보고 끝난 방문**도 completed 로 닫힌다
            # (유방외과 「진료 완료」, PATCH /exam-orders/{id}/complete). 창구
            # 접수 · 내원 처리된 예약은 세 칸이 빈 requested 인데, 이 제약이
            # completed 를 막아서 진료 완료가 매번 IntegrityError → 500 이었다.
            # visited_at 이 있는 행만 연다 — 안 온 예약이 빈 칸으로 completed
            # 가 되는 길은 그대로 막힌다(0026).
            models.CheckConstraint(
                condition=Q(order_status__in=['requested', 'scheduled', 'cancelled'])
                | (Q(order_status='completed') & Q(visited_at__isnull=False))
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
        verbose_name = "검사(영상)"
        verbose_name_plural = "검사(영상)"
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
    # PATCH /storage-objects/{id}/cancel (업로드 취소) 전용 — 누가 · 왜.
    # AiResult 가 이미 붙은 뒤에는 취소 자체가 막혀서(뷰가 409), 이 둘은
    # 「분석 시작 전에 취소된」 행에만 찍힌다.
    deleted_by = models.ForeignKey('Account', models.PROTECT, blank=True, null=True,
                                   related_name='+', db_column='deleted_by')
    delete_reason = models.CharField(max_length=250, blank=True, null=True)

    class Meta:
        db_table = 'storage_object'
        verbose_name = "저장 파일"
        verbose_name_plural = "저장 파일"
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
        verbose_name = "영상 파일"
        verbose_name_plural = "영상 파일"
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
    # 검출기 판. 분류기(model_version)와 따로 올라가는 소켓이 있어 한 칸에
    # 담으면 어느 쪽이 바뀌었는지 구분이 안 된다.
    det_version = models.CharField(max_length=100, blank=True, null=True)
    lora_version = models.CharField(max_length=100, blank=True, null=True)
    threshold_version = models.CharField(max_length=30, blank=True, null=True)
    operating_point = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(blank=True, null=True)
    registered_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        # 표 이름은 model 이다 — 클래스 이름만 AiModel 이다(위 주석 참고)
        db_table = 'model'
        verbose_name = "AI 모델"
        verbose_name_plural = "AI 모델"


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
    # 100 자로는 모자란다. 추론 서버가 긴 사유를 보내면 varchar 가 DataError 를
    # 내고 **AI 결과 저장이 통째로 실패한다** — 기권은 정상 종료인데 기록이
    # 안 남는 셈이다.
    abstain_reason = models.TextField(blank=True, null=True)
    run_status = models.CharField(max_length=20, choices=as_choices(RUN_STATUS),
                                  blank=True, null=True)
    requested_by = models.ForeignKey(Staff, models.PROTECT, blank=True, null=True,
                                     related_name='+', db_column='requested_by')
    analyzed_at = models.DateTimeField(blank=True, null=True)
    elapsed_sec = models.DecimalField(max_digits=8, decimal_places=3,
                                      blank=True, null=True)

    class Meta:
        db_table = 'ai_result'
        verbose_name = "AI 결과"
        verbose_name_plural = "AI 결과"
        constraints = [
            # storage_object_owner_ck 와 같은 모양이다.
            models.CheckConstraint(
                condition=Exact(NumNonNulls('study', 'specimen'), 1),
                name='ai_result_owner_ck'),
        ]


class Lesion(AuditBase):
    """병변 1개. 판정 · 검체 · 대조가 모두 여기에 붙는 허브다.

    **병변은 영상이 만든다. 검체가 거기 매달린다.** 그래서 영상 판독 없이
    병리만 도는 경로는 구조상 없다 — specimen.lesion_id 가 NOT NULL 인 것이
    그 뜻이고, 사후에 이어 붙일 수 없어서 Hard Stop 으로 둔 것이다.
    """

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
        verbose_name = "병변"
        verbose_name_plural = "병변"
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
        verbose_name = "판정"
        verbose_name_plural = "판정"
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
        verbose_name = "검체"
        verbose_name_plural = "검체"
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
        verbose_name = "불일치 플래그"
        verbose_name_plural = "불일치 플래그"
        constraints = [
            models.CheckConstraint(
                condition=Q(disposition_type__in=DISPOSITION_TYPE)
                | Q(disposition_type__isnull=True),
                name='discordance_flag_disposition_type_ck'),
        ]


class Report(AuditBase):
    """리포트 1건. 검사별(stage)과 종합(final), 의료진용과 환자용."""
    specimen = models.ForeignKey('Specimen', models.PROTECT, blank=True,null=True, related_name='reports')
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
        verbose_name = "리포트"
        verbose_name_plural = "리포트"
        constraints = [
            # lesion_modality_ck 와 같은 누락이었다 — 값 집합은 정의해 뒀는데
            # CHECK 을 안 걸어서 DB 가 아무 문자열이나 받았다.
            models.CheckConstraint(
                condition=Q(socket_id__in=REPORT_SOCKET_ID)
                | Q(socket_id__isnull=True),
                name='report_socket_id_ck'),
        ]


class Prescription(AuditBase):
    """유방외과 처방 1건.

    ⚠ v10 신설 — DB_스키마_v10_20260908.docx 에 없던 표다. 처방 API가
    아직 없어 화면이 임시 상태였던 것을 메우려고 09-21 추가했다. 팀 확인
    대상 — 문서에 반영 요청할 것 (§15 의 「prescription 표가 없다」 메모와
    같은 자리).

    exam_order 또는 report 중 **정확히 하나**에 매달린다 — StorageObject의
    owner 제약(study/specimen/report 중 하나)과 같은 자리다. 검사(오더)
    시점에 바로 처방할 수도, 확정 리포트를 보고 처방할 수도 있어 둘 다
    열어 두되 동시에 채우거나 둘 다 비우는 것은 막는다.
    """

    prescription_id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='prescriptions')
    exam_order = models.ForeignKey(ExamOrder, models.PROTECT, blank=True, null=True,
                                   related_name='prescriptions')
    report = models.ForeignKey('Report', models.PROTECT, blank=True, null=True,
                               related_name='prescriptions')
    # 약품명 · 용법 등. 항목 수가 처방마다 달라 고정 칼럼으로 못 쪼갠다 —
    # Report.content_json 과 같은 사정이다.
    content = models.JSONField(blank=True, null=True)
    prescribed_by = models.ForeignKey('Account', models.PROTECT, blank=True, null=True,
                                      related_name='+', db_column='prescribed_by')
    prescribed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'prescription'
        verbose_name = "처방"
        verbose_name_plural = "처방"
        constraints = [
            models.CheckConstraint(
                condition=Exact(NumNonNulls('exam_order', 'report'), 1),
                name='prescription_owner_ck'),
        ]


# ── 처방 약 · 복약 기록 ───────────────────────────────────────────────────
#
# 위 Prescription(09-21 다희님)에 **매달리는** 두 표다. 그쪽을 고치지 않는다 —
# content(jsonb)도 exam_order/report owner CHECK 도 그대로 둔다.
#
# ── 왜 content 만으로는 안 되나 ─────────────────────────────────────
#
# 환자 앱의 복약 관리가 「먹었다」를 적는다. 그 기록이 약 한 줄을 가리켜야
# 하는데 **jsonb 안의 배열에는 가리킬 열쇠가 없다.** 순서로 가리키면 의사가
# 약을 하나 지우는 순간 지난 기록이 전부 다른 약을 가리킨다.
#
# 그래서 content 를 없애지 않고, 저장할 때 그 안의 drugs 를 행으로도 편다
# (core/views/surgery.py 의 PrescriptionViewSet.create). content 는 의사가
# 보낸 것 그대로의 원본이고, 아래 표는 환자 앱이 회차를 걸 수 있는 열쇠다.
#
# ── 환자에게 언제 보이나 ────────────────────────────────────────────
#
# ⚠ **저장하는 즉시 보인다.** 리포트의 lock_status 를 따르지 않는다
#   (2026-09-21 팀 결정). 약은 오늘부터 먹어야 하는 것이라 대면 설명
#   날짜까지 묶어 두면 복약이 그만큼 늦어진다.
#
#   잠금이 막으려던 것은 「설명 전에 환자가 결과를 먼저 읽는 것」인데 처방에는
#   소견이 실리지 않으므로 그 취지도 깨지지 않는다. 그래서 **purpose · how ·
#   watch 에 소견 문장을 적지 말 것** — 적는 순간 잠금 우회로가 된다.

class PrescriptionDrug(models.Model):
    """처방 안의 약 한 줄.

    ⚠ AuditBase 를 안 쓴다. Prescription 이 감사 칸을 들고 있고, 약은 그것과
      **함께 생겼다 함께 사라지는** 종속물이다. 약마다 created_by 를 또 두면
      처방의 것과 다를 수 있는 것처럼 보인다 — 그런 경로는 없다.
    """

    drug_id = models.BigAutoField(primary_key=True)
    prescription = models.ForeignKey(Prescription, models.CASCADE, related_name='drugs')
    name = models.CharField(max_length=200)
    # 성분명. 같은 성분의 다른 제품으로 바뀌었을 때 환자가 알아보게 한다.
    ingredient = models.CharField(max_length=200, blank=True, null=True)
    dose = models.CharField(max_length=50)              # 1회 복용량 — "1정"
    # 하루 중 언제 먹나. ["09:00", "19:00"] 다.
    #
    # ⚠ 개수(per_day)를 따로 두지 않는다. times 의 길이가 곧 그것이라
    #   두 칸을 두면 어긋날 수 있고, 어긋나면 어느 쪽이 맞는지 아무도 모른다.
    times = models.JSONField(default=list)
    # 이 약을 며칠 먹나. **약마다 다르다** (2026-09-21 팀 결정) — 한 장 안에
    # 3일치 진통제와 30일치 호르몬제가 같이 나온다. 그래서 Prescription 이
    # 아니라 여기 있다.
    days = models.IntegerField()
    purpose = models.CharField(max_length=250, blank=True, null=True)   # 무엇에 쓰나요
    how = models.TextField(blank=True, null=True)                       # 어떻게 드시나요
    watch = models.TextField(blank=True, null=True)                     # 이럴 땐 알려 주세요

    class Meta:
        db_table = 'prescription_drug'
        verbose_name = "처방 약"
        verbose_name_plural = "처방 약"
        constraints = [
            models.CheckConstraint(condition=Q(days__gte=1),
                                   name='prescription_drug_days_ck'),
        ]

    def __str__(self):
        return "%s %s" % (self.name, self.dose)


class MedicationLog(models.Model):
    """「먹었다」 한 번.

    ── 시각을 둘로 나눠 둔다 ───────────────────────────────────────
    slot_time   어느 회차인가 ("09:00"). 앱이 보낸다.
    taken_at    실제로 누른 때. **서버가 찍는다.**

    ⚠ 앱이 보낸 시각을 taken_at 에 넣지 않는다. 기기 시계가 틀어진 만큼
      기록이 어긋나는데, 나중에 「언제 드셨나요」를 되짚을 때 그것이 유일한
      근거다.

    ⚠ 환자가 잘못 눌렀을 때는 **행을 지운다**(DELETE .../log/{id}).
      취소 표시를 남기지 않는 이유는 그것이 자료가 아니라 오타이기 때문이다.
    """

    log_id = models.BigAutoField(primary_key=True)
    drug = models.ForeignKey(PrescriptionDrug, models.CASCADE, related_name='logs')
    # 약에서 처방을 거쳐 환자로 갈 수 있지만, 조회가 늘 환자에서 시작해서
    # 두 번 건너야 한다. 자주 도는 길이라 여기 둔다.
    patient = models.ForeignKey(Patient, models.PROTECT, related_name='medication_logs')
    slot_time = models.CharField(max_length=5)          # "09:00"
    taken_at = models.DateTimeField(auto_now_add=True)
    # 어느 날의 회차인가. taken_at 에서 뽑을 수도 있지만 자정 직전에 누른
    # 「저녁 약」이 다음 날로 넘어가면 안 된다 — 앱이 보는 날짜를 그대로 둔다.
    taken_on = models.DateField()

    class Meta:
        db_table = 'medication_log'
        verbose_name = "복약 기록"
        verbose_name_plural = "복약 기록"
        constraints = [
            # 같은 날 같은 회차를 두 번 적지 않는다. 화면이 낙관적으로
            # 채우는 자리라 두 번 눌리는 일이 실제로 난다.
            models.UniqueConstraint(fields=['drug', 'taken_on', 'slot_time'],
                                    name='medication_log_slot_uq'),
        ]

    def __str__(self):
        return "%s %s %s" % (self.drug_id, self.taken_on, self.slot_time)


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
        verbose_name = "알림"
        verbose_name_plural = "알림"
        constraints = [
            models.CheckConstraint(condition=Q(notification_type__in=NOTIFICATION_TYPE),
                                   name='notification_type_ck'),
            # choices 만 있고 CHECK 이 없었다. choices 는 폼 검증이라
            # I-3 콜백처럼 .save() 로 들어오는 값은 아무거나 통과한다.
            models.CheckConstraint(
                condition=Q(channel__in=NOTIFICATION_CHANNEL)
                | Q(channel__isnull=True),
                name='notification_channel_ck'),
            # 환자 아니면 의료진, 정확히 하나
            models.CheckConstraint(
                condition=(Q(patient__isnull=False) & Q(staff__isnull=True))
                | (Q(patient__isnull=True) & Q(staff__isnull=False)),
                name='notification_recipient_ck'),
        ]


class PersonalNote(models.Model):
    """Todo · 스티키 메모 공용 표 — 개인 전용, 본인만 본다.

    ⚠ v10 에도 §15 문서에도 없다. 대시보드 "내 업무" 할일과 노란 스티키
    메모가 지금까지 브라우저 저장만 됐던 것을 서버로 옮기며 09-21 새로
    만들었다 — 팀 확인 대상.

    todo 와 sticky 는 "사람이 자기 화면에 잠깐 적어 두는 것"이라는 성격이
    같아 표 하나로 묶는다. 모양만 다르고 그 모양은 content 안에서 갈린다
    (여기서 스키마로 강제하지 않는다 — 화면마다 칸이 늘 수 있어서 JSON
    으로 열어 둔다):
        todo    {"text": …, "done": false}
        sticky  {"text": …, "color": "#fef08a"}

    AuditBase 를 안 쓴다 — created_by/updated_by 는 이 표에서 owner 와
    항상 같은 값이라(본인 것만 본인이 쓴다) 칸을 하나 더 둘 이유가 없다.
    """

    personal_note_id = models.BigAutoField(primary_key=True)
    owner = models.ForeignKey('Account', models.CASCADE, related_name='personal_notes')
    note_type = models.CharField(max_length=10, choices=as_choices(NOTE_TYPE))
    content = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'personal_note'
        verbose_name = "개인 메모"
        verbose_name_plural = "개인 메모"
        constraints = [
            models.CheckConstraint(condition=Q(note_type__in=NOTE_TYPE),
                                   name='personal_note_type_ck'),
        ]
