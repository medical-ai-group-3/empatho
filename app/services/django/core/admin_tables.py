"""주요 표 일곱 — 관리자가 자료를 찾아보는 자리.

  patient · exam_order · study · ai_result · specimen · discordance_flag · report

여기는 **고치는 자리가 아니라 찾는 자리**다. 관리자가 「그 환자 검사가 어디까지
갔나」 · 「AI 가 실패한 건이 몇 개인가」를 볼 수 있어야 한다. 그래서 세 가지를
공통으로 맞춘다.

  list_display    한 줄로 무엇인지 알 수 있는 칸들
  list_filter     큐를 가르는 상태 칸
  search_fields   환자번호 · 이름으로 닿는 길

── 검색은 환자번호와 이름으로 ──────────────────────────────────────
관리자가 들고 오는 것은 거의 언제나 환자번호나 이름이다. 표마다 환자로 가는
길이 달라서(study → patient, specimen → patient) 각 표에서 그 경로를 적어 준다.

⚠ 이름은 patient_pii 에 있다. 개인정보라 목록 칸으로는 안 내보내고
  **검색으로만** 닿게 한다 — 목록을 열면 전부 보이는 것과, 아는 이름을
  쳐서 찾는 것은 다르다.

⚠ **admin 으로 고친 행은 updated_by 가 NULL 이다.** 그 칸은 account 를
  가리키는데 admin 은 auth_user 로 로그인해서 옮길 수가 없다.
"""

from django.contrib import admin

from .models import (
    AiResult, DiscordanceFlag, ExamOrder, Patient, Report, Specimen, Study,
)

# 전 표 공통. 감사 칸은 손으로 고치는 것이 아니다
AUDIT_RO = ("created_at", "created_by", "updated_at", "updated_by")


class ReadMostly(admin.ModelAdmin):
    """찾는 자리의 공통 뼈대.

    지우기를 막는다 — 이 표들은 전부 PROTECT 로 얽혀 있어서 한 줄을 지우면
    어디가 끊길지 admin 화면에서는 안 보인다. 그리고 임상 기록은 지우는 것이
    아니라 상태로 물린다(cancelled · superseded).
    """

    list_per_page = 50
    readonly_fields = AUDIT_RO

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Patient)
class PatientAdmin(ReadMostly):
    list_display = ("patient_number", "name", "sex", "birth_year",
                    "allergy", "first_visited_at", "primary_staff")
    list_filter = ("sex", "has_allergy")
    search_fields = ("patient_number", "pii__name", "pii__phone")
    list_select_related = ("pii", "primary_staff")
    ordering = ("-created_at",)

    @admin.display(description="이름", ordering="pii__name")
    def name(self, obj):
        pii = getattr(obj, "pii", None)
        return pii.name if pii else "—"

    # 조영제 알레르기는 촬영 전에 반드시 보여야 하는 값이라 목록에 세운다
    @admin.display(description="알레르기", boolean=True)
    def allergy(self, obj):
        return bool(obj.has_allergy)


@admin.register(ExamOrder)
class ExamOrderAdmin(ReadMostly):
    list_display = ("exam_order_id", "patient_number", "order_status",
                    "modality", "exam_purpose", "scheduled_at", "visited_at",
                    "assigned_to")
    list_filter = ("order_status", "modality", "exam_purpose")
    search_fields = ("patient__patient_number", "patient__pii__name")
    list_select_related = ("patient", "assigned_to")
    date_hierarchy = "scheduled_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(Study)
class StudyAdmin(ReadMostly):
    list_display = ("study_id", "patient_number", "modality", "read_status",
                    "quality_status", "density_category", "performed_at")
    list_filter = ("modality", "read_status", "quality_status",
                   "density_category")
    # study_uid 로도 찾게 둔다 — PACS 쪽에서 그 값을 들고 문의가 온다
    search_fields = ("patient__patient_number", "patient__pii__name",
                     "study_uid", "orthanc_study_id")
    list_select_related = ("patient",)
    date_hierarchy = "performed_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(AiResult)
class AiResultAdmin(ReadMostly):
    list_display = ("ai_result_id", "patient_number", "requested_socket_id",
                    "run_status", "abstained", "model", "elapsed_sec",
                    "analyzed_at")
    list_filter = ("run_status", "abstained", "requested_socket_id", "model")
    search_fields = ("patient__patient_number", "patient__pii__name")
    list_select_related = ("patient", "model")
    date_hierarchy = "analyzed_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(Specimen)
class SpecimenAdmin(ReadMostly):
    list_display = ("specimen_label", "patient_number", "accession_status",
                    "specimen_type", "b_category", "diagnosis_code",
                    "collected_at", "finalized_at")
    list_filter = ("accession_status", "specimen_type", "guidance_route",
                   "b_category")
    search_fields = ("specimen_label", "patient__patient_number",
                     "patient__pii__name")
    list_select_related = ("patient",)
    date_hierarchy = "collected_at"
    ordering = ("-created_at",)

    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number


@admin.register(DiscordanceFlag)
class DiscordanceFlagAdmin(ReadMostly):
    """영상 판정과 병리 확진이 갈린 건. **미처리로 남으면 안 되는 표다.**

    그래서 flag_status 가 맨 앞에 오고 기본 정렬이 오래된 순이다 — 늦게 들어온
    것이 위에 쌓이면 오래 묵은 건이 아래로 밀려 안 보인다.
    """

    list_display = ("discordance_flag_id", "flag_status", "violated_rule",
                    "disposition_type", "flagged_at", "reviewed_by",
                    "closed_at")
    list_filter = ("flag_status", "violated_rule", "disposition_type")
    search_fields = ("specimen__patient__patient_number",
                     "specimen__patient__pii__name",
                     "specimen__specimen_label")
    list_select_related = ("specimen", "reviewed_by")
    date_hierarchy = "flagged_at"
    ordering = ("flagged_at",)          # 오래된 것이 위


@admin.register(Report)
class ReportAdmin(ReadMostly):
    list_display = ("report_id", "patient_number", "report_type", "audience",
                    "socket_id", "lock_status", "patient_confirmed",
                    "view_count", "last_viewed_at")
    list_filter = ("report_type", "audience", "lock_status",
                   "patient_confirmed", "socket_id")
    search_fields = ("patient__patient_number", "patient__pii__name")
    list_select_related = ("patient",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    # 본문은 목록에 안 낸다 — 길어서 표가 못 읽게 되고, 환자에게 나가는
    # 글이라 목록에 펼쳐 두는 것이 맞지 않다
    @admin.display(description="환자번호", ordering="patient__patient_number")
    def patient_number(self, obj):
        return obj.patient.patient_number
