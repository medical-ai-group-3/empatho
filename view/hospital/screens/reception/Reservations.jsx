import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Page, Card, Btn } from "../../lib/Page";
import { Body, Empty } from "../../lib/Body";
import { Chip, useCan } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";

/* 예약 판 — 달력이 본체인 화면 (6.1)
 * ════════════════════════════════════════════════════════════════
 *
 * 예약이 환자 목록에 얹혀 있던 것을 뺀다. 검체 등록 팝업·히스토리 레일과
 * 같은 규칙으로 짠다 —
 * **왼쪽에 무엇을 볼지, 가운데에 이미 있는 것, 오른쪽에 지금 쓰는 것.**
 *
 * ⚠ **「칸은 사람이다」를 못 만들었다.** 6.1 은 주치의로 칸을 나누라고
 *   했는데 `GET /exam-orders` 응답(ExamOrderSerializer)에 `primary_staff`
 *   가 없다 — 그 칸은 PatientSerializer 에만 있다. 주마다 환자 상세를
 *   한 명씩 더 부르면 줄 수만큼 요청이 나간다. 칸을 하나로 두고 왼쪽
 *   「보는 사람」에 그 사실을 적어 두었다(8장 12번).
 *
 * ── 한 사람 · 한 날 · 예약 하나 (09-28) ──────────────────────────
 * 고칠 수 있는 예약(안 옴 · 신청/확정)을 고르면 오른쪽은 **고치는 자리**다
 * — [변경 저장](PATCH /exam-orders/{id}/reschedule) · [예약 취소]. 판의 빈
 * 칸을 누르면 그 예약이 그 칸으로 옮겨 갈 자리가 된다. 새로 만드는 [예약]
 * 은 그날 이 환자에게 취소 안 된 오더가 **하나라도**(내원한 것 포함) 있으면
 * 잠기고 [그 예약 고치기]로 넘어간다. 서버도 같은 기준으로 409
 * DUPLICATE_RESERVATION 을 준다(core/views/reception.py _refuse_same_day).
 *
 * ⚠ **메모 칸을 내지 않는다.** `schedule` 이 `patient_id`·`scheduled_at`
 *   둘만 받아서 쓴 글이 그냥 버려진다. 칸을 만들어 놓고 버리는 것이
 *   제일 나쁘다(1.3).
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

/* 아직 확정 안 된 예약(requested) — 확정(scheduled)과 판에서 모양을 달리한다.
   같은 사람이 확정 예약을 두고 다른 날 또 신청했을 때 어느 쪽이 진짜인지
   한눈에 갈라야 한다 */
const isPending = (r) => r.order_status === "requested" && !r.visited_at;

/* 고칠 수 있는 예약 — 아직 안 왔고(visited_at 빈) 신청 · 확정인 것. 서버
   ExamOrderRescheduleView.EDITABLE 과 같은 기준이다. 내원했거나 진행 중인
   오더는 서버가 409 RESERVATION_LOCKED 로 막는다 */
const isEditable = (r) => Boolean(r) && r.exam_order_id != null && !r.visited_at
  && ["requested", "scheduled"].includes(r.order_status);

/* 08:00–18:00 을 30분으로 끊는다(6.1) */
const SLOTS = [];
for (let h = 8; h < 18; h += 1) {
  SLOTS.push(`${pad(h)}:00`);
  SLOTS.push(`${pad(h)}:30`);
}

/* 빠른 날짜 — 참고 화면의 `1주 2주 … 12주` 자리다. 유방 쪽은 간격이 달라
   BI-RADS 3 추적(6·12·24개월)이 제일 많이 눌린다 */
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

export default function Reservations({ cfg }) {
  const api = cfg.api;
  const today = ymd(new Date());

  /* 홈 달력에서 날을 눌러 오면 ?date= 가 붙는다 — 그 하루를 연다 */
  const [params] = useSearchParams();
  const asked = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") ?? "")
    ? params.get("date") : null;

  const [span, setSpan] = useState(asked ? "day" : "week"); /* day · week · month */
  const [anchor, setAnchor] = useState(asked ?? today);      /* 보고 있는 날 */
  const [pick, setPick] = useState(null);        /* 오른쪽에 띄운 예약·환자 */
  const [tab, setTab] = useState("board");       /* board · requests */

  const range = useMemo(() => rangeOf(span, anchor), [span, anchor]);
  const [ver, setVer] = useState(0);   /* 예약을 잡으면 작은 달력 점도 다시 */

  const board = useApi(
    () => api.schedule(range.from, range.to), [range.from, range.to]);
  const requests = useApi(() => api.requests(), []);

  /* 취소한 예약은 판에서 뺀다 — 서버는 지우지 않고 cancelled 로 남긴다 */
  const rows = (board.data ?? []).filter((r) => r.order_status !== "cancelled");
  const asks = requests.data ?? [];

  return (
    <Page crumb={[cfg.name, "예약"]} title="예약 관리" className="resv-page"
          right={(
            <span className="sorts">
              <button type="button" className={`pill${tab === "board" ? " on" : ""}`}
                      onClick={() => setTab("board")}>예약 판</button>
              {/* 예약 신청은 화면을 따로 두지 않는다 — 둘 다 예약이고
                  신청은 「앱에서 들어온 것」일 뿐이다(6.1) */}
              <button type="button" className={`pill${tab === "requests" ? " on" : ""}`}
                      onClick={() => setTab("requests")}>
                예약 신청{asks.length > 0 && <i className="pill-n">{asks.length}</i>}
              </button>
            </span>
          )}>
      <div className="resv">
        {/* 작은 달력은 **하루**를 고른다 — 주 전체가 칠해지면 어느 날을
            골랐는지 안 보였다. 주·월로 넓히는 것은 가운데 머리의 단추다 */}
        <Side anchor={anchor} onPick={(d) => { setAnchor(d); setSpan("day"); }}
              cfg={cfg} ver={ver} />

        <div className="resv-mid">
          {tab === "board" ? (
            <Board span={span} setSpan={setSpan} anchor={anchor} setAnchor={setAnchor}
                   range={range} state={board} rows={rows}
                   /* 고칠 수 있는 예약을 고른 채 빈 칸을 누르면 **그 예약을
                      그 칸으로 옮기는 자리**다. 예전엔 고른 예약이 떨어지고
                      환자만 남아 [예약] 이 떴다 — 옮기려던 사람이 누르면 같은
                      사람 예약이 하나 더 섰다(09-28) */
                   onSlot={(at) => setPick((p) => (isEditable(p?.order)
                     ? { at, order: p.order } : { at }))}
                   onOrder={(r) => setPick({ at: r.scheduled_at, order: r })} />
          ) : (
            <Requests state={requests} rows={asks}
                      onOpen={(r) => { setAnchor(dayOf(r.scheduled_at) || today);
                                       setTab("board"); setPick({ at: r.scheduled_at, order: r }); }} />
          )}
        </div>

        <Aside cfg={cfg} pick={pick} rows={rows} ver={ver}
               onEdit={(order, at) => setPick({ at, order })}
               onDone={(changed) => {
          board.reload(true);
          requests.reload(true);
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

/* ── 왼쪽 220 — 무엇을 볼지 ───────────────────────────────────── */
function Side({ anchor, onPick, cfg, ver }) {
  const d = new Date(`${anchor}T00:00:00`);
  const months = [
    { y: d.getFullYear(), m: d.getMonth() },
    { y: d.getFullYear(), m: d.getMonth() + 1 },
  ];

  /* 두 달 치 예약을 한 번에 받아 **날마다 몇 건인지**만 센다 — 점과
     건수로 예약 있는 날이 보이게. 못 불러도 달력은 선다 */
  const from = ymd(new Date(d.getFullYear(), d.getMonth(), 1));
  const to = ymd(new Date(d.getFullYear(), d.getMonth() + 2, 0));
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
  /* 「보는 사람」 목록은 부를 수 있다. 다만 예약을 그 사람에게 붙일 수가
     없어서 지금은 **거르지 못한다** — 체크를 만들어 두고 안 듣는 것보다
     못 한다고 적는 편이 낫다 */
  const staff = useApi(() => cfg.api.surgeons().catch(() => []), []);
  const people = Array.isArray(staff.data) ? staff.data : [];

  return (
    <div className="resv-side">
      {months.map(({ y, m }) => (
        <Mini key={`${y}-${m}`} y={y} m={m} anchor={anchor} onPick={onPick}
              counts={counts} />
      ))}

      <section className="resv-people">
        <h3>보는 사람</h3>
        {people.length === 0
          ? <p className="hcard-k">명단을 못 불렀습니다</p>
          : people.slice(0, 8).map((s) => (
            <p key={s.staff_id ?? s.id}>{s.full_name ?? s.name ?? `직원 ${s.staff_id}`}</p>
          ))}
        {/* ⚠ 6.1 의 「칸은 사람이다」를 못 만든 이유를 화면에도 적는다 —
            체크박스를 놓고 안 듣게 두면 고장으로 오해한다 */}
        <p className="hcard-k">
          예약 응답에 주치의가 실려 오지 않아 사람별로 나누지 못합니다.
        </p>
      </section>
    </div>
  );
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
function Board({ span, setSpan, anchor, setAnchor, range, state, rows,
                 onSlot, onOrder }) {
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
  /* ⚠ 월 보기에서 30일씩 밀면 31일에 서 있을 때 한 달을 건너뛴다
     (1월 31일 + 30 = 3월 2일 — 2월이 안 보인다). 월은 달력의 달로 옮긴다 */
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
        <span className="hcard-k">{rows.length}건</span>
      </div>

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
                      className={`resv-ev${isPending(r) ? " pending" : ""}`}
                      title={isPending(r) ? "미확정 예약" : undefined}
                      onClick={() => onOrder(r)}>
                {isPending(r) && <i className="resv-tag">미확정</i>}
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
                {timeOf(r.scheduled_at)} {r.patient_name ?? `#${r.patient}`}
              </button>
            ))}
            {here.length > 3 && <span className="hcard-k">외 {here.length - 3}건</span>}
          </div>
        );
      })}
    </div>
  );
}

/* ── 예약 신청 탭 — 앱으로 들어온 것 ──────────────────────────── */
function Requests({ state, rows, onOpen }) {
  return (
    <Body loading={state.loading} error={state.error} onRetry={state.reload}
          empty={rows.length === 0 && <Empty title="확인할 신청이 없습니다" />}>
      <div className="qrows resv-asks">
        {rows.map((r, i) => (
          <article className="qrow" role="button" tabIndex={0}
                   key={r.exam_order_id ?? i}
                   onClick={() => onOpen(r)}
                   onKeyDown={(e) => { if (e.key === "Enter") onOpen(r); }}>
            <i className="qrow-n">{i + 1}</i>
            <b>{r.patient_name ?? `#${r.patient}`}</b>
            {(r.age != null || r.sex) && (
              <span className="qrow-meta">
                {[r.age, r.sex === "female" ? "여" : r.sex === "male" ? "남" : r.sex]
                  .filter(Boolean).join(" · ")}
              </span>
            )}
            {r.visit_type && <Chip>{r.visit_type}</Chip>}
            <span className="qrow-sub">희망 {dayOf(r.scheduled_at)} {timeOf(r.scheduled_at)}</span>
            <span className="qrow-r">
              {r.patient_number && <i className="qrow-no">{r.patient_number}</i>}
              <i className="qrow-go" aria-hidden="true">›</i>
            </span>
          </article>
        ))}
      </div>
    </Body>
  );
}

/* ── 오른쪽 340 — 지금 쓰는 것 ────────────────────────────────── */
function Aside({ cfg, pick, rows, ver, onEdit, onDone, onDate, onClear }) {
  const api = cfg.api;
  const order = pick?.order ?? null;
  const patientId = order?.patient ?? null;

  const past = useApi(
    () => (patientId == null ? Promise.resolve([]) : api.ordersOf(patientId)),
    [patientId, ver]);
  const list = Array.isArray(past.data) ? past.data : [];

  /* 안 오신 적 — 지난 예약인데 내원 기록이 없는 것.
     ⚠ **「부도」라고 쓰지 않는다.** 창구에서 내원을 안 찍었을 수도 있어
       단정할 수 없다. 횟수와 날짜만 보이고 판단은 사람이 한다(6.1) */
  const today = ymd(new Date());
  /* ⚠ 취소한 예약은 안 센다 — 미리 취소한 사람이 「안 오신 적」으로 잡혔다 */
  const missed = list.filter(
    (r) => dayOf(r.scheduled_at) && dayOf(r.scheduled_at) < today && !r.visited_at
      && r.order_status !== "cancelled");

  return (
    <div className="resv-aside">
      {/* 새 예약이 맨 위다 — 창구에서 제일 많이 누르는 것이 여기라 스크롤
          아래에 두면 매번 내려가야 했다 */}
      <New cfg={cfg} pick={pick} rows={rows} ver={ver}
           onEdit={onEdit} onDone={onDone} onDate={onDate} onClear={onClear} />

      <Card title="예약 정보">
        {order ? (
          <>
            <p className="resv-who">
              <b>{order.patient_name ?? `#${order.patient}`}</b>
              {(order.age != null || order.sex) && (
                <span>{[order.age, order.sex === "female" ? "여"
                  : order.sex === "male" ? "남" : order.sex].filter(Boolean).join(" · ")}</span>
              )}
            </p>
            {missed.length > 0 && (
              <p className="resv-miss">
                안 오신 적 {missed.length}번
                <span>{missed.slice(0, 3).map((r) => dayOf(r.scheduled_at)).join(" · ")}</span>
              </p>
            )}
          </>
        ) : (
          <Empty title="달력에서 예약을 고르세요" />
        )}
      </Card>

      <Card title="지난 예약">
        {patientId == null
          ? <Empty title="고른 예약이 없습니다" />
          : (
            <Body loading={past.loading} error={past.error} onRetry={past.reload}
                  empty={list.length === 0 && <Empty title="지난 예약이 없습니다" />}>
              <div className="resv-past">
                {list.map((r) => (
                  <p key={r.exam_order_id}>
                    <i>{r.order_status === "cancelled" ? "취소"
                      : r.visited_at ? "완료"
                      : dayOf(r.scheduled_at) < today ? "안 옴"
                      : isPending(r) ? "미확정" : "확정"}</i>
                    <time>{dayOf(r.scheduled_at)}</time>
                    <span>{r.primary_staff_name ?? "담당 미정"}</span>
                    {/* 종류는 유방외과가 정하기 전까지 「미정」이다 — 빈 칸으로
                        두면 자료가 없는 건지 아직 안 정한 건지 모른다 */}
                    <em>{r.modality ?? "미정"}</em>
                  </p>
                ))}
              </div>
            </Body>
          )}
      </Card>

    </div>
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
  const [seen, setSeen] = useState(pick);
  if (pick && pick !== seen) {
    setSeen(pick);
    if (at) {
      setDate(dayOf(at));
      setTime(timeOf(at));
    }
    if (order) {
      setWho({ patient_id: order.patient, name: order.patient_name,
               patient_number: order.patient_number });
    }
  }

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
    if (!who) return null;
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
      setOk(`${order.patient_name ?? `#${order.patient}`} · ${date} ${time} 로 바꿨습니다`);
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
                          scheduled_at: `${date}T${time}:00` });
      /* 누구 것인지 같이 적고 고른 사람을 비운다 — 그대로 두면 판이 다시
         불리면서 방금 잡은 예약이 「같은 날 이미 예약이 있습니다」로 떠
         실패한 것처럼 보였고, 한 번 더 누르면 중복 예약이 생겼다 */
      setOk(`${who.name ?? `#${who.patient_id}`} · ${date} ${time} 로 잡았습니다`);
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
      setOk(`${order.patient_name ?? `#${order.patient}`} · ${date} ${time} 로 확정했습니다`);
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

      <p className="hcard-k">검사 종류는 여기서 안 정합니다 — 진료 뒤 유방외과가 오더를 냅니다.</p>

      {editable && !clash && (
        <p className="hcard-k">판의 빈 칸을 누르면 이 예약을 그 시각으로 옮깁니다.</p>
      )}
      {clash && (clashLive ? (
        <p className="note err">
          {date} 에 이 환자 예약이 이미 있습니다 — {timeOf(clash.scheduled_at)}.
          {editable ? " 한 날에 둘을 둘 수 없습니다." : " 새로 잡지 않고 그 예약을 고칩니다."}
          {" "}
          <button type="button" className="resv-jump"
                  onClick={() => { setErr(null); setOk(null);
                                   onEdit(clash, `${date}T${time}:00`); }}>
            그 예약 고치기
          </button>
        </p>
      ) : (
        <p className="note err">
          {date} {timeOf(clash.scheduled_at)} 예약으로 이미 내원했습니다 — 다른 날을 골라 주세요.
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
               disabled={busy || !mayConfirm.ok || Boolean(clash)}>이 시각으로 신청 확정</Btn>
        )}
        {editable ? (
          <>
            <Btn onClick={cancel} {...may.attrs} disabled={busy || !may.ok}>예약 취소</Btn>
            <Btn kind={pending ? undefined : "fill"} onClick={reschedule} {...may.attrs}
                 disabled={busy || !may.ok || Boolean(clash) || unchanged}>변경 저장</Btn>
          </>
        ) : (
          <Btn kind="fill" onClick={save} {...may.attrs}
               disabled={!who || busy || !may.ok || Boolean(clash)}>예약</Btn>
        )}
      </div>

      {order && !editable && (
        <p className="hcard-k">이미 내원했거나 진행 중인 예약이라 바꿀 수 없습니다.</p>
      )}
    </Card>
  );
}
