import { useState } from "react";
import { reception as api } from "../../api";
import { Page, Card, Btn } from "../../lib/Page";
import { Body } from "../../lib/Body";
import { Chip, Table, Warn } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { can } from "../../perm";

/* 원무 4장 — 예약 확인 (앱 신청분)
 * ════════════════════════════════════════════════════════════════
 *
 * 3장과 하는 일이 다르다.
 *   3장  원무가 새로 만든다    POST /exam-orders/schedule
 *   4장  앱 신청을 확정한다    PATCH /exam-orders/{id}/confirm
 *
 * 거르는 조건 둘 —
 *   order_status = requested   아직 확정 안 된 신청
 *   visited_at   비어 있음     차 있으면 이미 창구에 온 환자다. 그 사람은
 *                              예약 확인이 아니라 간호 큐로 간다
 *
 * **원무가 정하는 것은 날짜와 시간뿐이다.**
 * 검사 종류(modality) · 목적(exam_purpose) · 지시의(ordered_by)를 받는 칸을
 * 두지 않는다 — 의학적 판단이라 유방외과 몫이다.
 *
 * ⚠ **확정하면 scheduled 다. ordered 가 아니다.** 검사 종류가 정해져야
 *   ordered 이고 그건 유방외과가 한다.
 *
 * ⚠ **지금 진짜 서버로는 확정이 안 된다.** ExamOrderConfirmView 가
 *   modalities · exam_purpose · ordered_by 를 필수로 받는다 —
 *
 *       if not modalities or not exam_purpose or not ordered_by_id:
 *           raise ApiError("VALIDATION_ERROR", …)
 *
 *   명세가 반대로 적혀 그대로 구현된 것이고, scheduled_at 만 받도록 바뀔
 *   예정이다. 그때까지 [예약 확인] 은 목업에서만 돈다. 화면은 바뀐 뒤의
 *   모양으로 지어 두었으니 서버가 오면 고칠 것이 없다.
 */

export default function Requests() {
  const [pick, setPick] = useState(null);       // 고른 exam_order_id

  const list = useApi(() => api.requests(), []);
  const rows = list.data ?? [];
  const chosen = rows.find((r) => r.exam_order_id === pick) ?? null;

  return (
    <Page
      crumb={["원무과", "예약 확인"]}
      title="예약 확인"
      sub="앱으로 들어온 예약 신청을 확정합니다. 날짜와 시간만 정합니다 — 검사 종류는 유방외과가 정합니다."
    >
      <div className="split wide">
        <div className="split-l">
          <Card title="예약 신청" right={<Chip>{rows.length}건</Chip>} pad={false}>
            <Body loading={list.loading} error={list.error} onRetry={list.reload}>
              {list.data && (
                <>
                  <Table
                    cols={COLS}
                    rows={rows.map(row)}
                    value={pick}
                    onPick={setPick}
                  />
                  <Missing rows={rows} />
                </>
              )}
            </Body>
          </Card>
        </div>

        <aside className="split-r">
          {chosen ? (
            <Confirm key={chosen.exam_order_id} order={chosen}
                     onDone={() => { setPick(null); list.reload(); }} />
          ) : (
            <div className="slot big">
              <b>왼쪽에서 신청을 고르세요</b>
              <span>고르면 환자 정보와 희망 시각을 보고 확정할 수 있습니다.</span>
            </div>
          )}
        </aside>
      </div>
    </Page>
  );
}

/* ── 목록 ────────────────────────────────────────────────────── */

const COLS = [
  { key: "who",  label: "환자" },
  { key: "sex",  label: "성별", w: "10%" },
  { key: "age",  label: "나이", w: "10%" },
  { key: "when", label: "희망 일시", w: "34%" },
];

const SEX = { female: "여", male: "남" };

const dayOf  = (s) => (s ? s.slice(0, 10) : "");
const timeOf = (s) => (s ? s.slice(11, 16) : "");

/* 이름이 없으면 번호로 떨어진다. ExamOrderSerializer 가 patient 를 숫자
   id 로만 주기 때문이다 — 캘린더와 같은 구멍이다 */
const who = (r) => r.patient_name || `#${r.patient}`;

function row(r) {
  const age = r.patient_birth_year
    ? new Date().getFullYear() - r.patient_birth_year
    : null;
  return {
    id: r.exam_order_id,
    who: <b>{who(r)}</b>,
    sex: SEX[r.patient_sex] ?? "—",
    age: age == null ? "—" : <span className="num">{age}</span>,
    when: r.scheduled_at
      ? <span className="num">{dayOf(r.scheduled_at)} {timeOf(r.scheduled_at)}</span>
      : <span className="dim">시각 없음</span>,
  };
}

function Missing({ rows }) {
  const lack = rows.some((r) => !r.patient_name || r.patient_sex == null);
  if (!lack) return null;
  return (
    <Warn>
      서버가 이름 · 성별 · 나이를 주지 않는 건은 「—」로 둡니다. 고르면 오른쪽에서 불러옵니다.
    </Warn>
  );
}

/* ── 확정 ────────────────────────────────────────────────────── */

/* 오른쪽 — 환자 정보 + 희망 시각 고치기 + [예약 확인].
 *
 * 환자 정보는 **따로 불러온다.** 신청 줄(ExamOrderSerializer)에는 patient 가
 * 숫자 id 로만 있어서 성별·생년월일·알레르기를 알 수 없다. GET /patients/{id}/
 * 는 지금도 제대로 도는 경로라 여기서 부른다.
 *
 * 알레르기는 **촬영 전에 반드시 보여야 하는 값**이라 눈에 띄게 세운다.
 */
function Confirm({ order, onDone }) {
  const [date, setDate] = useState(dayOf(order.scheduled_at));
  const [time, setTime] = useState(timeOf(order.scheduled_at) || "09:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const patient = useApi(() => api.detail(order.patient), [order.patient]);

  /* 환자가 낸 시각. 바뀐 것을 「무엇에서 무엇으로」로 보여주려고 들고 있는다 */
  const was = order.scheduled_at
    ? `${dayOf(order.scheduled_at)} ${timeOf(order.scheduled_at)}`
    : "";
  const moved = date !== dayOf(order.scheduled_at)
             || time !== (timeOf(order.scheduled_at) || "09:00");

  async function submit(e) {
    e.preventDefault();
    if (!date || !time || busy) return;
    setBusy(true); setError(null);
    try {
      const out = await api.confirm(order.exam_order_id, `${date}T${time}:00`);
      setDone(out);
    } catch (e2) {
      setError(e2);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Card title="예약 확인">
        <div className="slot ok" role="status">
          <b>{date} {time} 로 확정했습니다</b>
          <span>
            오더 {done.exam_order_id ?? order.exam_order_id} ·
            상태 {done.order_status ?? "scheduled"} · 검사 종류는 유방외과가 정합니다
          </span>
        </div>
        <div className="save-b">
          <Btn kind="fill" onClick={onDone}>다음 신청</Btn>
        </div>
      </Card>
    );
  }

  return (
    <Card title="예약 확인">
      <form onSubmit={submit}>
        <Body loading={patient.loading} error={patient.error} onRetry={patient.reload}>
          {patient.data && (
            <>
              <dl className="kv">
                <dt>환자번호</dt>
                <dd className="num">{patient.data.patient_number}</dd>
                <dt>이름</dt><dd>{patient.data.pii?.name ?? who(order)}</dd>
                <dt>생년월일</dt>
                <dd className="num">{patient.data.pii?.birth_date ?? "—"}</dd>
                <dt>성별</dt><dd>{SEX[patient.data.sex] ?? "—"}</dd>
                <dt>전화번호</dt>
                <dd className="num">{patient.data.pii?.phone ?? "—"}</dd>
              </dl>
              {patient.data.has_allergy && (
                <Warn>
                  조영제 알레르기 있음{patient.data.allergy_note
                    ? ` — ${patient.data.allergy_note}` : ""}
                </Warn>
              )}
            </>
          )}
        </Body>

        <dl className="kv">
          <dt>환자 희망</dt>
          <dd className="num">
            {order.scheduled_at
              ? `${dayOf(order.scheduled_at)} ${timeOf(order.scheduled_at)}`
              : "시각 없이 신청"}
          </dd>
        </dl>

        <div className="fields">
          <label className="field">
            <span>확정 날짜</span>
            <input type="date" value={date} disabled={busy}
                   onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="field">
            <span>확정 시간</span>
            <input type="time" value={time} step={600} disabled={busy}
                   onChange={(e) => setTime(e.target.value)} />
          </label>
        </div>

        {/* **회색 한 줄로 두지 않는다.** 시각을 바꿔 확정하면 환자에게 알림이
            나가고 되돌리기 어렵다. 색을 새로 만들지 않고 점선 상자로만 세운다 */}
        {moved && (
          <div className="slot" role="status">
            <b>환자 희망 시각과 다릅니다</b>
            <span>
              {was || "시각 없이 신청"} → <b>{date} {time}</b>
            </span>
            <span>확정하면 환자에게 바뀐 시각으로 알림이 갑니다.</span>
          </div>
        )}

        <div className="save-b">
          <Btn kind="fill" type="submit"
               disabled={!date || !time || busy || !can("reception.confirm")}>
            {busy ? "확정하는 중…" : "예약 확인"}
          </Btn>
        </div>

        {error && <Failed error={error} onDone={onDone} />}
      </form>
    </Card>
  );
}

/* 확정 실패.
   **409 는 따로 적는다** — 「이미 확정됨」은 고장이 아니라 남이 먼저 처리한
   것이라, 오류처럼 보이면 창구에서 다시 누르게 된다 */
function Failed({ error, onDone }) {
  if (error.code === "ALREADY_CONFIRMED") {
    return (
      <div className="slot" role="status">
        <b>이미 확정된 신청입니다</b>
        <span>다른 사람이 먼저 처리했거나, 두 번 눌렸습니다.</span>
        <Btn onClick={onDone}>목록 새로 받기</Btn>
      </div>
    );
  }
  return (
    <div className="slot bad" role="alert">
      <b>{error.detail || error.message}</b>
      <span>{error.code}{error.traceId && <> · {error.traceId}</>}</span>
    </div>
  );
}
