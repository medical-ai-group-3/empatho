"""유방외과 워크리스트 — GET /api/v1/surgery/worklist (views/surgery.py SurgeryWorklistView).

한 환자 = 한 줄. 줄마다 「이 환자에게 지금 해야 할 일」 하나(next_step)를
서버가 정한다. 화면이 여러 응답을 모아 추론하던 것을 한 곳으로 모은다.

── 누가 줄에 서나 ─────────────────────────────────────────────────
  (a) 주치의가 나(?primary_staff=me, 기본) · 그 직원 번호 · 또는
      ?scope=all 이면 주치의가 유방외과인 환자 전부
  (b) 최근 30일 안에 움직임이 있거나(오더 · 내원 · 예약 · 판독 확정 ·
      검체 확정 · 소견서 · 치료 결정 · 설명 · 처방) **끝나지 않은 일**이
      있다(next_step 이 SOFT_STEPS 가 아닌 것)

── next_step — next_step() 한 함수가 정한다 ──────────────────────
  위에서부터 처음 걸리는 것이 답이다.
    discordance   처분 안 된 영상·병리 불일치가 있다(closed_at IS NULL)
    review        확정된 결과(판독 · 병리)가 유방외과 마지막 열람보다 새롭다
    wait_results  낸 검사가 아직 결과 전이다(pending_orders > 0)
    report        확정된 결과가 있는데 종합 소견서가 없거나, 소견서보다
                  새 결과가 있다
    decision      소견서는 있는데 가장 새 결과 이후의 치료 결정이 없다
    explain       가장 새 소견서를 아직 환자에게 설명하지 않았다
    prescription  설명은 했는데(30일 안) 그 뒤 처방이 없다
    exam          오늘 내원해 진료 중인데 오늘 낸 검사가 없다(오늘 결과
                  설명을 한 방문은 제외 — 그건 close)
    close         오늘 내원 오더가 아직 안 닫혔다(진료 완료 전)
    followup      그 밖 — 다음 방문 · 추적 관찰 대기

  prescription · followup 은 「무른 단계」(SOFT_STEPS)다 — 처방이 필요
  없는 환자도 있고, 추적은 끝이 없는 일이라 이 둘만으로는 줄에 세우지
  않는다(최근 30일 움직임이 있어야 선다).

── 칸의 뜻 ────────────────────────────────────────────────────────
  pending_orders   결과 전인 것의 수 = 영상 오더(modality 가 있고 취소 ·
                   재촬영으로 대체 · 촬영 없이 완료된 것을 뺀 것 중 판독 확정
                   study 가 없는 것) + 병리 확정 전 검체
  unseen_results   유방외과가 아직 못 본 확정 결과의 수. core/viewed.py 의
                   기준 그대로 — study · specimen 의 판독 리포트(stage)에
                   유방외과가 남긴 마지막 열람 시각이 없거나 확정 시각보다
                   이르면 미열람. ⚠ 판독 리포트가 아직 없는 결과는 열람을
                   남길 자리가 없어 세지 않는다(세면 영영 안 꺼진다).
  final_report_id  가장 새 종합 소견서(의사용 우선). 없으면 null
  report_explained 그 소견서(같은 발급 묶음)를 설명했는가
  decision         가장 새 치료 결정의 decision_value(없으면 null)
  prescription_count 이 환자의 처방 전체 건수

── 쿼리 수 ─────────────────────────────────────────────────────────
  줄 수와 상관없이 고정이다(환자 1 + 오늘 오더 1 + 미열람 판독 1 + 미열람
  검체 1). 줄마다 부르지 않는다 — test_flow_0928_surgery_nursing 이 센다.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db.models import (Count, Exists, F, IntegerField, Max, OuterRef, Q,
                              Subquery, Value)
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import models, viewed

WINDOW_DAYS = 30

#: 우선순위 순서. 화면 탭 순서로도 쓴다.
STEPS = ("discordance", "review", "wait_results", "report", "decision",
         "explain", "prescription", "exam", "close", "followup")
SOFT_STEPS = frozenset({"prescription", "followup"})

# 아직 안 닫힌 방문(reception._OPEN_VISIT_STATUSES 와 같은 값)
OPEN_VISIT = ("requested", "scheduled", "ordered", "accepted", "in_progress")


def next_step(f, today=None):
    """사실 묶음 f(dict)로 다음 할 일을 하나 정한다. 순수 함수 — DB 를 안 본다.

    f 의 열쇠: open_discordance · unseen_results · pending_orders ·
    last_result_at · final_report_id · final_report_at · decided_at ·
    explained_at · last_prescribed_at · open_visit_today ·
    exam_ordered_today. 시각은 aware datetime 이거나 None.
    """
    now = timezone.now()
    today = today or timezone.localdate()
    if f.get("open_discordance"):
        return "discordance"
    if f.get("unseen_results"):
        return "review"
    if f.get("pending_orders"):
        return "wait_results"

    last_result = f.get("last_result_at")
    report_at = f.get("final_report_at")
    if last_result is not None and (f.get("final_report_id") is None
                                    or report_at is None or last_result > report_at):
        return "report"

    explained_at = f.get("explained_at")
    if f.get("final_report_id") is not None:
        decided = f.get("decided_at")
        if decided is None or (last_result is not None and decided < last_result):
            return "decision"
        if explained_at is None:
            return "explain"
        anchor = last_result or report_at
        rx = f.get("last_prescribed_at")
        recent = explained_at >= now - timedelta(days=WINDOW_DAYS)
        if recent and (rx is None or (anchor is not None and rx < anchor)):
            return "prescription"

    if f.get("open_visit_today"):
        explained_today = (explained_at is not None
                           and timezone.localtime(explained_at).date() == today)
        if not f.get("exam_ordered_today") and not explained_today:
            return "exam"
        return "close"
    return "followup"


def _count(qs):
    """상관 서브쿼리로 센다 — 조인 곱으로 수가 부풀지 않게. qs 는 patient_id 로 걸린 것."""
    return Coalesce(Subquery(
        qs.order_by().values("patient_id").annotate(n=Count("pk")).values("n")[:1],
        output_field=IntegerField()), Value(0))


def _latest(qs, field, order):
    return Subquery(qs.order_by(order).values(field)[:1])


def patient_scope(request_staff, primary_staff="me", scope=None):
    """(a) 조건의 환자 쿼리셋."""
    qs = models.Patient.objects.all()
    if scope == "all":
        return qs.filter(primary_staff__account__role="surgery")
    if primary_staff == "me":
        if request_staff is None:
            return qs.none()
        return qs.filter(primary_staff=request_staff)
    return qs.filter(primary_staff_id=int(primary_staff))


def build(patients_qs):
    """patients_qs(환자 쿼리셋)로 {items, counts} 를 만든다."""
    now = timezone.now()
    today = timezone.localdate()
    cut = now - timedelta(days=WINDOW_DAYS)
    P = OuterRef("pk")

    orders = models.ExamOrder.objects.filter(patient_id=P)
    finals = models.Report.objects.filter(patient_id=P, report_type="final")
    decided = models.Assessment.objects.filter(study__patient_id=P, decided_at__isnull=False)
    rx = models.Prescription.objects.filter(patient_id=P)

    pending_imaging = orders.filter(modality__isnull=False).exclude(
        order_status="cancelled").exclude(
        Exists(models.Study.objects.filter(exam_order_id=OuterRef("pk"),
                                           read_status="finalized"))).exclude(
        Exists(models.ExamOrder.objects.filter(parent_order_id=OuterRef("pk")))).exclude(
        Q(order_status="completed")
        & ~Exists(models.Study.objects.filter(exam_order_id=OuterRef("pk"))))
    pending_specimens = models.Specimen.objects.filter(patient_id=P, finalized_at__isnull=True)

    qs = (patients_qs
          .select_related("pii")
          .annotate(
              last_visit_at=_latest(orders.filter(visited_at__isnull=False),
                                    "visited_at", "-visited_at"),
              open_discordance=Exists(models.DiscordanceFlag.objects.filter(
                  lesion__patient_id=P, closed_at__isnull=True)),
              last_flag_at=_latest(models.DiscordanceFlag.objects.filter(
                  lesion__patient_id=P, flagged_at__isnull=False),
                  "flagged_at", "-flagged_at"),
              final_report_id=Coalesce(
                  _latest(finals.filter(audience="clinician"), "report_id", "-report_id"),
                  _latest(finals, "report_id", "-report_id")),
              final_report_at=_latest(finals, "created_at", "-created_at"),
              decision=_latest(decided, "decision_value", "-decided_at"),
              decided_at=_latest(decided, "decided_at", "-decided_at"),
              prescription_count=_count(rx),
              last_prescribed_at=Subquery(
                  rx.annotate(at=Coalesce("prescribed_at", "created_at"))
                  .order_by("-at").values("at")[:1]),
              pending_orders=_count(pending_imaging) + _count(pending_specimens),
              last_study_final_at=_latest(
                  models.Assessment.objects.filter(study__patient_id=P, read_stage="final",
                                                   finalized_at__isnull=False),
                  "finalized_at", "-finalized_at"),
              # 09-28 — 전체 환자 표의 「최근 BI-RADS · B」 칸. 정정으로 덮인
              # 판정은 뺀다(superseded_by 가 찬 것)
              latest_birads=_latest(
                  models.Assessment.objects.filter(study__patient_id=P, read_stage="final",
                                                   finalized_at__isnull=False,
                                                   superseded_by__isnull=True),
                  "category", "-finalized_at"),
              latest_b_category=_latest(
                  models.Specimen.objects.filter(patient_id=P, finalized_at__isnull=False),
                  "b_category", "-finalized_at"),
              last_specimen_final_at=_latest(
                  models.Specimen.objects.filter(patient_id=P, finalized_at__isnull=False),
                  "finalized_at", "-finalized_at"),
              recent_order=Exists(orders.filter(
                  Q(visited_at__gte=cut) | Q(ordered_at__gte=cut)
                  | Q(scheduled_at__gte=cut) | Q(created_at__gte=cut))),
          )
          # 설명은 **가장 새 소견서 발급 뒤**의 것만 센다 — 옛 소견서를 설명한
          # 기록이 새 소견서를 「설명함」으로 만들지 않게.
          .annotate(explained_at=Subquery(
              models.Report.objects.filter(
                  patient_id=P, report_type="final", explained_at__isnull=False,
                  explained_at__gte=OuterRef("final_report_at"))
              .order_by("-explained_at").values("explained_at")[:1]))
          .order_by("pk"))
    patients = list(qs)
    if not patients:
        return {"items": [], "counts": _counts([])}
    ids = [p.pk for p in patients]

    # 오늘 오더 — 내원했거나 오늘 검사를 낸 것. 한 번에 읽는다
    todays = (models.ExamOrder.objects
              .filter(patient_id__in=ids)
              .filter(Q(visited_at__date=today)
                      | Q(ordered_at__date=today, modality__isnull=False))
              .annotate(has_study=Exists(models.Study.objects.filter(
                  exam_order_id=OuterRef("pk"))))
              .order_by("visited_at", "exam_order_id"))
    today_by = {}
    for o in todays:
        today_by.setdefault(o.patient_id, []).append(o)

    # 미열람 — core/viewed.py 기준. 판독 리포트가 있는 확정 결과만
    unseen = {}
    studies = (models.Study.objects
               .filter(patient_id__in=ids, read_status="finalized")
               .filter(Exists(models.Report.objects.filter(
                   study_id=OuterRef("pk"), report_type="stage")))
               .annotate(final_at=Max("assessments__finalized_at",
                                      filter=Q(assessments__read_stage="final")),
                         viewed_at=viewed.last_seen("study"))
               .values("patient_id", "final_at", "viewed_at"))
    specimens = (models.Specimen.objects
                 .filter(patient_id__in=ids, finalized_at__isnull=False)
                 .filter(Exists(models.Report.objects.filter(
                     specimen_id=OuterRef("pk"), report_type="stage")))
                 .annotate(final_at=F("finalized_at"),
                           viewed_at=viewed.last_seen("specimen"))
                 .values("patient_id", "final_at", "viewed_at"))
    for row in list(studies) + list(specimens):
        if row["final_at"] is None:
            continue
        if row["viewed_at"] is None or row["viewed_at"] < row["final_at"]:
            unseen[row["patient_id"]] = unseen.get(row["patient_id"], 0) + 1

    from .views.reception import PatientTodayStatusView   # 단계 이름을 한 곳에서
    items = []
    for p in patients:
        mine = today_by.get(p.pk, [])
        visits = [o for o in mine if o.visited_at is not None]
        open_visits = [o for o in visits if o.order_status in OPEN_VISIT]
        stage_order = (open_visits or visits or [None])[-1]
        results = [t for t in (p.last_study_final_at, p.last_specimen_final_at) if t]
        facts = {
            "open_discordance": p.open_discordance,
            "unseen_results": unseen.get(p.pk, 0),
            "pending_orders": p.pending_orders,
            "last_result_at": max(results) if results else None,
            "final_report_id": p.final_report_id,
            "final_report_at": p.final_report_at,
            "decided_at": p.decided_at,
            "explained_at": p.explained_at,
            "last_prescribed_at": p.last_prescribed_at,
            "open_visit_today": bool(open_visits),
            "exam_ordered_today": any(
                o.modality and o.ordered_at and o.order_status != "cancelled"
                and timezone.localtime(o.ordered_at).date() == today for o in mine),
        }
        step = next_step(facts, today=today)
        stamps = [p.last_visit_at, p.last_flag_at, p.final_report_at, p.decided_at,
                  p.explained_at, p.last_prescribed_at, facts["last_result_at"]]
        recent = p.recent_order or any(t is not None and t >= cut for t in stamps)
        if not recent and step in SOFT_STEPS:
            continue
        pii = getattr(p, "pii", None)
        items.append({
            "patient_id": p.pk,
            "patient_name": getattr(pii, "name", None),
            "patient_number": p.patient_number,
            "age": _age(getattr(pii, "birth_date", None), today),
            "sex": p.sex,
            "has_allergy": p.has_allergy,
            "last_visit_at": p.last_visit_at,
            "today_stage": (PatientTodayStatusView._stage(stage_order)[2]
                            if stage_order is not None else None),
            "pending_orders": p.pending_orders,
            "unseen_results": facts["unseen_results"],
            "open_discordance": p.open_discordance,
            "final_report_id": p.final_report_id,
            "report_explained": p.explained_at is not None,
            "decision": p.decision,
            "latest_birads": p.latest_birads,
            "latest_b_category": p.latest_b_category,
            "prescription_count": p.prescription_count,
            "next_step": step,
        })

    rank = {s: i for i, s in enumerate(STEPS)}
    far = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
    items.sort(key=lambda i: (rank[i["next_step"]],
                              -(i["last_visit_at"] or far).timestamp(),
                              i["patient_id"]))
    return {"items": items, "counts": _counts(items)}


def _counts(items):
    out = {s: 0 for s in STEPS}
    for i in items:
        out[i["next_step"]] += 1
    out["open_discordance"] = sum(1 for i in items if i["open_discordance"])
    out["total"] = len(items)
    return out


def _age(birth_date, today):
    if birth_date is None:
        return None
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day))
