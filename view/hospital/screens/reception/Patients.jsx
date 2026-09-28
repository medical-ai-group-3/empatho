import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ALL_PATIENTS, reception as api, nursing as nur } from "../../api";
import { Page, Card, Btn } from "../../lib/Page";
import { Body, Empty } from "../../lib/Body";
import { Chip, Search, Sort, Table } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { can } from "../../perm";
import { go } from "../../nav";
import { MODALITY, SEX, label, modality as asModality } from "../../codes";
import * as H from "../../dept/home";

const permitted = (key, integrated) => can(integrated ? [key, "nursing.waiting.view"] : key);

/* 환자 목록 — 찾고, 고르고, 그 사람의 정보 · 방문 · 추적을 한 자리에서
 * ════════════════════════════════════════════════════════════════
 *
 *   ┌ 목록 ─────────────────────────────┬ 고른 환자(따라 내려온다) ─┐
 *   │ 검색 · [전체][알레르기][미배정][앱 미가입] │ [정보][방문·예약][추적]   │
 *   │ 번호 이름 전화 주치의 앱 알레르기   │                          │
 *   └───────────────────────────────────┴──────────────────────────┘
 *
 * ⚠ 09-28 **여기서 예약을 잡지 않는다.** 이 화면의 [예약] 카드는 예약 관리의
 *   같은 날 중복 막이(서버 _refuse_same_day 와 같은 기준 · [그 예약 고치기])가
 *   없는 두 번째 길이었다. 이제 [예약 잡기 →]가 예약 관리로 그 사람을 싣고 간다.
 * ⚠ 오른쪽 칸은 **따라 내려온다(sticky).** 목록이 길어 아래 사람을 누르면
 *   정보가 화면 위에 있어 다시 올라가야 했다.
 *
 * 주소 — ?patient= 로 그 사람을 골라 둔 채 열고, ?date= 는 [예약 잡기]로
 * 그대로 넘긴다(홈 달력에서 온 날짜).
 */
export default function Patients({ cfg, integrated: asked = false }) {
  /* ⚠ 간호과로 합친 뒤 이 화면은 main.jsx 가 cfg 만 주고 연다 — 간호과
     안에서 열리면 합친 과로 본다(간호 열쇠로도 쓰는 단추가 열린다) */
  const integrated = asked || cfg?.key === "nursing";
  const [sp] = useSearchParams();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(sp.get("date") ?? "") ? sp.get("date") : "";

  const [q, setQ] = useState("");
  const [sent, setSent] = useState("");        // 실제로 서버에 보낸 검색어
  const [only, setOnly] = useState("all");     // 필터 — 서버가 아니라 화면이 건다
  const [pick, setPick] = useState(() => {     // 고른 patient_id
    const n = Number(sp.get("patient"));
    return Number.isFinite(n) && n > 0 ? n : sp.get("patient") || null;
  });

  const list = useApi(
    () => api.list(sent ? { q: sent } : ALL_PATIENTS),
    [sent],
  );

  const all = useMemo(() => list.data ?? [], [list.data]);
  const rows = useMemo(() => filter(all, only), [all, only]);
  const chosen = all.find((r) => String(r.patient_id) === String(pick)) ?? null;

  /* 거르개마다 몇 명인지 — 누르기 전에 보인다. ⚠ 서버가 그 칸을 안 주면
     (has_account · primary_staff 가 목록에 없다) 그 거르개는 안 세운다 */
  const filters = FILTERS
    .filter((f) => !f.need || all.some((r) => f.need in r))
    .map((f) => ({ ...f, label: `${f.label} ${filter(all, f.key).length}` }));

  return (
    <Page crumb={[integrated ? "간호과" : "원무과", "환자 목록"]} title="환자 목록"
          right={<Btn to={go.nursing.reservations()}>예약 관리</Btn>}>
      <div className="split wide plist">
        <div className="split-l">
          <Card
            title="환자"
            /* 서버가 한 번에 200명까지만 준다 — 더 있으면 총원을 같이 적는다 */
            right={<Chip>{only === "all" && list.data?.total > rows.length
              ? `${rows.length} / ${list.data.total}명` : `${rows.length}명`}</Chip>}
            pad={false}
          >
            <div className="tbl-top">
              <form onSubmit={(e) => { e.preventDefault(); setSent(q.trim()); }}>
                <Search placeholder="이름 · 전화 · 환자번호 · 생년월일"
                        value={q} onChange={setQ} />
              </form>
              <Sort items={filters} value={only} onChange={setOnly} />
            </div>

            <Body loading={list.loading} error={list.error} onRetry={list.reload}>
              {list.data && (
                <Table cols={COLS} rows={rows.map(row)} value={pick} onPick={setPick} />
              )}
            </Body>
          </Card>
        </div>

        <aside className="split-r plist-side">
          {chosen ? (
            /* key — 환자가 바뀌면 칸이 새로 선다. 앞사람의 고치던 값이 안 남는다 */
            <Panel key={chosen.patient_id} patient={chosen} date={date}
                   integrated={integrated} onSaved={() => list.reload(true)} />
          ) : (
            <div className="slot big">
              <b>왼쪽에서 환자를 고르세요</b>
              <span>정보를 고치고, 지난 방문 · 예약과 추적 회차를 봅니다.</span>
            </div>
          )}
        </aside>
      </div>
    </Page>
  );
}

/* ── 목록 ────────────────────────────────────────────────────── */

/* ⚠ 09-28 「상태」 칸을 뺐다 — 목록 응답에 그 값이 없어 늘 「—」였다.
   대신 창구가 실제로 보는 전화 · 주치의 · 앱 연동을 둔다 */
const COLS = [
  { key: "no",      label: "환자번호", w: "15%" },
  { key: "name",    label: "이름" },
  { key: "phone",   label: "전화", w: "17%" },
  { key: "staff",   label: "주치의", w: "13%" },
  { key: "app",     label: "앱", w: "9%" },
  { key: "allergy", label: "알레르기", w: "11%" },
];

/* 필터는 **화면이 건다.** 서버 목록에 거를 칸이 없어서다.
   need — 그 칸이 목록에 실려 와야 세울 수 있는 거르개 */
const FILTERS = [
  { key: "all",     label: "전체" },
  { key: "allergy", label: "알레르기" },
  { key: "none",    label: "미배정", need: "primary_staff" },
  { key: "noapp",   label: "앱 미가입", need: "has_account" },
];

function filter(rows, only) {
  if (only === "allergy") return rows.filter((r) => r.has_allergy === true);
  if (only === "none") return rows.filter((r) => "primary_staff" in r && r.primary_staff == null);
  /* ⚠ has_account 가 없는(옛 서버) 줄은 「미가입」으로 세지 않는다 — 모르는 것이다 */
  if (only === "noapp") return rows.filter((r) => r.has_account === false);
  return rows;
}

/* 생년월일이 있으면 만 나이를, 없으면 출생연도로 연 나이를 쓴다 */
function ageOf(r) {
  if (r.age != null) return r.age;
  const birthDate = r.pii?.birth_date ?? r.birth_date ?? null;
  if (birthDate) {
    const birth = new Date(`${String(birthDate).slice(0, 10)}T00:00:00`);
    if (!Number.isNaN(birth.getTime())) {
      const today = new Date();
      const age = today.getFullYear() - birth.getFullYear();
      const beforeBirthday = today.getMonth() < birth.getMonth()
        || (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate());
      return age - Number(beforeBirthday);
    }
  }
  if (!r.birth_year) return null;
  return new Date().getFullYear() - r.birth_year;
}

function row(r) {
  const age = ageOf(r);
  const who = [age, label(SEX, r.sex)].filter((v) => v != null && v !== "").join(" · ");
  return {
    id: r.patient_id,
    no: <span className="num dim">{r.patient_number ?? "—"}</span>,
    name: <span className="plist-nm"><b>{r.name ?? "—"}</b>{who && <span>{who}</span>}</span>,
    phone: <span className="num">{r.phone ?? "—"}</span>,
    staff: r.primary_staff_name ?? (r.primary_staff != null ? `#${r.primary_staff}` : <span className="dim">미배정</span>),
    app: r.has_account == null ? "—" : r.has_account ? "연동" : <span className="dim">미가입</span>,
    allergy: r.has_allergy == null
      ? "—"
      : (r.has_allergy ? <Chip tone="fill">있음</Chip> : "없음"),
  };
}

/* ── 오른쪽 — 고른 환자 한 사람 ───────────────────────────────── */

const TABS = [
  { key: "info", label: "정보" },
  { key: "visits", label: "방문 · 예약" },
  { key: "follow", label: "추적" },
];

function Panel({ patient, date, integrated, onSaved }) {
  const [tab, setTab] = useState("info");
  const pid = patient.patient_id;
  const age = ageOf(patient);
  const reserveTo = `${go.nursing.reservations()}?patient=${pid}${date ? `&date=${date}` : ""}`;

  return (
    <Card className="plist-card" pad={false}
          title={(
            <span className="plist-who">
              <b>{patient.name ?? "—"}</b>
              <span>{[patient.patient_number, age != null && `${age}세`, label(SEX, patient.sex)]
                .filter(Boolean).join(" · ")}</span>
            </span>
          )}
          right={<Btn to={go.patient(pid)}>환자 상세 열기</Btn>}>
      <nav className="qtabs" aria-label="환자 정보 구분">
        {TABS.map((t) => (
          <button type="button" key={t.key} className={`qtab${t.key === tab ? " on" : ""}`}
                  aria-pressed={t.key === tab} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </nav>
      <div className="plist-b">
        {tab === "info" && <Info patient={patient} integrated={integrated} onSaved={onSaved} />}
        {tab === "visits" && <Visits pid={pid} reserveTo={reserveTo} integrated={integrated} />}
        {tab === "follow" && <Follow pid={pid} />}
      </div>
    </Card>
  );
}

/* ── 정보 ────────────────────────────────────────────────────────
 * 두 덩이다 — 진료 정보(성별 · 알레르기, PATCH /patients/{id}/)와 인적 사항
 * 정정(이름 · 전화 · 생년월일, PATCH /patients/{id}/pii).
 * ⚠ 둘은 **다른 표**다. 인적 사항은 patient_pii 에 있어 위 PATCH 로는 조용히
 *   안 바뀐다 — 그래서 저장 단추도 따로 둔다.
 */
function Info({ patient, integrated, onSaved }) {
  const [edited, setEdited] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const full = useApi(() => api.detail(patient.patient_id), [patient.patient_id]);

  /* **고친 칸만 들고 있는다.** 그리는 순간에 «서버 값 + 내가 고친 것»을 겹친다.
     목록 행이 아니라 **상세**로 세운다 — 목록엔 알레르기 메모가 없어 저장할 때
     메모를 빈 값으로 덮어썼다 */
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
      setEdited({});
      setSaved(true);
      full.reload(true);
      onSaved?.();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  }

  return (
    <Body loading={full.loading} error={full.error} onRetry={full.reload}>
      {full.data && form && (
        <>
          <dl className="kv patient-facts">
            <div><dt>환자번호</dt><dd className="num">{full.data.patient_number ?? patient.patient_number ?? "—"}</dd></div>
            <div><dt>주치의</dt><dd>{full.data.primary_staff_name ?? patient.primary_staff_name ?? "미배정"}</dd></div>
            <div><dt>앱 연동</dt><dd>{patient.has_account == null ? "—" : patient.has_account ? "연동" : "미가입"}</dd></div>
            <div><dt>내원 구분</dt><dd>{full.data.first_visited_at ? "재진" : "초진"}</dd></div>
          </dl>

          <h3 className="plist-h">진료 정보</h3>
          <div className="fields one">
            <label className="field">
              <span>성별</span>
              <select value={form.sex} onChange={(e) => set("sex", e.target.value)} disabled={busy}>
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
            {saved && <span className="hcard-k" role="status">저장했습니다</span>}
            <Btn kind="fill" onClick={save}
                 disabled={busy || !permitted("reception.patient.edit", integrated)}>
              {busy ? "저장하는 중…" : "저장"}
            </Btn>
          </div>
          {error && <Failed error={error} />}

          <Pii key={full.data.patient_id ?? patient.patient_id} pid={patient.patient_id}
               now={full.data.pii ?? {}} integrated={integrated}
               onDone={() => { full.reload(true); onSaved?.(); }} />
        </>
      )}
    </Body>
  );
}

/* 인적 사항 정정 — 창구에서 이름 오타 · 번호 바뀜 · 생년월일 잘못 적힘을 고친다.
   **바뀐 칸만** 보낸다. 전화가 다른 환자와 겹치면 서버가 400 을 준다.
   ⚠ 서버에 경로가 없으면(404 · 405) 그렇다고 적는다 — 저장된 척하지 않는다 */
function Pii({ pid, now, integrated, onDone }) {
  const [f, setF] = useState({
    name: now.name ?? "", phone: now.phone ?? "", birth_date: now.birth_date ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);
  const changed = Object.fromEntries(
    Object.entries(f).filter(([k, v]) => v.trim() !== "" && v.trim() !== (now[k] ?? "")));
  const may = permitted("reception.patient.edit", integrated);

  async function save() {
    if (busy || Object.keys(changed).length === 0) return;
    setBusy(true); setErr(null); setOk(null);
    try {
      await api.correctPii(pid, changed);
      setOk("고쳤습니다");
      onDone?.();
    } catch (e) {
      setErr([404, 405].includes(e?.status)
        ? { ...e, detail: "서버에 인적 사항 정정 경로가 아직 없습니다 — 고치지 않았습니다" } : e);
    } finally { setBusy(false); }
  }

  return (
    <>
      <h3 className="plist-h">인적 사항 정정</h3>
      <div className="fields plist-pii">
        <label className="field"><span>이름</span>
          <input value={f.name} disabled={busy || !may}
                 onChange={(e) => setF((x) => ({ ...x, name: e.target.value }))} /></label>
        <label className="field"><span>전화</span>
          <input value={f.phone} disabled={busy || !may} inputMode="tel"
                 onChange={(e) => setF((x) => ({ ...x, phone: e.target.value }))} /></label>
        <label className="field"><span>생년월일</span>
          <input type="date" value={f.birth_date} disabled={busy || !may}
                 onChange={(e) => setF((x) => ({ ...x, birth_date: e.target.value }))} /></label>
      </div>
      <div className="save-b">
        {ok && <span className="hcard-k" role="status">{ok}</span>}
        <Btn onClick={save} disabled={busy || !may || Object.keys(changed).length === 0}>
          {busy ? "고치는 중…" : "정정 저장"}
        </Btn>
      </div>
      {err && <Failed error={err} />}
    </>
  );
}

/* ── 방문 · 예약 ─────────────────────────────────────────────────
 * 이 사람의 오더 전부 — 다가오는 것이 위, 지난 것이 아래.
 * 안 오신 적 — 지난 예약인데 내원 기록이 없는 것.
 * ⚠ **「부도」라고 쓰지 않는다.** 창구에서 내원을 안 찍었을 수도 있다.
 */
const STATUS = {
  requested: "미확정", scheduled: "예약 확정", ordered: "검사 지시",
  accepted: "접수됨", in_progress: "검사 중", completed: "완료", cancelled: "취소",
};
const dayOf = (s) => (s ? String(s).slice(0, 10) : "");
const timeOf = (s) => (s ? String(s).slice(11, 16) : "");
const missedOf = (o, today) => dayOf(o.scheduled_at) && dayOf(o.scheduled_at) < today
  && !o.visited_at && o.order_status !== "cancelled";

function statusOf(o, today) {
  if (missedOf(o, today)) return "안 옴";
  if (o.visited_at && o.order_status === "requested") return "내원";
  return STATUS[o.order_status] ?? o.order_status ?? "—";
}

function Visits({ pid, reserveTo, integrated }) {
  const orders = useApi(() => api.ordersOf(pid), [pid]);
  const today = H.iso(new Date());
  const list = (orders.data ?? []).slice()
    .sort((a, b) => String(b.scheduled_at ?? b.visited_at ?? "").localeCompare(String(a.scheduled_at ?? a.visited_at ?? "")));
  const ahead = list.filter((o) => dayOf(o.scheduled_at) >= today && !o.visited_at
    && o.order_status !== "cancelled");
  const missed = list.filter((o) => missedOf(o, today));

  return (
    <>
      <div className="plist-act">
        <span className="hcard-k">
          다가오는 예약 {ahead.length}건{missed.length > 0 && ` · 안 오신 적 ${missed.length}번`}
        </span>
        <span className="home-fill" />
        {/* 예약은 예약 관리에서만 잡는다 — 같은 날 중복 막이가 거기 있다 */}
        {permitted("reception.reserve", integrated)
          ? <Btn kind="fill" to={reserveTo}>예약 잡기 →</Btn>
          : <Btn kind="fill" disabled title="권한이 없습니다. 관리자에게 문의하세요">예약 잡기 →</Btn>}
      </div>
      <Body loading={orders.loading} error={orders.error} onRetry={orders.reload}
            empty={orders.data && list.length === 0 && <Empty title="방문 · 예약 기록이 없습니다" />}>
        <div className="resv-past plist-visits">
          {list.map((o) => (
            <p key={o.exam_order_id} className={o.order_status === "cancelled" ? "off" : undefined}>
              <i>{statusOf(o, today)}</i>
              <time>{dayOf(o.scheduled_at ?? o.visited_at) || "일시 미정"} {timeOf(o.scheduled_at ?? o.visited_at)}</time>
              <span>{label(MODALITY, asModality(o.modality)) || "검사 미정"}</span>
              <em>{o.primary_staff_name ?? o.handed_to_name ?? ""}</em>
            </p>
          ))}
        </div>
      </Body>
    </>
  );
}

/* ── 추적 ────────────────────────────────────────────────────────
 * BI-RADS 3 추적 회차. 전화 · 회차 결과는 추적 관리에서 한다 — 여기는 본다 */
const ROUND = { stable: "변화 없음", changed: "변화 있음", no_show: "안 오심" };

function Follow({ pid }) {
  const list = useApi(() => nur.followupsOf(pid), [pid]);
  const rows = H.rows(list.data);
  return (
    <>
      <div className="plist-act">
        <span className="hcard-k">{rows.length === 0 ? "추적 회차가 없습니다" : `회차 ${rows.filter((r) => r.status !== "candidate").length}`}</span>
        <span className="home-fill" />
        <Btn to={`${go.nursing.followups()}?patient=${pid}`}>추적 관리에서 열기</Btn>
      </div>
      <Body loading={list.loading} error={list.error} onRetry={list.reload}
            empty={list.data && rows.length === 0 && <Empty title="추적 중인 회차가 없습니다" hint="BI-RADS 3 으로 확정되면 여기에 후보로 뜹니다" />}>
        <div className="resv-past plist-visits">
          {rows.map((r, i) => (
            <p key={r.followup_id ?? `c${i}`}>
              <i>{r.status === "candidate" ? "후보" : H.openFollowup(r) ? "진행" : "종결"}</i>
              <time>{r.due_at ? dayOf(r.due_at) : "예정일 없음"}</time>
              <span>{r.status === "candidate" ? "회차 없음 · BI-RADS 3" : `${r.round_no}회차`}</span>
              <em>{ROUND[r.round_result] ?? r.call_result ?? ""}</em>
            </p>
          ))}
        </div>
      </Body>
    </>
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
