"""admin 안의 우리 화면들 — 대시보드 · 서버 상태 · 계정 승인 · DB 조회.

⚠ 숫자만 낸다. 환자 이름도 소견도 안 나온다 — 관리자는 시스템 관리자다.

표 하나당 GROUP BY 한 번으로 상태별 개수를 통째로 받는다. 칸마다 count()
를 부르면 첫 화면 한 번에 스무 번 넘게 DB 를 친다.
"""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta
from functools import partial
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from ..models import (
    Account, AiResult, Assessment, DiscordanceFlag, ExamOrder, Followup, Image,
    Lesion, Notification, Patient, Specimen, Study,
)

#: 시안의 칩 차례 그대로다. 개수 순으로 정렬하지 않는다 — 순서가 매번 바뀌면
#: 「우리 과가 몇 명인지」를 보려고 눈이 자리를 외울 수가 없다.
ROLE_ORDER = ("admin", "reception", "nursing", "radiology", "surgery",
              "pathology", "patient")
ROLE_NAMES = {
    "reception": "원무", "nursing": "간호", "radiology": "영상의학",
    "pathology": "병리", "surgery": "유방외과", "admin": "관리자",
    "patient": "환자",
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
    """「진행 중」 칸 하나. warn 은 오래 두면 안 되는 것이라 눈에 걸리게 한다."""
    return {"label": label, "count": count, "url": url, "warn": warn}


#: 진료 흐름 막대. (라벨, 모델, 색 열쇠) — 차례도 색도 시안 그대로다.
#: 개수 순으로 정렬하지 않는다: 진료가 흐르는 차례라 순서 자체가 뜻이다.
FLOW = (
    ("검사 오더", ExamOrder, "cyan"),
    ("알림", Notification, "indigo"),
    ("AI 결과", AiResult, "mint"),
    ("병변", Lesion, "mint"),
    ("영상 파일", Image, "amber"),
    ("환자", Patient, "pink"),
    ("추적 관찰", Followup, "none"),
)

#: 검사 오더 잔무늬에 쓸 날 수.
SPARK_DAYS = 5

#: 도넛 둘레. 반지름 60 의 2πr 이고, 시안의 stroke-dasharray 값과 같다.
RING = 377

#: 요일. Django 템플릿으로는 한글 요일이 안 나온다 — LANGUAGE_CODE 를 건드리지
#: 않고 여기서 만든다.
WEEKDAYS = "월화수목금토일"


def _pending_staff():
    """승인 대기 직원. 환자는 승인 대상이 아니라 뺀다.

    ⚠ 사이드바 배지와 **같은 함수를 쓴다.** 한 화면에 같은 것을 세는 수가
      둘이면 어느 쪽이 맞는지 아무도 모른다 — 예전에 대시보드는 환자를
      포함해 세고 배지는 빼고 세서 둘이 달랐다.
    """
    from ..adminsite import _pending
    return _pending()


def _order_spark():
    """최근 5일 일별 검사 오더 수.

    0 인 날도 칸을 남긴다 — 빈 날이 보이는 것이 이 잔무늬의 목적이다.
    """
    first = timezone.localdate() - timedelta(days=SPARK_DAYS - 1)
    rows = (ExamOrder.objects
            .filter(created_at__date__gte=first)
            .annotate(d=TruncDate("created_at"))
            .values("d").annotate(n=Count("pk")))
    by_day = {r["d"]: r["n"] for r in rows}
    counts = [by_day.get(first + timedelta(days=i), 0)
              for i in range(SPARK_DAYS)]
    top = max(counts) or 1
    # 0 건인 날도 자국은 남긴다(최소 12%) — 칸이 아예 없으면 날이 빠진 줄 안다
    return [{"n": c, "pct": max(round(c / top * 100), 12)} for c in counts]


def _flow_rows():
    """단계별 건수 막대. 제일 큰 것을 100% 로 본다."""
    rows = [{"label": label, "n": model.objects.count(), "tone": tone,
             "url": _url(model)}
            for label, model, tone in FLOW]
    top = max((r["n"] for r in rows), default=0) or 1
    for r in rows:
        r["pct"] = round(r["n"] / top * 100)
    return rows


def dash_numbers(request):
    """첫 화면에 넘길 값 — 시안(Main.dc.html) 이 그리는 것만."""
    today = timezone.localtime()

    acc_total = Account.objects.count()
    role = _tally(Account, "role")
    flag = _tally(DiscordanceFlag, "flag_status")
    run = _tally(AiResult, "run_status")
    read = _tally(Study, "read_status")
    acc_st = _tally(Specimen, "accession_status")

    # 불일치는 pass 를 뺀 나머지가 전부 미해소다 — sev1 · sev2 · review ·
    # unbindable 이 각각 다른 이유로 남아 있는 것이라 한 덩어리로 센다.
    open_flags = sum(n for s, n in flag.items() if s != "pass")

    # ── 진행 중 ─────────────────────────────────────────────────
    # 시안에는 없지만 되살렸다(2026-09-25). 여기가 **막힌 데를 보는 유일한
    # 자리**라, 빼 두면 워커가 죽거나 큐가 밀린 것을 아무도 모른다.
    #
    # 승인 대기는 위 KPI 카드가 이미 말하므로 여기서 뺀다 — 같은 수를 한
    # 화면에 두 번 두면 어느 쪽이 맞는지 눈이 먼저 묻는다.
    working = [
        _cell("AI 분석 대기", run.get("queued", 0),
              _url(AiResult, run_status__exact="queued")),
        _cell("AI 실패", run.get("failed", 0),
              _url(AiResult, run_status__exact="failed"),
              warn=run.get("failed", 0) > 0),
        _cell("판독 대기", read.get("pending", 0),
              _url(Study, read_status__exact="pending")),
        _cell("검체 접수 대기", acc_st.get("unbound", 0) + acc_st.get("bound", 0),
              _url(Specimen, accession_status__exact="bound")),
        _cell("미해소 불일치", open_flags,
              _url(DiscordanceFlag), warn=open_flags > 0),
    ]

    # 서비스 고리는 상태 화면과 **같은 값**을 쓴다. 따로 찌르면 첫 화면에
    # 최대 ADMIN_PROBE_DEADLINE_SEC 이 붙는다(probe_all_cached 의 머리말).
    probes = probe_all_cached()
    service = probe_summary(probes)
    service["ring"] = (round(RING * service["ok"] / service["total"])
                       if service["total"] else 0)
    service["names"] = [{"name": p["name"], "ok": p["ok"], "slow": p["slow"]}
                        for p in probes]

    return {
        "date_label": "%s (%s)" % (today.strftime("%Y-%m-%d"),
                                   WEEKDAYS[today.weekday()]),
        # ── 핵심 지표 넉 장 ─────────────────────────────────────
        "pending_staff": _pending_staff(),
        "orders": ExamOrder.objects.count(),
        "order_spark": _order_spark(),
        "ai_results": AiResult.objects.count(),
        "lesions": Lesion.objects.count(),
        "assessments": Assessment.objects.count(),
        "open_flags": open_flags,
        # ── 아래 세 덩어리 ──────────────────────────────────────
        "working": working,
        "flow": _flow_rows(),
        "service": service,
        "accounts_total": acc_total,
        "roles": [{"label": ROLE_NAMES.get(r, r), "n": role.get(r, 0),
                   "url": _url(Account, approval="all", kind="all",
                               role__exact=r)}
                  for r in ROLE_ORDER],
        # 누르면 가는 곳
        "url_pending": _url(Account, approval="pending", kind="staff"),
        "url_orders": _url(ExamOrder),
        "url_ai": _url(AiResult),
        "url_flags": _url(DiscordanceFlag),
        "url_accounts": _url(Account, approval="all", kind="all"),
    }


# ── 우리 화면 ────────────────────────────────────────────────────────
#
# 전부 site.page() 를 거친다 — each_context 를 넣어야 머리띠와 사이드바가
# 붙는다. 빠뜨리면 맨 화면이 나온다.


def dashboard(site, request):
    """지금 뭐가 밀려 있나. 카드를 누르면 그 일을 하는 화면으로 간다."""
    return site.page(request, "admin/empatho/dashboard.html", "대시보드", {"dash": dash_numbers(request)})


def status(site, request):
    """지금 무엇이 살아 있나. 찌르는 쪽은 브라우저가 아니라 web 컨테이너다.

    ?refresh=1 은 캐시를 버리고 다시 찌른다 — 화면의 [지금 다시 확인] 이다.
    고치고 나서 30초를 기다리게 하면 고쳐졌는지를 못 본다.
    """
    probes = probe_all_cached(force=bool(request.GET.get("refresh")))
    return site.page(request, "admin/empatho/status.html", "서버 상태", {
        "probes": probes,
        "summary": probe_summary(probes),
        "checked_at": timezone.localtime().strftime("%H:%M:%S"),
        "refresh_sec": settings.ADMIN_STATUS_REFRESH_SEC,
    })


def db_index(site, request):
    """표 목록 — 한글명 · 표 이름 · 행 수 · 칸 수.

    ?q= 로 좁힌다. 서버에서 거르는 이유 — 화면에 스크립트를 들이지 않으려는
    것이다. 이 화면은 서버가 그리고 끝이라 붙일 것이 그것 하나뿐인데, 그 하나
    때문에 정적파일과 CSP 를 신경 써야 한다.
    """
    q = (request.GET.get("q") or "").strip()
    all_tables = db_tables()
    shown = [t for t in all_tables if _matches(t, q)] if q else all_tables
    return site.page(request, "admin/empatho/db_index.html", "DB 조회", {
        "tables": _with_bars(shown),
        "summary": db_summary(all_tables, len(shown)),
        "q": q,
    })


def _matches(table, q):
    """표 이름(account)으로도 한글명(계정)으로도 찾힌다."""
    low = q.lower()
    return low in table["table"].lower() or low in table["name"].lower()


def _with_bars(tables):
    """행 수 막대의 길이. 제일 큰 표를 100% 로 본다.

    ⚠ 0 행이어도 막대를 그린다(길이 0). 칸 자체가 사라지면 «빠뜨린 표»로
      보이는데, 비어 있는 것과 없는 것은 다르다.
    """
    top = max((t["rows"] for t in tables), default=0) or 1
    for t in tables:
        t["pct"] = round(t["rows"] / top * 100, 1)
    return tables


def db_summary(tables, shown):
    """머리말 넉 장.

    ⚠ 표 이름만 낸다. 「가린 표」의 값은 여기서도 안 보여준다 — 이름을 세는
      것과 안을 들여다보는 것은 다른 일이다.
    """
    biggest = max(tables, key=lambda t: t["rows"], default=None)
    return {
        "total": len(tables),
        "shown": shown,
        "biggest_name": biggest["name"] if biggest else "",
        "biggest_rows": biggest["rows"] if biggest else 0,
        "hidden": _join_names([t["name"] for t in tables if t["hidden"]]),
        "empty": _join_names([t["name"] for t in tables if not t["rows"]]),
        "empty_count": sum(1 for t in tables if not t["rows"]),
    }


#: 머리말 한 칸에 늘어놓을 이름 수. 넘치면 「…」로 줄인다 — 다 적으면 카드가
#: 목록이 되고, 그러면 아래 표와 같은 말을 두 번 하는 셈이다.
SUMMARY_NAMES = 5


def _join_names(names):
    if not names:
        return "없음"
    head = " · ".join(names[:SUMMARY_NAMES])
    return head + (" …" if len(names) > SUMMARY_NAMES else "")


def db_detail(site, request, table):
    """표 하나. 구조는 늘 보이고, 값 분포는 상태형 칸에만."""
    model = _model_by_table(table)
    if model is None:
        raise Http404("그런 표가 없습니다: %s" % table)

    hidden = _is_sensitive(model)
    return site.page(request, "admin/empatho/db_detail.html",
                     _table_title(model), {
                         "table": _table_row(model),
                         "columns": db_columns(model),
                         "spreads": [] if hidden else db_spreads(model),
                         "hidden": hidden,
                     })


# ── DB 조회 ──────────────────────────────────────────────────────────
#
# 구조는 어느 표든 보인다. 막는 것은 **값**이다 — 표를 통째로 가리면 관리자가
# 스키마도 못 봐서 일을 못 한다. 가릴 표는 settings.ADMIN_DB_SENSITIVE 다.
#
# 분포를 내는 칸은 **상태형뿐**이다(choices 가 있거나 참거짓). 자유 텍스트는
# 어느 표든 안 낸다 — 길이 분포도 안 낸다. 몇 자인지도 사람을 좁히는 단서다.

#: 한 칸에서 보여줄 값 가짓수. 넘치면 목록이 아니라 덤프가 된다
SPREAD_LIMIT = 12


def _models():
    from django.apps import apps as django_apps

    return sorted(django_apps.get_app_config("core").get_models(),
                  key=lambda m: m._meta.db_table)


def _model_by_table(table):
    for model in _models():
        if model._meta.db_table == table:
            return model
    return None


def _is_sensitive(model):
    return model._meta.db_table in settings.ADMIN_DB_SENSITIVE


def _table_title(model):
    name = model._meta.verbose_name
    return "%s (%s)" % (name, model._meta.db_table)


def _table_row(model):
    meta = model._meta
    return {
        "name": str(meta.verbose_name),
        "table": meta.db_table,
        "rows": model.objects.count(),
        "columns": len(meta.fields),
        "hidden": _is_sensitive(model),
        "url": reverse("admin:empatho_db_detail", args=[meta.db_table]),
        "admin_url": (_url(model) if admin.site.is_registered(model) else ""),
    }


def db_tables():
    return [_table_row(model) for model in _models()]


def db_columns(model):
    """칸의 생김새. 값이 아니라 구조다 — 민감한 표에서도 이건 보인다."""
    out = []
    for field in model._meta.fields:
        out.append({
            "name": field.column,
            "type": _type_of(field),
            "null": field.null,
            "default": _default_of(field),
            "kind": "상태" if _spreadable(field) else "",
            "link": (field.related_model._meta.db_table
                     if field.is_relation and field.related_model else ""),
        })
    return out


def _type_of(field):
    kind = field.get_internal_type().replace("Field", "").lower()
    if getattr(field, "max_length", None):
        return "%s(%d)" % (kind, field.max_length)
    return kind


def _default_of(field):
    from django.db.models import NOT_PROVIDED

    value = field.default
    if value is NOT_PROVIDED:
        return ""
    if callable(value):
        return value.__name__
    return str(value)


def _spreadable(field):
    """분포를 내도 되는 칸인가.

    상태형만 낸다 — 값이 미리 정해진 소수 집합이라 한 줄이 사람을 가리키지
    않는다. 자유 텍스트 · 날짜 · 숫자 · 외래키는 그렇지 않다.
    """
    if field.is_relation or field.primary_key:
        return False
    if field.get_internal_type() == "BooleanField":
        return True
    return bool(field.choices)


def db_spreads(model):
    """상태형 칸마다 값별 개수. 칸 하나에 GROUP BY 한 번."""
    out = []
    for field in model._meta.fields:
        if not _spreadable(field):
            continue
        rows = (model.objects.values(field.name)
                .annotate(n=Count("*")).order_by("-n")[:SPREAD_LIMIT])
        counted = [{"value": _label(r[field.name]), "n": r["n"]} for r in rows]
        if counted:
            out.append({"name": field.column, "rows": counted})
    return out


def _label(value):
    if value is None:
        return "(비어 있음)"
    if value is True:
        return "참"
    if value is False:
        return "거짓"
    return str(value)


# ── 서버 상태 ────────────────────────────────────────────────────────
#
# 셋을 각각 다르게 본다.
#   DB       실제로 질의를 던진다. 연결만 봐서는 인증 · 권한 문제가 안 드러난다
#   워커     브로커를 거쳐 ping 을 돌린다. 답한 워커 수가 곧 상태다
#   나머지   TCP 연결까지만. health 경로가 서비스마다 달라 경로를 넣으면
#            살아 있는데도 404 로 죽은 것처럼 보인다
#
# Redis 는 줄을 따로 안 세운다. 워커 ping 이 브로커를 거치므로 Redis 가
# 죽으면 워커가 「응답 없음」으로 뜬다 — 두 줄이 늘 같이 움직인다.
#
# ⚠ 어느 것도 화면을 멎게 하면 안 된다. 예외는 전부 「실패」 한 줄로 바꾼다.


#: 이름 밑에 붙는 한 줄. 「llm-proxy 가 죽었다」만 보면 무엇이 멈추는지
#: 모르는 사람이 있다. 이름은 ADMIN_PROBES 의 열쇠와 같아야 붙는다.
PROBE_SUBTITLES = {
    "postgres": "DB",
    "celery 워커": "작업 큐",
    "file-gateway": "Go 업로드",
    "llm-proxy": "소견문 중계",
    "notify": "실시간 알림",
    "garage (S3)": "파일 저장소",
    "orthanc (PACS)": "DICOM",
}


def _result(name, ok, detail, ms, hint=""):
    ms = None if ms is None else round(ms * 1000)
    return {"name": name, "ok": ok, "detail": detail, "ms": ms, "hint": hint,
            "subtitle": PROBE_SUBTITLES.get(name, ""),
            # 살아 있지만 느린 것. 색이 갈려야 한 화면에서 구별된다
            "slow": bool(ok and ms is not None and ms >= settings.ADMIN_SLOW_MS)}


def _timed(fn):
    """(결과, 걸린 초). 예외는 부르는 쪽이 받는다."""
    start = time.monotonic()
    value = fn()
    return value, time.monotonic() - start


def probe_db():
    from django.db import connection

    try:
        def run():
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        _, took = _timed(run)
    except Exception as exc:
        return _result("postgres", False, _why(exc), None,
                       "web 이 DB 를 못 본다 — 다른 화면도 전부 안 뜬다")
    finally:
        # 딴 실에서 돌면 그 실의 연결이 남는다 — 화면을 열 때마다 쌓인다.
        # 본 실의 것은 안 닫는다. 요청이 쓰는 연결이라 닫으면 그 요청이 깨진다.
        if threading.current_thread() is not threading.main_thread():
            connection.close()
    return _result("postgres", True, "질의 응답", took)


def probe_worker():
    """Celery 워커. 답한 수를 낸다.

    브로커가 죽어 있으면 여기서 예외가 난다 — 그래서 Redis 줄이 따로 없다.
    """
    from cdss_backend.celery import app

    timeout = settings.ADMIN_PROBE_TIMEOUT_SEC
    try:
        replies, took = _timed(lambda: app.control.ping(timeout=timeout) or [])
    except Exception as exc:
        return _result("celery 워커", False, _why(exc), None,
                       "브로커(redis)가 죽었을 수도 있다 — 소견문 생성이 멈춘다")
    if not replies:
        return _result("celery 워커", False, "응답한 워커 없음", took,
                       "worker 컨테이너나 브로커를 본다")
    return _result("celery 워커", True, "%d대 응답" % len(replies), took)


def probe_tcp(name, base):
    """듣고 있는가까지만. 주소는 settings.ADMIN_PROBES 에서 온다."""
    parsed = urlparse(base)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return _result(name, False, "주소를 읽을 수 없다: %s" % base, None)

    timeout = settings.ADMIN_PROBE_TIMEOUT_SEC
    try:
        def connect():
            with socket.create_connection((host, port), timeout=timeout):
                return True
        _, took = _timed(connect)
    except Exception as exc:
        return _result(name, False, _why(exc), None, "%s:%s" % (host, port))
    return _result(name, True, "%s:%s" % (host, port), took)


def _why(exc):
    """사람이 읽을 한 줄. 클래스 이름만으로는 무엇이 문제인지 안 보인다."""
    text = str(exc).strip()
    return text[:120] if text else type(exc).__name__


def probe_all():
    """전부 한꺼번에 돌리고 마감시각에 끊는다.

    ⚠ **하나씩 부르면 안 된다.** 이름 조회 실패가 2~3초, celery 가 7초라
      일곱 줄이면 20초가 넘는다 — 서버가 아플 때 열 화면인데 그때 제일 느려진다.

    끊고 나서 기다리지 않는다(shutdown wait=False). 끝내지 못한 실은 알아서
      끝난다 — 붙잡고 있으면 병렬로 돌린 뜻이 없어진다.
    """
    jobs = [("postgres", probe_db), ("celery 워커", probe_worker)]
    jobs += [(name, partial(probe_tcp, name, base))
             for name, base in settings.ADMIN_PROBES.items()]

    deadline = settings.ADMIN_PROBE_DEADLINE_SEC
    pool = ThreadPoolExecutor(max_workers=len(jobs),
                              thread_name_prefix="admin-probe")
    futures = {pool.submit(fn): name for name, fn in jobs}
    wait(futures, timeout=deadline)
    pool.shutdown(wait=False)

    out = []
    for future, name in futures.items():
        if not future.done():
            out.append(_result(name, False, "%g초 안에 답이 없다" % deadline,
                               None, "죽었거나 아주 느리다"))
            continue
        try:
            out.append(future.result())
        except Exception as exc:          # 찌르는 함수가 터져도 화면은 뜬다
            out.append(_result(name, False, _why(exc), None))
    # 부른 순서를 유지한다. ThreadPoolExecutor 의 futures 는 끝난 순서라,
    # 그대로 두면 **빠른 것이 먼저 오도록 화면이 매번 뒤바뀐다** — 같은 칸을
    # 보려고 눈이 자리를 외우는 화면인데 그게 안 된다.
    order = {name: i for i, (name, _) in enumerate(jobs)}
    out.sort(key=lambda r: order.get(r["name"], 99))
    return out


# ── 찔러 본 결과를 잠깐 들고 있는다 ──────────────────────────────────
#
# 대시보드와 상태 화면이 같은 값을 쓴다. 둘이 따로 찌르면 대시보드를 열 때마다
# 최대 ADMIN_PROBE_DEADLINE_SEC 이 붙는데, 대시보드는 admin 의 첫 화면이라
# 그게 곧 «admin 이 느리다» 가 된다.
#
# ⚠ 프로세스 메모리다. gunicorn 워커가 넷이면 워커마다 따로 센다 — 그래도
#   화면마다 찌르는 것보다 훨씬 적다. Redis 로 옮길 값은 아니다.
_PROBE_CACHE = {"at": 0.0, "value": None}
_PROBE_LOCK = threading.Lock()


def probe_all_cached(force=False):
    """캐시된 결과. force 면 버리고 다시 찌른다.

    ⚠ 찌르는 동안 잠금을 쥐지 않는다. 쥐면 두 사람이 같이 열었을 때 뒤엣사람이
      앞사람의 4초를 그대로 기다린다 — 겹쳐서 두 번 찌르는 편이 낫다.
    """
    now = time.monotonic()
    if not force:
        with _PROBE_LOCK:
            value, at = _PROBE_CACHE["value"], _PROBE_CACHE["at"]
        if value is not None and now - at < settings.ADMIN_PROBE_CACHE_SEC:
            return value

    value = probe_all()
    with _PROBE_LOCK:
        _PROBE_CACHE["value"] = value
        _PROBE_CACHE["at"] = time.monotonic()
    return value


def probe_cache_clear():
    """들고 있던 것을 버린다. 시험이 서로 앞 시험의 값을 보지 않게 한다."""
    with _PROBE_LOCK:
        _PROBE_CACHE["value"] = None
        _PROBE_CACHE["at"] = 0.0


def probe_summary(probes):
    """머리말 한 줄에 쓸 값.

    「가장 느린 것」을 따로 빼고 나머지 평균을 낸다. 같이 평균 내면 celery
    2초가 나머지 열 배를 끌어올려 전부 느려 보인다 — 실제로 느린 것은 하나다.
    """
    total = len(probes)
    ok = sum(1 for p in probes if p["ok"])
    timed = sorted((p for p in probes if p["ms"] is not None),
                   key=lambda p: p["ms"])
    slowest = timed[-1] if timed else None
    rest = timed[:-1]
    return {
        "ok": ok,
        "total": total,
        "all_ok": ok == total and total > 0,
        "down": total - ok,
        "slowest_ms": slowest["ms"] if slowest else None,
        "slowest_name": slowest["name"] if slowest else "",
        "slowest_slow": bool(slowest and slowest["slow"]),
        "rest_avg_ms": (round(sum(p["ms"] for p in rest) / len(rest))
                        if rest else None),
    }
