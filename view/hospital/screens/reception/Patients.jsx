import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ALL_PATIENTS, reception as api } from "../../api";
import { Page, Card, Btn } from "../../lib/Page";
import { Body } from "../../lib/Body";
import { Chip, Search, Sort, Table, Warn } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { can } from "../../perm";
import { MODALITY, SEX, label, modality as asModality } from "../../codes";

const permitted = (key, integrated) => can(integrated ? [key, "nursing.waiting.view"] : key);

/* 원무 3장 — 환자 목록 · 예약
 * ════════════════════════════════════════════════════════════════
 *
 *   왼쪽        검색 + 필터 + 목록
 *   오른쪽 위   고른 환자 상세 (고칠 수 있다)
 *   오른쪽 아래 [예약] 을 누르면 열리는 자리
 *
 * **원무는 검사 종류를 정하지 않는다.**
 *   채우는 것   patient_id · scheduled_at
 *   안 채우는 것 modality · exam_purpose · ordered_by — 유방외과 몫이다.
 *   DB CHECK 도 그렇게 열려 있다 (requested · cancelled 일 때만 셋이 비어도 됨).
 *
 * ── 캘린더에서 넘어오는 길 ──────────────────────────────────────
 * 1장 캘린더에서 날짜를 더블클릭하면 ?date=2026-09-13 을 달고 여기로 온다.
 * 그 값을 예약 날짜 칸의 **첫 값**으로 넣는다.
 *
 * 주소에 담는 이유는 붙여 넣은 주소로 같은 자리가 다시 열려야 해서다.
 * 다만 **주소를 계속 따라가지는 않는다** — 사람이 칸을 고친 뒤에도 주소를
 * 읽으면 고친 값이 되돌아간다. 첫 값으로만 쓴다.
 */

export default function Patients({ integrated = false }) {
  const [sp] = useSearchParams();
  const fromCalendar = sp.get("date") ?? "";

  const [q, setQ] = useState("");
  const [sent, setSent] = useState("");        // 실제로 서버에 보낸 검색어
  const [only, setOnly] = useState("all");     // 필터 — 서버가 아니라 화면이 건다
  const [pick, setPick] = useState(null);      // 고른 patient_id
  /* 예약 자리를 **누구 것으로** 열었나. true/false 로 두면 열어 둔 채 딴
     사람을 고를 때 「누구 예약인지」가 어긋난 채로 [예약 완료] 를 누르게
     된다. id 로 들고 있으면 고른 사람과 다를 때 저절로 닫힌다 */
  const [reserveFor, setReserveFor] = useState(null);

  const list = useApi(
    () => api.list(sent ? { q: sent } : ALL_PATIENTS),
    [sent],
  );

  const rows = useMemo(() => filter(list.data ?? [], only), [list.data, only]);
  const chosen = rows.find((r) => r.patient_id === pick)
    ?? (list.data ?? []).find((r) => r.patient_id === pick)
    ?? null;

  return (
    <Page
      crumb={[integrated ? "간호과" : "원무과", "환자 목록"]}
      title="환자 목록 · 예약"
    >
      <div className="split wide">
        <div className="split-l">
          <Card
            title="환자"
            right={<Chip>{rows.length}명</Chip>}
            pad={false}
          >
            <div className="tbl-top">
              <form onSubmit={(e) => { e.preventDefault(); setSent(q.trim()); }}>
                <Search placeholder="이름 · 전화 · 환자번호 · 생년월일"
                        value={q} onChange={setQ} />
              </form>
              <Sort items={FILTERS} value={only} onChange={setOnly} />
            </div>

            <Body loading={list.loading} error={list.error} onRetry={list.reload}>
              {list.data && (
                <>
                  <Table
                    cols={COLS}
                    rows={rows.map((r) => row(r, {
                      onReserve: () => { setPick(r.patient_id); setReserveFor(r.patient_id); },
                      onOpen: () => setPick(r.patient_id),
                    }, integrated))}
                    value={pick}
                    onPick={setPick}
                  />
                </>
              )}
            </Body>
          </Card>
        </div>

        <aside className="split-r">
          {chosen ? (
            <>
              {/* key 를 주면 환자가 바뀔 때 상세가 새로 선다 — 앞사람의
                  고치던 값이 다음 사람 칸에 남지 않는다 */}
              <Detail key={chosen.patient_id} patient={chosen} onSaved={list.reload}
                      onReserve={() => setReserveFor(chosen.patient_id)} integrated={integrated} />
              <ReservationHistory key={`history-${chosen.patient_id}`} patient={chosen} />
              {reserveFor === chosen.patient_id && (
                <Reserve key={chosen.patient_id} patient={chosen} firstDate={fromCalendar}
                         onClose={() => setReserveFor(null)} integrated={integrated} />
              )}
            </>
          ) : (
            <div className="slot big">
              <b>왼쪽에서 환자를 고르세요</b>
              <span>고르면 정보를 보고 고치거나 예약을 잡을 수 있습니다.</span>
            </div>
          )}
        </aside>
      </div>
    </Page>
  );
}

/* ── 목록 ────────────────────────────────────────────────────── */

const COLS = [
  { key: "no",      label: "환자번호", w: "18%" },
  { key: "name",    label: "이름" },
  { key: "sex",     label: "성별", w: "10%" },
  { key: "age",     label: "나이", w: "10%" },
  { key: "allergy", label: "알레르기", w: "14%" },
  { key: "state",   label: "상태", w: "14%" },
  { key: "act",     label: "", w: "16%" },
];

/* 필터는 **화면이 건다.** 서버 목록에 거를 칸이 없어서다 — 아래 Missing 참고.
   자료가 오면 그대로 서버 질의로 옮긴다 */
const FILTERS = [
  { key: "all",     label: "전체" },
  { key: "allergy", label: "알레르기" },
  { key: "first",   label: "초진" },
];

function filter(rows, only) {
  if (only === "allergy") return rows.filter((r) => r.has_allergy === true);
  if (only === "first")   return rows.filter((r) => !r.first_visited_at);
  return rows;
}


/* 생년월일이 있으면 기준일에 맞춘 만 나이를, 없으면 기존 출생연도
   정보로 계산한 연 나이를 쓴다. 예약 목록과 상세의 나이가 어긋나지
   않도록 한 곳에서 계산한다. */
function ageOf(r) {
  if (r.age != null) return r.age;
  const birthDate = r.pii?.birth_date ?? r.birth_date ?? null;
  if (birthDate) {
    const birth = new Date(`${String(birthDate).slice(0, 10)}T00:00:00`);
    if (!Number.isNaN(birth.getTime())) {
      const today = new Date();
      let age = today.getFullYear() - birth.getFullYear();
      const beforeBirthday = today.getMonth() < birth.getMonth()
        || (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate());
      return age - Number(beforeBirthday);
    }
  }
  if (!r.birth_year) return null;
  return new Date().getFullYear() - r.birth_year;
}

function row(r, { onReserve, onOpen }, integrated) {
  const age = ageOf(r);
  return {
    id: r.patient_id,
    no: <span className="num dim">{r.patient_number ?? "—"}</span>,
    name: <b>{r.name ?? "—"}</b>,
    sex: label(SEX, r.sex) || "—",
    age: age == null ? "—" : <span className="num">{age}</span>,
    allergy: r.has_allergy == null
      ? "—"
      : (r.has_allergy ? <Chip tone="fill">있음</Chip> : "없음"),
    state: r.status ?? (r.first_visited_at ? "재진" : "—"),
    act: (
      <span className="rowacts">
        <Btn onClick={(e) => { e.stopPropagation(); onOpen(); }}>상세보기</Btn>
        <Btn kind="fill" onClick={(e) => { e.stopPropagation(); onReserve(); }}
             disabled={!permitted("reception.reserve", integrated)}>예약</Btn>
      </span>
    ),
  };
}

/* ── 상세 ────────────────────────────────────────────────────── */

/* 고칠 수 있는 것만 칸으로 둔다.
   ⚠ **이름 · 생년월일 · 전화는 못 고친다.** 그 셋은 patient_pii 에 있고
     PATCH /patients/{id} 가 쓰는 PatientSerializer 는 patient 표만 다룬다
     (상세의 pii 는 읽기 전용). 칸을 만들어 두면 저장해도 조용히 안 바뀐다 —
     그래서 아예 «읽기»로 보여준다. */
function Detail({ patient, onSaved, onReserve, integrated }) {
  /* **고친 칸만 들고 있는다.** 서버 값을 통째로 state 에 복사해 두면 그것을
     언제 다시 세울지(효과·의존성)를 계속 맞춰야 하고, 저장 후 새로 받은
     값과 어긋나기 쉽다. 그리는 순간에 «서버 값 + 내가 고친 것»을 겹친다 */
  const [edited, setEdited] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const full = useApi(() => api.detail(patient.patient_id), [patient.patient_id]);

  /* 목록 행이 아니라 **상세**로 칸을 세운다. 목록에는 알레르기 메모가 없어서
     목록 값으로 세우면 저장할 때 메모를 빈 값으로 덮어쓴다 */
  const form = full.data && {
    sex: full.data.sex ?? "",
    has_allergy: full.data.has_allergy === true,
    allergy_note: full.data.allergy_note ?? "",
    ...edited,
  };

  const set = (k, v) => { setEdited((f) => ({ ...f, [k]: v })); setSaved(false); };

  async function save() {
    if (!form || busy) return;
    setBusy(true); setError(null);
    try {
      await api.update(patient.patient_id, {
        sex: form.sex || null,
        has_allergy: form.has_allergy,
        allergy_note: form.has_allergy ? form.allergy_note : "",
      });
      /* 고친 것을 비운다 — 이제 서버 값이 곧 내 값이다. 안 비우면 겹침이
         남아서, 다른 곳에서 바뀐 값이 화면에 안 보인다 */
      setEdited({});
      setSaved(true);
      full.reload();
      onSaved?.();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="환자 정보"
      right={<Btn kind="fill" onClick={onReserve}
                  disabled={!permitted("reception.reserve", integrated)}>예약</Btn>}
    >
      <Body loading={full.loading} error={full.error} onRetry={full.reload}>
        {full.data && form && (
          <>
            <dl className="kv patient-facts">
              <dt>환자번호</dt><dd className="num">{full.data.patient_number ?? patient.patient_number ?? "—"}</dd>
              <dt>이름</dt><dd>{full.data.pii?.name ?? full.data.name ?? patient.name ?? "—"}</dd>
              <dt>생년월일</dt><dd className="num">{full.data.pii?.birth_date ?? full.data.birth_date ?? "—"}</dd>
              <dt>전화번호</dt><dd className="num">{full.data.pii?.phone ?? full.data.phone ?? "—"}</dd>
              <dt>내원 구분</dt><dd>{full.data.first_visited_at ? "재진" : "초진"}</dd>
            </dl>
            <div className="fields one">
              <label className="field">
                <span>성별</span>
                <select value={form.sex} onChange={(e) => set("sex", e.target.value)}
                        disabled={busy}>
                  <option value="">—</option>
                  <option value="female">여</option>
                  <option value="male">남</option>
                </select>
              </label>
            </div>

            <label className="check">
              <input type="checkbox" checked={form.has_allergy} disabled={busy}
                     onChange={(e) => set("has_allergy", e.target.checked)} />
              <span>조영제 알레르기 있음</span>
            </label>
            {form.has_allergy && (
              <label className="field">
                <span>알레르기 메모</span>
                <textarea value={form.allergy_note} disabled={busy} maxLength={250}
                          onChange={(e) => set("allergy_note", e.target.value)} />
              </label>
            )}

            <div className="save-b">
              <Btn kind="fill" onClick={save}
                   disabled={busy || !permitted("reception.patient.edit", integrated)}>
                {busy ? "저장하는 중…" : "저장"}
              </Btn>
            </div>

            {saved && <div className="slot ok" role="status"><b>저장했습니다</b></div>}
            {error && <Failed error={error} />}
          </>
        )}
      </Body>
    </Card>
  );
}

/* 예약을 새로 잡기 전에도 이 환자에게 이미 확정된 약속을 한눈에 본다.
   예약 입력 카드와 분리해야 담당자가 기존 일정을 확인한 뒤 새 예약을
   판단할 수 있다. */
function ReservationHistory({ patient }) {
  const orders = useApi(() => api.ordersOf(patient.patient_id), [patient.patient_id]);
  const rows = (orders.data ?? []).filter((order) => order.order_status !== "cancelled");

  return (
    <Card title="환자 예약 기록">
      <Body loading={orders.loading} error={orders.error} onRetry={orders.reload}>
        {orders.data && (rows.length ? (
          <Table
            cols={[
              { key: "when", label: "예약 일시" },
              { key: "status", label: "상태", w: "28%" },
            ]}
            rows={rows.map((order) => ({
              id: order.exam_order_id,
              when: order.scheduled_at
                ? <span className="num">{dayOf(order.scheduled_at)} {timeOf(order.scheduled_at)}</span>
                : "일시 미정",
              status: order.order_status ?? "—",
            }))}
          />
        ) : <p className="hint">확정된 예약 기록이 없습니다.</p>)}
      </Body>
    </Card>
  );
}

/* ── 예약 ────────────────────────────────────────────────────── */

const dayOf = (s) => (s ? s.slice(0, 10) : "");
const timeOf = (s) => (s ? s.slice(11, 16) : "");

/* [예약] 을 누르면 열리는 자리.
 *
 * **중복은 막지 않고 보여준다.** 같은 날 예약이 이미 있어도 못 잡게 하면
 * 오전 유방촬영 · 오후 초음파처럼 하루에 둘을 잡는 정상 경우가 막힌다.
 * 원무가 목록을 보고 판단한다.
 *
 * ⚠ **시간대 정원은 보지 않는다.** 검사마다 걸리는 시간이 달라서 «몇 건»으로
 *   자리를 세면 틀린 답이 나온다.
 */
function Reserve({ patient, firstDate, onClose, integrated }) {
  const [date, setDate] = useState(firstDate || "");
  const [time, setTime] = useState("09:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const orders = useApi(() => api.ordersOf(patient.patient_id), [patient.patient_id]);

  /* 고른 날에 이미 잡힌 것 */
  const sameDay = (orders.data ?? [])
    .filter((o) => o.scheduled_at && dayOf(o.scheduled_at) === date
                   && o.order_status !== "cancelled");

  async function submit(e) {
    e.preventDefault();
    if (!date || !time || busy) return;
    setBusy(true); setError(null);
    try {
      /* 서버가 DateTimeField 로 받는다. 시간대를 안 붙이면 서버가 KST 로
         읽는다 (settings 의 TIME_ZONE) — 화면과 같은 뜻이라 그대로 보낸다 */
      const order = await api.reserve({
        patient_id: patient.patient_id,
        scheduled_at: `${date}T${time}:00`,
      });
      setDone(order);
      orders.reload();
    } catch (e2) {
      setError(e2);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Card title="예약" right={<Btn onClick={onClose}>닫기</Btn>}>
        <div className="slot ok" role="status">
          <b>{date} {time} 예약했습니다</b>
          <span>
            오더 {done.exam_order_id} · 검사 종류는 유방외과가 정합니다
          </span>
        </div>
      </Card>
    );
  }

  return (
    <Card title="예약" right={<Btn onClick={onClose} disabled={busy}>닫기</Btn>}>
      <form onSubmit={submit}>
        <dl className="kv">
          <dt>환자</dt>
          <dd>{patient.name ?? "—"} · <span className="num">{patient.patient_number}</span></dd>
        </dl>

        <div className="fields appointment-fields">
          <label className="field">
            <span>날짜</span>
            <input type="date" value={date} disabled={busy}
                   onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="field">
            <span>시간</span>
            <input type="time" value={time} step={600} disabled={busy}
                   onChange={(e) => setTime(e.target.value)} />
          </label>
        </div>

        <Body loading={orders.loading} error={orders.error} onRetry={orders.reload}>
          {orders.data && date && (
            sameDay.length > 0 ? (
              <div className="slot bad" role="alert">
                <b>이 환자는 {date} 에 이미 예약이 있습니다</b>
                <ul className="dup">
                  {sameDay.map((o) => (
                    <li key={o.exam_order_id}>
                      <b>{timeOf(o.scheduled_at)}</b>
                      <span>{label(MODALITY, asModality(o.modality)) || "검사 미정"}</span>
                      <em>{o.order_status}</em>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null
          )}
        </Body>

        <div className="save-b">
          <Btn kind="fill" type="submit"
               disabled={!date || !time || busy || !permitted("reception.reserve", integrated)}>
            {busy ? "예약하는 중…" : "예약 완료"}
          </Btn>
        </div>

        {error && <Failed error={error} />}
      </form>
    </Card>
  );
}


function Failed({ error }) {
  return (
    <div className="slot bad" role="alert">
      <b>{error.detail || error.message}</b>
      <span>{error.code}{error.traceId && <> · {error.traceId}</>}</span>
    </div>
  );
}
