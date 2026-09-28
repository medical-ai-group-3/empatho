import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Page, Card, Btn } from "../../lib/Page";
import { Body, Empty } from "../../lib/Body";
import { Chip, useCan } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";
import * as H from "../../dept/home";

/* 예약 관리 — 왼쪽 할 일 · 가운데 예약 판 · 오른쪽 지금 쓰는 것 (6.1)
 * ════════════════════════════════════════════════════════════════
 *
 *   ┌ 할 일(흐름 순) ─┬ 예약 판(일·주·월) ───────────┬ 새 예약 / 예약 변경 ┐
 *   │ 앱 신청 n     › │ [전체][서나영][최민수]…       │ / 예약 보기(내원 끝) │
 *   │ 다음 예약 필요 › │  08:00 …                     ├─────────────────────┤
 *   │ 추적 예약 필요 › │                              │ 이 환자 예약(안 옴 n)│
 *   │ 안 오심(7일)  › │                              │                     │
 *   │ 달력             │                              │                     │
 *   └─────────────────┴──────────────────────────────┴─────────────────────┘
 *
 * 09-28 왼쪽을 **할 일 줄**로 바꿨다 — 환자가 흐르는 순서대로 「앱 신청 확정
 * → 진료 끝난 사람 다음 예약 → 추적 회차 예약 → 안 오신 분 다시 잡기」.
 * 줄을 누르면 사람 목록이 펴지고, 사람을 누르면 오른쪽에 그 사람이 들어간다.
 * 예전 머리의 [예약 판][예약 신청] 알약은 뺐다 — 신청은 할 일 첫 줄이다.
 *
 * 주소 — ?tab=requests|next|followup|noshow 는 그 줄을 펴서 열고, ?patient=
 * (· ?followup= · ?date=)는 그 사람을 새 예약에 싣고 연다(환자 목록 · 추적 관리
 * · 홈에서 넘어오는 길).
 *
 * ── 한 사람 · 한 날 · 예약 하나 (09-28) ──────────────────────────
 * 고칠 수 있는 예약(안 옴 · 신청/확정)을 고르면 오른쪽은 **고치는 자리**다
 * — [변경 저장](PATCH /exam-orders/{id}/reschedule) · [예약 취소]. 판의 빈
 * 칸을 누르면 그 예약이 그 칸으로 옮겨 갈 자리가 된다. 새로 만드는 [예약]
 * 은 그날 이 환자에게 취소 안 된 오더가 **하나라도**(내원한 것 포함) 있으면
 * 잠기고 [그 예약 고치기]로 넘어간다. 서버도 같은 기준으로 409
 * DUPLICATE_RESERVATION 을 준다(core/views/reception.py _refuse_same_day).
 * ⚠ 내원했거나 진행 중인 예약을 누르면 **보기 전용**이다. 예전엔 그 예약의
 *   날짜 · 시각을 채운 새 예약이 떠서, 방금 누른 그 예약과 겹친다는 경고가
 *   떴다. [다음 예약 잡기]를 눌러야 날짜가 빈 새 예약이 된다.
 *
 * ⚠ **메모 칸을 내지 않는다.** `schedule` 이 받지 않는 글이라 버려진다(1.3).
 *
 * ── 날짜를 문자열에서 잘라 쓰는 이유 ──────────────────────────
 * `scheduled_at` 은 `"2026-09-13T09:30:00+09:00"` 로 온다. `new Date()` 로
 * 돌리면 **보는 사람의 시간대로 다시 옮겨져** 병원 밖에서 열면 13일 예약이
 * 12일 칸에 들어간다. 병원이 말하는 날짜는 +09:00 기준 하나뿐이다.
 */
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const dayOf = (s) => (s ? String(s).slice(0, 10) : "");
const timeOf = (s) => (s ? String(s).slice(11, 16) : "");
const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

/* 아직 확정 안 된 예약(requested) — 확정(scheduled)과 판에서 모양을 달리한다 */
const isPending = (r) => r.order_status === "requested" && !r.visited_at;

/* 고칠 수 있는 예약 — 아직 안 왔고(visited_at 빈) 신청 · 확정인 것. 서버
   ExamOrderRescheduleView.EDITABLE 과 같은 기준이다. 내원했거나 진행 중인
   오더는 서버가 409 RESERVATION_LOCKED 로 막는다 */
const isEditable = (r) => Boolean(r) && r.exam_order_id != null && !r.visited_at
  && ["requested", "scheduled"].includes(r.order_status);

/* 아직 올 수 있는 예약 — 취소 안 됐고 안 왔다 */
const isLive = (r) => r.order_status !== "cancelled" && !r.visited_at;

/* 오더에서 사람만 — 새 예약에 싣는다 */
const personOf = (r) => ({ patient_id: r.patient ?? r.patient_id,
                           name: r.patient_name ?? r.name ?? null,
                           patient_number: r.patient_number ?? null });

const STATUS = {
  requested: "미확정", scheduled: "예약 확정", ordered: "검사 확정",
  accepted: "접수됨", in_progress: "검사 중", completed: "완료", cancelled: "취소",
};

/* 08:00–18:00 을 30분으로 끊는다(6.1) */
const SLOTS = [];
for (let h = 8; h < 18; h += 1) {
  SLOTS.push(`${pad(h)}:00`);
  SLOTS.push(`${pad(h)}:30`);
}

/* 빠른 날짜 — 유방 쪽은 BI-RADS 3 추적(6·12·24개월)이 제일 많이 눌린다 */
const QUICK = [
  ["1주", 7], ["2주", 14], ["4주", 28],
  ["3개월", 91], ["6개월", 182], ["12개월", 365], ["24개월", 730],
];

function addDays(from, n) {
  const d = new Date(`${from}T00:00:00`);
  d.setDate(d.getDate() + n);
  return ymd(d);
}

function startOfWeek(iso) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() - d.getDay());
  return ymd(d);
}

/* 할 일 줄 — 환자가 흐르는 순서 */
const QUEUES = [
  { key: "requests", label: "앱 신청", empty: "확인할 신청이 없습니다" },
  { key: "next", label: "다음 예약 필요", empty: "다음 예약이 필요한 환자가 없습니다" },
  { key: "followup", label: "추적 예약 필요", empty: "예약을 기다리는 추적 회차가 없습니다" },
  { key: "noshow", label: "미내원(7일)", empty: "지난 7일간 미내원 환자가 없습니다" },
];

export default function Reservations({ cfg }) {
  const api = cfg.api;
  const today = ymd(new Date());

  /* 홈 달력 · 환자 목록 · 추적 관리에서 ?date= ?patient= ?followup= ?tab= 을
     달고 온다. **첫 값으로만** 쓴다 — 사람이 고친 뒤에 주소가 되돌리면 안 된다 */
  const [params] = useSearchParams();
  const asked = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") ?? "")
    ? params.get("date") : null;
  const askedPid = params.get("patient");
  const askedFup = params.get("followup");

  const [span, setSpan] = useState(asked ? "day" : "week"); /* day · week · month */
  const [anchor, setAnchor] = useState(asked ?? today);      /* 보고 있는 날 */
  const [pick, setPick] = useState(null);        /* 오른쪽에 띄운 예약·환자 */
  const [queue, setQueue] = useState(() => (QUEUES.some((q) => q.key === params.get("tab"))
    ? params.get("tab") : null));                /* 편 할 일 줄 */
  const [doc, setDoc] = useState("all");         /* 판을 거르는 주치의 */
  /* 화면을 보는 중에 ?tab= · ?date= 만 바뀌어 오면 그것도 한 번 따라간다 */
  const tabKey = `${params.get("tab") ?? ""}|${asked ?? ""}`;
  const [seenTab, setSeenTab] = useState(tabKey);
  if (tabKey !== seenTab) {
    setSeenTab(tabKey);
    if (QUEUES.some((q) => q.key === params.get("tab"))) setQueue(params.get("tab"));
    if (asked) { setAnchor(asked); setSpan("day"); }
  }

  const range = useMemo(() => rangeOf(span, anchor), [span, anchor]);
  const [ver, setVer] = useState(0);   /* 예약을 잡으면 할 일 · 달력 점도 다시 */

  const board = useApi(
    () => api.schedule(range.from, range.to), [range.from, range.to]);

  /* ?patient= 로 왔으면 그 사람을 새 예약에 싣는다. 이름을 모르면 번호로
     부르게 되니 상세를 한 번 받아 온다 — 못 받아도 번호로 연다 */
  const asker = useApi(
    () => (askedPid ? H.soft(api.detail(askedPid)).then((d) => ({ pid: askedPid, d }))
      : Promise.resolve(null)), [askedPid]);
  /* ⚠ 한 번 받은 주소는 다시 안 싣는다. 이 화면을 보는 중에 다른 사람 주소로
     오면(화면이 다시 서지 않는다) 그 주소로 한 번 더 — 받아 온 상세가
     **그 사람 것일 때만** 싣는다(앞사람 상세로 이름을 달면 안 된다) */
  const askKey = `${askedPid ?? ""}|${askedFup ?? ""}|${asked ?? ""}`;
  const [took, setTook] = useState(null);
  if (askedPid && took !== askKey && asker.data?.pid === askedPid) {
    setTook(askKey);
    const d = asker.data.d && !Array.isArray(asker.data.d) ? asker.data.d : null;
    setPick({
      patient: { patient_id: Number(askedPid) || askedPid,
                 name: d?.pii?.name ?? d?.name ?? null,
                 patient_number: d?.patient_number ?? null },
      at: asked ? `${asked}T09:30:00` : null,
      followup: askedFup ? Number(askedFup) || askedFup : null,
      fresh: true,
    });
  }

  /* 취소한 예약은 판에서 뺀다 — 서버는 지우지 않고 cancelled 로 남긴다 */
  const rows = (board.data ?? []).filter((r) => r.order_status !== "cancelled");
  /* 판의 주치의 거르개 — 겹침 검사(New 의 clash)는 거르기 **전** 줄로 한다 */
  const docs = useMemo(() => [...new Set(rows.map((r) => r.primary_staff_name).filter(Boolean))], [rows]);
  const shownRows = doc === "all" ? rows
    : doc === "none" ? rows.filter((r) => !r.primary_staff_name)
      : rows.filter((r) => r.primary_staff_name === doc);

  const work = useWork(api, today, ver);

  /* 할 일 줄에서 사람을 눌렀을 때 */
  function take(key, r) {
    if (key === "requests" || key === "noshow") {
      /* 신청 · 안 온 예약은 **그 오더를** 연다 — 새로 만들지 않고 확정하거나
         옮긴다. 신청은 희망일로 판을 옮기고, 안 오심은 오늘부터 빈 칸을 찾게 */
      setAnchor(key === "requests" ? (dayOf(r.scheduled_at) || today) : today);
      setPick({ at: r.scheduled_at, order: r });
      return;
    }
    if (key === "next") {
      setPick({ patient: personOf(r), at: null, fresh: true });
      return;
    }
    /* 추적 — 예정일이 앞이면 그날로, 지났으면 날짜를 비워 고르게 */
    const due = dayOf(r.due_at);
    const ahead = due && due >= today;
    if (ahead) setAnchor(due);
    setPick({ patient: personOf(r), followup: r.followup_id,
              at: ahead ? `${due}T09:30:00` : null, fresh: true });
  }

  return (
    <Page crumb={[cfg.name, "예약"]} title="예약 관리" className="resv-page"
          right={<Btn to={go.nursing.patients()}>환자 목록</Btn>}>
      <div className="resv">
        <Side anchor={anchor} onPick={(d) => { setAnchor(d); setSpan("day"); }}
              cfg={cfg} ver={ver} work={work} queue={queue} setQueue={setQueue}
              onTake={take} />

        <div className="resv-mid">
          <Board span={span} setSpan={setSpan} anchor={anchor} setAnchor={setAnchor}
                 range={range} state={board} rows={shownRows} all={rows.length}
                 docs={docs} doc={doc} setDoc={setDoc}
                 /* 고칠 수 있는 예약을 고른 채 빈 칸을 누르면 **그 예약을
                    그 칸으로 옮기는 자리**다(09-28). 내원 끝난 예약을 보던
                    중이면 그 사람의 **다음 예약** 자리가 된다 */
                 onSlot={(at) => setPick((p) => (isEditable(p?.order)
                   ? { at, order: p.order }
                   : p?.order ? { at, patient: personOf(p.order), fresh: true }
                     : p?.patient ? { ...p, at }
                       : { at }))}
                 onOrder={(r) => setPick({ at: r.scheduled_at, order: r })} />
        </div>

        <Aside cfg={cfg} pick={pick} rows={rows} ver={ver}
               onEdit={(order, at) => setPick({ at, order })}
               onNext={(order) => setPick({ patient: personOf(order), at: null, fresh: true })}
               onDone={(changed) => {
          board.reload(true);
          setVer((n) => n + 1);
          /* 신청을 확정하면 서버가 바뀐 오더를 돌려준다 — 고른 것을 그것으로
             갈아 끼워야 오른쪽이 아직 「신청」인 줄 안다 */
          if (changed?.exam_order_id != null) {
            setPick((p) => ({ at: changed.scheduled_at ?? p?.at,
                              order: { ...(p?.order ?? {}), ...changed } }));
          }
        }} onDate={(d) => setAnchor(d)} onClear={() => setPick(null)} />
      </div>
    </Page>
  );
}

function rangeOf(span, anchor) {
  if (span === "day") return { from: anchor, to: anchor, days: [anchor] };
  if (span === "month") {
    const d = new Date(`${anchor}T00:00:00`);
    const first = ymd(new Date(d.getFullYear(), d.getMonth(), 1));
    const last = ymd(new Date(d.getFullYear(), d.getMonth() + 1, 0));
    const days = [];
    for (let i = 0; ; i += 1) {
      const at = addDays(first, i);
      days.push(at);
      if (at === last) break;
    }
    return { from: first, to: last, days };
  }
  const from = startOfWeek(anchor);
  const days = Array.from({ length: 7 }, (_, i) => addDays(from, i));
  return { from, to: days[6], days };
}

/* ── 할 일 넷 ──────────────────────────────────────────────────
 * 서버에 「다음 예약이 없는 사람」 같은 거르개가 없어서 **화면이 센다.**
 * 부르는 것은 넷 — 앱 신청 · 지난 14일 예약 · 앞으로 1년 예약 · 오늘 내원 ·
 * 추적 회차. 못 부른 것은 그 줄만 0 이 된다(H.soft).
 *
 *   다음 예약 필요  최근 14일 · 오늘 진료가 끝났고(completed) 앞으로 잡힌
 *                   예약이 없는 사람
 *   추적 예약 필요  열린 추적 회차 중 예정일이 30일 안(지난 것 포함)인데
 *                   그 회차에 이어진 예약(order.followup)이 없는 것
 *   안 오심(7일)    지난 7일 예약 시각이 지났는데 내원이 없고, 그 뒤로
 *                   다시 잡은 예약도 없는 것
 *
 * ⚠ 「진료 끝」을 order_status completed 로 본다 — 외래만 보고 가는 날은
 *   검사 오더가 안 끝난 채 남을 수 있다. 서버가 「진료 완료」를 따로 주면 바꾼다.
 * ⚠ 앞으로 1년 치는 200건(PAGE_ALL)에서 잘린다 — 넘으면 「예약 없음」으로
 *   잘못 셀 수 있다. 그래도 빠뜨리는 쪽이 아니라 더 보이는 쪽으로 틀린다.
 */
function useWork(api, today, ver) {
  const d = useApi(() => Promise.all([
    H.soft(api.requests()),
    H.soft(api.schedule(addDays(today, -14), today)),
    H.soft(api.schedule(today, addDays(today, 365))),
    H.soft(api.todayStatus()),
    H.soft(api.followups()),
  ]), [today, ver]);

  return useMemo(() => {
    const [asks = [], recent = [], ahead = [], came = [], fups = []] = d.data ?? [];
    const pidOf = (r) => String(r.patient ?? r.patient_id);
    /* 앞으로 올 예약이 있는 사람 · 그 예약이 이어진 추적 회차 */
    const future = ahead.filter((r) => isLive(r) && dayOf(r.scheduled_at) >= today
      && !H.isPast(r.scheduled_at));
    const booked = new Set(future.map(pidOf));
    const linked = new Set(future.map((r) => r.followup).filter((x) => x != null).map(String));

    /* 다음 예약 필요 — 사람마다 가장 최근 것 하나 */
    const done = new Map();
    for (const r of [...H.rows(recent), ...H.rows(came)]) {
      const fin = r.order_status === "completed" || r.stage === "completed"
        || r.stage_code === "completed";
      if (!fin || booked.has(pidOf(r))) continue;
      const at = r.visited_at ?? r.scheduled_at ?? "";
      const had = done.get(pidOf(r));
      if (!had || String(at) > String(had.visited_at ?? had.scheduled_at ?? "")) done.set(pidOf(r), r);
    }

    const soon = addDays(today, 30);
    const fup = H.rows(fups).filter((f) => H.openFollowup(f) && f.due_at
      && dayOf(f.due_at) <= soon && !linked.has(String(f.followup_id)))
      .sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)));

    const week = addDays(today, -7);
    const cameToday = new Set(H.rows(came).map(pidOf));
    const noshow = H.rows(recent).filter((r) => isLive(r)
      && ["requested", "scheduled"].includes(r.order_status)
      && dayOf(r.scheduled_at) >= week && H.isPast(r.scheduled_at)
      && !booked.has(pidOf(r)) && !cameToday.has(pidOf(r)))
      .sort((a, b) => String(b.scheduled_at).localeCompare(String(a.scheduled_at)));

    return {
      loading: d.loading && !d.data,
      requests: H.rows(asks),
      next: [...done.values()],
      followup: fup,
      noshow,
    };
  }, [d.data, d.loading, today]);
}

/* ── 왼쪽 — 할 일 · 작은 달력 ───────────────────────────────────── */
function Side({ anchor, onPick, cfg, ver, work, queue, setQueue, onTake }) {
  const d = new Date(`${anchor}T00:00:00`);

  /* 한 달 치 예약을 받아 **날마다 몇 건인지**만 센다. 못 불러도 달력은 선다 */
  const from = ymd(new Date(d.getFullYear(), d.getMonth(), 1));
  const to = ymd(new Date(d.getFullYear(), d.getMonth() + 1, 0));
  const booked = useApi(
    () => cfg.api.schedule(from, to).catch(() => []), [from, to, ver]);
  const counts = useMemo(() => {
    const m = new Map();
    for (const r of Array.isArray(booked.data) ? booked.data : []) {
      const day = dayOf(r.scheduled_at);
      if (day) m.set(day, (m.get(day) ?? 0) + 1);
    }
    return m;
  }, [booked.data]);

  return (
    <div className="resv-side">
      <section className="resv-work" aria-label="예약 할 일">
        {QUEUES.map((q) => {
          const list = work[q.key];
          const on = queue === q.key;
          return (
            <div key={q.key} className={`resv-wq${on ? " on" : ""}`}>
              <button type="button" className="resv-wq-h" aria-expanded={on}
                      onClick={() => setQueue(on ? null : q.key)}>
                <b>{q.label}</b>
                <i className={list.length ? "n" : undefined}>{work.loading ? "…" : list.length}</i>
                <span aria-hidden="true">{on ? "⌄" : "›"}</span>
              </button>
              {on && (
                <div className="resv-wq-b">
                  {list.length === 0 && <p className="hcard-k">{q.empty}</p>}
                  {list.map((r, i) => (
                    <button type="button" className="resv-wrow"
                            key={r.exam_order_id ?? r.followup_id ?? `${q.key}${i}`}
                            onClick={() => onTake(q.key, r)}>
                      <b>{H.nameOf(r)}</b>
                      <span>{subOf(q.key, r)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </section>

      {/* 작은 달력은 **하루**를 고른다 — 주·월로 넓히는 것은 가운데 머리의 단추다 */}
      <Mini y={d.getFullYear()} m={d.getMonth()} anchor={anchor} onPick={onPick}
            counts={counts} />
    </div>
  );
}

/* 할 일 한 줄의 둘째 줄 — 왜 이 사람이 여기 있나 */
function subOf(key, r) {
  if (key === "requests") return `희망 ${dayOf(r.scheduled_at) || "날짜 없음"} ${timeOf(r.scheduled_at)}`.trim();
  if (key === "next") {
    return [`${dayOf(r.visited_at ?? r.scheduled_at).slice(5)} 진료 완료`, r.primary_staff_name]
      .filter(Boolean).join(" · ");
  }
  if (key === "followup") {
    const due = dayOf(r.due_at);
    return `${r.round_no ?? "—"}회차 · 예정 ${due.slice(5)}${H.dueBucket(r.due_at) === "over" ? " 지남" : ""}`;
  }
  return `${dayOf(r.scheduled_at).slice(5)} ${timeOf(r.scheduled_at)} 예약 · 미내원`;
}

function Mini({ y, m, anchor, onPick, counts }) {
  const date = new Date(y, m, 1);
  const year = date.getFullYear();
  const mon = date.getMonth();
  const first = new Date(year, mon, 1).getDay();
  const last = new Date(year, mon + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < first; i += 1) cells.push(null);
  for (let n = 1; n <= last; n += 1) cells.push(`${year}-${pad(mon + 1)}-${pad(n)}`);

  return (
    <section className="resv-mini">
      <h3>{year}. {pad(mon + 1)}</h3>
      <div className="resv-mini-grid">
        {WEEK.map((w, i) => <i key={w} className={`hcal-dow w${i}`}>{w}</i>)}
        {cells.map((iso, i) => iso === null
          ? <i className="hcal-d off" key={`x${i}`} />
          : (
            <button type="button" key={iso}
                    className={`hcal-d w${new Date(`${iso}T00:00:00`).getDay()}`
                      + `${iso === anchor ? " now" : ""}`}
                    aria-pressed={iso === anchor}
                    title={counts.get(iso) ? `예약 ${counts.get(iso)}건` : undefined}
                    onClick={() => onPick(iso)}>
              {Number(iso.slice(8))}
              {/* 빈 점도 자리를 지킨다 — 안 그러면 예약 있는 날만 숫자가 뜬다 */}
              <s className={`hcal-dot${counts.get(iso) ? " k0" : ""}`} />
            </button>
          ))}
      </div>
    </section>
  );
}

/* ── 가운데 — 이미 있는 것 ────────────────────────────────────── */
function Board({ span, setSpan, anchor, setAnchor, range, state, rows, all,
                 docs, doc, setDoc, onSlot, onOrder }) {
  const byDay = useMemo(() => {
    const m = new Map();
    /* 한 오더는 한 덩어리 — 같은 번호가 두 번 오면 두 덩어리로 그려져
       중복 예약처럼 보인다. 판의 두 덩어리는 언제나 서로 다른 오더다 */
    const seen = new Set();
    for (const r of rows) {
      const day = dayOf(r.scheduled_at);
      if (!day) continue;
      const id = r.exam_order_id ?? r.id;
      if (id != null) {
        if (seen.has(id)) continue;
        seen.add(id);
      }
      const list = m.get(day) ?? [];
      list.push(r);
      m.set(day, list);
    }
    return m;
  }, [rows]);

  const step = span === "month" ? 30 : span === "week" ? 7 : 1;
  const today = ymd(new Date());
  /* ⚠ 월 보기에서 30일씩 밀면 31일에 서 있을 때 한 달을 건너뛴다 —
     월은 달력의 달로 옮긴다 */
  const move = (dir) => {
    if (span !== "month") { setAnchor(addDays(anchor, dir * step)); return; }
    const d = new Date(`${anchor}T00:00:00`);
    setAnchor(ymd(new Date(d.getFullYear(), d.getMonth() + dir, 1)));
  };

  return (
    <>
      <div className="resv-bar">
        <span className="sorts">
          {[["day", "일"], ["week", "주"], ["month", "월"]].map(([k, name]) => (
            <button type="button" key={k} className={`pill${span === k ? " on" : ""}`}
                    onClick={() => setSpan(k)}>{name}</button>
          ))}
        </span>
        <button type="button" className="cal-nav" aria-label="이전"
                onClick={() => move(-1)}>‹</button>
        <button type="button" className="pill" onClick={() => setAnchor(today)}>오늘</button>
        <button type="button" className="cal-nav" aria-label="다음"
                onClick={() => move(1)}>›</button>
        <span className="resv-range">{range.from} – {range.to}</span>
        <span className="home-fill" />
        <span className="hcard-k">{rows.length === all ? `${all}건` : `${rows.length} / ${all}건`}</span>
      </div>

      {/* 주치의로 거른다 — 예약 응답(ExamOrderSerializer)의 primary_staff_name.
          덩어리 앞 글자도 그 이름의 첫 자다 */}
      {docs.length > 0 && (
        <div className="resv-docs sorts" role="group" aria-label="주치의">
          <span className="sorts-k">주치의</span>
          {[["all", "전체"], ...docs.map((n) => [n, n]), ["none", "미배정"]].map(([k, name]) => (
            <button type="button" key={k} className={`pill${doc === k ? " on" : ""}`}
                    aria-pressed={doc === k} onClick={() => setDoc(k)}>
              {k !== "all" && k !== "none" && <i className="resv-doc" aria-hidden="true">{name[0]}</i>}
              {name}
            </button>
          ))}
        </div>
      )}

      <Body loading={state.loading} error={state.error} onRetry={state.reload}>
        {span === "month"
          ? <Month days={range.days} byDay={byDay} onOrder={onOrder} onSlot={onSlot} />
          : <Grid days={range.days} byDay={byDay} onOrder={onOrder} onSlot={onSlot} />}
      </Body>
    </>
  );
}

/* 일·주 — 세로 08:00–18:00, 가로 날짜. 빈 칸을 누르면 오른쪽에 그 시각이
   들어가고, 덩어리를 누르면 오른쪽이 그 환자로 바뀐다. 화면은 안 옮긴다 */
function Grid({ days, byDay, onOrder, onSlot }) {
  const today = ymd(new Date());
  return (
    <div className="resv-grid" style={{ "--resv-cols": days.length }}>
      <i className="resv-corner" />
      {days.map((d) => (
        <b className={`resv-head${d === today ? " now" : ""}`} key={d}>
          {Number(d.slice(8))}({WEEK[new Date(`${d}T00:00:00`).getDay()]})
          <em>{(byDay.get(d) ?? []).length}건</em>
        </b>
      ))}

      {SLOTS.map((slot) => (
        <Row key={slot} slot={slot} days={days} byDay={byDay}
             today={today} onOrder={onOrder} onSlot={onSlot} />
      ))}
    </div>
  );
}

function Row({ slot, days, byDay, today, onOrder, onSlot }) {
  return (
    <>
      <i className="resv-slot">{slot}</i>
      {days.map((d) => {
        const here = (byDay.get(d) ?? []).filter((r) => timeOf(r.scheduled_at) === slot);
        return (
          <div className={`resv-cell${d === today ? " now" : ""}`} key={`${d}-${slot}`}>
            {here.length === 0 ? (
              <button type="button" className="resv-free"
                      aria-label={`${d} ${slot} 새 예약`}
                      onClick={() => onSlot(`${d}T${slot}:00`)} />
            ) : here.map((r) => (
              <button type="button" key={r.exam_order_id ?? r.id}
                      className={`resv-ev${isPending(r) ? " pending" : ""}${r.visited_at ? " came" : ""}`}
                      title={[isPending(r) && "미확정 예약", r.visited_at && "내원함",
                        r.primary_staff_name].filter(Boolean).join(" · ") || undefined}
                      onClick={() => onOrder(r)}>
                {isPending(r) && <i className="resv-tag">미확정</i>}
                {r.primary_staff_name && <i className="resv-doc" aria-hidden="true">{r.primary_staff_name[0]}</i>}
                <time>{slot}</time>
                <b>{r.patient_name ?? `#${r.patient}`}</b>
              </button>
            ))}
          </div>
        );
      })}
    </>
  );
}

/* 월 — 날짜 칸마다 그날 건수와 앞 몇 줄 */
function Month({ days, byDay, onOrder }) {
  const first = new Date(`${days[0]}T00:00:00`).getDay();
  const today = ymd(new Date());
  return (
    <div className="resv-month">
      {WEEK.map((w, i) => <i key={w} className={`hcal-dow w${i}`}>{w}</i>)}
      {Array.from({ length: first }, (_, i) => <i className="resv-mcell off" key={`x${i}`} />)}
      {days.map((d) => {
        const here = byDay.get(d) ?? [];
        return (
          <div className={`resv-mcell${d === today ? " now" : ""}`} key={d}>
            <b>{Number(d.slice(8))}</b>
            {here.length > 0 && <em>{here.length}건</em>}
            {here.slice(0, 3).map((r) => (
              <button type="button" key={r.exam_order_id ?? r.id}
                      className={`resv-mev${isPending(r) ? " pending" : ""}`}
                      title={isPending(r) ? "미확정 예약" : undefined}
                      onClick={() => onOrder(r)}>
                {isPending(r) && "(미확정) "}
                {timeOf(r.scheduled_at)} {r.primary_staff_name ? `${r.primary_staff_name[0]} · ` : ""}
                {r.patient_name ?? `#${r.patient}`}
              </button>
            ))}
            {here.length > 3 && <span className="hcard-k">외 {here.length - 3}건</span>}
          </div>
        );
      })}
    </div>
  );
}

/* ── 오른쪽 340 — 지금 쓰는 것 ────────────────────────────────── */
function Aside({ cfg, pick, rows, ver, onEdit, onNext, onDone, onDate, onClear }) {
  const api = cfg.api;
  const order = pick?.order ?? null;
  const patientId = order?.patient ?? pick?.patient?.patient_id ?? null;
  const person = order ? personOf(order) : pick?.patient ?? null;

  const past = useApi(
    () => (patientId == null ? Promise.resolve([]) : api.ordersOf(patientId)),
    [patientId, ver]);
  const list = Array.isArray(past.data) ? past.data : [];

  /* 안 오신 적 — 지난 예약인데 내원 기록이 없는 것.
     ⚠ **「부도」라고 쓰지 않는다.** 창구에서 내원을 안 찍었을 수도 있어
       단정할 수 없다. 횟수와 날짜만 보이고 판단은 사람이 한다(6.1)
     ⚠ 취소한 예약은 안 센다 — 미리 취소한 사람이 「안 오신 적」으로 잡혔다 */
  const today = ymd(new Date());
  const missed = list.filter(
    (r) => dayOf(r.scheduled_at) && dayOf(r.scheduled_at) < today && !r.visited_at
      && r.order_status !== "cancelled");

  return (
    <div className="resv-aside">
      {/* 새 예약이 맨 위다 — 창구에서 제일 많이 누르는 것이 여기라 스크롤
          아래에 두면 매번 내려가야 했다.
          ⚠ 고칠 수 없는 예약(내원 · 진행 중)은 **보기 전용**이다 — 새 예약
            칸에 그 예약의 날짜를 채우면 방금 누른 예약과 겹친다고 떴다 */}
      {order && !isEditable(order)
        ? <Done order={order} onNext={() => onNext(order)} />
        : <New cfg={cfg} pick={pick} rows={rows} ver={ver}
               onEdit={onEdit} onDone={onDone} onDate={onDate} onClear={onClear} />}

      {/* 예약 정보 · 지난 예약을 한 카드로 — 둘 다 「이 사람의 예약」이다 */}
      <Card title="이 환자 예약"
            right={missed.length > 0 && <Chip tone="fill">미내원 {missed.length}</Chip>}>
        {patientId == null ? <Empty title="예약이나 환자를 선택하세요" /> : (
          <>
            <p className="resv-who">
              <b>{person?.name ?? `#${patientId}`}</b>
              {person?.patient_number && <span>{person.patient_number}</span>}
              {order && (order.age != null || order.sex) && (
                <span>{[order.age, order.sex === "female" ? "여"
                  : order.sex === "male" ? "남" : order.sex].filter(Boolean).join(" · ")}</span>
              )}
            </p>
            {missed.length > 0 && (
              <p className="resv-miss">
                미내원 {missed.length}회
                <span>{missed.slice(0, 3).map((r) => dayOf(r.scheduled_at)).join(" · ")}</span>
              </p>
            )}
            <Body loading={past.loading} error={past.error} onRetry={past.reload}
                  empty={list.length === 0 && <p className="hcard-k">예약 기록이 없습니다</p>}>
              <div className="resv-past">
                {list.map((r) => (
                  <p key={r.exam_order_id}
                     className={String(r.exam_order_id) === String(order?.exam_order_id) ? "on" : undefined}>
                    <i>{r.order_status === "cancelled" ? "취소"
                      : r.visited_at ? "완료"
                      : dayOf(r.scheduled_at) < today ? "미내원"
                      : isPending(r) ? "미확정" : "확정"}</i>
                    <time>{dayOf(r.scheduled_at)}</time>
                    <span>{r.primary_staff_name ?? "주치의 미배정"}</span>
                    {/* 종류는 유방외과가 정하기 전까지 「미정」이다 */}
                    <em>{r.modality ?? "미정"}</em>
                  </p>
                ))}
              </div>
            </Body>
            <div className="rowb">
              <Btn to={go.patient(patientId)}>환자 기록</Btn>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

/* 고칠 수 없는 예약 — 내원했거나 진행 중이거나 끝난 것. 보기만 한다.
   [다음 예약 잡기]를 눌러야 **날짜가 빈** 새 예약이 된다 — 그때부터 같은 날
   겹침 규칙이 선다(그 날을 또 고르면 그때의 경고는 맞다) */
function Done({ order, onNext }) {
  const may = useCan(["reception.reserve", "nursing.waiting.view"]);
  const came = Boolean(order.visited_at);
  const state = came
    ? (order.order_status === "completed" ? "내원 · 완료" : "내원 처리됨")
    : STATUS[order.order_status] ?? order.order_status ?? "—";
  return (
    <Card title="예약 보기" className="resv-new">
      <p className="resv-who">
        <b>{order.patient_name ?? `#${order.patient}`}</b>
        {order.patient_number && <span>{order.patient_number}</span>}
      </p>
      <p className="resv-done">
        이 예약은 {came ? "내원 처리됐습니다" : "진행 중입니다"}
        <span>{dayOf(order.scheduled_at)} {timeOf(order.scheduled_at)} · {state}</span>
      </p>
      <dl className="kv">
        <div><dt>예약</dt><dd className="num">{dayOf(order.scheduled_at) || "—"} {timeOf(order.scheduled_at)}</dd></div>
        {came && <div><dt>내원</dt><dd className="num">{dayOf(order.visited_at)} {timeOf(order.visited_at)}</dd></div>}
        <div><dt>상태</dt><dd>{state}</dd></div>
        <div><dt>주치의</dt><dd>{order.primary_staff_name ?? "미배정"}</dd></div>
        <div><dt>검사</dt><dd>{order.modality ?? "미정"}</dd></div>
      </dl>
      <div className="rowb">
        <Btn kind="fill" onClick={onNext} {...may.attrs} disabled={!may.ok}>다음 예약 잡기</Btn>
      </div>
      <p className="hcard-k">내원했거나 진행 중인 예약은 변경할 수 없습니다.</p>
    </Card>
  );
}

function New({ cfg, pick, rows, ver, onEdit, onDone, onDate, onClear }) {
  const api = cfg.api;
  const at = pick?.at;
  const order = pick?.order ?? null;
  /* ⚠ 간호 계정도 예약을 잡는다 — 한 과다(Patients.jsx 의 integrated).
     reception.reserve 만 보면 간호 열쇠만 가진 사람은 [예약] 이 늘 잠겼다 */
  const may = useCan(["reception.reserve", "nursing.waiting.view"]);
  const mayConfirm = useCan(["reception.confirm", "nursing.waiting.view"]);

  const [q, setQ] = useState("");
  const [found, setFound] = useState(null);
  const [who, setWho] = useState(null);
  const [date, setDate] = useState(dayOf(at) || ymd(new Date()));
  const [time, setTime] = useState(timeOf(at) || "09:30");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);

  /* 달력에서 고른 자리가 바뀌면 날짜·시각을 따라간다. 고른 예약이 있으면
     그 환자도 같이 들어온다 — 화면을 옮기지 않는다는 것이 이 판의 규칙이다.
     ⚠ **고른 것(pick) 자체로 가른다.** 예전엔 날짜·시각 글자로 갈라서 같은
       칸의 다른 덩어리를 누르면 오른쪽 환자가 안 바뀌었다 — 오른쪽 이름은
       A 인데 고치는 오더는 B 였다. 누를 때마다 새 pick 이 오므로 같은
       덩어리를 다시 누르면 고치던 날짜·시각이 그 예약 값으로 돌아간다 */
  /* ⚠ 09-28 처음 값을 null 로 둔다 — 이 칸이 이제 보기 전용(Done)과 번갈아
       서서, 예약을 고른 채로 **새로 선** 때도 한 번은 따라가야 한다 */
  const [seen, setSeen] = useState(null);
  if (pick && pick !== seen) {
    setSeen(pick);
    if (at) {
      setDate(dayOf(at));
      setTime(timeOf(at));
    } else if (pick.fresh) {
      /* [다음 예약 잡기] · 할 일 줄 — 날짜를 비워 둔다. 내원한 예약의 날짜가
         그대로 들어가면 그 예약과 겹친다고 떴다 */
      setDate("");
    }
    if (order) {
      setWho({ patient_id: order.patient, name: order.patient_name,
               patient_number: order.patient_number });
    } else if (pick.patient) {
      setWho(pick.patient);
    }
  }
  /* 추적 회차에서 온 예약 — 같은 사람일 때만 그 회차에 잇는다(다른 사람을
     찾아 바꿔 넣으면 서버가 400 「다른 환자의 추적 회차」) */
  const fup = pick?.followup != null && who
    && String(pick.patient?.patient_id) === String(who.patient_id) ? pick.followup : null;

  /* 고른 환자의 예약을 **그 사람 기준으로** 따로 받는다. 판(rows)은 지금
     보는 날·주만 들고 있어서, 다른 날을 보고 있으면 같은 날 예약을 못
     찾아 [예약] 이 그대로 눌렸다 */
  const mine = useApi(
    () => (who?.patient_id != null ? api.ordersOf(who.patient_id) : Promise.resolve([])),
    [who?.patient_id, ver]);

  /* 고른 예약이 아직 안 온 것이면 **고치는 자리**가 된다. 예전엔 여기서
     [예약] 을 누르면 같은 사람 예약이 또 하나 생겼다 — 바꾸려던 것이
     늘어나기만 했다 */
  const editable = isEditable(order);

  /* 그날 이 환자에게 **취소 안 된 오더**가 이미 있는가 — 서버
     _refuse_same_day 와 같은 기준이다(409 DUPLICATE_RESERVATION).
     ⚠ 내원한 것도 센다. 예전엔 「안 온 것」만 봐서, 내원한 예약을 눌러
       [예약] 을 누르면 같은 날 · 같은 시각에 새 예약이 또 섰다(09-28).
     ⚠ 고치는 중(editable)일 때만 그 오더 자신을 뺀다. 고칠 수 없는 예약을
       고른 채면 오른쪽은 **새 예약**이라 고른 그 오더도 겹침이다 */
  const clash = useMemo(() => {
    if (!who || !date) return null;
    const pool = [...(Array.isArray(mine.data) ? mine.data : []), ...rows];
    return pool.find((r) => String(r.patient) === String(who.patient_id)
      && dayOf(r.scheduled_at) === date && r.order_status !== "cancelled"
      && !(editable && r.exam_order_id === order.exam_order_id)) ?? null;
  }, [mine.data, rows, who, date, order, editable]);
  const clashLive = isEditable(clash);
  /* 고칠 것이 없다 — 날짜 · 시각이 그대로면 [변경 저장] 은 「바꿨습니다」만
     띄우고 아무것도 안 바꾼다. 사람은 저장이 안 된 줄 안다 */
  const unchanged = editable && dayOf(order.scheduled_at) === date
    && timeOf(order.scheduled_at) === time;

  /* 연타 막기 — busy 는 다음 그림에서야 단추를 잠그므로 그 사이 두 번째
     클릭이 또 나갔다. 이 표시는 바로 선다 */
  const sending = useRef(false);

  async function reschedule() {
    if (sending.current || clash || unchanged) return;
    sending.current = true;
    setBusy(true); setErr(null); setOk(null);
    try {
      const changed = await api.reschedule(order.exam_order_id, `${date}T${time}:00`);
      setOk(`${order.patient_name ?? `#${order.patient}`} · ${date} ${time} 예약으로 변경했습니다`);
      onDone(changed ?? { exam_order_id: order.exam_order_id, scheduled_at: `${date}T${time}:00` });
    } catch (e2) {
      setErr(e2);
      /* 409 — 그새 누가 그날 예약을 잡았거나(겹침) 환자가 와 버렸다(잠김).
         판과 이 사람 예약을 다시 불러 겹침 안내가 서게 한다 */
      if (e2?.status === 409) onDone();
    } finally { setBusy(false); sending.current = false; }
  }

  async function cancel() {
    const name = order.patient_name ?? `#${order.patient}`;
    // eslint-disable-next-line no-alert
    if (!window.confirm(`${name} · ${dayOf(order.scheduled_at)} ${timeOf(order.scheduled_at)} 예약을 취소할까요?`)) return;
    setBusy(true); setErr(null); setOk(null);
    try {
      await api.cancel(order.exam_order_id);
      setOk(`${name} 예약을 취소했습니다`);
      setWho(null);
      onClear();
      onDone();
    } catch (e2) { setErr(e2); }
    finally { setBusy(false); }
  }

  async function find(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setErr(null);
    try { setFound(await api.search(q.trim()) ?? []); }
    catch (e2) { setErr(e2); setFound([]); }
  }

  async function save() {
    if (sending.current || clash) return;
    sending.current = true;
    setBusy(true); setErr(null); setOk(null);
    try {
      await api.reserve({ patient_id: who.patient_id,
                          scheduled_at: `${date}T${time}:00`,
                          ...(fup != null ? { followup_id: fup } : {}) });
      /* 누구 것인지 같이 적고 고른 사람을 비운다 — 그대로 두면 판이 다시
         불리면서 방금 잡은 예약이 「같은 날 이미 예약이 있습니다」로 떠
         실패한 것처럼 보였고, 한 번 더 누르면 중복 예약이 생겼다 */
      setOk(`${who.name ?? `#${who.patient_id}`} · ${date} ${time}에 예약했습니다`);
      setWho(null); setFound(null); setQ("");
      onDone();
    } catch (e2) {
      setErr(e2);
      /* 409 DUPLICATE_RESERVATION — 판이 낡아 못 본 같은 날 예약이 서버에
         있다. 다시 불러 겹침 안내([그 예약 고치기])가 서게 한다 */
      if (e2?.status === 409) onDone();
    } finally { setBusy(false); sending.current = false; mine.reload(true); }
  }

  /* 앱 신청(requested · 아직 안 옴)을 고른 경우 — **새로 만들지 않고 그
     오더를 확정한다.** 예전엔 여기에 [예약] 하나뿐이라 신청을 열어 누르면
     같은 사람 오더가 하나 더 생기고 신청은 「예약 신청」 탭에 그대로 남았다.
     ⚠ 09-27 부터 창구가 잡은 예약은 처음부터 scheduled 로 선다
       (ExamOrderScheduleView) — 이 단추는 앱 신청에만 뜬다 */
  const pending = order && order.order_status === "requested" && !order.visited_at
    && order.exam_order_id != null;
  async function confirm() {
    setBusy(true); setErr(null); setOk(null);
    try {
      const changed = await api.confirm(order.exam_order_id, `${date}T${time}:00`);
      setOk(`${order.patient_name ?? `#${order.patient}`} · ${date} ${time} 예약으로 확정했습니다`);
      onDone(changed ?? { exam_order_id: order.exam_order_id, order_status: "scheduled" });
    } catch (e2) { setErr(e2); if (e2?.status === 409) onDone(); }
    finally { setBusy(false); }
  }

  return (
    <Card title={editable ? "예약 변경" : "새 예약"} className="resv-new"
          right={editable && (
            /* 고른 예약을 놓고 빈 새 예약으로 */
            <Btn onClick={() => { setWho(null); setFound(null); onClear(); }}>새 예약</Btn>
          )}>
      {who ? (
        <p className="resv-who">
          <b>{who.name ?? `#${who.patient_id}`}</b>
          {who.patient_number && <span>{who.patient_number}</span>}
          <button type="button" className="note-x" aria-label="지우기"
                  onClick={() => { setWho(null); setFound(null); if (editable) onClear(); }}>×</button>
        </p>
      ) : (
        <>
          {/* 「날짜」·「시간」과 같은 두 단 리듬에 맞춘다 — 라벨이 없으면
              이 줄만 왼쪽으로 튀어나와 폼이 어긋나 보인다(09-23) */}
          <form className="resv-field resv-find" onSubmit={find}>
            <span>환자</span>
            <input value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="이름 · 전화 · 생년월일" aria-label="환자 찾기" />
            <button className="btn dark" type="submit">찾기</button>
          </form>
          {(found ?? []).slice(0, 4).map((p) => (
            <button type="button" className="resv-hit" key={p.patient_id}
                    onClick={() => setWho(p)}>
              <b>{p.name}</b>
              <span>{[p.patient_number, p.birth_date].filter(Boolean).join(" · ")}</span>
            </button>
          ))}
          {found?.length === 0 && <p className="hcard-k">찾는 환자가 없습니다</p>}
        </>
      )}

      <label className="resv-field">
        <span>날짜</span>
        <input type="date" value={date}
               onChange={(e) => { setDate(e.target.value); onDate(e.target.value); }} />
      </label>

      {/* 빠른 날짜 — 누르면 오늘부터 그만큼 뒤가 들어가고 달력도 따라 움직인다 */}
      <div className="resv-quick">
        {QUICK.map(([name, days]) => (
          <button type="button" className="pill" key={name}
                  onClick={() => {
                    const d = addDays(ymd(new Date()), days);
                    setDate(d); onDate(d);
                  }}>{name}</button>
        ))}
      </div>

      <label className="resv-field">
        <span>시간</span>
        <select value={time} onChange={(e) => setTime(e.target.value)}>
          {SLOTS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>

      <p className="hcard-k">검사 종류는 여기서 정하지 않습니다 — 진료 후 유방외과에서 오더를 냅니다.</p>
      {fup != null && !editable && (
        <p className="hcard-k resv-fup">추적 회차 예약 — 예약하면 해당 회차에 연결됩니다.</p>
      )}
      {!date && who && !editable && (
        <p className="hcard-k">날짜를 선택하세요 — 달력의 빈 칸이나 위의 빠른 날짜를 누르세요.</p>
      )}

      {editable && !clash && (
        <p className="hcard-k">달력의 빈 칸을 누르면 이 예약을 그 시간으로 옮깁니다.</p>
      )}
      {clash && (clashLive ? (
        <p className="note err">
          {date}에 이 환자의 예약이 이미 있습니다 — {timeOf(clash.scheduled_at)}.
          {editable ? " 하루에 두 건을 예약할 수 없습니다." : " 새로 예약하지 말고 기존 예약을 변경하세요."}
          {" "}
          <button type="button" className="resv-jump"
                  onClick={() => { setErr(null); setOk(null);
                                   onEdit(clash, `${date}T${time}:00`); }}>
            기존 예약 변경
          </button>
        </p>
      ) : (
        <p className="note err">
          {date} {timeOf(clash.scheduled_at)} 예약으로 이미 내원했습니다 — 다른 날짜를 선택해 주세요.
        </p>
      ))}
      {/* 겹침 안내가 이미 선 409 는 같은 말을 두 번 하지 않는다 */}
      {err && !(clash && err.code === "DUPLICATE_RESERVATION")
        && <p className="note err">{err.detail || err.message}</p>}
      {ok && <p className="hcard-k" role="status">{ok}</p>}

      <div className="rowb">
        <Btn to={go.nursing.patients()}>환자 목록</Btn>
        {pending && (
          <Btn kind="fill" onClick={confirm} {...mayConfirm.attrs}
               disabled={busy || !mayConfirm.ok || Boolean(clash)}>이 시간으로 예약 확정</Btn>
        )}
        {editable ? (
          <>
            <Btn onClick={cancel} {...may.attrs} disabled={busy || !may.ok}>예약 취소</Btn>
            <Btn kind={pending ? undefined : "fill"} onClick={reschedule} {...may.attrs}
                 disabled={busy || !may.ok || Boolean(clash) || unchanged}>변경 저장</Btn>
          </>
        ) : (
          <Btn kind="fill" onClick={save} {...may.attrs}
               disabled={!who || !date || busy || !may.ok || Boolean(clash)}>예약</Btn>
        )}
      </div>

    </Card>
  );
}
