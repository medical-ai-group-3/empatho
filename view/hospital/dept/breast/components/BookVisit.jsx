import { useRef, useState } from "react";
import { reception } from "../../../api";
import * as H from "../../home";

/* 재진 · 추적 예약 — 진료를 마친 자리에서 바로 다음 방문을 잡는다.
 *
 * 원무 예약과 같은 경로다(POST /exam-orders/schedule — patient_id ·
 * scheduled_at 둘뿐). 검사 종류는 안 보낸다 — 서버가 안 받는다.
 * ⚠ 같은 날 취소 안 된 오더가 있으면 서버가 409 DUPLICATE_RESERVATION 을
 *   준다(core/views/reception.py _refuse_same_day). 그 말을 그대로 옮기고
 *   날을 바꾸게 한다 — 조용히 삼키면 예약이 잡힌 줄 안다.
 * ⚠ 한 번 누르는 사이 두 번 가지 않게 sending 으로 막는다(Reservations.jsx
 *   에서 같은 날 예약이 두 벌 섰던 일). */
const QUICK = [
  ["1주", 7], ["2주", 14], ["1개월", 30], ["3개월", 91], ["6개월", 182], ["1년", 365],
];

const after = (days) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return H.iso(d);
};

export function BookForm({ patient, suggest = 14, onDone, onSkip, skipLabel = "나중에" }) {
  const [date, setDate] = useState(() => after(suggest));
  const [time, setTime] = useState("10:00");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);
  const sending = useRef(false);

  async function book() {
    if (sending.current || !date || !time) return;
    sending.current = true;
    setBusy(true); setErr(null);
    try {
      /* 시간대를 안 붙인다 — 서버가 KST 로 읽는다(reception/Patients.jsx 와 같다) */
      const order = await reception.reserve({
        patient_id: patient.patient_id, scheduled_at: `${date}T${time}:00`,
      });
      setOk(`${date} ${time} 재진 예약을 잡았습니다`);
      onDone?.(order);
    } catch (e) {
      setErr(e?.code === "DUPLICATE_RESERVATION" || e?.status === 409
        ? `${date} 에 이미 예약(또는 내원)이 있습니다 — 다른 날을 골라 주세요`
        : (e?.detail || e?.message || "예약하지 못했습니다"));
    } finally { setBusy(false); sending.current = false; }
  }

  return (
    <div className="bf-book">
      <div className="bf-book-q" role="group" aria-label="빠른 날짜">
        {QUICK.map(([k, d]) => (
          <button type="button" key={k}
                  className={`bf-chip${date === after(d) ? " on" : ""}`}
                  onClick={() => { setDate(after(d)); setOk(null); setErr(null); }}>
            {k} 뒤
          </button>
        ))}
      </div>
      <div className="bf-book-f">
        <label>
          <span>날짜</span>
          <input type="date" value={date} min={after(0)}
                 onChange={(e) => { setDate(e.target.value); setOk(null); }} />
        </label>
        <label>
          <span>시각</span>
          <input type="time" value={time} step={600}
                 onChange={(e) => { setTime(e.target.value); setOk(null); }} />
        </label>
        <span className="home-fill" />
        {/* line ghost — .breast 안(팝업 · 치료 방침)에서는 ghost 가, 밖에서는
            line 이 잡힌다. 두 판이 같은 이름을 다른 뜻으로 쓴다(breast.css 머리) */}
        {onSkip && <button type="button" className="btn line ghost" onClick={onSkip}>{skipLabel}</button>}
        <button type="button" className="btn fill" onClick={book}
                disabled={busy || !date || !time || Boolean(ok)}>
          {busy ? "예약하는 중…" : ok ? "예약됨" : "재진 예약"}
        </button>
      </div>
      {err && <p className="note err">{err}</p>}
      {ok && <p className="hcard-k" role="status">{ok}</p>}
    </div>
  );
}

/* 팝업판 — 대기 환자의 「재진 예약」 · 진료 완료 뒤 */
export default function BookVisitModal({ patient, suggest, title = "재진 예약", lead = null,
                                         onClose, onDone }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title} — {patient.name ?? H.nameOf(patient)}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {lead && <p className="bf-lead">{lead}</p>}
          <BookForm patient={patient} suggest={suggest}
                    onDone={onDone} onSkip={onClose} skipLabel="닫기" />
        </div>
      </div>
    </div>
  );
}
