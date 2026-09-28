import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip } from "../../../lib/Parts";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";
import ExamOrderModal from "../components/ExamOrderModal";
import CloseVisitModal from "../components/CloseVisitModal";
import CareGuideModal from "../components/CareGuideModal";
import BookVisitModal from "../components/BookVisit";
import { FlowBar } from "../components/Stepper";
import { PathRows, PendingLine, RadRows } from "../components/Results";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";
import { isHandled, markHandled, unmarkHandled } from "../handled";
import { historyDetail, historyTo } from "../history";
import { NEXT, flowOf } from "../flow";

/* 유방외과 · 대기 환자 — `docs/mockup/Surgery.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **이 과의 본진이다.** 집는 절차가 없다 — 주치의로 배정된 환자가 곧
 * 큐다. 고르고 · 읽고 · 다음 할 일로 넘기는 것이 한 화면에서 끝난다.
 *
 *   ┌ 300px ──┬ 1fr ─────────────────────────┬ 330px ──┐
 *   │ 대기     │ 김민지  47 · 여                │ 진료 이력│
 *   │ [탭]     │ ✓접수 ✓오더 ✓촬영 ✓판독 ● 불일치…│  09-21  │
 *   │  · 김민지│ 다음 할 일 · 불일치 처분         │  09-11  │
 *   │  · 이서준│ [촬영][검체][상세][방침][완료]   │         │
 *   │ ▸ 결과대기│ ┌영상 판독─┬병리 판독─┐        │         │
 *   └──────────┴───────────────────────────────┴─────────┘
 *
 * 다음 할 일은 flow.js 가 센다. 서버 worklist 가 있으면 그 next_step,
 * 없으면 고른 환자의 상세 · 이력 · 처방으로 되짚는다.
 *
 * ⚠ **주 단추는 하나다** — 다음 할 일. 단추 줄은 진료 순서대로 늘어놓고
 *   그중 다음 할 일만 채운다. 불일치가 열린 동안 「진료 완료」는 주 단추가
 *   아니다(09-28).
 * ⚠ **경과 시간을 안 쓴다.** 목업 줄 끝의 `1h52m` `27′` 은 서버가 주지
 *   않는다.
 * ⚠ **칸을 카드로 띄우지 않는다.** 단을 1px 선으로 가른다(4.5).
 * ⚠ **색으로 뜻을 나르지 않는다.** BI-RADS 는 글자로 적는다.
 * ⚠ 09-28 — 오른쪽 「결정 사유 상용구」 단을 뺐다. 누르면 아무 데도 안
 *   붙는 글이었다. 상용구는 치료 방침의 결정 사유 칸 위 칩으로 옮겼다 —
 *   누르면 그 칸에 들어간다.
 */
export default function Waiting() {
  const nav = useNavigate();
  const [q, setQ] = useSearchParams();
  const want = q.get("next");               /* 홈 「진료 흐름」에서 온 거르개 */
  const list = useApi(() => api.waiting(), []);
  /* 서버 worklist — 없으면(404 · 옛 서버) null 로 두고 되짚는다 */
  const wl = useApi(() => api.worklist().catch(() => null), []);
  const [tab, setTab] = useState("all");
  const [pick, setPick] = useState(null);
  const [modal, setModal] = useState(null);
  const [examModality, setExamModality] = useState(null);
  const [openWait, setOpenWait] = useState(false);
  const [, bump] = useState(0);              /* handled.js 가 바뀌면 다시 그린다 */

  const items = useMemo(() => {
    const m = new Map();
    for (const it of H.rows(wl.data)) m.set(String(it.patient_id), it);
    return m;
  }, [wl.data]);
  const hasWl = wl.data != null && Array.isArray(H.rows(wl.data));

  const rows = H.rows(list.data);
  const itemOf = (r) => items.get(String(r.patient_id)) ?? null;
  /* 결과 대기 — 서버가 세면 그것, 없으면 오늘 다른 과로 넘긴 기록(handled.js) */
  const waitingOn = (r) => (hasWl && itemOf(r)
    ? itemOf(r).next_step === "wait_results"
    : isHandled(r.patient_id));
  const active = rows.filter((r) => !waitingOn(r));
  const parked = rows.filter(waitingOn);
  const odd = active.filter((r) => r.has_open_discordance || itemOf(r)?.open_discordance);
  const byNext = want ? rows.filter((r) => itemOf(r)?.next_step === want) : null;
  const shown = byNext ?? (tab === "odd" ? odd : active);
  const pool = [...shown, ...(byNext ? [] : parked)];
  const picked = pool.some((r) => r.patient_id === pick)
    ? pick : (shown[0]?.patient_id ?? parked[0]?.patient_id ?? null);

  const detail = useApi(
    () => (picked ? api.patient(picked) : Promise.resolve(null)), [picked]);
  const line = useApi(
    () => (picked ? H.soft(api.timeline(picked)) : Promise.resolve([])), [picked]);
  const rx = useApi(
    () => (picked ? api.prescriptions(picked).catch(() => undefined) : Promise.resolve(undefined)), [picked]);

  const p = detail.data;
  const flow = useMemo(() => (p ? flowOf({
    p, item: itemOf({ patient_id: p.patient_id }), timeline: H.rows(line.data), rx: rx.data,
  }) : null), [p, line.data, rx.data, items]);   // eslint-disable-line react-hooks/exhaustive-deps

  /* 결과가 돌아왔다 — 되짚은 흐름이 대기를 벗어나면 묶음에서 올린다 */
  useEffect(() => {
    if (!hasWl && p && flow?.next && flow.next.key !== "wait_results" && isHandled(p.patient_id)) {
      unmarkHandled(p.patient_id);
      bump((n) => n + 1);
    }
  }, [hasWl, p, flow]);

  /* 치료 방침에서 「다음 환자」로 왔다(state.advance) — 방금 본 사람 다음 줄을 편다 */
  const loc = useLocation();
  const from = loc.state?.advance ? String(loc.state.from ?? "") : null;
  useEffect(() => {
    if (!from || pick != null || !shown.length) return;
    const i = shown.findIndex((r) => String(r.patient_id) === from);
    if (i >= 0 && shown.length > 1) setPick(shown[(i + 1) % shown.length].patient_id);
  }, [from, shown.length]);   // eslint-disable-line react-hooks/exhaustive-deps

  function next() {
    const i = shown.findIndex((r) => r.patient_id === picked);
    if (shown.length > 0) setPick(shown[(i + 1) % shown.length].patient_id);
  }

  /* 다음 할 일 실행 — 팝업이면 열고, 화면이면 간다 */
  function run(n) {
    if (!n) return;
    if (n.act === "exam") { setExamModality(n.modality); setModal("exam"); }
    else if (n.act) setModal(n.act);
    else if (n.to) nav(n.to);
  }

  const sent = () => {
    markHandled(p.patient_id);
    setModal(null); setPick(null);
    detail.reload(true); list.reload(true); wl.reload(true);
  };

  return (
    <Page className="surgery-page" crumb={["유방외과", "대기 환자"]}
          title="대기 환자"
          right={<Btn to={go.breast.patients()}>전체 환자</Btn>}>
      <div className="work bf-work">
        <Queue state={list} rows={shown} parked={byNext ? [] : parked} odd={odd} all={active}
               tab={tab} onTab={setTab} pick={picked} onPick={setPick}
               itemOf={itemOf} openWait={openWait} onOpenWait={setOpenWait}
               want={want} onClearWant={() => { q.delete("next"); setQ(q, { replace: true }); }} />

        <div className="work-mid">
          {!picked
            ? <Empty title="지금 기다리는 환자가 없습니다" />
            : (
              <Body loading={detail.loading && !detail.data} error={detail.error}
                    onRetry={detail.reload}>
                {p && (
                  <Mid p={p} flow={flow} onNext={next} onRun={run} onOpen={setModal}
                       waiting={waitingOn(p)} />
                )}
              </Body>
            )}
        </div>

        <History id={picked} line={line} />
      </div>

      {/* ⚠ **팝업만 .breast 안에 넣는다.** breast.css 는 --ink · --line-2 ·
          --gap 을 제 값으로 덮어쓴다(그 파일 머리에 적혀 있다). 쪽 전체를
          .breast 로 열면 새로 짠 이 화면이 hospital 토큰 대신 저쪽 팔레트를
          조용히 집어 간다 — 팝업만 저 규칙으로 그려져서 그것만 싼다 */}
      {modal && p && (
        <div className="breast">
          {modal === "exam" && (
            <ExamOrderModal patient={p} initialModality={examModality}
                            onClose={() => setModal(null)} onDone={sent} />
          )}
          {modal === "specimen" && (
            <SpecimenBindingModal patient={p} onClose={() => setModal(null)} onDone={sent} />
          )}
          {modal === "close" && (
            <CloseVisitModal patient={p} suggest={suggestDays(flow)}
                             onClose={() => setModal(null)}
                             onDone={() => { setModal(null); next(); list.reload(true); wl.reload(true); }} />
          )}
          {modal === "book" && (
            <BookVisitModal patient={p} suggest={suggestDays(flow)}
                            onClose={() => setModal(null)} />
          )}
          {modal === "guide" && (
            <CareGuideModal patient={p} flow={flow} onClose={() => setModal(null)}
                            onRun={(n) => { setModal(null); run(n); }} />
          )}
        </div>
      )}
    </Page>
  );
}

/* 재진 권하는 간격 — BI-RADS 3 은 6개월 추적, 그 밖은 2주 */
function suggestDays(flow) {
  return flow?.facts?.grade === "3" ? 182 : 14;
}

/* ── 왼쪽 300px — 대기 ─────────────────────────────────────────
 * 탭 둘(대기 · 불일치) + 아래 접힌 「결과 대기」 묶음.
 *
 * ⚠ **`patients()` 가 아니라 `waiting()` 을 부른다.** `has_open_discordance`
 *   는 `status=waiting` 쪽에만 붙어 온다. `patients()` 로 받으면 불일치
 *   탭이 **말없이 늘 0** 이 된다.
 * ⚠ 결과 대기 묶음은 **숨기지 않는다**(handled.js 머리말). 같은 날 결과가
 *   돌아오면 위로 다시 올라온다.
 */
const TABS = [
  { key: "all", label: "대기" },
  { key: "odd", label: "불일치" },
];

function Queue({ state, rows, parked, all, odd, tab, onTab, pick, onPick, itemOf,
                 openWait, onOpenWait, want, onClearWant }) {
  const count = { all: all.length, odd: odd.length };
  const onParked = parked.some((r) => r.patient_id === pick);
  return (
    <aside className="work-q">
      <header className="work-q-h">
        <h2>대기 환자</h2>
        {want ? (
          <div className="bf-want">
            <span>{NEXT[want]?.name ?? want} · {rows.length}명</span>
            <button type="button" className="btn line sm" onClick={onClearWant}>전체 보기</button>
          </div>
        ) : (
          <div className="work-tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.key} type="button" role="tab"
                      aria-selected={t.key === tab}
                      className={`work-tab${t.key === tab ? " on" : ""}`}
                      onClick={() => onTab(t.key)}>
                {t.label} <i>{count[t.key]}</i>
              </button>
            ))}
          </div>
        )}
      </header>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}>
        <div className="work-q-b">
          {rows.length === 0 && (
            <p className="bf-q-none">
              {want ? "해당하는 환자가 없습니다" : tab === "odd" ? "판정 불일치 환자가 없습니다" : "지금 기다리는 환자가 없습니다"}
            </p>
          )}
          {rows.map((r) => (
            <QRow key={r.patient_id} r={r} it={itemOf(r)} on={r.patient_id === pick} onPick={onPick} />
          ))}
          {parked.length > 0 && (
            <div className="bf-park">
              <button type="button" className="bf-park-h" aria-expanded={openWait || onParked}
                      onClick={() => onOpenWait(!(openWait || onParked))}>
                <i aria-hidden="true">{openWait || onParked ? "▾" : "▸"}</i>
                결과 대기 <em>{parked.length}</em>
                <span className="home-fill" />
                <small>영상 · 병리로 넘긴 환자</small>
              </button>
              {(openWait || onParked) && parked.map((r) => (
                <QRow key={r.patient_id} r={r} it={itemOf(r)} on={r.patient_id === pick}
                      onPick={onPick} dim />
              ))}
            </div>
          )}
        </div>
      </Body>
    </aside>
  );
}

function QRow({ r, it, on, onPick, dim = false }) {
  const odd = r.has_open_discordance || it?.open_discordance;
  const say = it?.next_step ? NEXT[it.next_step]?.name : odd ? "판정 불일치" : (r.status ?? "");
  return (
    <button type="button"
            className={`work-row${on ? " on" : ""}${dim ? " bf-dim" : ""}`}
            onClick={() => onPick(r.patient_id)}>
      <span className="work-row-1">
        <i className={`work-dot${odd ? " k1" : ""}`} aria-hidden="true" />
        <b>{H.nameOf(r)}</b>
        {H.who(r) && <span>{H.who(r)}</span>}
        {(H.allergy(r) || it?.has_allergy) && <em className="bf-q-flag">알레르기</em>}
      </span>
      <span className="work-row-2">
        {H.noOf(r) && <i>{H.noOf(r)}</i>}
        <span>{say}</span>
      </span>
    </button>
  );
}

/* ── 가운데 — 고른 환자 ───────────────────────────────────────── */
function Mid({ p, flow, onNext, onRun, onOpen, waiting }) {
  const d = p.open_discordance;
  const readings = p.readings ?? { radiology: [], pathology: [] };
  const key = flow?.next?.key;
  /* 단추 줄 — 진료 순서대로. 다음 할 일과 맞는 것 하나만 채운다 */
  const primary = (k) => (k === key ? "fill" : "line");
  const exam = key === "exam" ? (flow.next.act === "specimen" ? "specimen" : "exam") : null;

  return (
    <>
      {p.data_warnings?.length > 0 && (
        <p className="warnline">
          일부 자료를 불러오지 못했습니다: {p.data_warnings.join(", ")}. 새로고침 후 다시 확인해 주세요.
        </p>
      )}
      <header className="work-head">
        <span className="work-ava" aria-hidden="true">{H.nameOf(p)[0]}</span>
        <span className="work-who">
          <span className="work-1">
            <b>{H.nameOf(p)}</b>
            {H.who(p) && <span>{H.who(p)}</span>}
          </span>
          <span className="work-2">
            {[H.noOf(p), p.visit_type, waiting ? "결과 대기" : null].filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="home-fill" />
        {H.some(p.family_history) && <Chip>가족력 {H.some(p.family_history)}</Chip>}
        {H.some(p.allergy) && <span className="pb-warn"><i aria-hidden="true">⚠</i>{H.some(p.allergy)}</span>}
        <Btn onClick={() => onOpen("guide")}>다음 단계 안내</Btn>
      </header>

      {/* ⚠ 되돌릴 수 없는 갈림길이라 맨 위에 둔다 — 영상과 병리가 엇갈린
          채로 치료 방침을 정하면 안 된다 */}
      {d && (
        <Link to={go.breast.discordance(d.discordance_id)} className="work-odd">
          <i aria-hidden="true">⚠</i>
          <span><b>판정 불일치</b> · {d.violated_rule}</span>
          <span className="home-fill" />
          <b>처분하기 →</b>
        </Link>
      )}

      <FlowBar flow={flow} run={onRun} button={false} />

      <div className="work-foot">
        <Btn kind={exam === "exam" ? "fill" : "line"} onClick={() => onRun({ act: "exam", modality: flow?.next?.modality })}>촬영 요청</Btn>
        <Btn kind={exam === "specimen" ? "fill" : "line"} onClick={() => onOpen("specimen")}>검체 등록</Btn>
        <Btn kind={primary("review")} to={go.breast.review(p.patient_id)}>환자 상세</Btn>
        {d && <Btn kind={primary("discordance")} to={go.breast.discordance(d.discordance_id)}>불일치 처분</Btn>}
        <Btn kind={["report", "decision", "explain", "prescription"].includes(key) ? "fill" : "line"}
             to={go.breast.decision(p.patient_id, ["report", "decision", "explain", "prescription"].includes(key) ? key : null)}>
          {["report", "explain", "prescription"].includes(key) ? flow.next.label : "치료 방침"}
        </Btn>
        <Btn kind={primary("close")} onClick={() => onOpen("close")}>진료 완료</Btn>
        <Btn kind={primary("followup")} onClick={() => onOpen("book")}>재진 예약</Btn>
        <span className="home-fill" />
        <Btn kind={key === "wait_results" ? "fill" : "line"} onClick={onNext}>다음 환자 →</Btn>
      </div>

      <div className="work-reads">
        <section className="work-read">
          <header>
            <h3>영상 판독</h3>
            <span className="home-fill" />
            <span className="hcard-k">{readings.radiology.length}건 확정</span>
          </header>
          <PendingLine orders={p.orders} />
          <RadRows rows={readings.radiology} />
        </section>
        <section className="work-read">
          <header>
            <h3>병리 판독</h3>
            <span className="home-fill" />
            <span className="hcard-k">{readings.pathology.length}건 확진</span>
          </header>
          <PathRows rows={readings.pathology} />
        </section>
      </div>
    </>
  );
}

/* ── 330px — 진료 이력 ─────────────────────────────────────────
   `/patients/{id}/timeline` 이 이 칸의 전부다. 최근 것이 위로 온다.
   흐름(flow.js)도 같은 이력을 읽어서 부르는 쪽(Waiting)에서 받아 온다.

   ⚠ **줄마다 누르는 자리다.** 누르면 환자 상세가 그 건의 판독을 펴서
     연다. 치료 결정 · 리포트 · 결과 설명 · 처방은 치료 방침의 그 칸으로 간다 */
function History({ id, line }) {
  const nav = useNavigate();
  const rows = [...H.rows(line.data)].reverse();

  return (
    <section className="work-hist">
      <header className="bcol-h">
        <i className="hdot ring" aria-hidden="true" />
        <b>진료 이력</b>
        <em>{rows.length}</em>
      </header>
      <div className="work-hist-b">
        {rows.length === 0
          ? <p className="hcard-k hpad">{line.loading ? "불러오는 중…" : "아직 없습니다"}</p>
          : rows.map((r, i) => {
            const to = historyTo(id, r);
            const open = () => nav(to);
            const say = historyDetail(r);
            return (
              <article className="work-ev" key={`${r.at}-${i}`}
                       role="button" tabIndex={0}
                       aria-label={`${H.day(r.at) ?? ""} ${r.type} 기록 보기`}
                       onClick={open}
                       onKeyDown={(e) => { if (e.key === "Enter") open(); }}>
                <div className="work-ev-h">
                  <time>{H.day(r.at)}</time>
                  <Chip>{r.type}</Chip>
                  <span className="home-fill" />
                  <i className="work-ev-go" aria-hidden="true">›</i>
                </div>
                {say && <p>{say}</p>}
              </article>
            );
          })}
      </div>
    </section>
  );
}
