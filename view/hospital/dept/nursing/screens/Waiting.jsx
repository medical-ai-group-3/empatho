import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, Locked } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";
import { DESK, go } from "../../../nav";
import { specimens as specApi } from "../../../api";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";
import * as H from "../../home";
import { ORDER_STATUS, label } from "../../../codes";

/* 내원 대기 · 유방외과 배정 — `docs/mockup/Nursing-내원대기.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **접수 화면의 아래 절반이다.** 화면 줄에서 뺐고(6.1) 접수 화면이 이걸
 * 통째로 끼워 쓴다 — 이 과에서 제일 많이 보이는 자리다.
 *
 *   ┌ 330px ─────────────┬ 1fr ─────────────────────┬ 380px ─────────┐
 *   │ [문진][배정][검체]  │ 고른 환자                 │ 배정 현황(오늘) │
 *   │  1 …               │  방문 정보 │ 문진          │  서나영 대기 2  │
 *   │  2 …               │  간호 메모                │  최민수 대기 1  │
 *   │                    ├──────────────────────────┤  …             │
 *   │                    │ 의사 칩(대기 n) [보내기]   │  미배정 4       │
 *   └────────────────────┴──────────────────────────┴────────────────┘
 *
 * 탭은 환자가 거치는 순서다 — 문진 대기 → 배정 대기 → (보낸 뒤) 검체 확인.
 * **왼쪽 줄을 누르면 가운데가 그 환자로 바뀐다.** 화면을 옮기지 않는다.
 *
 * ⚠ 09-28 **[보내기]를 바닥 줄에 못 박았다.** 배정 칸이 가운데 안쪽 스크롤
 *   맨 아래라 문진이 길면 화면 밖이었다 — 이 과의 주 업무 단추가 안 보였다.
 * ⚠ **순번은 표시 전용이다.** 접수한 순서 그대로고 끌어서 못 바꾼다.
 * ⚠ **경과 시간을 안 쓴다.** 서버가 주지 않는다 — 접수 시각만 적는다.
 * ⚠ **칸을 카드로 띄우지 않는다.** 상자 하나를 1px 선으로 가른다(4.5).
 * ⚠ **쪽 머리가 없다.** 접수 화면 안에 들어가므로 제목을 또 달지 않는다.
 */
export default function NursingWaiting({ cfg, embedded = false }) {
  /* 간호과는 원무 일까지 하는 한 과다 — **보는 것**은 과 열쇠 하나면 된다.
     쓰는 동작은 아래에서 제 열쇠로 그대로 잠근다 */
  if (!can(DESK)) {
    const locked = <Locked what="내원 대기" need="nursing.waiting.view" />;
    return embedded ? locked : (
      <Page crumb={[cfg.name, "내원 대기"]} title="내원 대기">{locked}</Page>
    );
  }
  return <Inner cfg={cfg} embedded={embedded} />;
}

/* 몇 초마다 조용히 다시 불러온다. 깜빡이면 고른 환자가 사라진다 */
const POLL_MS = 7000;

const TABS = [
  { key: "q", label: "문진 대기" },
  { key: "assign", label: "배정 대기" },
  { key: "specimen", label: "검체 확인" },
];
/* 주소의 ?tab= — 홈 「검체」 줄은 specimen 으로 온다 */
const TAB_ALIAS = { q: "q", questionnaire: "q", assign: "assign", specimen: "specimen" };

const idOf = (r) => r.exam_order_id ?? r.id;
const staffId = (s) => s.staff_id ?? s.id;
const staffName = (s) => s.full_name ?? s.name ?? `직원 ${staffId(s)}`;

/* 보낸 오더 — today-status 의 handed_at 이 찬 줄. 취소는 뺀다 */
const handed = (r) => r.handed_at != null && r.stage_code !== "cancelled"
  && r.order_status !== "cancelled";

function Inner({ cfg, embedded }) {
  const api = cfg.api;
  /* 홈 현황판 줄은 ?order= 를, 홈 「검체」 줄은 ?tab=specimen 을 달고 온다.
     ⚠ 목업 번호는 글자(eo-w1)라 숫자로만 읽지 않는다 */
  const [params] = useSearchParams();
  const [pick, setPick] = useState(() => params.get("order") || null);
  const [tab, setTab] = useState(() => TAB_ALIAS[params.get("tab")] ?? null);
  const [spick, setSpick] = useState(null);   /* 검체 탭에서 고른 오더 */
  const [tick, setTick] = useState(0);
  /* ⚠ 이 화면을 보는 중에 같은 주소로 또 오면(홈 → 접수 → 홈 줄) 다시 서지
     않는다 — 주소가 바뀐 것을 보고 한 번 따라간다 */
  const asked = `${params.get("tab") ?? ""}|${params.get("order") ?? ""}`;
  const [seenAsk, setSeenAsk] = useState(asked);
  if (asked !== seenAsk) {
    setSeenAsk(asked);
    if (TAB_ALIAS[params.get("tab")]) setTab(TAB_ALIAS[params.get("tab")]);
    if (params.get("order")) setPick(params.get("order"));
  }

  const arrived = useApi(() => api.waitingArrived(), [tick]);
  /* 오늘 온 사람 전부 — 보낸 사람(handed_at)과 선생님별 부하가 여기서 나온다 */
  const came = useApi(() => H.soft(api.todayStatus()), [tick]);
  const staff = useApi(() => H.soft(api.surgeons()), []);
  /* 오늘 예약했고 아직 안 온 사람 — 왼쪽 「오늘 요약」 밑. 줄 박자(7초)마다
     부를 만큼 급한 값이 아니라 다섯 박자에 한 번 */
  const slow = Math.floor(tick / 5);
  const booked = useApi(() => H.soft(api.scheduledToday()), [slow]);
  /* 문항 말 — 못 부르면 null 이고 화면은 코드 그대로 적는다 */
  const form = useApi(() => api.questionnaireForm().catch(() => null), []);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => clearInterval(t);
  }, []);

  /* 유방외과로 보낸 오더는 서버가 뺀다(waitingArrived 의 handed=none) */
  const rows = H.rows(arrived.data);
  const today = H.rows(came.data);
  const people = H.rows(staff.data);
  const lists = useMemo(() => ({
    q: rows.filter((r) => !hasAnswers(r.questionnaire)),
    assign: rows.filter((r) => hasAnswers(r.questionnaire)),
    specimen: today.filter(handed),
  }), [rows, today]);

  /* 안 고른 탭이면 — 고른 오더가 든 칸, 없으면 일이 있는 첫 칸 */
  const here = tab
    ?? (pick && lists.assign.some((r) => String(idOf(r)) === String(pick)) ? "assign"
      : pick ? "q"
        : lists.q.length ? "q" : lists.assign.length ? "assign" : "q");
  const shown = lists[here];
  /* 아무도 안 골랐으면 **그 탭의 첫 사람**을 편다 — 가운데가 빈 채로 서 있으면
     창구가 매번 한 번 더 눌러야 했다 */
  const cur = pick ?? (here !== "specimen" && shown[0] ? idOf(shown[0]) : null);
  const scur = spick ?? (lists.specimen[0] ? idOf(lists.specimen[0]) : null);
  const detail = useApi(
    () => (cur ? api.examOrder(cur) : Promise.resolve(null)), [cur, tick]);

  /* 선생님별 오늘 부하 — 보낸 뒤 아직 외래 차례(stage_code outpatient)인 사람과
     오늘 보낸 사람 전부. 칩 · 오른쪽 현황판이 같은 수를 쓴다 */
  const load = useMemo(() => {
    const m = new Map();
    for (const r of today.filter(handed)) {
      const k = String(r.handed_to ?? r.primary_staff ?? "");
      if (!k) continue;
      const it = m.get(k) ?? { wait: [], sent: 0, name: r.handed_to_name ?? r.primary_staff_name };
      it.sent += 1;
      if (r.stage_code === "outpatient") it.wait.push(r);
      m.set(k, it);
    }
    return m;
  }, [today]);

  /* 보내고 나면 **다음 사람을 골라 둔다** — 창구가 줄을 다시 누르는 한 걸음을
     던다. 방금 보낸 사람 자리의 다음, 없으면 앞사람 */
  function sent(id) {
    const ids = shown.map(idOf).filter((x) => String(x) !== String(id));
    const at = shown.findIndex((r) => String(idOf(r)) === String(id));
    setPick(ids[at] ?? ids[at - 1] ?? null);
    setTick((n) => n + 1);
  }

  const srow = here === "specimen"
    ? lists.specimen.find((r) => String(idOf(r)) === String(scur)) ?? null : null;

  const body = (
    <div className="nwait">
      {/* 탭을 바꾸면 고른 사람을 놓는다 — 다른 탭 사람이 가운데 남아 있으면 헷갈린다 */}
      <Queue state={arrived} tab={here} setTab={(t) => { setTab(t); setPick(null); }}
             lists={lists} people={people} today={today}
             booked={H.notYetCame(H.rows(booked.data), rows, today)}
             pick={here === "specimen" ? scur : cur}
             onPick={here === "specimen" ? setSpick : setPick} />

      <div className="nwait-mid">
        {here === "specimen" ? (
          srow
            ? <Specimen key={idOf(srow)} r={srow} people={people} />
            : <Empty title="왼쪽 목록에서 환자를 선택하세요"
                     hint="유방외과에서 검체를 채취하면 여기서 라벨을 확인하고 등록합니다" />
        ) : !cur
          ? <Empty title="왼쪽 목록에서 환자를 선택하세요" />
          : (
            <Body loading={detail.loading && !detail.data} error={detail.error}
                  onRetry={detail.reload}>
              {/* ⚠ key 로 오더를 건다. 안 걸면 다른 사람을 골라도 Detail 이
                  그대로 살아 있어서 **앞사람의 간호 메모·고른 의사가 다음
                  사람 칸에 남았다** — 그대로 [적어 두기]를 누르면 남의 메모가
                  이 사람 오더에 들어간다 */}
              {detail.data && (
                <Detail key={idOf(detail.data)}
                        cfg={cfg} d={detail.data} form={form.data} people={people}
                        load={load}
                        onSent={sent} onSaved={() => setTick((n) => n + 1)} />
              )}
            </Body>
          )}
      </div>

      <Load people={people} load={load} today={today} />
    </div>
  );

  return embedded ? body : (
    <Page crumb={[cfg.name, "내원 대기"]} title="내원 대기">{body}</Page>
  );
}

/* ── 왼쪽 330px — 탭 셋 ────────────────────────────────────────
 * 환자 줄은 세 줄이다(5.2).
 *
 *   박서연  47 · 여  [예약 · 결과 상담]
 *   P-2026-00418 · 09:05 접수
 *   문진 완료 · 배정 대기                        ← 어디까지 왔나
 *
 * ⚠ **셋째 줄에 검사 진행 점을 못 찍는다.** 이 큐는 촬영 전 환자만 모아서
 *   네 모달리티가 다 ○ 로 같아진다 — 문진 유무를 적는다(홈 현황판과 같은 기준).
 */
function Queue({ state, tab, setTab, lists, people, today, booked, pick, onPick }) {
  const rows = lists[tab];
  const nameOf = (id) => {
    const s = people.find((p) => String(staffId(p)) === String(id));
    return s ? staffName(s) : null;
  };
  return (
    <section className="nwait-q">
      <nav className="qtabs" aria-label="대기 구분">
        {TABS.map((t) => (
          <button type="button" key={t.key} className={`qtab${t.key === tab ? " on" : ""}`}
                  aria-pressed={t.key === tab} onClick={() => setTab(t.key)}>
            {t.label} <i>{lists[t.key].length}</i>
          </button>
        ))}
      </nav>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}
            empty={rows.length === 0 && (
              <Empty title={{ q: "문진을 기다리는 환자가 없습니다",
                              assign: "배정을 기다리는 환자가 없습니다",
                              specimen: "오늘 유방외과로 보낸 환자가 없습니다" }[tab]} />
            )}>
        <div className="nwait-q-b">
          {rows.map((r, i) => {
            const id = idOf(r);
            const on = String(id) === String(pick);
            return (
              <article key={id} className={`nrow${on ? " on" : ""}`}
                       role="button" tabIndex={0}
                       onClick={() => onPick(id)}
                       onKeyDown={(e) => { if (e.key === "Enter") onPick(id); }}>
                <i className="nrow-n">{i + 1}</i>
                <span className="nrow-tx">
                  <span className="nrow-1">
                    <b>{H.nameOf(r)}</b>
                    {H.who(r) && <span>{H.who(r)}</span>}
                    {r.visit_type && <Chip>{r.visit_type}</Chip>}
                  </span>
                  <span className="nrow-2">
                    {H.noOf(r) && <i>{H.noOf(r)}</i>}
                    {/* ⚠ 경과 시간이 아니라 접수 · 보낸 시각이다 */}
                    {tab === "specimen"
                      ? H.at(r.handed_at) && <time>{H.at(r.handed_at)} 보냄</time>
                      : H.at(r.visited_at) && <time>{H.at(r.visited_at)} 접수</time>}
                  </span>
                  <span className="nrow-3">
                    {tab === "specimen" ? (
                      <>
                        <span>→ {r.handed_to_name ?? nameOf(r.handed_to) ?? r.primary_staff_name ?? "유방외과"}</span>
                        {r.stage_detail && <span>{r.stage_detail}</span>}
                      </>
                    ) : (
                      <>
                        <span>{hasAnswers(r.questionnaire) ? "문진 완료 · 배정 대기" : "문진 대기"}</span>
                        {r.followup && <span>추적 관찰 건</span>}
                      </>
                    )}
                  </span>
                </span>
              </article>
            );
          })}
        </div>
      </Body>
      <Summary today={today} lists={lists} booked={booked} />
    </section>
  );
}

/* ── 왼쪽 아래 — 오늘 요약 ──────────────────────────────────────
 * 09-28 「줄이 둘뿐이면 왼쪽이 통째로 빈다」. 목록은 제 줄 수만큼만 서고
 * (hospital.css .nwait-q-b) 남는 자리에 오늘 하루의 수와 **아직 안 오신
 * 예약**을 둔다 — 창구가 다음에 전화할 사람이다.
 * ⚠ 수는 전부 서버 목록을 센 것이다 — 접수 · 보냄 · 검사는 today-status,
 *   문진 · 배정은 위 탭과 같은 목록. 지어낸 값이 없다.
 * ⚠ 안 오신 예약을 누르면 이 화면 위 찾기에 그 사람을 걸어 둔다(?find=).
 *   **접수는 사람이 누른다**(동명이인) */
const EXAM_STAGE = ["영상의학과 대기", "영상의학과 촬영중", "AI 분석중"];

function Summary({ today, lists, booked }) {
  const live = today.filter((r) => r.stage_code !== "cancelled" && r.order_status !== "cancelled");
  const nums = [
    ["오늘 접수", live.length],
    ["문진 대기", lists.q.length],
    ["배정 대기", lists.assign.length],
    ["유방외과로 보냄", lists.specimen.length],
    ["검사 진행", live.filter((r) => EXAM_STAGE.includes(r.stage)).length],
  ];
  const late = booked.filter((r) => H.isPast(r.scheduled_at)).length;
  return (
    <section className="nq-sum" aria-label="오늘 요약">
      <header className="bcol-h">
        <b>오늘 요약</b>
      </header>
      <dl className="nq-nums">
        {nums.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <p className="nq-sub">
        <b>미내원 예약</b>
        <span className="home-fill" />
        <span>{booked.length}명{late > 0 && ` · 시간 지남 ${late}`}</span>
      </p>
      <div className="nq-late">
        {booked.length === 0
          ? <p className="hcard-k hpad">오늘 남은 예약이 없습니다</p>
          : [...booked]
            .sort((a, b) => String(a.scheduled_at ?? "").localeCompare(String(b.scheduled_at ?? "")))
            .map((r) => {
              const find = H.noOf(r) ?? H.nameOf(r);
              return (
                <Link key={idOf(r) ?? `${r.patient}-${r.scheduled_at}`} className="nside-row"
                      to={`${go.nursing.intake()}?find=${encodeURIComponent(find)}`}
                      title="위 검색창에 넣습니다 — 접수하려면 [접수]를 누르세요">
                  <time>{H.at(r.scheduled_at) ?? "—"}</time>
                  <b>{H.nameOf(r)}</b>
                  <span className="home-fill" />
                  {H.isPast(r.scheduled_at) && <span>시간 지남</span>}
                </Link>
              );
            })}
      </div>
    </section>
  );
}

/* ── 문진 ────────────────────────────────────────────────────────
 * 저장 모양은 {form_version, answers:{코드: 선택지 id}} 다(서버 questionnaire.py).
 * 옛 자료는 {문항: 값} 을 통째로 들고 있다 — 둘 다 읽는다.
 *
 * ⚠ **⚠ 표시 기준 — 답이 「yes」(있다)인 문항.** v1 의 예 문항(증상 · 가족력 ·
 *   수술 이력)은 다 「있다」가 주의할 쪽이다. 정의가 `warn` 을 주면 그것을
 *   먼저 본다 — 문항이 늘어 「있다」가 괜찮은 쪽인 문항이 생기면 거기서 가른다.
 */
function answersOf(q) {
  if (!q || typeof q !== "object") return null;
  const a = q.answers && typeof q.answers === "object" ? q.answers : q;
  const out = Object.fromEntries(Object.entries(a).filter(([k]) => k !== "form_version"));
  return Object.keys(out).length ? out : null;
}
const hasAnswers = (q) => answersOf(q) != null;

function questionsOf(form) {
  const list = Array.isArray(form) ? form : form?.questions ?? form?.items ?? [];
  return Array.isArray(list) ? list : [];
}

function qaRows(answers, form) {
  const defs = new Map(questionsOf(form).map((q) => [q.code, q]));
  return Object.entries(answers ?? {}).map(([code, val]) => {
    const q = defs.get(code);
    const opt = (q?.options ?? []).find((o) => String(o.id) === String(val));
    const warn = q?.warn != null
      ? [].concat(q.warn).map(String).includes(String(val))
      : String(val) === "yes";
    return { code, label: q?.text ?? code, value: opt?.text ?? String(val), warn };
  }).sort((a, b) => Number(b.warn) - Number(a.warn));
}

/* ── 가운데 — 고른 환자 ────────────────────────────────────────
 * 머리(누구인가) · 방문 정보 · 문진 · 간호 메모 · **바닥 줄 = 배정과 보내기**.
 */
function Detail({ cfg, d, form, people, load, onSent, onSaved }) {
  const api = cfg.api;
  const id = idOf(d);
  const patientId = d.patient ?? d.patient_id;

  const full = useApi(
    () => (patientId ? H.soft(api.patient(patientId)) : Promise.resolve(null)),
    [patientId]);
  const p = full.data && !Array.isArray(full.data) ? full.data : null;

  const [note, setNote] = useState(d.order_note ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [modal, setModal] = useState(null);
  const [bound, setBound] = useState(null);
  const [paper, setPaper] = useState(false);

  const mayNote = can("nursing.waiting.assign");
  const mayAssign = can("nursing.waiting.assign");
  const allergy = H.allergy(p ?? d);
  const answers = answersOf(d.questionnaire);
  const qs = qaRows(answers, form);

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.saveNote(id, note);
      setMsg("메모를 저장했습니다");
    } catch (e) { setMsg(e.detail || e.message); }
    finally { setSaving(false); }
  }

  const patient = {
    patient_id: patientId, name: H.nameOf(d), age: d.age, sex: d.sex,
    patient_number: H.noOf(d),
  };

  return (
    <>
      <header className="ndet-h">
        <span className="ndet-ava" aria-hidden="true">{H.nameOf(d)[0]}</span>
        <span className="ndet-who">
          <span className="ndet-1">
            <b>{H.nameOf(d)}</b>
            {H.who(d) && <span>{H.who(d)}</span>}
          </span>
          <span className="ndet-2">
            {[H.noOf(d), p?.pii?.birth_date,
              H.at(d.visited_at) && `${H.at(d.visited_at)} 접수`]
              .filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="home-fill" />
        {/* 경고는 환자 띠와 같은 모양을 쓴다 — 같은 뜻에 이름을 또 만들지 않는다 */}
        {allergy && <span className="pb-warn"><i aria-hidden="true">⚠</i>{allergy}</span>}
        {d.visit_type && <Chip>{d.visit_type}</Chip>}
      </header>

      <div className="ndet-b">
        <section className="ndet-box">
          <h3>방문 정보</h3>
          <dl className="kv">
            <div><dt>방문 구분</dt><dd>{d.visit_type ?? "—"}</dd></div>
            <div><dt>연락처</dt><dd>{p?.pii?.phone ?? "—"}</dd></div>
            <div><dt>알레르기</dt><dd>{allergy ?? "표시 없음"}</dd></div>
            <div><dt>접수 메모</dt><dd>{d.order_note || "—"}</dd></div>
          </dl>
          <div className="rowb">
            {/* 검체는 보통 보낸 뒤(검체 확인 탭)다. 채취를 먼저 한 날을 위해 둔다 */}
            <Btn onClick={() => { setBound(null); setModal("specimen"); }}>검체 등록</Btn>
            <Btn to={go.patient(patientId)}>환자 기록</Btn>
          </div>
          {bound && <span className="hcard-k" role="status">{bound}</span>}
        </section>

        <section className="ndet-box">
          <h3>
            문진
            {answers ? <Chip>{d.questionnaire?.form_version ? "앱 · 창구 문진" : "작성 완료"}</Chip>
              : <Chip>없음</Chip>}
          </h3>
          {paper ? (
            <Paper cfg={cfg} pid={patientId} form={form}
                   onClose={() => setPaper(false)}
                   onDone={() => { setPaper(false); onSaved(); }} />
          ) : qs.length === 0 ? (
            <>
              <p className="hcard-k">앱으로 제출한 문진이 없습니다 — 종이 문진을 받았다면 입력해 주세요.</p>
              <Btn onClick={() => setPaper(true)} disabled={!can(["nursing.waiting.assign", "reception.intake.view"])}>
                종이 문진 입력
              </Btn>
            </>
          ) : (
            <dl className="kv nqa">
              {qs.map((r) => (
                <div key={r.code} className={r.warn ? "warn" : undefined}>
                  <dt>{r.warn && <i aria-hidden="true">⚠ </i>}{r.label}</dt>
                  <dd>{r.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {!paper && qs.length > 0 && !form && (
            <span className="hcard-k">문항 정보를 불러오지 못해 코드로 표시합니다</span>
          )}
        </section>

        <section className="ndet-box wide">
          <h3>간호 메모</h3>
          <textarea value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="인계할 내용" rows={2} disabled={!mayNote} />
          <div className="rowb">
            {msg && <span className="hcard-k">{msg}</span>}
            <Btn onClick={save} disabled={saving || !mayNote}>
              {saving ? "저장하는 중…" : "메모 저장"}
            </Btn>
          </div>
        </section>
      </div>

      {/* ⚠ picked 는 **환자의 주치의(primary_staff)** 다 — 재진이면 미리 골라
          둔다. 상세가 늦게 오므로 key 로 다시 세운다 */}
      <Assign key={`${id}-${p?.primary_staff ?? ""}`}
              cfg={cfg} orderId={id} picked={p?.primary_staff} people={people}
              load={load} may={mayAssign} onSent={() => onSent(id)} />

      {modal === "specimen" && (
        <SpecimenBindingModal patient={patient} onClose={() => setModal(null)}
                              onDone={() => { setModal(null); setBound("검체를 등록했습니다"); }} />
      )}
    </>
  );
}

/* ── 종이 문진 옮겨 적기 ─────────────────────────────────────────
 * 앱을 안 쓰는 분이 종이에 적어 온 것을 창구가 옮긴다. 서버가 환자 캐시와
 * **오늘 방문 오더** 둘 다에 쓴다 — 그래서 접수 줄이 「배정 대기」로 넘어간다.
 * ⚠ 문항 정의가 없으면 칸을 못 세운다. 코드를 손으로 치게 하지 않는다.
 * ⚠ 덜 채워도 저장된다(서버 validate) — 모르는 칸은 비워 둔다.
 */
function Paper({ cfg, pid, form, onClose, onDone }) {
  const qs = questionsOf(form).filter((q) => q.active !== false);
  const [ans, setAns] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  if (qs.length === 0) {
    return (
      <>
        <p className="note err">문항 정보를 불러오지 못해 입력란을 표시할 수 없습니다.</p>
        <Btn onClick={onClose}>닫기</Btn>
      </>
    );
  }

  async function save() {
    setBusy(true); setErr(null);
    try {
      await cfg.api.saveQuestionnaire(pid, ans);
      onDone();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="npaper">
      {qs.map((q) => (
        <div className="npaper-q" key={q.code}>
          <span>{q.text ?? q.code}</span>
          <div className="work-seg narrow" role="radiogroup" aria-label={q.text ?? q.code}>
            {(q.options ?? []).map((o) => (
              <button type="button" key={o.id} role="radio"
                      aria-checked={ans[q.code] === o.id}
                      className={`work-opt${ans[q.code] === o.id ? " on" : ""}`}
                      onClick={() => setAns((a) => ({ ...a, [q.code]: o.id }))}>
                {o.text ?? o.id}
              </button>
            ))}
          </div>
        </div>
      ))}
      {err && <p className="note err">{err}</p>}
      <div className="rowb">
        <Btn onClick={onClose} disabled={busy}>취소</Btn>
        <Btn kind="fill" onClick={save} disabled={busy || Object.keys(ans).length === 0}>
          {busy ? "저장하는 중…" : "문진 저장"}
        </Btn>
      </div>
    </div>
  );
}

/* ── 바닥 줄 — 유방외과 의사 배정 ────────────────────────────────
 * 칩을 고르고 [보내기]. 팝업을 띄우지 않는다.
 *
 * ⚠ **되돌릴 수 없다.** 고른 사람이 주치의가 되고 그 뒤로는 그 의사의
 *   화면에만 뜬다. 그래서 고르는 것과 보내는 것을 두 걸음으로 나눈다.
 * 칩의 「대기 n」은 today-status 의 handed_to 로 센 **보낸 뒤 아직 외래
 * 차례인 사람** 수다 — 한쪽으로 몰리는지 보고 고른다.
 */
function Assign({ cfg, orderId, picked, people, load, may, onSent }) {
  const [who, setWho] = useState(picked ?? null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function send() {
    if (!who || busy) return;
    setBusy(true);
    setErr(null);
    try {
      /* ⚠ 오더 번호로 보낸다 — 서버가 오더에 인계를 남기고 주치의도 바꾼다 */
      await cfg.api.handoff(orderId, who);
      onSent?.();
    } catch (e) { setErr(e.detail || e.message); setBusy(false); }
  }

  return (
    <footer className="ndet-f nassign">
      {/* 칸 이름을 단다 — 칩만 늘어서 있으면 「무엇을 고르는 줄」인지 안 읽힌다(09-28) */}
      <div className="nassign-h">
        <b>담당 의사 배정</b>
        <span className="hcard-k">의사를 선택한 뒤 보냅니다 · 숫자는 현재 대기 중인 환자 수</span>
      </div>
      {people.length === 0
        ? <span className="hcard-k">유방외과 의사 명단을 불러오지 못했습니다</span>
        : (
          <div className="ndocs" role="radiogroup" aria-label="유방외과 의사">
            {people.map((s) => {
              const id = staffId(s);
              const on = String(id) === String(who);
              const l = load.get(String(id));
              return (
                <button type="button" key={id} disabled={!may} role="radio"
                        className={`ndoc${on ? " on" : ""}`} aria-checked={on}
                        onClick={() => setWho(id)}>
                  <i aria-hidden="true" />
                  <b>{staffName(s)}</b>
                  <em>대기 {l?.wait.length ?? 0}</em>
                </button>
              );
            })}
          </div>
        )}
      <div className="nassign-go">
        {err ? <p className="note err">{err}</p>
          /* ⚠ 되돌릴 수 없다 — 9장이 남기라고 한 두 문구 중 하나다 */
          : <span className="hcard-k">보낸 뒤에는 되돌릴 수 없습니다 — 선택한 의사의 「내 환자」에만 표시됩니다</span>}
        <span className="home-fill" />
        <Btn kind="fill" onClick={send} disabled={!who || busy || !may}>
          {busy ? "보내는 중…" : "유방외과로 보내기"}
        </Btn>
      </div>
    </footer>
  );
}

/* ── 가운데(검체 확인 탭) — 보낸 환자의 검체 ─────────────────────
 * ⚠ **누가 검체가 필요한지는 모른다.** 채취는 유방외과 진료 뒤에 정해지고
 *   「채취했는데 안 이은 것」을 거르는 경로가 서버에 없다. 그래서 오늘 보낸
 *   사람을 전부 두고, 이 환자에게 이미 이은 검체를 같이 보여 판단하게 한다.
 */
function Specimen({ r, people }) {
  const pid = r.patient_id ?? r.patient;
  const list = useApi(() => (pid != null ? H.soft(specApi.list(pid)) : Promise.resolve([])), [pid]);
  const [modal, setModal] = useState(false);
  const [msg, setMsg] = useState(null);
  const items = H.rows(list.data);
  const to = r.handed_to_name
    ?? people.map((s) => (String(staffId(s)) === String(r.handed_to) ? staffName(s) : null)).find(Boolean)
    ?? r.primary_staff_name;
  const patient = { patient_id: pid, name: H.nameOf(r), age: r.age, sex: r.sex,
                    patient_number: H.noOf(r) };

  return (
    <>
      <header className="ndet-h">
        <span className="ndet-ava" aria-hidden="true">{H.nameOf(r)[0]}</span>
        <span className="ndet-who">
          <span className="ndet-1"><b>{H.nameOf(r)}</b>{H.who(r) && <span>{H.who(r)}</span>}</span>
          <span className="ndet-2">
            {[H.noOf(r), to && `→ ${to}`, H.at(r.handed_at) && `${H.at(r.handed_at)} 보냄`]
              .filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="home-fill" />
        {r.stage_detail && <Chip>{r.stage_detail}</Chip>}
      </header>
      <div className="ndet-b one">
        <section className="ndet-box wide">
          <h3>이 환자에게 등록된 검체 <Chip>{items.length}</Chip></h3>
          <Body loading={list.loading && !list.data} error={list.error} onRetry={list.reload}
                empty={items.length === 0 && <p className="hcard-k">아직 등록된 검체가 없습니다</p>}>
            <dl className="kv">
              {items.map((s, i) => (
                <div key={s.specimen_id ?? s.id ?? i}>
                  <dt>{s.specimen_label ?? s.label ?? `검체 ${i + 1}`}</dt>
                  <dd>{[s.specimen_type, s.status, H.day(s.collected_at)].filter(Boolean).join(" · ")}</dd>
                </div>
              ))}
            </dl>
          </Body>
          <p className="hcard-k">
            채취 여부는 유방외과 진료에서 정합니다 — 라벨을 확인하고 등록해야 병리과로 넘어갑니다.
          </p>
        </section>
      </div>
      <footer className="ndet-f">
        {msg && <span className="hcard-k" role="status">{msg}</span>}
        <span className="home-fill" />
        <Btn to={go.patient(pid)}>환자 기록</Btn>
        <Btn kind="fill" onClick={() => { setMsg(null); setModal(true); }}
             disabled={!can(["nursing.waiting.assign", "nursing.waiting.view"])}>검체 등록</Btn>
      </footer>
      {modal && (
        <SpecimenBindingModal patient={patient} onClose={() => setModal(false)}
                              onDone={() => { setModal(false); setMsg("검체를 등록했습니다"); list.reload(true); }} />
      )}
    </>
  );
}

/* ── 오른쪽 380px — 배정 현황(오늘) ─────────────────────────────
 * 선생님마다 **상자 하나** — 이름 · 지금 외래 차례로 기다리는 수 · 오늘 보낸
 * 수를 큰 숫자로, 기다리는 사람은 이름 칩으로. 줄글(「김서연 · 박하은 · …」)
 * 이던 것이 한눈에 안 읽힌다는 말을 들었다(09-28).
 * ⚠ 「미배정」 줄은 뺐다 — 왼쪽 문진 · 배정 탭의 숫자와 같은 말이다(09-28).
 * ⚠ 09-28 전에는 「금일 내원 예정 · 오늘 추적 콜」을 두었다 — 홈과 같은 줄이라
 *   뺐다. 「검체 바인딩 필요」 칸은 늘 비어 있어서 왼쪽 검체 확인 탭이 됐다.
 */
function Load({ people, load, today }) {
  const known = new Set(people.map((s) => String(staffId(s))));
  /* 명단에 없는데 보낸 기록이 있는 사람(퇴사 · 다른 과 등)도 상자를 세운다 */
  const extra = [...load.entries()].filter(([k]) => !known.has(k));
  const rows = [
    ...people.map((s) => ({ key: String(staffId(s)), name: staffName(s), l: load.get(String(staffId(s))) })),
    ...extra.map(([k, l]) => ({ key: k, name: l.name ?? `직원 ${k}`, l })),
  ];

  return (
    <div className="nwait-side">
      <section className="nside fit">
        <header className="bcol-h">
          <i className="hdot ring" aria-hidden="true" />
          <b>배정 현황(오늘)</b>
          <span className="home-fill" />
          <span className="hcard-k">의사별</span>
        </header>
        <div className="nside-b nload-grid">
          {rows.length === 0 && <p className="hcard-k hpad">의사 명단을 불러오지 못했습니다</p>}
          {rows.map(({ key, name, l }) => {
            const wait = l?.wait ?? [];
            return (
              <article className="nload-box" key={key}>
                <header className="nload-h">
                  <b>{name}</b>
                  <span className="home-fill" />
                  <span className="nload-stat">
                    <em>{wait.length}</em><i>대기</i>
                  </span>
                  <span className="nload-stat muted">
                    <em>{l?.sent ?? 0}</em><i>오늘 보냄</i>
                  </span>
                </header>
                {wait.length > 0
                  ? (
                    <ul className="nload-chips">
                      {wait.map((r) => <li key={idOf(r)}>{H.nameOf(r)}</li>)}
                    </ul>
                  )
                  : <p className="nload-empty">대기 환자 없음</p>}
              </article>
            );
          })}
        </div>
      </section>
      <Sent today={today} />
    </div>
  );
}

/* ── 오른쪽 아래 — 오늘 보낸 환자 ─────────────────────────────────
 * 09-28 배정 현황 밑이 통째로 비었다. 오늘 유방외과로 보낸 사람을 **보낸
 * 시각 최신순**으로 — 「방금 누구를 누구에게 보냈나」를 창구에서 되짚는
 * 자리다. 왼쪽 「검체 확인」 탭과 같은 목록(handed_at)이고, 이쪽은 누르면
 * 환자 상세로 간다. 단계는 서버 말(stage) 그대로 */
function Sent({ today }) {
  const rows = today.filter(handed)
    .sort((a, b) => String(b.handed_at ?? "").localeCompare(String(a.handed_at ?? "")));
  return (
    <section className="nside">
      <header className="bcol-h">
        <i className="hdot ink" aria-hidden="true" />
        <b>오늘 보낸 환자</b>
        <em>{rows.length}</em>
        <span className="home-fill" />
        <span className="hcard-k">최근 순</span>
      </header>
      <div className="nside-b">
        {rows.length === 0
          ? <p className="hcard-k hpad">오늘 유방외과로 보낸 환자가 아직 없습니다</p>
          : rows.map((r) => {
            const pid = r.patient_id ?? r.patient;
            const body = (
              <>
                <time>{H.at(r.handed_at) ?? "—"}</time>
                <b>{H.nameOf(r)}</b>
                <span className="nsent-to">→ {r.handed_to_name ?? r.primary_staff_name ?? "유방외과"}</span>
                <span className="home-fill" />
                {r.stage && <span>{label(ORDER_STATUS, r.stage)}</span>}
              </>
            );
            return pid != null
              ? <Link key={idOf(r)} className="nside-row" to={go.patient(pid)}>{body}</Link>
              : <p key={idOf(r)} className="nside-row">{body}</p>;
          })}
      </div>
    </section>
  );
}
