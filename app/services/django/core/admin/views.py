"""admin 안의 우리 화면들 — 대시보드 · 서버 상태 · 계정 승인 · DB 조회.

⚠ 숫자만 낸다. 환자 이름도 소견도 안 나온다 — 관리자는 시스템 관리자다.

표 하나당 GROUP BY 한 번으로 상태별 개수를 통째로 받는다. 칸마다 count()
를 부르면 첫 화면 한 번에 스무 번 넘게 DB 를 친다.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.db.models.functions import TruncHour
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from ..models import (
    Account, AiResult, DiscordanceFlag, ExamOrder, Patient, Report, Specimen,
    Study,
)

ROLE_NAMES = {
    "reception": "원무", "nursing": "간호", "radiology": "영상",
    "pathology": "병리", "surgery": "유방외과", "admin": "관리자",
    "patient": "환자",
}
STATUS_NAMES = {
    "pending": "승인 대기", "active": "활성",
    "rejected": "거절", "suspended": "정지",
}


def _tally(model, field):
    """상태별 개수를 한 번에. {값: 개수}"""
    rows = model.objects.values(field).annotate(n=Count("*"))
    return {r[field]: r["n"] for r in rows}


def _url(model, **params):
    """그 표의 admin 목록 주소. params 가 있으면 필터를 걸어 연다."""
    meta = model._meta
    path = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")
    if not params:
        return path
    return path + "?" + "&".join(f"{k}={v}" for k, v in params.items())


def _cell(label, count, url=None, warn=False):
    """칸 하나. warn 은 「오래 두면 안 되는 것」이라 눈에 걸리게 한다."""
    return {"label": label, "count": count, "url": url, "warn": warn}


def dash_numbers(request):
    """첫 화면에 넘길 묶음 넷."""
    today = timezone.localdate()

    acc = _tally(Account, "account_status")
    role = _tally(Account, "role")
    order = _tally(ExamOrder, "order_status")
    run = _tally(AiResult, "run_status")
    read = _tally(Study, "read_status")
    acc_st = _tally(Specimen, "accession_status")
    flag = _tally(DiscordanceFlag, "flag_status")

    # ── 계정 ────────────────────────────────────────────────────
    accounts = [
        _cell("전체", sum(acc.values()), _url(Account, approval="all", kind="all")),
        _cell("승인 대기", acc.get("pending", 0),
              _url(Account, approval="pending"), warn=acc.get("pending", 0) > 0),
        _cell("활성", acc.get("active", 0), _url(Account, approval="active")),
        _cell("정지", acc.get("suspended", 0), _url(Account, approval="suspended")),
    ]
    roles = [
        _cell(ROLE_NAMES.get(r, r), n,
              _url(Account, approval="all", kind="all", role__exact=r))
        for r, n in sorted(role.items(), key=lambda x: -x[1]) if n
    ]

    # ── 진행 중 ─────────────────────────────────────────────────
    #
    # 승인 대기가 맨 위다. 관리자가 지금 할 일이고, 안 풀면 그 사람이
    # 아예 못 들어온다.
    #
    # 불일치는 pass 를 뺀 나머지가 전부 미해소다 — sev1 · sev2 · review ·
    # unbindable 이 각각 다른 이유로 남아 있는 것이라 한 덩어리로 센다.
    open_flags = sum(n for s, n in flag.items() if s != "pass")
    working = [
        _cell("승인 대기 계정", acc.get("pending", 0),
              _url(Account, approval="pending"), warn=acc.get("pending", 0) > 0),
        _cell("AI 분석 대기", run.get("queued", 0),
              _url(AiResult, run_status__exact="queued")),
        _cell("AI 실행 중", run.get("running", 0),
              _url(AiResult, run_status__exact="running")),
        _cell("AI 실패", run.get("failed", 0),
              _url(AiResult, run_status__exact="failed"),
              warn=run.get("failed", 0) > 0),
        _cell("판독 대기", read.get("pending", 0),
              _url(Study, read_status__exact="pending")),
        _cell("판독 작성 중", read.get("draft", 0),
              _url(Study, read_status__exact="draft")),
        _cell("검체 접수 대기", acc_st.get("unbound", 0) + acc_st.get("bound", 0),
              _url(Specimen, accession_status__exact="bound")),
        _cell("미해소 불일치", open_flags,
              _url(DiscordanceFlag), warn=open_flags > 0),
    ]

    # ── 최근 24시간 ─────────────────────────────────────────────
    # 「막힌 데가 있나」를 본다. 그중 **추론 대기**가 핵심이다 — 워커가 죽거나
    # 큐가 막히면 여기만 는다. 나머지 셋은 정상이어도 는다.
    since = timezone.now() - timedelta(hours=24)
    stuck_before = timezone.now() - timedelta(
        minutes=settings.ADMIN_INFERENCE_WAIT_MIN)

    # 실패와 보류는 칸이 다르다 — run_status 는 실행 결과, abstained 는 판단 보류
    ai = AiResult.objects.filter(created_at__gte=since).aggregate(
        made=Count("pk"),
        bad=Count("pk", filter=Q(run_status="failed") | Q(abstained=True)),
    )
    stuck = Study.objects.filter(
        created_at__lt=stuck_before, ai_results__isnull=True).count()

    today_cells = [
        _cell("추론 결과", ai["made"], _url(AiResult)),
        _cell("추론 실패·보류", ai["bad"],
              _url(AiResult, run_status__exact="failed"), warn=ai["bad"] > 0),
        _cell("추론 대기", stuck, _url(Study, read_status__exact="pending"),
              warn=stuck > 0),
        # 확정 시각을 따로 안 들고 있어 updated_at 으로 센다. 근사치다
        _cell("판독 완료",
              Study.objects.filter(read_status="finalized",
                                   updated_at__gte=since).count(),
              _url(Study, read_status__exact="finalized")),
    ]

    # ── 데이터 ──────────────────────────────────────────────────
    #
    # 검사 · 검체는 위 GROUP BY 를 더해 쓴다 — 같은 표를 또 세지 않는다.
    data = [
        _cell("환자", Patient.objects.count(), _url(Patient)),
        _cell("검사", sum(order.values()), _url(ExamOrder)),
        _cell("검체", sum(acc_st.values()), _url(Specimen)),
        _cell("리포트", Report.objects.count(), _url(Report)),
    ]

    return {
        "accounts": accounts,
        "roles": roles,
        "working": working,
        "today": today_cells,
        "data": data,
        "today_label": today.strftime("%Y-%m-%d"),
        "chart": _chart(),
    }


# ── 화면 넷 ──────────────────────────────────────────────────────────
#
# 전부 site.page() 를 거친다 — each_context 를 넣어야 머리띠와 사이드바가
# 붙는다. 빠뜨리면 맨 화면이 나온다.
#
# ⚠ 지금은 대시보드만 채워져 있다. 나머지 셋은 자리만 잡아 두었다.


def dashboard(site, request):
    """지금 뭐가 밀려 있나. 카드를 누르면 그 일을 하는 화면으로 간다."""
    return site.page(request, "admin/empatho/dashboard.html", "dashboard",
                     "대시보드", {"dash": dash_numbers(request)})


def status(site, request):
    """DB · Redis · Celery · Garage · Orthanc 를 찔러 본다."""
    return site.page(request, "admin/empatho/soon.html", "status",
                     "서버 상태", {"what": "각 서비스를 찔러 보고 응답시간을 냅니다."})


def accounts(site, request):
    """승인 대기 목록과 승인 · 거절."""
    return site.page(request, "admin/empatho/soon.html", "accounts",
                     "계정 승인", {"what": "승인 대기 계정을 여기서 처리합니다."})


def db_index(site, request):
    """표 목록 — 이름 · 한글명 · 행 수 · 컬럼 수."""
    return site.page(request, "admin/empatho/soon.html", "db",
                     "DB 조회", {"what": "표 구조와 값 분포를 봅니다."})


# ── 최근 24시간 막대 (SVG) ────────────────────────────────────────────
#
# 빈 시간대가 보이는 것이 목적이라 **0 건인 시간도 칸을 그린다.**
# 라이브러리를 안 쓰는 이유 — CDN 이 막힌 망이 있고, collectstatic·CSP 에
# 짐만 는다. 막대 24개는 SVG 로 충분하다.

CHART_W, CHART_H = 960, 180
PAD_L, PAD_B, PAD_T = 34, 22, 10


def _hourly(since):
    """시간별 완료·실패 수. **DB 에서 한 번에 묶는다** — 24번 세지 않는다.

    TruncHour 는 settings.TIME_ZONE(KST)로 자른다. 사람이 보는 시각과 맞는다.
    """
    rows = (AiResult.objects
            .filter(created_at__gte=since)
            .annotate(h=TruncHour("created_at"))
            .values("h")
            .annotate(done=Count("pk", filter=Q(run_status="done")),
                      bad=Count("pk", filter=Q(run_status="failed")
                                | Q(abstained=True)))
            .order_by("h"))
    return {r["h"]: (r["done"], r["bad"]) for r in rows}


def _chart():
    """24칸 막대. 완료는 기본색, 실패는 경고색으로 쌓는다."""
    now = timezone.localtime().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=23)
    by_hour = _hourly(start)

    slots = []
    for i in range(24):
        t = start + timedelta(hours=i)
        done, bad = by_hour.get(t, (0, 0))
        slots.append((t, done, bad))

    top = max((d + b) for _, d, b in slots) or 1
    gap = 4
    band = (CHART_W - PAD_L) / 24
    bw = band - gap
    plot = CHART_H - PAD_B - PAD_T

    bars = []
    for i, (t, done, bad) in enumerate(slots):
        x = PAD_L + i * band + gap / 2
        h_done = done / top * plot
        h_bad = bad / top * plot
        label = "%d시 · 완료 %d · 실패 %d" % (t.hour, done, bad)

        # 0 건이어도 바닥에 자국을 남긴다 — 칸이 있다는 것이 보여야 한다
        bars.append(format_html(
            '<g><title>{}</title>'
            '<rect x="{}" y="{}" width="{}" height="{}" class="c-zero"/>'
            '<rect x="{}" y="{}" width="{}" height="{}" class="c-done"/>'
            '<rect x="{}" y="{}" width="{}" height="{}" class="c-bad"/>'
            '</g>',
            label,
            round(x, 1), CHART_H - PAD_B - 1, round(bw, 1), 1,
            round(x, 1), round(CHART_H - PAD_B - h_done, 1), round(bw, 1),
            round(h_done, 1),
            round(x, 1), round(CHART_H - PAD_B - h_done - h_bad, 1),
            round(bw, 1), round(h_bad, 1),
        ))

    # y 눈금 — 최대값에 맞춰 둘만
    ticks = []
    for v in (top, top // 2 if top > 1 else 0):
        y = CHART_H - PAD_B - (v / top * plot)
        ticks.append(format_html(
            '<line x1="{}" y1="{}" x2="{}" y2="{}" class="c-grid"/>'
            '<text x="{}" y="{}" class="c-ax" text-anchor="end">{}</text>',
            PAD_L, round(y, 1), CHART_W, round(y, 1),
            PAD_L - 6, round(y + 4, 1), v))

    # x 눈금 — 3시간마다
    marks = format_html_join(
        "", '<text x="{}" y="{}" class="c-ax" text-anchor="middle">{}</text>',
        ((round(PAD_L + i * band + band / 2, 1), CHART_H - 6,
          "%d시" % slots[i][0].hour)
         for i in range(0, 24, 3)))

    return format_html(
        '<svg class="e-chart" viewBox="0 0 {} {}" role="img" '
        'aria-label="최근 24시간 추론 완료와 실패">{}{}{}</svg>',
        CHART_W, CHART_H,
        mark_safe("".join(ticks)), mark_safe("".join(bars)), marks)
