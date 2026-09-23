import { useMemo, useState } from "react";
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
 * ⚠ **만든 예약을 여기서 못 지운다.** 취소·변경 경로가 서버에 없다
 *   (8장 7번). 화면에 한 줄로 적어 둔다.
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

  const [span, setSpan] = useState("week");      /* day · week · month */
  const [anchor, setAnchor] = useState(today);   /* 보고 있는 날 */
  const [pick, setPick] = useState(null);        /* 오른쪽에 띄운 예약·환자 */
  const [tab, setTab] = useState("board");       /* board · requests */

  const range = useMemo(() => rangeOf(span, anchor), [span, anchor]);

  const board = useApi(
    () => api.schedule(range.from, range.to), [range.from, range.to]);
  const requests = useApi(() => api.requests(), []);

  const rows = board.data ?? [];
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
        <Side anchor={anchor} onPick={(d) => { setAnchor(d); setSpan("week"); }}
              cfg={cfg} />

        <div className="resv-mid">
          {tab === "board" ? (
            <Board span={span} setSpan={setSpan} anchor={anchor} setAnchor={setAnchor}
                   range={range} state={board} rows={rows}
                   onSlot={(at) => setPick({ at })}
                   onOrder={(r) => setPick({ at: r.scheduled_at, order: r })} />
          ) : (
            <Requests state={requests} rows={asks}
                      onOpen={(r) => { setAnchor(dayOf(r.scheduled_at) || today);
                                       setTab("board"); setPick({ at: r.scheduled_at, order: r }); }} />
          )}
        </div>

        <Aside cfg={cfg} pick={pick} rows={rows} onDone={() => {
          board.reload(true);
          requests.reload(true);
        }} onDate={(d) => setAnchor(d)} />
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
function Side({ anchor, onPick, cfg }) {
  const d = new Date(`${anchor}T00:00:00`);
  const months = [
    { y: d.getFullYear(), m: d.getMonth() },
    { y: d.getFullYear(), m: d.getMonth() + 1 },
  ];
  /* 「보는 사람」 목록은 부를 수 있다. 다만 예약을 그 사람에게 붙일 수가
     없어서 지금은 **거르지 못한다** — 체크를 만들어 두고 안 듣는 것보다
     못 한다고 적는 편이 낫다 */
  const staff = useApi(() => cfg.api.surgeons().catch(() => []), []);
  const people = Array.isArray(staff.data) ? staff.data : [];

  return (
    <div className="resv-side">
      {months.map(({ y, m }) => (
        <Mini key={`${y}-${m}`} y={y} m={m} anchor={anchor} onPick={onPick} />
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

function Mini({ y, m, anchor, onPick }) {
  const date = new Date(y, m, 1);
  const year = date.getFullYear();
  const mon = date.getMonth();
  const first = new Date(year, mon, 1).getDay();
  const last = new Date(year, mon + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < first; i += 1) cells.push(null);
  for (let n = 1; n <= last; n += 1) cells.push(`${year}-${pad(mon + 1)}-${pad(n)}`);

  const week = startOfWeek(anchor);
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
                      + `${startOfWeek(iso) === week ? " now" : ""}`}
                    onClick={() => onPick(iso)}>
              {Number(iso.slice(8))}
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
    for (const r of rows) {
      const day = dayOf(r.scheduled_at);
      if (!day) continue;
      const list = m.get(day) ?? [];
      list.push(r);
      m.set(day, list);
    }
    return m;
  }, [rows]);

  const step = span === "month" ? 30 : span === "week" ? 7 : 1;
  const today = ymd(new Date());

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
                onClick={() => setAnchor(addDays(anchor, -step))}>‹</button>
        <button type="button" className="pill" onClick={() => setAnchor(today)}>오늘</button>
        <button type="button" className="cal-nav" aria-label="다음"
                onClick={() => setAnchor(addDays(anchor, step))}>›</button>
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
              <button type="button" className="resv-ev" key={r.exam_order_id ?? r.id}
                      onClick={() => onOrder(r)}>
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
              <button type="button" className="resv-mev" key={r.exam_order_id ?? r.id}
                      onClick={() => onOrder(r)}>
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
function Aside({ cfg, pick, rows, onDone, onDate }) {
  const api = cfg.api;
  const order = pick?.order ?? null;
  const patientId = order?.patient ?? null;

  const past = useApi(
    () => (patientId == null ? Promise.resolve([]) : api.ordersOf(patientId)),
    [patientId]);
  const list = Array.isArray(past.data) ? past.data : [];

  /* 안 오신 적 — 지난 예약인데 내원 기록이 없는 것.
     ⚠ **「부도」라고 쓰지 않는다.** 창구에서 내원을 안 찍었을 수도 있어
       단정할 수 없다. 횟수와 날짜만 보이고 판단은 사람이 한다(6.1) */
  const today = ymd(new Date());
  const missed = list.filter(
    (r) => dayOf(r.scheduled_at) && dayOf(r.scheduled_at) < today && !r.visited_at);

  return (
    <div className="resv-aside">
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
                    <i>{r.visited_at ? "완료" : dayOf(r.scheduled_at) < today ? "안 옴" : "예정"}</i>
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

      <New cfg={cfg} at={pick?.at} order={order} rows={rows}
           onDone={onDone} onDate={onDate} />
    </div>
  );
}

function New({ cfg, at, order, rows, onDone, onDate }) {
  const api = cfg.api;
  const may = useCan("reception.reserve");

  const [q, setQ] = useState("");
  const [found, setFound] = useState(null);
  const [who, setWho] = useState(null);
  const [date, setDate] = useState(dayOf(at) || ymd(new Date()));
  const [time, setTime] = useState(timeOf(at) || "09:30");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);

  /* 달력에서 고른 자리가 바뀌면 날짜·시각을 따라간다. 고른 예약이 있으면
     그 환자도 같이 들어온다 — 화면을 옮기지 않는다는 것이 이 판의 규칙이다 */
  const slot = `${dayOf(at)}T${timeOf(at)}`;
  const [seen, setSeen] = useState(slot);
  if (at && slot !== seen) {
    setSeen(slot);
    setDate(dayOf(at));
    setTime(timeOf(at));
    if (order) {
      setWho({ patient_id: order.patient, name: order.patient_name,
               patient_number: order.patient_number });
    }
  }

  const clash = useMemo(() => {
    if (!who) return null;
    return rows.find((r) => String(r.patient) === String(who.patient_id)
      && dayOf(r.scheduled_at) === date) ?? null;
  }, [rows, who, date]);

  async function find(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setErr(null);
    try { setFound(await api.search(q.trim()) ?? []); }
    catch (e2) { setErr(e2); setFound([]); }
  }

  async function save() {
    setBusy(true); setErr(null); setOk(null);
    try {
      await api.reserve({ patient_id: who.patient_id,
                          scheduled_at: `${date}T${time}:00` });
      setOk(`${date} ${time}`);
      onDone();
    } catch (e2) { setErr(e2); }
    finally { setBusy(false); }
  }

  return (
    <Card title="새 예약" className="resv-new">
      {who ? (
        <p className="resv-who">
          <b>{who.name ?? `#${who.patient_id}`}</b>
          {who.patient_number && <span>{who.patient_number}</span>}
          <button type="button" className="note-x" aria-label="지우기"
                  onClick={() => { setWho(null); setFound(null); }}>×</button>
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

      {clash && (
        <p className="note err">같은 날 이미 예약이 있습니다 — {timeOf(clash.scheduled_at)}</p>
      )}
      {err && <p className="note err">{err.detail || err.message}</p>}
      {ok && <p className="hcard-k">{ok} 로 잡았습니다</p>}

      <div className="rowb">
        <Btn to={go.nursing.patients()}>환자 목록</Btn>
        <Btn kind="fill" onClick={save} {...may.attrs}
             disabled={!who || busy || !may.ok}>예약</Btn>
      </div>

      {/* ⚠ 서버에 취소·변경 경로가 없다(8장 7번). 화면에 적어 둔다 */}
      <p className="hcard-k">만든 예약은 여기서 못 지웁니다.</p>
    </Card>
  );
}
