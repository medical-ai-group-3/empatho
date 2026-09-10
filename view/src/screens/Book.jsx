import { useState } from "react";
import { api, onlyAnswered } from "../api";
import { useApi } from "../lib/useApi";
import Calendar from "../lib/Calendar";
import Choices from "../lib/Choices";
import { Body, Head } from "../lib/Screen";
import { fmtDateKey, fmtWhen } from "../lib/when";

/* 05 · 예약
 *
 * **환자는 날짜와 시간만 신청한다.** 어떤 검사를 받을지는 병원이 정한다 —
 * 신청 본문에 modality 가 없는 이유가 그것이고, 앱이 보내서도 안 된다.
 * 그래서 「확인 중」인 예약은 검사 종류 자리가 비어 있다. 오류가 아니다.
 *
 * 날짜를 고르는 곳은 이 화면 하나다. 홈의 달력은 보기만 한다.
 *
 * ── 왜 신청할 때 문진을 같이 받나 ─────────────────────────────
 * 병원은 requested → ordered 로 확정하면서 **검사 종류를 정한다.** 그때
 * 임신 여부 · 보형물 · 조영제 알레르기를 모르면 잡아 놓고 다시 연락해야
 * 한다 — 임신이면 촬영을 미루거나 초음파로 돌리고, 보형물이면 찍는 법이
 * 달라진다.
 *
 * 그래서 **그 셋만** 받는다. 가족력·폐경은 촬영 방법을 안 바꾸므로 검사
 * 전에 문진 화면에서 채우면 된다. 다섯을 다 받으면 예약이 문턱이 된다.
 *
 * 지난번 답이 실려 오므로 다시 쓰게 하지 않는다. 바뀐 것만 고치면 된다.
 */
export default function Book() {
  const { loading, data, error, reload } = useApi(() => api.reservations());

  return (
    <>
      <Head title="예약" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} reload={reload} />}
      </Body>
    </>
  );
}

function Inner({ d, reload }) {
  const [date, setDate] = useState(null);
  const [time, setTime] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);     // { ok:true|false, text }

  // 지난번 답을 출발점으로 삼는다 — 그대로면 아무것도 안 눌러도 된다
  const reqQ = d.required_questions ?? [];
  const [qa, setQa] = useState(() =>
    Object.fromEntries(reqQ.map((q) => [q.id, q.answer ?? null])));
  const qLeft = reqQ.filter((q) => !qa[q.id]).length;
  const hadAll = reqQ.length > 0 && reqQ.every((q) => q.answer);
  const [asking, setAsking] = useState(null); // 취소를 되묻는 중인 예약 id

  const slots = d.open_slots ?? [];
  // 열린 자리를 달력 표시로 바꾼다. 여러 달에 걸치면 첫 달만 보여준다 —
  // 지금 병원이 2주치만 열어 두고 있어서 그걸로 충분하다.
  const month = slots[0]?.date.slice(0, 7);
  const marks = slots.map((s) => ({
    date: s.date,
    kind: "open",
    label: `예약 가능 ${s.times.length}칸`,
  }));
  const times = slots.find((s) => s.date === date)?.times ?? [];

  function pickDate(key) {
    setDate(key);
    setTime(null);       // 날이 바뀌면 시간은 다시 골라야 한다
    setMsg(null);
  }

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.requestVisit({
        date, time,
        // 문진 화면이 보내는 것과 **같은 모양**이다. 두 곳이 달라지면
        // Django 가 한쪽만 읽게 된다
        questionnaire: { answers: onlyAnswered(qa) },
      });
      setDate(null);
      setTime(null);
      setMsg({ ok: true, text: r.detail || "방문 신청이 접수되었습니다" });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: e.detail || e.message });
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id) {
    setBusy(true);
    setMsg(null);
    try {
      await api.cancelVisit(id);
      setAsking(null);
      setMsg({ ok: true, text: "예약을 취소했습니다" });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: e.detail || e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {msg && (
        <div className={msg.ok ? "card accent" : "card flag"}>
          <span className="s">{msg.text}</span>
        </div>
      )}

      {/* ── 내 예약 ── */}
      <h3 className="sec">내 예약</h3>
      {/* 담당 주치의는 환자에게 붙는 값이라 예약마다가 아니라 위에 한 번만
          쓴다. 줄마다 같은 이름을 반복하면 읽는 사람이 «예약별로 다른가»
          하고 한 번 더 본다 */}
      {d.attending_name && (
        <p className="note">
          담당 주치의 <b>{d.attending_name}</b>
          {d.attending_dept ? ` · ${d.attending_dept}` : ""}
        </p>
      )}
      {d.items?.length ? (
        <div className="list">
          {d.items.map((r) => (
            <div key={r.exam_order_id} className="col">
              <div className="row">
                <span className="tx">
                  <b>{fmtWhen(r.scheduled_at)}</b>
                  <span>
                    {/* 확인 중이면 검사 종류가 아직 없다. 병원이 정한다 */}
                    {r.modality_label ?? r.hint ?? "검사 종류는 병원에서 정합니다"}
                    {r.place ? ` · ${r.place}` : ""}
                  </span>
                </span>
                <span className={r.order_status === "ordered" ? "pill new" : "pill read"}>
                  {r.status_label}
                </span>
              </div>

              {/* 취소는 되돌릴 수 없다. 한 번 더 묻는다 — 실수로 눌러서
                  자리를 잃으면 다시 잡는 것은 전화를 걸어야 한다 */}
              {r.can_cancel && (
                asking === r.exam_order_id ? (
                  <div className="ask">
                    <span>이 예약을 취소할까요?</span>
                    <button className="lnk warn" disabled={busy}
                            onClick={() => cancel(r.exam_order_id)}>
                      취소한다
                    </button>
                    <button className="lnk" disabled={busy}
                            onClick={() => setAsking(null)}>
                      그만두기
                    </button>
                  </div>
                ) : (
                  <div className="ask">
                    <button className="lnk"
                            onClick={() => setAsking(r.exam_order_id)}>
                      예약 취소
                    </button>
                  </div>
                )
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="note">예정된 예약이 없습니다.</p>
      )}

      {/* ── 방문 신청 ── */}
      <h3 className="sec">방문 신청</h3>
      {slots.length === 0 ? (
        <p className="note">
          지금 열린 자리가 없습니다. {d.hospital_phone} 로 문의해 주세요.
        </p>
      ) : (
        <>
          <Calendar month={month} marks={marks}
                    onPick={pickDate} selected={date} />

          {date && (
            <div className="card">
              <span className="k">{fmtDateKey(date)}</span>
              <div className="chips">
                {times.map((t) => (
                  <button key={t} type="button"
                          className={time === t ? "chip on" : "chip"}
                          aria-pressed={time === t}
                          onClick={() => setTime(t)}>
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 시간까지 고른 뒤에 나온다. 처음부터 펼쳐 두면 «예약이 이렇게
              길구나»로 보여서 시작을 안 한다 */}
          {date && time && reqQ.length > 0 && (
            <>
              <h3 className="sec">확인할 것 {reqQ.length}가지</h3>
              <p className="note">
                {hadAll
                  ? "지난번에 답하신 내용입니다. 바뀐 것만 고쳐 주세요."
                  : d.required_note}
              </p>
              {reqQ.map((q) => (
                <Choices key={q.id} q={q} value={qa[q.id]} disabled={busy}
                         onPick={(c) => setQa({ ...qa, [q.id]: c })} />
              ))}
            </>
          )}

          <button className="btn"
                  disabled={!date || !time || qLeft > 0 || busy}
                  onClick={submit}>
            {busy ? "보내는 중…"
                  : !date || !time ? "날짜와 시간을 골라 주세요"
                  : qLeft > 0 ? `확인할 것이 ${qLeft}가지 남았습니다`
                  : `${fmtDateKey(date)} ${time} 신청하기`}
          </button>
        </>
      )}

      <p className="note">
        {d.note}
        {d.hospital_phone && <> 문의 {d.hospital_phone}</>}
      </p>
    </>
  );
}
