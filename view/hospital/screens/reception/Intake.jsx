import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Page, Btn } from "../../lib/Page";
import { Body } from "../../lib/Body";
import { Chip, useCan } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go, DESK } from "../../nav";
import * as H from "../../dept/home";
import NursingWaiting from "../../dept/nursing/screens/Waiting";
import Register from "./Register";

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
 *   │ 내원 대기 화면 통째로 — 문진 · 유방외과 배정          │
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

/* 칸 다섯. 무엇으로 채우는지가 칸마다 다르다 —
 *
 *   접수 대기   내원 대기 목록 중 문진이 아직 없는 사람
 *   간호 · 문진  내원 대기 목록 중 문진을 낸 사람(배정 차례)
 *   검사 진행   today-status 의 영상 쪽 stage
 *   외래 진료   today-status 의 stage_code outpatient — 간호가 이 오더를
 *               유방외과로 보냈고(handed_at) 아직 검사·종결로 안 넘어간 사람
 *   오늘 종결   today-status 의 completed · cancelled
 *
 * ⚠ 앞 둘은 today-status 가 아니라 **아래 내원 대기와 같은 목록**을 쓴다.
 *   today-status 는 둘을 「접수 대기」 하나로 뭉쳐 주고, 따로 세면 아래
 *   목록과 숫자가 어긋난다. 보낸 사람은 앞 둘에서 빠지고 외래 칸으로 간다. */
const EXAM_STAGE = ["영상의학과 대기", "영상의학과 촬영중", "AI 분석중"];
const CLOSED_STAGE = ["completed", "cancelled"];

const BOARD = [
  { key: "checkin", title: "접수 대기" },
  { key: "nurse", title: "간호 · 문진" },
  { key: "exam", title: "검사 진행" },
  { key: "clinic", title: "외래 진료" },
  { key: "closed", title: "오늘 종결" },
];

/* 아래 내원 대기와 같은 박자로 다시 부른다 — 보내면 위 칸도 바로 옮겨야 한다 */
const POLL_MS = 7000;

export default function Intake({ cfg }) {
  const api = cfg.api;

  const [tick, setTick] = useState(0);
  const today = useApi(() => api.todayStatus(), [tick]);
  const arrived = useApi(() => H.soft(api.waitingArrived()), [tick]);
  const rows = H.rows(today.data);
  const again = () => setTick((n) => n + 1);

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => clearInterval(t);
  }, []);

  return (
    <Page crumb={[cfg.name, "접수"]} title="접수" className="intake-page"
          right={(
            <Btn to={go.nursing.patients()}>환자 목록 · 예약</Btn>
          )}>
      <Find api={api} onDone={again} />

      <Body loading={today.loading && !today.data} error={today.error}
            onRetry={today.reload}>
        <Board rows={rows} arrived={H.rows(arrived.data)} />
      </Body>

      {/* 아래는 **내원 대기 화면 통째로**다. 목록만 다시 그리면 문진·배정을
          할 데가 없어진다 — 화면 줄에서 뺀 자리가 여기다(nav.js) */}
      <div className="intake-wq">
        <NursingWaiting cfg={cfg} embedded />
      </div>
    </Page>
  );
}

/* ── 찾아서 접수 ───────────────────────────────────────────────
 * 찾아서 확인한 뒤 누른다. **자동으로 접수하지 않는다** — 동명이인이
 * 있어서 한 명이어도 사람이 골라야 한다.
 */
function Find({ api, onDone }) {
  /* 홈의 「안 오심 · 오늘 예약」 줄은 ?find= 를 달고 온다 — 그 사람을 찾아
     둔 채로 연다. **접수는 여전히 사람이 누른다**(동명이인) */
  const [params] = useSearchParams();
  const asked = params.get("find") ?? "";
  const [q, setQ] = useState(asked);
  const [found, setFound] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [reg, setReg] = useState(false);
  const [ok, setOk] = useState(null);
  /* ⚠ 간호 계정도 접수한다 — 한 과다(Patients.jsx 의 integrated 와 같은
     규칙). reception.checkin 만 보면 간호 열쇠만 가진 사람은 [접수] 가 늘
     잠겨 있었다. 서버도 이제 간호에게 원무 권한을 준다 */
  const may = useCan(["reception.checkin", "nursing.waiting.view"]);

  useEffect(() => {
    if (!asked) return;
    api.search(asked).then((r) => setFound(r ?? [])).catch((e2) => { setErr(e2); setFound([]); });
  }, [api, asked]);

  async function find(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setErr(null);
    setOk(null);
    try { setFound(await api.search(q.trim()) ?? []); }
    catch (e2) { setErr(e2); setFound([]); }
  }

  async function take(p) {
    setBusy(p.patient_id);
    setErr(null);
    try {
      await api.checkIn({ patient_id: p.patient_id });
      setFound((list) => list.filter((r) => r.patient_id !== p.patient_id));
      /* 줄이 조용히 사라지기만 하면 됐는지 모른다 — 어디로 갔는지 적는다 */
      setOk(`${p.name ?? "환자"} 님을 접수했습니다 — 아래 내원 대기에 올라갑니다`);
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
        {/* 창구에서 바로 만든다 — 환자 목록으로 넘기면 접수하러 다시 와야
            한다. 만든 사람은 아래 찾은 줄에 올라와 [접수] 만 누르면 된다 */}
        <Btn type="button" onClick={() => setReg(true)}>+ 신규 등록</Btn>
      </form>

      {reg && (
        <Register onClose={() => setReg(false)}
                  onDone={(p, how) => {
                    setReg(false); setErr(null); setFound([p]);
                    /* 새로 만든 건지 있던 사람인지 알려 준다 — 모르면 창구에서
                       「방금 만든 게 맞나」를 다시 찾아본다 */
                    setOk(how === "exists"
                      ? "이미 등록된 분입니다 — 아래 줄에서 [접수] 를 누르세요"
                      : "등록했습니다 — 아래 줄에서 [접수] 를 누르세요");
                  }} />
      )}

      {err && <p className="note err">{err.detail || err.message}</p>}
      {ok && !err && <p className="hcard-k hpad" role="status">{ok}</p>}
      {found?.length === 0 && !err && !ok && (
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
 *   → 09-27 서버가 stage_code(nursing · outpatient …)를 더했다. 「외래 진료」
 *     칸은 이제 그것도 읽는다(아래 clinic).
 *   **칸을 없애지 않는다** — 없애면 흐름이 끊겨 보이고, 나중에 stage 가
 *   늘었을 때 자리를 다시 찾아야 한다.
 */
function Board({ rows, arrived }) {
  /* 보낸 사람은 서버가 이미 뺐다(waitingArrived 의 handed=none) */
  const waiting = arrived;
  const moved = (r) => EXAM_STAGE.includes(r.stage) || CLOSED_STAGE.includes(r.stage);

  const cols = {
    checkin: waiting.filter((r) => !r.questionnaire)
      .map((r) => ({ ...r, stage: "문진 대기" })),
    nurse: waiting.filter((r) => r.questionnaire)
      .map((r) => ({ ...r, stage: "문진 완료 · 배정 대기" })),
    exam: rows.filter((r) => EXAM_STAGE.includes(r.stage)),
    /* ⚠ 09-27 — outpatient 는 **오더의 handed_at** 으로 갈린다(서버). 예전
       처럼 주치의 유무로 보지 않아 재진 환자가 보내기 전에 여기 오지 않는다 */
    clinic: rows.filter((r) => !moved(r)
      && (r.stage_code === "outpatient" || r.handed_at))
      .map((r) => ({ ...r, stage: "유방외과 진료 대기" })),
    closed: rows.filter((r) => CLOSED_STAGE.includes(r.stage)),
  };

  return (
    <div className="board">
      {BOARD.map((col) => {
        const here = cols[col.key];
        return (
          <section className="bcol" key={col.key}>
            <header className="bcol-h">
              <i className="hdot" aria-hidden="true" />
              <b>{col.title}</b>
              <em>{here.length}</em>
            </header>
            <div className="bcol-b">
              {here.length === 0
                ? <p className="hcard-k hpad">대기 중인 환자가 없습니다</p>
                : here.map((r) => <BRow key={r.exam_order_id ?? r.id ?? r.patient_id} row={r} />)}
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

/* 이 화면은 접수 열쇠든 간호 열쇠든 하나면 연다 — 한 과다(nav.js 의 DESK).
   쓰는 동작(접수·등록)은 위에서 제 열쇠로 따로 잠근다 */
Intake.need = DESK;
