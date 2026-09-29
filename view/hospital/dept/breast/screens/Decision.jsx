import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { breast as api, currentAssessment } from "../../../api";
import { REPORT_DEPT, SEX, label } from "../../../codes";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { useCan } from "../../../lib/Parts";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";   /* 유방외과 전용 — .breast 안에 갇혀 있다. 네 화면이 각자
                             끌고 온다: 주소로 곧장 들어와도 스타일이 빠지면 안 된다 */
import CloseVisitModal from "../components/CloseVisitModal";
import { BookForm } from "../components/BookVisit";
import FollowupRounds from "../components/FollowupRounds";
import PrescriptionDraft from "../components/Prescription";
import { CondList, LockPanel } from "../components/Unlock";
import { ruleText, unlockConds } from "../unlock";
import { PathRows, PendingLine, RadRows } from "../components/Results";
import { lesionText } from "../results";
import { flowOf } from "../flow";

/* 서버 DECISION_VALUE 그대로다(2026-09-18 확인, models.py:80) — "수술함/
 * 안 함/보류"라는 세 갈래를 우리가 새로 지은 게 아니라 서버 값이다.
 * decision_type 은 이 화면이 늘 "surgery" 하나로 고정해 보낸다 — 다른
 * 값(biopsy·imaging·rebiopsy)은 이 화면에서 다루는 결정이 아니다. */
const DECISIONS = [
  { v: "yes",   label: "수술 시행" },
  { v: "no",    label: "수술하지 않음" },
  { v: "defer", label: "보류" },
];
const EXPLAIN_METHODS = ["대면", "유선", "영상"];

/* 결정 사유 상용구 — 누르면 사유 칸 끝에 붙는다.
 * ⚠ **서버가 주는 값이 아니다.** 상용구를 저장하는 경로가 없다 — 화면에
 *   박아 둔 글이다(목업의 세 묶음). */
const PHRASES = [
  ["수술", ["단일 병변, 유방보존술 가능", "다발성 병변으로 전절제 고려"]],
  ["추가 검사", ["병변 범위 평가 위해 MRI 시행", "표적 미포함 의심, 재조직검사"]],
  ["보류 · 추적", ["환자 상의 후 재내원", "6개월 추적 관찰"]],
];

/* 화면 3 · 치료 방침 ("/patients/:id/decision") — 한 쪽에서 위아래로 한 번
 * ════════════════════════════════════════════════════════════════
 *
 *   ┌ 1fr ─────────────────────────────────┬ 320px (붙박이) ────────┐
 *   │ ① 결과 요약            (읽기 전용)      │ 환자 · 알레르기         │
 *   │ ② 판정 불일치          (열리면 문)      │ 진료 단계 목차(①~⑦)     │
 *   │ ③ AI 종합 리포트 · 의사 종합 소견       │   번호 · 제목 · 상태 ·  │
 *   │ ④ 수술 여부            (저장된 값을 편다)│   한 줄 요약 — 누르면 │
 *   │ ⑤ 환자 설명 → 잠금 해제                │   그 카드로 내려간다    │
 *   │ ⑥ 처방                                │ 다음 할 일              │
 *   │ ⑦ 진료 완료 · 재진 예약 · 추적          │ 잠금 조건 셋(까닭 · 할 일)│
 *   └───────────────────────────────────────┴───────────────────────┘
 *
 * ⚠ 09-28 사용자 의견 — 「플로우별로 가로로 구성되어 있어 가독성이 떨어진다.
 *   진료 단계를 한 페이지에서 확인할 수 있게」. 오른쪽에 있던 열두 칸짜리
 *   흐름 줄(접수 · 문진 → … → 추적)을 뺐다 — 이 화면에서 손대는 것은 ①~⑦
 *   이고, 앞 단계(접수 · 촬영 · 판독 · 병리)는 ① 결과 요약이 말한다. 목차의
 *   줄 하나와 카드 머리 하나가 **같은 번호 · 같은 상태 · 같은 요약**을 쓴다
 *   (steps 한 벌에서 둘 다 그린다).
 * ⚠ 끝난 카드는 접힌다(머리만 — 번호 · 제목 · 상태 · 한 줄 요약). ① · ③ 은
 *   결정의 재료라 끝나도 펴 둔다. 머리를 누르면 편다.
 * ⚠ **판정 불일치가 열려 있으면 ④ ~ ⑥ 을 잠근다.** 엇갈린 채로 방침을
 *   정하면 안 된다 — 서버의 잠금 해제 조건 ②(대조 종결)와 같은 말이다.
 * ⚠ 잠금 해제 3조건은 서버가 판단한다(GET /reports/{id}/unlock-status).
 *   **환자용 번호**로 묻는다 — 환자가 읽는 벌이 그것이다(components/Unlock.jsx).
 * ⚠ **목업의 「수술 계획」 칸(술식·측·수술 예정일·집도)은 못 만든다.**
 *   그 값을 받는 경로가 서버에 없다.
 *
 * 진료 이력의 치료 결정 · 리포트 · 결과 설명 · 처방 줄에서 오면 ?focus= 가
 * 붙는다(dept/breast/history.js — decision · report · patient-report ·
 * explain · prescription). 그 칸을 펴고(id="dec-…") 그리로 내려간다. */
export default function Decision() {
  const { id } = useParams();
  const nav = useNavigate();
  const [q] = useSearchParams();
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);
  const back = () => nav(go.breast.waiting(), { state: { advance: true, from: id } });

  return (
    /* 되돌릴 수 없는 결정을 저장하는 화면이다. **누구인지 안 보이면 안 된다** */
    <Page className="breast" crumb={["유방외과", "치료 방침"]}
            title="치료 방침" patient={patient} back={back}>
      <div className="pane">
        <Body loading={loading && !patient} error={error} onRetry={reload}>
          {patient && <Inner key={patient.patient_id} patient={patient} onReload={() => reload(true)}
                             focus={q.get("focus")} onNextPatient={back} />}
        </Body>
      </div>
    </Page>
  );
}

const day = (v) => (v ? String(v).slice(0, 10) : null);
const upper = (v) => (v == null ? null : String(v).toUpperCase());

/* ?focus= 값 → 카드. patient-report 는 ⑤ 안의 칸이다 */
const FOCUS_CARD = { "patient-report": "explain" };

const WRITING_POLL = 4000;          /* 소견문 채워졌나 보는 박자 */
const WRITING_MAX = 180000;         /* 3분 넘으면 멈추고 [다시 확인] */

function Inner({ patient, onReload, focus, onNextPatient }) {
  const pid = patient.patient_id;
  const report = patient.report;                           /* 의사용 — ③ 이 읽고 쓴다 */
  const target = patient.patient_report ?? report;         /* 환자용 — ⑤ 설명 · 잠금 해제 */
  const targetId = target?.report_id ?? null;
  const reports = useApi(() => api.reports(pid), [pid]);

  /* 종합 리포트 — 행은 바로 서고 소견문(narrative)은 리포트 서버가 뒤에
     채운다(수십 초). ⚠ 09-29 전에는 「잠시 뒤 새로고침해 주세요」라고만 했다.
     소견문이 빈 리포트가 있는 동안은 여기서 조용히 다시 불러 채워지는 순간
     뜨게 한다. 너무 오래 걸리면(WRITING_MAX) 멈추고 [다시 확인]을 준다 —
     서버가 실패해 영영 안 채워지는 리포트를 끝없이 두드리지 않게 */
  const writing = Boolean(report && !report.ai_summary);
  const [waited, setWaited] = useState(0);
  useEffect(() => { setWaited(0); }, [report?.report_id]);
  useEffect(() => {
    if (!writing || waited >= WRITING_MAX) return undefined;
    const t = setTimeout(() => {
      onReload();
      reports.reload(true);
      setWaited((n) => n + WRITING_POLL);
    }, WRITING_POLL);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [writing, waited]);
  const writingLate = writing && waited >= WRITING_MAX;
  const unlock = useApi(
    () => (targetId ? api.unlockStatus(targetId) : Promise.resolve(null)),
    [targetId],
  );
  const timeline = useApi(() => api.timeline(pid), [pid]);
  const saved = useApi(() => api.prescriptions(pid), [pid]);
  const [closing, setClosing] = useState(false);

  const events = H.rows(timeline.data);
  const flow = useMemo(() => flowOf({ p: patient, timeline: events, rx: saved.data ?? undefined }),
    [patient, events, saved.data]);
  const blocked = Boolean(patient.open_discordance);

  /* 수술 결정은 assessment 한 건에 매달린다(models.py:675 — study 에 물려
   * 있다). 확정(final) 「판독」 줄만 본다 — 초안에 결정을 걸면 확정 판독이
   * 오면서 결정이 사라진다. read_stage 가 없는 옛 줄은 확정으로 친다. 그
   * 검사의 판 목록에서 **지금 유효한 판**을 다시 고른다 */
  const finals = events.filter((e) => e.type === "판독" && e.assessment_id != null
    && (e.read_stage == null || e.read_stage === "final"));
  const lastRead = finals.at(-1) ?? null;
  const cur = useApi(
    () => (lastRead?.study_id != null ? api.assessments(lastRead.study_id).then(H.rows) : Promise.resolve([])),
    [lastRead?.study_id ?? null],
  );
  const current = currentAssessment(H.rows(cur.data)) ?? null;
  const assessmentId = current?.assessment_id ?? lastRead?.assessment_id ?? null;
  const lastDecided = [...events].reverse().find((e) => e.type === "치료 결정") ?? null;
  const savedDecision = current?.decision_value
    ? { value: current.decision_value, reason: current.decision_reason ?? "", at: current.decided_at }
    : lastDecided?.decision_value
      /* ⚠ 이력 줄의 detail 은 **결정 코드**(yes · no)다 — 사유가 아니다. 전에는
         그 코드를 사유 칸에 넣어서 저장 직후 사유가 「no」로 보였다 */
      ? { value: lastDecided.decision_value, reason: "", at: lastDecided.at }
      : null;

  const st = (key) => flow.steps.find((s) => s.key === key)?.state ?? "todo";
  const conds = unlockConds(unlock.data);
  const metCount = conds.filter((c) => c.met).length;
  const unlocked = Boolean(target?.is_unlocked || unlock.data?.unlocked);
  const explained = Boolean(flow.facts.explained || target?.explained_at
    || conds.find((c) => c.key === "explained")?.met);
  const rx = saved.data ?? [];
  const rad = patient.readings?.radiology ?? [];
  const pat = patient.readings?.pathology ?? [];
  const decisionLabel = DECISIONS.find((d) => d.v === savedDecision?.value)?.label ?? savedDecision?.value;
  const sources = (reports.data ?? []).filter((r) => r.report_type === "stage").length;

  /* 한 벌 — 목차와 카드 머리가 같이 읽는다 */
  const steps = [
    { n: 1, id: "results", title: "결과 요약", state: "done", pill: "읽기 전용", keepOpen: true,
      summary: [rad[0]?.grade != null ? `BI-RADS ${rad[0].grade}` : null,
        pat[0]?.grade ? `병리 ${upper(pat[0].grade)}` : null,
        flow.facts.pendingCount ? `${flow.facts.pendingCount}건 판독 대기` : null,
        flow.facts.pendingPath?.length ? "병리 확진 대기" : null,
      ].filter(Boolean).join(" · ") || "확정된 결과 없음" },
    { n: 2, id: "discordance", title: "판정 불일치",
      state: blocked ? "now" : "done", pill: blocked ? "처분 필요" : "없음",
      summary: blocked ? ruleText(patient.open_discordance) : "미처분 불일치 없음" },
    { n: 3, id: "report", title: "AI 종합 리포트 · 의사 종합 소견", keepOpen: true,
      state: report ? "done" : st("report"), pill: report ? "생성됨" : "생성 전",
      summary: report
        ? `#${report.report_id}${report.ai_summary ? "" : " · 소견문 작성 중"}${report.content_json?.doctor_summary ? " · 의사 소견 있음" : ""}`
        : sources ? `확정 판독문 ${sources}건으로 만들 수 있음` : "확정 판독문 없음" },
    { n: 4, id: "decision", title: "수술 여부",
      state: savedDecision ? "done" : blocked ? "lock" : st("decision"),
      pill: savedDecision ? "저장됨" : blocked ? "잠김" : "결정 전",
      summary: savedDecision ? [decisionLabel, day(savedDecision.at)].filter(Boolean).join(" · ")
        : blocked ? "불일치 처분 후" : "수술 시행 · 안 함 · 보류 중 하나" },
    { n: 5, id: "explain", title: "환자 설명 → 잠금 해제",
      state: unlocked ? "done" : explained ? "now" : blocked ? "lock" : st("explain"),
      pill: unlocked ? "공개됨" : explained ? "설명 완료 · 잠김" : blocked ? "잠김" : "설명 전",
      summary: unlocked ? `환자 앱 공개${target?.unlocked_at ? ` · ${day(target.unlocked_at)}` : ""}`
        : !target ? "종합 리포트(③) 생성 후"
        : `잠금 조건 ${metCount}/3${explained ? " · 설명 기록됨" : ""}` },
    { n: 6, id: "prescription", title: "처방",
      state: rx.length ? "done" : blocked ? "lock" : "opt",
      pill: rx.length ? `${rx.length}건` : "필요할 때만",
      summary: rx.length
        ? `${(rx.at(-1)?.content?.drugs ?? []).map((d) => d.name).slice(0, 2).join(", ") || "처방"}${day(rx.at(-1)?.prescribed_at ?? rx.at(-1)?.created_at) ? ` · ${day(rx.at(-1)?.prescribed_at ?? rx.at(-1)?.created_at)}` : ""}`
        : "약이 필요 없으면 건너뜀" },
    { n: 7, id: "close", title: "진료 완료 · 재진 예약 · 추적",
      state: flow.facts.closed ? "done" : st("close") === "now" || st("followup") === "now" ? "now" : "todo",
      pill: flow.facts.closed ? "진료 완료" : flow.facts.visitOpen ? "진료 중" : "—",
      summary: flow.facts.closed ? "진료 완료 · 재진 · 추적 예약은 언제든 가능"
        : flow.facts.visitOpen ? "진료 중 — 마치면 진료 완료를 누르세요" : "진행 중인 방문 없음 · 다음 예약만 가능" },
  ];

  /* 펴고 접기 — 끝난 카드는 접어 둔다(keepOpen 은 늘 편다). 누르면 그 값이 이긴다 */
  const [opened, setOpened] = useState(() => {
    const f = FOCUS_CARD[focus] ?? focus;
    return f ? { [f]: true } : {};
  });
  const isOpen = (s) => opened[s.id] ?? (s.keepOpen || s.state !== "done");
  const toggle = (idKey) => setOpened((o) => ({ ...o, [idKey]: !isOpen(steps.find((s) => s.id === idKey)) }));

  const pendingJump = useRef(null);
  function jump(idKey, inner = null) {
    setOpened((o) => ({ ...o, [idKey]: true }));
    pendingJump.current = inner ?? `dec-${idKey}`;
  }
  useEffect(() => {
    if (!pendingJump.current) return;
    const el = document.getElementById(pendingJump.current);
    pendingJump.current = null;
    if (!el) return;
    el.scrollIntoView({ block: "start", behavior: "smooth" });
    const f = el.matches("textarea, input, button") ? el : el.querySelector("h3 button, textarea");
    f?.focus({ preventScroll: true });
  });

  /* 이력에서 골라 온 칸. ⚠ 리포트 칸은 뒤늦게 차며 길어진다 — 머리로 맞춘다.
     같은 쪽에서 ?focus= 만 바뀌면(다음 할 일 링크) 그 카드를 렌더 중에 편다 */
  const at = (key) => focus === key;
  const [seenFocus, setSeenFocus] = useState(focus);
  if (focus !== seenFocus) {
    setSeenFocus(focus);
    if (focus) setOpened((o) => ({ ...o, [FOCUS_CARD[focus] ?? focus]: true }));
  }
  useEffect(() => {
    if (focus) document.getElementById(`dec-${focus}`)?.scrollIntoView({ block: "start" });
  }, [focus]);

  const card = (s) => ({ ...s, open: isOpen(s), onToggle: () => toggle(s.id) });
  const S = Object.fromEntries(steps.map((s) => [s.id, card(s)]));

  return (
    <>
      {patient.data_warnings?.length > 0 && (
        <p className="warnline">
          일부 자료를 불러오지 못했습니다: {patient.data_warnings.join(", ")}. 새로고침 후 다시 확인해 주세요.
        </p>
      )}
      <div className="bf-dec">
        <div className="bf-dec-main">
          <StepCard {...S.results}
                    right={<Link className="edit-btn" to={go.breast.review(pid)}>환자 상세 ›</Link>}>
            <Results patient={patient} />
          </StepCard>

          <StepCard {...S.discordance}>
            {blocked ? (
              <div className="bf-gate">
                {(patient.open_discordances ?? [patient.open_discordance]).map((d) => (
                  <div className="bf-gate-row" key={d.discordance_id}>
                    <p className="card-text"><b>영상과 병리 판정이 엇갈립니다.</b> {ruleText(d)}</p>
                    <Link className="btn" to={go.breast.discordance(d.discordance_id)}>처분하기 →</Link>
                  </div>
                ))}
                <p className="note">처분하기 전에는 ④ 수술 여부 · ⑤ 환자 설명 · ⑥ 처방을 저장할 수 없습니다.
                  처분하면 이 화면으로 돌아옵니다.</p>
              </div>
            ) : <p className="note">처분할 판정 불일치가 없습니다. 치료 방침을 정할 수 있습니다.</p>}
          </StepCard>

          <StepCard {...S.report} here={at("report")}>
            {report && <AiSummary report={report} late={writingLate}
                                  onRecheck={() => { setWaited(0); onReload(); }} />}
            {/* 만든 뒤에도 생성 칸을 남긴다 — 판독이 더 들어와도 다시 만들 길 */}
            <FinalReport patient={patient} reports={reports} onCreated={onReload} again={Boolean(report)} />
            {report
              ? <DoctorSummary key={report.report_id} report={report} />
              : <p className="note">종합 리포트를 만든 뒤 여기에 의사 종합 소견을 작성합니다.</p>}
          </StepCard>

          <StepCard {...S.decision} here={at("decision")}>
            <DecisionForm key={`${assessmentId}-${savedDecision?.value ?? ""}-${savedDecision?.reason ?? ""}`}
                          assessmentId={assessmentId}
                          loading={timeline.loading || cur.loading}
                          saved={savedDecision} blocked={blocked}
                          onSaved={() => { timeline.reload(true); cur.reload(true); }} />
          </StepCard>

          <StepCard {...S.explain} here={at("explain") || at("patient-report")}>
            <div id="dec-patient-report">
              <PatientReport report={patient.patient_report} reports={reports} />
            </div>
            {target
              ? <ExplainForm key={target.report_id} report={target} patient={patient} blocked={blocked}
                             unlock={unlock} unlocked={unlocked}
                             onExplainJump={() => jump("explain", "dec-explain-content")}
                             onSaved={() => { onReload(); unlock.reload(true); timeline.reload(true); }} />
              : <p className="note">종합 리포트(③)가 생성된 뒤 설명을 기록할 수 있습니다.</p>}
          </StepCard>

          <StepCard {...S.prescription} here={at("prescription")}>
            <PrescriptionDraft patient={patient} report={report} saved={saved} blocked={blocked} />
          </StepCard>

          <StepCard {...S.close}>
            <div className="bf-close">
              <p className="card-text">
                {flow.facts.visitOpen
                  ? "진료를 완료하면 대기 목록과 환자 앱 예약에서 빠집니다."
                  : "진행 중인 방문이 없습니다. 다음 예약만 잡으면 됩니다."}
              </p>
              <p className="section-label">재진 예약</p>
              <BookForm patient={patient} suggest={flow.facts.grade === "3" ? 182 : 14} />
              {/* 추적 회차도 여기서 건다 — 서버가 안 열어 준 배포본이면
                  칸이 스스로 사라진다(FollowupRounds) */}
              <FollowupRounds patient={patient} />
              <div className="card-foot split">
                <button className="btn ghost" onClick={onNextPatient}>다음 환자 →</button>
                <button className="btn" onClick={() => setClosing(true)}
                        disabled={!flow.facts.visitOpen || blocked}
                        title={blocked ? "판정 불일치를 먼저 처분해 주세요" : !flow.facts.visitOpen ? "완료할 방문이 없습니다" : undefined}>
                  진료 완료
                </button>
              </div>
            </div>
          </StepCard>
        </div>

        <Rail patient={patient} flow={flow} steps={steps} conds={unlock.data ? conds : null}
              unlockLoading={unlock.loading} unlocked={unlocked} onJump={jump} />
      </div>

      {closing && (
        <CloseVisitModal patient={patient} suggest={flow.facts.grade === "3" ? 182 : 14}
                         onClose={() => setClosing(false)}
                         onDone={() => { setClosing(false); onNextPatient(); }} />
      )}
    </>
  );
}

/* 상태 → 칩 모양. 목차 · 카드 머리가 같이 쓴다 */
const PILL = { done: "ok", now: "warn", lock: "wait", todo: "wait", opt: "wait", wait: "wait", skip: "wait" };
const SAY = { done: "완료", now: "현재", lock: "잠김", todo: "예정", opt: "선택", wait: "진행 중", skip: "해당 없음" };

/* 단계 카드 한 장 — 번호 · 제목 · 상태 칩 · 한 줄 요약. id 는 늘 단다(?focus=
 * 가 찾는 자리). 접히면 머리만 남는다. 머리 단추가 펴고 접는다 */
function StepCard({ n, id, title, state = "todo", pill, summary, right = null, here = false,
                    open = true, onToggle, children }) {
  const bodyId = `dec-${id}-body`;
  return (
    <section id={`dec-${id}`} className={`card bf-sc ${state}${here ? " here" : ""}${open ? "" : " shut"}`}
             aria-labelledby={`dec-${id}-h`}>
      <div className="card-head bf-sc-head">
        <span className="bf-sc-n" aria-hidden="true">{n}</span>
        <h3 id={`dec-${id}-h`}>
          <button type="button" className="bf-sc-t" aria-expanded={open} aria-controls={bodyId}
                  onClick={onToggle}>
            <span className="bf-sc-title">{title}</span>
            {summary && <span className="bf-sc-sum">{summary}</span>}
          </button>
        </h3>
        {pill && <span className={`pill ${PILL[state] ?? "wait"}`} title={SAY[state]}>{pill}</span>}
        {right}
        <span className="bf-sc-fold" aria-hidden="true">{open ? "접기" : "펼치기"}</span>
      </div>
      <div id={bodyId} className="bf-sc-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}

/* ① 결과 요약 — 환자 상세와 같은 값(Results.jsx). 여기서는 고치지 않는다 */
function Results({ patient }) {
  const r = patient.readings ?? { radiology: [], pathology: [] };
  const lesions = (patient.lesions ?? []).filter((l) => l && !l.is_false_positive)
    .map((l) => lesionText(l)).filter(Boolean);
  return (
    <div className="bf-sum">
      <div>
        <p className="section-label">영상 판독</p>
        <PendingLine orders={patient.orders} />
        <RadRows rows={r.radiology} lead={false} />
        {lesions.length > 0 && <p className="note">병변 · {lesions.join(", ")}</p>}
      </div>
      <div>
        <p className="section-label">병리</p>
        <PathRows rows={r.pathology} />
      </div>
    </div>
  );
}

/* 오른쪽 320px — 붙박이. 환자 · 진료 단계 목차 · 다음 할 일 · 잠금 조건.
 * 목차 줄을 누르면 그 카드를 펴고 내려간다 */
function Rail({ patient, flow, steps, conds, unlockLoading, unlocked, onJump }) {
  const sex = label(SEX, patient.sex) || null;
  const next = flow.next;
  const here = ["report", "decision", "explain", "prescription", "close", "followup"];
  const nextCard = next && here.includes(next.key) ? (next.key === "followup" ? "close" : next.key) : null;
  return (
    <aside className="bf-rail" aria-label="진료 단계와 잠금 조건">
      <div className="card">
        <div className="pt-head">
          <span className="avatar" aria-hidden="true">{H.nameOf(patient)[0]}</span>
          <div>
            <p className="name">{H.nameOf(patient)}</p>
            <p className="sub">{[patient.age != null ? `${patient.age}세` : null, sex, H.noOf(patient)]
              .filter(Boolean).join(" · ")}</p>
          </div>
        </div>
        <div className="bf-rail-facts">
          {H.some(patient.allergy) && <span className="pill warn">알레르기 · {H.some(patient.allergy)}</span>}
          {H.some(patient.family_history) && <span className="pill wait">가족력 · {H.some(patient.family_history)}</span>}
          {patient.primary_staff_name && <span className="pill wait">주치의 {patient.primary_staff_name}</span>}
        </div>
      </div>

      <nav className="card bf-idx" aria-label="진료 단계">
        <div className="card-head"><h3>진료 단계</h3>
          <span className="meta">{steps.filter((s) => s.state === "done").length}/{steps.length} 완료</span></div>
        <ol>
          {steps.map((s) => (
            <li key={s.id}>
              <button type="button" className={`bf-idx-i ${s.state}`} onClick={() => onJump(s.id)}
                      aria-current={s.state === "now" ? "step" : undefined}>
                <span className="bf-sc-n" aria-hidden="true">{s.n}</span>
                <span className="bf-idx-t">
                  <b>{s.title}</b>
                  <small>{s.summary}</small>
                </span>
                <span className={`pill ${PILL[s.state] ?? "wait"}`}>{s.pill}</span>
              </button>
            </li>
          ))}
        </ol>
        {next && (
          <div className="bf-rail-next">
            <p className="section-label">다음 할 일</p>
            <p className="card-text"><b>{next.label}</b></p>
            {next.why && <p className="note">{next.why}</p>}
            {nextCard
              ? <button type="button" className="btn" onClick={() => onJump(nextCard)}>{next.label} ↓</button>
              : next.to && <Link className="btn" to={next.to}>{next.label} →</Link>}
          </div>
        )}
      </nav>

      <div className="card bf-rail-lock">
        <div className="card-head"><h3>잠금 조건</h3>
          <span className="meta">{unlocked ? "공개됨" : conds?.every((c) => c.met) ? "해제 가능" : "잠김"}</span></div>
        {!conds && !unlockLoading
          ? <p className="note">종합 리포트가 생성되면 잠금 조건을 확인합니다.</p>
          : !conds ? <p className="note">조건을 확인하는 중…</p>
          : <CondList conds={conds} patient={patient} compact
                      onExplain={() => onJump("explain", "dec-explain-content")} />}
      </div>
    </aside>
  );
}


/* ⑤ 안 — 환자에게 공개되는 리포트. 최종 리포트가 없으면 확정된 검사별
   리포트 목록을 보여 주고, 잠금 상태는 서버의 unlock-status를 그대로 쓴다 */
function PatientReport({ report, reports }) {
  const stageReports = (reports.data ?? []).filter((row) => row.report_type === "stage");
  const content = report?.content_json ?? {};

  return (
    <div className="bf-block patient-report-card">
      <div className="card-head">
        <p className="section-label">{report ? "환자용 리포트" : "환자 리포트 열람"}</p>
        <span className={`pill ${report?.is_unlocked ? "ok" : report ? "wait" : "warn"}`}>
          {report ? (report.is_unlocked ? "열람 가능" : "잠김") : "작성 대기"}
        </span>
      </div>
      {reports.loading ? <p className="note">리포트를 불러오는 중입니다.</p>
        : reports.error ? <p className="warnline">환자 리포트를 불러오지 못했습니다. 새로고침 후 다시 확인해 주세요.</p>
        : report ? (
          <div className="patient-report-body">
            <div className="report-meta-row">
              <span>리포트 번호</span><b>#{report.report_id}</b>
            </div>
            <div className="report-meta-row">
              {/* finalized_at · created_at 은 리포트 응답에 없다 — 있는 것은 공개(잠금 해제) 시각 */}
              <span>공개일</span><b>{String(report.unlocked_at ?? "").slice(0, 10) || "공개 전"}</b>
            </div>
            <p className="card-text">{report.ai_summary || content.doctor_summary || "등록된 요약이 없습니다."}</p>
          </div>
        ) : stageReports.length ? (
          <div className="patient-report-body">
            <p className="card-text">종합 리포트 생성 전입니다. 현재 확인 가능한 검사별 판독문:</p>
            <div className="report-stage-list">
              {stageReports.map((row) => (
                <div className="report-stage-row" key={row.report_id}>
                  <b>{stageName(row)}</b>
                  <span>{row.narrative_text || row.ai_summary || "내용 없음"}</span>
                </div>
              ))}
            </div>
          </div>
        ) : <p className="note">확정된 리포트가 없습니다. 검사 판독 확정 후 열람할 수 있습니다.</p>}
    </div>
  );
}

/* 검사별 판독문 이름. ⚠ Report 에는 title · modality 가 없다 — 어느 과가
   냈는지는 socket_id 로만 안다(codes.js REPORT_DEPT). 고르는 칸은 같은 과
   판독문이 둘일 수 있어 번호를 붙인다 */
function stageName(row, withId = false) {
  const dept = REPORT_DEPT[row.socket_id];
  if (!dept) return `검사 판독문 #${row.report_id}`;
  return withId ? `${dept} 판독문 #${row.report_id}` : `${dept} 판독문`;
}

function FinalReport({ patient, reports, onCreated, again = false }) {
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [open, setOpen] = useState(!again);
  const sources = (reports.data ?? []).filter((row) => row.report_type === "stage" && row.report_id != null);
  const effectiveSelected = selected ?? sources.map((row) => row.report_id);

  function toggle(id) {
    setSelected((current) => {
      const values = current ?? sources.map((row) => row.report_id);
      return values.includes(id) ? values.filter((value) => value !== id) : [...values, id];
    });
  }

  async function create() {
    if (!effectiveSelected.length) return;
    setBusy(true); setMsg(null);
    try {
      await api.finalReport({ patient_id: patient.patient_id, source_report_ids: effectiveSelected });
      onCreated?.();
    } catch (e) {
      setMsg(e.detail || "종합 리포트 생성에 실패했습니다.");
    } finally { setBusy(false); }
  }

  /* 이미 만들었으면 접어 둔다 — 판독이 더 들어왔을 때만 편다 */
  if (again && !open) {
    return (
      <div className="bf-block">
        <button className="edit-btn" onClick={() => setOpen(true)}>새 판독이 있으면 다시 만들기 ›</button>
      </div>
    );
  }

  return (
    <div className="bf-block">
      <p className="section-label">{again ? "다시 만들기" : "만들기"}</p>
      <p className="card-text">
        {again
          ? "추가된 판독문까지 선택해 새로 만듭니다. 새 리포트는 위에 표시됩니다."
          : "확정된 검사 판독문을 골라 AI 종합 리포트를 만듭니다."}
      </p>
      {reports.loading ? <p className="note">판독문을 불러오는 중입니다.</p>
        : reports.error ? <p className="warnline">판독문을 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.</p>
        : sources.length === 0 ? <p className="note">리포트를 만들 확정 판독문이 없습니다.</p>
        : <div className="stack">
            {sources.map((source) => (
              <label key={source.report_id} className="check-row">
                <input type="checkbox" checked={effectiveSelected.includes(source.report_id)} onChange={() => toggle(source.report_id)} />
                <span>{stageName(source, true)}</span>
              </label>
            ))}
          </div>}
      {msg && <p className="warnline">{msg}</p>}
      <div className="card-foot"><button className="btn" onClick={create} disabled={busy || !effectiveSelected.length}>
        {busy ? "생성 중…" : again ? "다시 생성" : "종합 리포트 생성"}
      </button></div>
    </div>
  );
}

function AiSummary({ report, late = false, onRecheck }) {
  return (
    <div className="bf-block">
      <div className="card-head">
        <p className="section-label">AI 요약</p>
        <span className="pill" style={{ background: "var(--accent-weak)", color: "var(--accent)" }}>
          {/* 센 것은 모달리티가 아니라 묶은 판독 수다(source_ai_ids) */}
          {report.ai_modality_count ? `판독 ${report.ai_modality_count}건 통합` : "통합"}
        </span>
      </div>
      {/* 리포트 행은 바로 서고 소견문은 리포트 서버가 뒤에 채운다(수십 초) */}
      {report.ai_summary ? <p className="card-text">{report.ai_summary}</p>
        : late ? (
          <p className="note">
            소견문이 3분 넘게 만들어지지 않고 있습니다.{" "}
            <button type="button" className="edit-btn" onClick={onRecheck}>다시 확인</button>
          </p>
        ) : (
          /* 화면이 알아서 다시 확인한다(Inner 의 writing) — 새로고침을 시키지 않는다 */
          <p className="note" role="status">소견문을 만드는 중입니다. 다 되면 여기에 바로 표시됩니다.</p>
        )}
      {report.ai_evidence?.length > 0 && (
        <>
          <p className="section-label">근거</p>
          <ul className="bullets">
            {report.ai_evidence.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </>
      )}
      {report.ai_suggestion && (
        <>
          <p className="section-label">참고 제안</p>
          <p className="card-text">{report.ai_suggestion}</p>
        </>
      )}
    </div>
  );
}

/* ⚠ 2026-09-18 다희님 확인 — report.content_json 하나에 전부 담긴다:
 * { doctor_summary, by_modality: {mammo, us, mri} }. PUT /reports/{id}/
 * 는 이 필드만 본다(surgery.py:97-103). 모달리티별 덮어쓰기(merge)는
 * 서버가 처리하기로 했다 — 여기서는 그냥 이 모양대로 보내기만 한다.
 * ⚠ doctor_summary_author 는 서버 Report 모델에 없는 필드라(목업 전용)
 *   작성자 칩을 뺐다 — 실서버에서 늘 빈 칸이었다. */
function DoctorSummary({ report }) {
  const [text, setText] = useState(report.content_json?.doctor_summary ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.saveReport(report.report_id, { content_json: { doctor_summary: text } });
      setMsg("저장되었습니다");
    } catch (e) {
      setMsg(e.detail || e.message || "리포트 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bf-block">
      <div className="field" style={{ marginBottom: 8 }}>
        <label>의사 종합 소견</label>
        <textarea value={text} onChange={(e) => setText(e.target.value)}
          style={{ minHeight: 90 }} placeholder="AI 요약을 보고 종합 소견을 적어 주세요" />
      </div>
      <div className="card-foot split">
        <span className="note">{msg}</span>
        <button className="btn ghost" onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "소견 저장"}
        </button>
      </div>
    </div>
  );
}

/* ④ 수술 여부.
 * ⚠ 09-28 — **저장한 결정을 다시 편다.** 전에는 늘 「수술 시행」 · 빈 사유로
 *   떠서, 이미 정한 환자를 열면 안 정한 것처럼 보였고 그대로 저장하면
 *   결정을 덮어썼다. 판 행의 decision_*(없으면 이력의 「치료 결정」)을
 *   처음 값으로 쓴다(부르는 쪽 saved). */
function DecisionForm({ assessmentId, loading, saved, blocked, onSaved }) {
  const [decisionValue, setDecisionValue] = useState(saved?.value ?? null);
  const [reason, setReason] = useState(saved?.reason ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const may = useCan("breast.decision.save");
  const off = !may.ok || blocked;

  function add(phrase) {
    setReason((r) => (r.includes(phrase) ? r : r.trim() ? `${r.trim()}, ${phrase}` : phrase));
  }

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.decide(assessmentId, {
        decision_type: "surgery", decision_value: decisionValue, decision_reason: reason,
      });
      setMsg("결정이 저장되었습니다");
      onSaved?.();
    } catch (e) {
      setMsg(e.detail || e.message || "결정 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  const changed = decisionValue !== (saved?.value ?? null) || reason !== (saved?.reason ?? "");

  return (
    <>
      {saved && (
        <p className="note">
          저장된 결정 · <b>{DECISIONS.find((d) => d.v === saved.value)?.label ?? saved.value}</b>
          {saved.at && ` (${String(saved.at).slice(0, 10)})`} — 수정하면 덮어씁니다.
        </p>
      )}
      <div className="radio-group bf-seg" style={{ marginTop: 10 }}>
        {DECISIONS.map((d) => (
          <label className="radio-row" key={d.v}>
            <input type="radio" name="decision_value" value={d.v}
              checked={decisionValue === d.v} disabled={off}
              onChange={() => setDecisionValue(d.v)} />
            {d.label}
          </label>
        ))}
      </div>
      <div className="field">
        <label>결정 사유</label>
        <div className="bf-phr" role="group" aria-label="상용구 — 누르면 사유 끝에 추가됩니다">
          {PHRASES.map(([group, items]) => (
            <span className="bf-phr-g" key={group}>
              <small>{group}</small>
              {items.map((it) => (
                <button type="button" key={it} className="bf-chip" disabled={off}
                        onClick={() => add(it)}>{it}</button>
              ))}
            </span>
          ))}
        </div>
        <textarea value={reason} disabled={off}
          onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="card-foot split">
        <span className="note">
          {msg ?? (blocked ? "판정 불일치(②)를 먼저 처분해 주세요"
            : !loading && !assessmentId ? "확정된 판독이 아직 없어 저장할 수 없습니다" : null)}
        </span>
        <button className="btn" onClick={save} {...may.attrs}
          disabled={saving || !assessmentId || off || !decisionValue || !changed}>
          {saving ? "저장 중…" : saved ? "결정 수정" : "결정 저장"}
        </button>
      </div>
    </>
  );
}


/* ⑤ 환자 설명 → 잠금 해제.
 * report — **환자용** 종합 소견서(없으면 의사용). 서버가 설명 · 해제를 짝
 * 전체에 건다(core/views/surgery.py _report_pair).
 * ⚠ 설명 내용(explain_content)은 모델 칸이 없어 서버가 content_json 에 둔다 —
 *   전에는 보낸 글이 그냥 버려졌다. */
function ExplainForm({ report, patient, onSaved, blocked, unlock, unlocked, onExplainJump }) {
  const [method, setMethod] = useState(report.explain_method ?? EXPLAIN_METHODS[0]);
  const [content, setContent] = useState(report.explain_content ?? report.content_json?.explain_content ?? "");
  const [confirmed, setConfirmed] = useState(report.patient_confirmed ?? false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.explain(report.report_id, {
        explain_method: method, explain_content: content, patient_confirmed: confirmed,
      });
      setMsg("환자 설명이 기록되었습니다 — 잠금 조건 ③이 충족됩니다");
      unlock.reload(true);
      onSaved?.();
    } catch (e) {
      setMsg(e.detail || e.message || "환자 설명 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bf-block" id="dec-explain-form">
      {report.explained_at && (
        <p className="note">설명 기록 · {String(report.explained_at).replace("T", " ").slice(0, 16)}
          {report.explain_method ? ` · ${report.explain_method}` : ""} — 다시 저장하면 새 기록으로 바뀝니다.</p>
      )}
      <p className="section-label" style={{ marginTop: 0 }}>설명 방법</p>
      <div className="radio-group" style={{ flexDirection: "row" }}>
        {EXPLAIN_METHODS.map((m) => (
          <label className="radio-row" key={m} style={{ flex: 1, justifyContent: "center" }}>
            <input type="radio" name="explain_method" value={m} disabled={blocked || unlocked}
              checked={method === m} onChange={() => setMethod(m)} />
            {m}
          </label>
        ))}
      </div>
      <div className="field">
        <label htmlFor="dec-explain-content">설명 내용</label>
        <textarea id="dec-explain-content" value={content} disabled={blocked || unlocked}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="진단 · 치료 계획 · 예상 경과를 어떻게 설명했는지 적어 주세요" />
      </div>
      <label className="check-row">
        <input type="checkbox" checked={confirmed} disabled={blocked || unlocked}
          onChange={(e) => setConfirmed(e.target.checked)} />
        환자가 결과 및 치료 계획을 확인함
      </label>
      <div className="card-foot split">
        <span className="note" role="status">{msg ?? (blocked ? "판정 불일치(②)를 먼저 처분해 주세요"
          : unlocked ? "이미 공개된 리포트입니다" : null)}</span>
        <button className="btn" onClick={save} disabled={saving || blocked || unlocked}>
          {saving ? "저장 중…" : report.explained_at ? "설명 기록 다시 저장" : "설명 기록 저장"}
        </button>
      </div>
      <section className="explain-lock" aria-label="환자 리포트 잠금">
        <p className="section-label">잠금 해제</p>
        <Body loading={unlock.loading && !unlock.data} error={unlock.error} onRetry={unlock.reload}>
          {unlock.data && (
            <LockPanel reportId={report.report_id} status={unlock.data} patient={patient}
              unlocked={unlocked} unlockedAt={report.unlocked_at}
              onExplain={onExplainJump}
              onUnlocked={() => { unlock.reload(true); onSaved?.(); }} />
          )}
        </Body>
      </section>
    </div>
  );
}
