import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Page, Btn } from "../../lib/Page";
import { useCan } from "../../lib/Parts";
import { go, DESK } from "../../nav";
import NursingWaiting from "../../dept/nursing/screens/Waiting";
import Register from "./Register";
import * as H from "../../dept/home";

/* 접수 — 찾기 위, 내원 대기 아래
 * ════════════════════════════════════════════════════════════════
 *
 *   ┌ 접수 ─────────────────────────────────────────────┐
 *   │ 이름 · 전화 · 생년월일  [검색] [+ 신환 등록]         │
 *   ├───────────────────────────────────────────────────┤
 *   │ 내원 대기 화면 통째로 — 문진 · 유방외과 배정          │
 *   └───────────────────────────────────────────────────┘
 *
 * ⚠ 09-28 **오늘 현황판(접수 대기 · 간호·문진 · 검사 진행 · 외래 진료)을
 *   홈으로 옮겼다**(lib/StageBoard.jsx). 「지금 누가 어디 있나」는 홈에서
 *   한눈에 보고, 이 화면은 찾고 · 문진 보고 · 배정하는 자리로 남긴다.
 *   현황판 줄을 누르면 ?order= 를, 홈 「검체」 줄은 ?tab=specimen 을 달고
 *   이리 온다 — 둘 다 아래 내원 대기(Waiting.jsx)가 읽는다.
 */
export default function Intake({ cfg }) {
  const api = cfg.api;
  /* 창구에서 예약을 볼 때는 거의 「오늘 누가 오나」다 — 오늘 하루로 연다.
     ⚠ 예전 「환자 목록 · 예약」은 환자 목록으로 갔는데 거기엔 이제 예약을
       잡는 자리가 없다(중복 막이가 없는 두 번째 길이라 뺐다) */
  const today = H.iso(new Date());

  return (
    <Page crumb={[cfg.name, "접수"]} title="접수" className="intake-page"
          right={(
            <span className="rowb">
              <Btn to={go.nursing.patients()}>환자 목록</Btn>
              <Btn to={`${go.nursing.reservations()}?date=${today}`}>예약 관리</Btn>
            </span>
          )}>
      {/* 접수하면 아래 내원 대기가 7초 박자로 스스로 다시 불러 올린다 —
          여기서 다시 마운트하면 고르던 사람이 풀린다 */}
      <Find api={api} onDone={() => {}} />

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
      setOk(`${p.name ?? "환자"} 님을 접수했습니다 — 아래 내원 대기에 표시됩니다`);
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
                      ? "이미 등록된 환자입니다 — 아래 목록에서 [접수]를 누르세요"
                      : "등록했습니다 — 아래 목록에서 [접수]를 누르세요");
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

/* 이 화면은 접수 열쇠든 간호 열쇠든 하나면 연다 — 한 과다(nav.js 의 DESK).
   쓰는 동작(접수·등록)은 위에서 제 열쇠로 따로 잠근다 */
Intake.need = DESK;
