import { useState } from "react";
import { Page, Btn } from "../../lib/Page";
import { Body, Empty } from "../../lib/Body";
import { Chip, useCan } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { can } from "../../perm";
import { go, DESK } from "../../nav";
import * as H from "../../dept/home";

/* 접수 — 오늘 현황판 위, 내원 대기 줄 아래
 * ════════════════════════════════════════════════════════════════
 *
 * 배치는 `docs/mockup/Reception-오늘현황판.html` 과
 * `docs/mockup/Nursing-내원대기.html` 이 정한다. 원무과와 간호과가 한 과가
 * 되면서 두 목업이 한 화면에 쌓인다 — **위는 오늘 현황판, 아래는 내원 대기.**
 *
 *   ┌ 접수 ─────────────────────────────────────────────┐
 *   │ 이름 · 전화 · 생년월일  [검색] [+ 신환 등록]         │
 *   ├───────────────────────────────────────────────────┤
 *   │ 접수 대기 │ 간호·문진 │ 검사 진행 │ 외래 진료 │ 종결 │  ← 칸 다섯
 *   ├───────────────────────────────────────────────────┤
 *   │ 내원 대기 줄 — 번호 · 이름 · 나이 성별 ···· 접수 시각 │
 *   └───────────────────────────────────────────────────┘
 *
 * ⚠ **경과 시간을 안 쓴다.** 목업 줄 끝의 `(38′)` `1h12m` 과 칸 머리의
 *   「평균 14분 · 최장 38분」은 서버가 주지 않는 값이다. 요청 시각만 적는다.
 *
 * ⚠ **칸을 카드로 띄우지 않는다.** 목업은 칸마다 테두리를 두르지만 그러면
 *   칸마다 안쪽 여백이 또 생긴다. 상자 하나를 1px 선으로 가른다(5.1).
 *
 * ⚠ **stage 는 서버가 쓰는 말 그대로** 둔다. 옮겨 부르면 서버가 단계를
 *   하나 늘렸을 때 그 줄이 어느 칸에도 안 들어간다.
 */

/* `/patients/today-status` 의 stage 가 곧 칸이다. 뷰가 다섯 값을 낸다 —
   앞 넷은 이름을 지어 주고, 그 밖(order_status 가 그대로 온 것)은 종결 칸 */
const BOARD = [
  { key: "checkin", title: "접수 대기", stage: "접수 대기" },
  { key: "nurse", title: "간호 · 문진", stage: null },
  { key: "exam", title: "검사 진행",
    stage: ["영상의학과 대기", "영상의학과 촬영중", "AI 분석중"] },
  { key: "clinic", title: "외래 진료", stage: null },
  { key: "closed", title: "오늘 종결", stage: ["completed", "cancelled"] },
];

export default function Intake({ cfg }) {
  const api = cfg.api;

  const today = useApi(() => api.todayStatus(), []);
  const waiting = useApi(() => api.waitingArrived(), []);

  const rows = H.rows(today.data);
  const queue = H.rows(waiting.data);

  const again = () => { today.reload(true); waiting.reload(true); };

  return (
    <Page crumb={[cfg.name, "접수"]} title="접수" className="intake-page"
          right={(
            <Btn to={go.nursing.patients()}>환자 목록 · 예약</Btn>
          )}>
      <Find api={api} go={cfg.go} onDone={again} />

      <Body loading={today.loading && !today.data} error={today.error}
            onRetry={today.reload}>
        <Board rows={rows} />
      </Body>

      <Waiting state={waiting} rows={queue} />
    </Page>
  );
}

/* ── 찾아서 접수 ───────────────────────────────────────────────
 * 찾아서 확인한 뒤 누른다. **자동으로 접수하지 않는다** — 동명이인이
 * 있어서 한 명이어도 사람이 골라야 한다.
 */
function Find({ api, go: goTo, onDone }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const may = useCan("reception.checkin");

  async function find(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setErr(null);
    try { setFound(await api.search(q.trim()) ?? []); }
    catch (e2) { setErr(e2); setFound([]); }
  }

  async function take(p) {
    setBusy(p.patient_id);
    setErr(null);
    try {
      await api.checkIn({ patient_id: p.patient_id });
      setFound((list) => list.filter((r) => r.patient_id !== p.patient_id));
      onDone();
    } catch (e2) { setErr(e2); }
    finally { setBusy(null); }
  }

  return (
    <section className="intake-find-box">
      <form className="intake-find" onSubmit={find}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="이름 · 전화 · 생년월일" aria-label="환자 검색" />
        <button className="btn dark" type="submit">검색</button>
        {can("reception.patient.create")
          && <Btn to={goTo.patients()}>+ 신환 등록</Btn>}
      </form>

      {err && <p className="note err">{err.detail || err.message}</p>}
      {found?.length === 0 && !err && (
        <p className="hcard-k hpad">찾는 환자가 없습니다</p>
      )}

      {(found ?? []).map((p) => (
        <div className="ifound" key={p.patient_id}>
          <span className="ifound-tx">
            <span className="ifound-1"><b>{p.name}</b></span>
            <span className="ifound-2">
              {[p.patient_number, p.birth_date, p.phone].filter(Boolean).join(" · ")}
            </span>
          </span>
          <Btn kind="fill" onClick={() => take(p)} {...may.attrs}
               disabled={busy === p.patient_id || !may.ok}>접수</Btn>
        </div>
      ))}
    </section>
  );
}

/* ── 위 — 오늘 현황판 ─────────────────────────────────────────
 * 칸을 가로로 나열하고 단계마다 하나씩. 환자가 왼쪽에서 오른쪽으로 흐른다.
 *
 * ⚠ **값이 없어 못 채우는 칸이 둘이다.** 「간호 · 문진」과 「외래 진료」는
 *   `today-status` 의 stage 에 그 단계가 없다(뷰가 접수·영상 쪽만 가른다).
 *   **칸을 없애지 않는다** — 없애면 흐름이 끊겨 보이고, 나중에 stage 가
 *   늘었을 때 자리를 다시 찾아야 한다.
 */
function Board({ rows }) {
  const bucket = (col) => {
    if (!col.stage) return [];
    const want = Array.isArray(col.stage) ? col.stage : [col.stage];
    return rows.filter((r) => want.includes(r.stage));
  };

  return (
    <div className="board">
      {BOARD.map((col) => {
        const here = bucket(col);
        return (
          <section className="bcol" key={col.key}>
            <header className="bcol-h">
              <i className="hdot" aria-hidden="true" />
              <b>{col.title}</b>
              <em>{here.length}</em>
            </header>
            <div className="bcol-b">
              {here.length === 0
                ? (
                  <p className="hcard-k hpad">
                    {col.stage ? "없습니다" : "서버가 이 단계를 아직 안 나눕니다"}
                  </p>
                )
                : here.map((r) => <BRow key={r.exam_order_id ?? r.patient_id} row={r} />)}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/* 환자 줄 — 세 줄(5.2)
 *
 *   시연환자03  62 · 여  [재진] ········ 13:54
 *   P-0003   앱 접수 · 확인 필요
 *   ● 촬영  ◐ AI  ○ 판독
 *
 * ⚠ 줄 끝의 경과 시간 `(38′)` 은 안 쓴다.
 * ⚠ 둘째 줄이 비는 과가 있다 — `today-status` 응답이 네 칸뿐이라
 *   환자번호·나이·성별이 안 온다(8장 9번).
 */
function BRow({ row }) {
  const steps = H.stageSteps(row.stage);
  return (
    <article className="brow">
      <div className="brow-1">
        <b>{H.nameOf(row)}</b>
        {H.who(row) && <span className="brow-who">{H.who(row)}</span>}
        {row.visit_type && <Chip>{row.visit_type}</Chip>}
        <span className="home-fill" />
        {H.at(row.visited_at) && <time>{H.at(row.visited_at)}</time>}
      </div>
      {(H.noOf(row) || row.stage) && (
        <p className="brow-2">
          {H.noOf(row) && <i>{H.noOf(row)}</i>}
          <span>{row.stage}</span>
        </p>
      )}
      {steps && <Steps steps={steps} />}
    </article>
  );
}

const DOT = { done: "●", going: "◐", none: "○" };

function Steps({ steps }) {
  return (
    <p className="brow-3">
      {steps.map(([name, state]) => (
        <span key={name} className={`pstep ${state}`}
              title={state === "unsure" ? "이 목록으로는 알 수 없습니다" : undefined}>
          <i aria-hidden="true">{DOT[state] ?? ""}</i>{name}
        </span>
      ))}
    </p>
  );
}

/* ── 아래 — 내원 대기 줄 ──────────────────────────────────────
 * `docs/mockup/Nursing-내원대기.html` 의 줄 모양이다. 번호 · 이름 ·
 * 나이 성별 ···· 접수 시각 / 둘째 줄에 구분 칩과 문진 상태.
 *
 * 접수 화면에서 [접수] 를 누른 환자가 **화면을 옮기지 않아도** 여기 줄에
 * 붙는다 — 한 과가 됐으니 탭을 건너뛸 이유가 없다(6.1).
 */
function Waiting({ state, rows }) {
  return (
    <section className="wq">
      <header className="bcol-h">
        <i className="hdot" aria-hidden="true" />
        <b>내원한 대기 환자</b>
        <em>{rows.length}</em>
        <span className="home-fill" />
        <span className="hcard-k">접수 순 · 순서 고정</span>
      </header>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}
            empty={rows.length === 0 && <Empty title="내원한 대기 환자가 없습니다" />}>
        <div className="wq-b">
          {rows.map((r, i) => (
            <article className="wrow" key={r.exam_order_id ?? i}>
              <i className="wrow-n">{i + 1}</i>
              <span className="wrow-tx">
                <span className="wrow-1">
                  <b>{H.nameOf(r)}</b>
                  {H.who(r) && <span>{H.who(r)}</span>}
                  <span className="home-fill" />
                  {H.at(r.visited_at) && <time>{H.at(r.visited_at)} 접수</time>}
                </span>
                <span className="wrow-2">
                  {H.noOf(r) && <i>{H.noOf(r)}</i>}
                  {r.visit_type && <Chip>{r.visit_type}</Chip>}
                  <span>{r.questionnaire ? "문진 완료 · 배정 대기" : "문진 대기"}</span>
                </span>
              </span>
              <Btn to={go.nursing.waiting()}>문진 · 배정</Btn>
            </article>
          ))}
        </div>
      </Body>
    </section>
  );
}

/* 이 화면은 접수 열쇠든 간호 열쇠든 하나면 연다 — 한 과다(nav.js 의 DESK).
   쓰는 동작(접수·등록)은 위에서 제 열쇠로 따로 잠근다 */
Intake.need = DESK;
