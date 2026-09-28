import { useRef, useState } from "react";
import { nursing } from "../../../api";
import { useApi } from "../../../lib/useApi";
import * as H from "../../home";

/* 추적 회차 — 진료를 마친 자리에서 다음 추적(6 · 12 · 24개월)을 건다.
 *
 * 09-28 서버가 유방외과에게도 POST /followups/new 를 열었다. 전에는 BI-RADS 3
 * 으로 끝낸 환자의 회차를 간호과가 추적 관리에서 따로 만들어야 했다 —
 * 결정한 사람이 그 자리에서 못 걸었다.
 *
 *   · 몸통은 간호 추적 관리(dept/nursing/screens/Followups.jsx 의 Make)와
 *     같다 — patient_id · round_no · due_at. 간격 칸이 서버에 없어서 단추가
 *     날짜를 계산해 넣는다
 *   · 회차 번호는 **이 환자의 마지막 회차 + 1** 이다. 목록을 못 받으면 번호를
 *     정할 수 없어서 칸을 통째로 감춘다 — 같은 번호가 둘 서는 것보다 낫다
 *
 * ⚠ **서버가 안 열어 준 배포본에서는 감춘다.** 목록이 403 · 404 면 처음부터
 *   안 그리고, 만들기가 403 · 404 면 폼을 거두고 한 줄로 까닭을 적는다.
 *   눌러 보고서야 안 되는 단추를 남겨 두지 않는다.
 * ⚠ 한 번 누르는 사이 두 번 가지 않게 sending 으로 막는다(BookVisit 과 같다). */
const MONTHS = [6, 12, 24];

function plus(months) {
  const d = new Date();
  d.setMonth(d.getMonth() + months);
  return H.iso(d);
}

const denied = (e) => e?.status === 403 || e?.status === 404;
const ROUND = { stable: "변화 없음", changed: "변화 있음", no_show: "미내원" };

export default function FollowupRounds({ patient, months = 6 }) {
  const pid = patient.patient_id;
  const list = useApi(() => nursing.followupsOf(pid), [pid]);
  const [due, setDue] = useState(() => plus(months));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);
  const [locked, setLocked] = useState(false);
  const sending = useRef(false);

  if (denied(list.error)) return null;
  if (list.error) {
    return <p className="note">추적 회차를 불러오지 못했습니다 — 간호과 추적 관리에서 확인해 주세요.</p>;
  }
  if (!list.data) return <p className="hcard-k">추적 회차를 불러오는 중…</p>;

  const rows = H.rows(list.data);
  const rounds = rows.filter((r) => r.status !== "candidate")
    .sort((a, b) => (a.round_no ?? 0) - (b.round_no ?? 0));
  const candidate = rows.some((r) => r.status === "candidate");
  const next = rounds.reduce((m, r) => Math.max(m, r.round_no ?? 0), 0) + 1;
  const open = rounds.filter(H.openFollowup);

  async function make() {
    if (sending.current || !due) return;
    sending.current = true;
    setBusy(true); setErr(null);
    try {
      /* due_at 은 DateTimeField 다 — 간호 추적 관리와 같이 오전 9시로 */
      await nursing.createFollowup({ patient_id: pid, round_no: next, due_at: `${due}T09:00:00` });
      setOk(`${next}회차 · ${due} 추적을 등록했습니다 — 간호과 추적 관리에 표시됩니다`);
      list.reload(true);
    } catch (e) {
      if (denied(e)) setLocked(true);
      else setErr(e?.detail || e?.message || "추적 회차를 등록하지 못했습니다");
    } finally { setBusy(false); sending.current = false; }
  }

  return (
    <div className="bf-fup">
      <p className="bf-fup-h">
        <b>추적 회차</b>
        <span className="hcard-k">
          {rounds.length ? `${rounds.length}회차까지 있음` : candidate ? "BI-RADS 3 추적 대상 · 회차 없음" : "아직 없음"}
        </span>
      </p>
      {rounds.length > 0 && (
        <ul className="bf-fup-list">
          {rounds.map((r) => (
            <li key={r.followup_id ?? r.round_no}>
              <b>{r.round_no}회차</b>
              <span>{r.due_at ? String(r.due_at).slice(0, 10) : "예정일 없음"}</span>
              <span className="hcard-k">
                {H.openFollowup(r) ? "진행 중" : "종결"}
                {r.round_result ? ` · ${ROUND[r.round_result] ?? r.round_result}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      {locked ? (
        <p className="hcard-k" role="status">이 계정으로는 추적 회차를 만들 수 없습니다 — 간호과 추적 관리에서 만듭니다.</p>
      ) : (
        <>
          <div className="bf-book-q" role="group" aria-label="추적 간격">
            {MONTHS.map((m) => (
              <button type="button" key={m} className={`bf-chip${due === plus(m) ? " on" : ""}`}
                      onClick={() => { setDue(plus(m)); setOk(null); setErr(null); }}>
                +{m}개월
              </button>
            ))}
          </div>
          <div className="bf-book-f">
            <label>
              <span>추적 예정일</span>
              <input type="date" value={due} min={plus(0)}
                     onChange={(e) => { setDue(e.target.value); setOk(null); }} />
            </label>
            <span className="home-fill" />
            <button type="button" className="btn line ghost" onClick={make}
                    disabled={busy || !due || Boolean(ok)}>
              {busy ? "등록하는 중…" : ok ? "등록했습니다" : `${next}회차 등록`}
            </button>
          </div>
          {open.length > 0 && !ok && (
            <p className="hcard-k">
              진행 중인 회차가 있습니다({open.map((r) => `${r.round_no}회차`).join(" · ")}) — 그 뒤 회차로 만듭니다.
            </p>
          )}
          {err && <p className="note err">{err}</p>}
          {ok && <p className="hcard-k" role="status">{ok}</p>}
        </>
      )}
    </div>
  );
}
