import { useEffect, useId, useMemo, useRef, useState } from "react";
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
import Stepper from "../components/Stepper";
import CloseVisitModal from "../components/CloseVisitModal";
import { BookForm } from "../components/BookVisit";
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
 *   박아 둔 글이다(목업의 세 묶음). 09-28 대기 환자 오른쪽 단에 누르면
 *   아무 데도 안 붙는 글로 있던 것을 여기로 옮겼다. */
const PHRASES = [
  ["수술", ["단일 병변, 유방보존술 가능", "다발성 병변으로 전절제 고려"]],
  ["추가 검사", ["병변 범위 평가 위해 MRI 시행", "표적 미포함 의심, 재조직검사"]],
  ["보류 · 추적", ["환자 상의 후 재내원", "6개월 추적 관찰"]],
];

/* 화면 3 · 치료 방침 ("/patients/:id/decision") — 09-28 흐름 순서로 다시 짬
 * ════════════════════════════════════════════════════════════════
 *
 *   ┌ 1fr ────────────────────────────────┬ 320px (붙박이) ─┐
 *   │ ① 결과 요약            (읽기 전용)     │ 환자 · 알레르기  │
 *   │ ② 판정 불일치          (열리면 문)     │ 진료 단계(세로)  │
 *   │ ③ AI 종합 리포트 · 의사 종합 소견      │ 잠금 조건 셋     │
 *   │ ④ 수술 여부            (저장된 값을 편다)│ [다음 할 일]     │
 *   │ ⑤ 환자 설명 → 잠금 해제               │                 │
 *   │ ⑥ 처방                               │                 │
 *   │ ⑦ 진료 완료 · 재진 예약 → 다음 환자    │                 │
 *   └──────────────────────────────────────┴─────────────────┘
 *
 * 전에는 두 단에 카드가 흩어져 있어서(결정이 맨 위, 설명이 오른쪽 아래)
 * 무엇을 어느 순서로 하는지 화면이 말하지 않았다. 이제 위에서 아래로 한
 * 번 내려가면 진료가 끝난다.
 *
 * ⚠ **판정 불일치가 열려 있으면 ④ ~ ⑥ 을 잠근다.** 엇갈린 채로 방침을
 *   정하면 안 된다 — 서버의 잠금 해제 조건 ②(대조 종결)와 같은 말이다.
 *   ③ 리포트는 만들 수 있다(엇갈림을 판단하는 재료다).
 * ⚠ 잠금 해제 3조건(①전 레코드 확정 ②대조 종결 ③대면 설명 완료)은 서버가
 *   판단해서 GET /reports/{id}/unlock-status 로 내려준다 — 화면은 그 결과를
 *   그대로 보여주고 셋 다 참일 때만 [잠금 해제] 버튼을 켠다.
 * ⚠ **목업의 「수술 계획」 칸(술식·측·수술 예정일·집도)은 못 만든다.**
 *   그 값을 받는 경로가 서버에 없다 — assessment 의 decision 은
 *   종류·가부·근거 셋뿐이고 수술 일정 자원이 따로 없다(8장).
 *
 * 진료 이력의 치료 결정 · 리포트 · 결과 설명 · 처방 줄에서 오면 ?focus= 가
 * 붙는다(dept/breast/history.js — decision · report · patient-report ·
 * explain · prescription). 그 칸(id="dec-…")으로 내려가 왼쪽 선으로 짚는다.
 * ⚠ 지난 결정 · 설명의 **그때 값**을 보여 주지는 못한다 — 서버가 결정을
 *   판독 행에 덮어쓰고(decision_*), 설명도 리포트 행에 덮어쓴다. */
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

function Inner({ patient, onReload, focus, onNextPatient }) {
  const pid = patient.patient_id;
  const report = patient.report;
  const reportId = report?.report_id ?? null;
  const reports = useApi(() => api.reports(pid), [pid]);
  const unlock = useApi(
    () => reportId ? api.unlockStatus(reportId) : Promise.resolve(null),
    [reportId],
  );
  const timeline = useApi(() => api.timeline(pid), [pid]);
  const saved = useApi(() => api.prescriptions(pid), [pid]);
  const [closing, setClosing] = useState(false);

  const events = H.rows(timeline.data);
  const flow = useMemo(() => flowOf({ p: patient, timeline: events, rx: saved.data ?? undefined }),
    [patient, events, saved.data]);
  const blocked = Boolean(patient.open_discordance);

  /* 수술 결정은 assessment 한 건에 매달린다(models.py:675 — study 에 물려
   * 있지 patient 에 안 물려 있다). timeline 의 「판독」 줄이 assessment_id ·
   * study_id 를 싣는다.
   * ⚠ 09-28 — 전에는 **마지막 「판독」 줄**을 집었는데, 서버 timeline 은
   *   초안(draft)도 「판독」으로 준다. 초안에 결정을 걸면 확정 판독이 오면서
   *   결정이 사라진다. 확정(final) 줄만 본다 — read_stage 가 없는 옛 줄은
   *   확정으로 친다. 그 검사의 판 목록에서 **지금 유효한 판**을 다시 고른다
   *   (정정으로 덮인 판에 걸지 않게) */
  const finals = events.filter((e) => e.type === "판독" && e.assessment_id != null
    && (e.read_stage == null || e.read_stage === "final"));
  const lastRead = finals.at(-1) ?? null;
  const target = useApi(
    () => (lastRead?.study_id != null ? api.assessments(lastRead.study_id).then(H.rows) : Promise.resolve([])),
    [lastRead?.study_id ?? null],
  );
  const current = currentAssessment(H.rows(target.data)) ?? null;
  const assessmentId = current?.assessment_id ?? lastRead?.assessment_id ?? null;
  /* 저장된 결정 — 판 행의 decision_* 가 지금 값이다. 판 목록을 못 받았으면
     이력의 마지막 「치료 결정」 줄로 대신한다 */
  const lastDecided = [...events].reverse().find((e) => e.type === "치료 결정") ?? null;
  const savedDecision = current?.decision_value
    ? { value: current.decision_value, reason: current.decision_reason ?? "", at: current.decided_at }
    : lastDecided?.decision_value
      ? { value: lastDecided.decision_value, reason: lastDecided.detail ?? "", at: lastDecided.at }
      : null;

  /* 이력에서 골라 온 칸. ⚠ 리포트 칸은 뒤늦게 차며 길어진다 — 머리로 맞춘다 */
  const at = (key) => focus === key;
  useEffect(() => {
    if (focus) document.getElementById(`dec-${focus}`)?.scrollIntoView({ block: "start" });
  }, [focus]);

  const st = (key) => flow.steps.find((s) => s.key === key)?.state ?? "todo";

  return (
    <>
      {patient.data_warnings?.length > 0 && (
        <p className="warnline">
          일부 자료를 불러오지 못했습니다: {patient.data_warnings.join(", ")}. 새로고침 후 다시 확인해 주세요.
        </p>
      )}
      <div className="bf-dec">
        <div className="bf-dec-main">
          <StepCard n="1" id="results" title="결과 요약" state="done" pill="읽기 전용"
                    right={<Link className="edit-btn" to={go.breast.review(pid)}>환자 상세 ›</Link>}>
            <Results patient={patient} />
          </StepCard>

          <StepCard n="2" id="discordance" title="판정 불일치"
                    state={blocked ? "now" : "done"} pill={blocked ? "처분 필요" : "없음"}>
            {blocked ? (
              <div className="bf-gate">
                <p className="card-text"><b>영상과 병리 판정이 엇갈립니다.</b> {patient.open_discordance.violated_rule}</p>
                <p className="note">처분하기 전에는 ④ 수술 여부 · ⑤ 환자 설명 · ⑥ 처방을 저장할 수 없습니다.
                  처분하면 이 화면으로 돌아옵니다.</p>
                <div className="card-foot">
                  <Link className="btn" to={go.breast.discordance(patient.open_discordance.discordance_id)}>
                    처분하기 →
                  </Link>
                </div>
              </div>
            ) : <p className="note">열린 불일치가 없습니다. 방침을 정할 수 있습니다.</p>}
          </StepCard>

          <StepCard n="3" id="report" here={at("report")} title="AI 종합 리포트 · 의사 종합 소견"
                    state={report ? "done" : st("report")} pill={report ? "생성됨" : "생성 전"}>
            {report && <AiSummary report={report} />}
            {/* 만든 뒤에도 생성 칸을 남긴다 — 판독이 더 들어와도 다시 만들 길 */}
            <FinalReport patient={patient} reports={reports} onCreated={onReload} again={Boolean(report)} />
            {report
              ? <DoctorSummary key={report.report_id} report={report} />
              : <p className="note">종합 리포트를 만들면 여기에 의사 종합 소견을 적습니다.</p>}
          </StepCard>

          <StepCard n="4" id="decision" here={at("decision")} title="수술 여부"
                    state={savedDecision ? "done" : blocked ? "lock" : st("decision")}
                    pill={savedDecision ? "저장됨" : blocked ? "잠김" : "결정 전"}>
            <DecisionForm key={`${assessmentId}-${savedDecision?.value ?? ""}`}
                          assessmentId={assessmentId}
                          loading={timeline.loading || target.loading}
                          saved={savedDecision} blocked={blocked}
                          onSaved={() => { timeline.reload(true); target.reload(true); }} />
          </StepCard>

          <StepCard n="5" id="explain" here={at("explain") || at("patient-report")}
                    title="환자 설명 → 잠금 해제"
                    state={flow.facts.explained ? (report?.is_unlocked ? "done" : "now") : blocked ? "lock" : st("explain")}
                    pill={report?.is_unlocked ? "공개됨" : flow.facts.explained ? "설명함 · 잠김" : blocked ? "잠김" : "설명 전"}>
            <div id="dec-patient-report">
              <PatientReport report={patient.patient_report} reports={reports} />
            </div>
            {report
              ? <ExplainForm report={report} blocked={blocked} unlock={unlock}
                             onSaved={() => { onReload(); unlock.reload(true); timeline.reload(true); }} />
              : <p className="note">종합 리포트(③)가 생긴 뒤 설명을 기록할 수 있습니다.</p>}
          </StepCard>

          <StepCard n="6" id="prescription" here={at("prescription")} title="처방"
                    state={(saved.data?.length ?? 0) > 0 ? "done" : blocked ? "lock" : "opt"}
                    pill={(saved.data?.length ?? 0) > 0 ? `${saved.data.length}건` : "필요할 때만"}>
            <PrescriptionDraft patient={patient} report={report} saved={saved} blocked={blocked} />
          </StepCard>

          <StepCard n="7" id="close" title="진료 완료 · 재진 예약"
                    state={flow.facts.closed ? "done" : st("close") === "now" || st("followup") === "now" ? "now" : "todo"}
                    pill={flow.facts.closed ? "방문 닫힘" : flow.facts.visitOpen ? "방문 중" : "—"}>
            <div className="bf-close">
              <p className="card-text">
                {flow.facts.visitOpen
                  ? "이번 방문을 닫으면 대기 목록과 환자 앱 예약에서 빠집니다."
                  : "열린 방문이 없습니다. 다음 방문만 잡으면 됩니다."}
              </p>
              <BookForm patient={patient} suggest={flow.facts.grade === "3" ? 182 : 14} />
              <div className="card-foot split">
                <button className="btn ghost" onClick={onNextPatient}>다음 환자 →</button>
                <button className="btn" onClick={() => setClosing(true)}
                        disabled={!flow.facts.visitOpen || blocked}
                        title={blocked ? "판정 불일치를 먼저 처분해 주세요" : !flow.facts.visitOpen ? "닫을 방문이 없습니다" : undefined}>
                  진료 완료
                </button>
              </div>
            </div>
          </StepCard>
        </div>

        <Rail patient={patient} flow={flow} unlock={unlock} />
      </div>

      {closing && (
        <CloseVisitModal patient={patient} suggest={flow.facts.grade === "3" ? 182 : 14}
                         onClose={() => setClosing(false)}
                         onDone={() => { setClosing(false); onNextPatient(); }} />
      )}
    </>
  );
}

/* 단계 카드 한 장 — 번호 · 제목 · 상태. id 는 늘 단다(?focus= 가 찾는 자리) */
const PILL = { done: "ok", now: "warn", lock: "wait", todo: "wait", opt: "wait", wait: "wait", skip: "wait" };

function StepCard({ n, id, title, state = "todo", pill, right = null, here = false, children }) {
  return (
    <section id={`dec-${id}`} className={`card bf-sc ${state}${here ? " here" : ""}`}>
      <div className="card-head">
        <span className="bf-sc-n" aria-hidden="true">{n}</span>
        <h3>{title}</h3>
        {pill && <span className={`pill ${PILL[state] ?? "wait"}`}>{pill}</span>}
        <span className="home-fill" />
        {right}
      </div>
      {children}
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

/* 오른쪽 320px — 보면서 하는 것. 붙박이라 아래로 내려가도 따라온다.
 * ⚠ 09-28 환자 정보 아홉 줄(이름 · 연락처 · 간호 메모 …)을 뺐다 — 쪽 머리
 *   환자 띠(PatientBar)와 겹쳤다. 결정할 때 봐야 하는 것만 남긴다 */
function Rail({ patient, flow, unlock }) {
  const sex = label(SEX, patient.sex) || null;
  const next = flow.next;
  const c = unlock.data?.conditions ?? null;
  return (
    <aside className="bf-rail">
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

      <div className="card">
        <div className="card-head"><h3>진료 단계</h3></div>
        <Stepper steps={flow.steps} col />
        {next && (
          <div className="bf-rail-next">
            <p className="section-label">다음 할 일</p>
            <p className="card-text"><b>{next.label}</b></p>
            {next.why && <p className="note">{next.why}</p>}
            {next.to && <Link className="btn" to={next.to}>{next.label} →</Link>}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head"><h3>잠금 조건</h3>
          <span className="meta">{unlock.data?.can_unlock ? "풀 수 있음" : "잠김"}</span></div>
        {!unlock.data && !unlock.loading
          ? <p className="note">종합 리포트가 생기면 서버가 조건을 셉니다.</p>
          : (
            <div className="cond-list">
              <Cond ok={c?.all_finalized} label="① 전 레코드 확정" />
              <Cond ok={c?.discordance_closed} label="② 대조 종결" />
              <Cond ok={c?.explained} label="③ 대면 설명 완료" />
            </div>
          )}
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
          {report ? (report.is_unlocked ? "열람 가능" : "잠금 상태") : "작성 대기"}
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
            <p className="card-text">최종 리포트 생성 전입니다. 현재 확인 가능한 검사별 판독문:</p>
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
      setMsg(e.detail || "최종 리포트 생성에 실패했습니다.");
    } finally { setBusy(false); }
  }

  /* 이미 만들었으면 접어 둔다 — 판독이 더 들어왔을 때만 편다 */
  if (again && !open) {
    return (
      <div className="bf-block">
        <button className="edit-btn" onClick={() => setOpen(true)}>판독이 더 들어왔으면 — 다시 만들기 ›</button>
      </div>
    );
  }

  return (
    <div className="bf-block">
      <p className="section-label">{again ? "다시 만들기" : "만들기"}</p>
      <p className="card-text">
        {again
          ? "판독이 더 들어왔으면 골라서 새로 만듭니다. 새 리포트가 위에 뜹니다."
          : "확정된 검사 판독문을 골라 AI 종합 리포트를 만듭니다."}
      </p>
      {reports.loading ? <p className="note">판독문을 불러오는 중입니다.</p>
        : reports.error ? <p className="warnline">판독문을 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.</p>
        : sources.length === 0 ? <p className="note">생성할 확정 검사 판독문이 없습니다.</p>
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

function AiSummary({ report }) {
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
      <p className="card-text">{report.ai_summary || "소견문을 만드는 중입니다. 잠시 뒤 새로고침해 주세요."}</p>
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
          {saved.at && ` (${String(saved.at).slice(0, 10)})`} — 고치면 덮어씁니다.
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
        <div className="bf-phr" role="group" aria-label="상용구 — 누르면 사유 끝에 붙습니다">
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
          {saving ? "저장 중…" : saved ? "결정 고치기" : "결정 저장"}
        </button>
      </div>
    </>
  );
}

/* 처방 한 줄의 빈 칸.
 *
 * ⚠ ingredient · watch 는 **환자 앱이 이미 그리고 있는 자리**다
 *   (src/screens/Meds.jsx 의 「어떤 약인가요」). 여기서 안 적으면 환자
 *   화면의 그 줄이 그냥 빈다. 특히 watch(「이럴 땐 알려 주세요」)는
 *   환자가 이상 증상을 알아차리는 유일한 안내라 비워 두지 않는 편이 좋다.
 */
const emptyDrug = () => ({
  name: "", ingredient: "", dose: "", times: "", days: "",
  purpose: "", how: "", watch: "",
});

/* e약은요 품목명은 끝 괄호에 성분을 적는다 — 「타이레놀정500밀리그람(아세트아미노펜)」.
 * 그 괄호만 꺼낸다. 수출명 같은 다른 괄호면 비워 둔다(틀린 성분보다 빈칸이 낫다). */
function ingredientOf(name) {
  const m = /\(([^()]+)\)\s*$/.exec(name ?? "");
  return m && !m[1].includes("수출명") ? m[1].trim() : "";
}

/* 약 이름 칸 + 자동완성.
 *
 * ⚠ 목록에 없는 약도 그대로 적을 수 있어야 한다 — 원내 조제약·신약은
 *   e약은요에 없다. 그래서 고르지 않아도 입력값이 곧 약 이름이다.
 * ⚠ 늦게 온 응답이 새 응답을 덮지 않게 요청마다 번호를 매긴다. */
function DrugNameInput({ value, onChange, onPick }) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [picked, setPicked] = useState(null);   /* 방금 고른 이름 — 그 값으로 다시 찾지 않는다 */
  /* 마지막으로 받은 답. 어느 질의의 답인지(q)를 함께 둬서 「찾는 중」을 따로
     들고 있지 않고 그 차이로 센다 */
  const [result, setResult] = useState({ q: "", items: [], error: null });
  const seq = useRef(0);

  const q = value.trim();
  const searching = q.length >= 2 && q !== picked;

  useEffect(() => {
    if (!searching) { seq.current += 1; return undefined; }
    const n = ++seq.current;
    const timer = setTimeout(async () => {
      try {
        const res = await api.drugs(q);
        if (n === seq.current) setResult({ q, items: res?.items ?? [], error: null });
      } catch (e) {
        if (n !== seq.current) return;
        setResult({ q, items: [], error: e.status === 503
          ? "약 검색을 지금 쓸 수 없습니다. 이름을 직접 입력해 주세요."
          : "약 검색에 실패했습니다. 이름을 직접 입력해 주세요." });
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [q, searching]);

  /* 새 답이 오기 전까지는 앞 답을 그대로 보여 준다 — 한 글자마다 목록이
     비었다 찼다 하면 읽을 수가 없다 */
  const items = searching ? result.items : [];
  const loading = searching && result.q !== q;
  const error = searching && result.q === q ? result.error : null;

  function choose(item) {
    setPicked(item.name);
    onPick(item);
    setOpen(false); setActive(-1);
  }

  function onKeyDown(e) {
    if (!open || !items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault(); setActive((i) => (i + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault(); setActive((i) => (i <= 0 ? items.length : i) - 1);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); choose(items[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const showList = open && searching;

  return (
    <div className="drug-suggest">
      <input
        role="combobox"
        aria-expanded={showList && items.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        value={value}
        onChange={(e) => { setPicked(null); setOpen(true); setActive(-1); onChange(e.target.value); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        placeholder="두 글자 이상 입력하면 약을 찾습니다"
      />
      {showList && (items.length > 0 || loading) && (
        <ul className="drug-suggest-list" id={listId} role="listbox">
          {items.map((item, i) => (
            <li
              key={item.item_seq}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "on" : undefined}
              /* blur 보다 먼저 잡아야 목록이 닫히기 전에 고른다 */
              onMouseDown={(e) => { e.preventDefault(); choose(item); }}
              onMouseEnter={() => setActive(i)}
            >
              <span className="drug-suggest-name">{item.name}</span>
              {item.maker && <span className="drug-suggest-maker">{item.maker}</span>}
            </li>
          ))}
          {loading && !items.length && <li className="drug-suggest-empty">찾는 중…</li>}
        </ul>
      )}
      {error && <span className="err">{error}</span>}
    </div>
  );
}

/* ⑥ 처방. 저장된 처방을 **약까지** 먼저 보여 준다 — 전에는 「저장된 처방
   N건」 숫자뿐이라 무엇을 이미 줬는지 보려면 환자 앱을 열어야 했다 */
function PrescriptionDraft({ patient, report, saved, blocked }) {
  const [drugs, setDrugs] = useState([emptyDrug()]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [writing, setWriting] = useState(false);
  const reportId = report?.report_id ?? null;
  const list = saved.data ?? [];

  function change(index, key, value) {
    setDrugs((rows) => rows.map((drug, i) => i === index ? { ...drug, [key]: value } : drug));
  }

  /* 자동완성에서 고른 약. 이름과, 비어 있으면 성분명까지만 채운다 —
     설명칸(purpose·how·watch)은 처방한 사람이 쓰는 자리라 건드리지 않는다 */
  function pick(index, item) {
    setDrugs((rows) => rows.map((drug, i) => i !== index ? drug : {
      ...drug,
      name: item.name,
      ingredient: drug.ingredient.trim() ? drug.ingredient : ingredientOf(item.name),
    }));
  }

  function remove(index) {
    setDrugs((rows) => rows.length === 1 ? rows : rows.filter((_, i) => i !== index));
  }

  async function save() {
    const cleaned = drugs.map((drug) => ({
      name: drug.name.trim(), ingredient: drug.ingredient.trim(),
      dose: drug.dose.trim(),
      /* 쉼표로 나눠 보낸다. 서버가 HH:MM 인지 보고 아니면 거절한다 —
         복약 기록이 이 값을 회차 열쇠로 쓰기 때문에 「아침」 같은 말이
         섞이면 같은 회차인지 판정할 길이 없다 */
      times: drug.times.split(",").map((time) => time.trim()).filter(Boolean),
      days: Number(drug.days), purpose: drug.purpose.trim(),
      how: drug.how.trim(), watch: drug.watch.trim(),
    }));
    if (!reportId || saving || blocked || cleaned.some((drug) => !drug.name || !drug.dose || !drug.times.length || !drug.days)) return;
    setSaving(true); setMsg(null);
    try {
      await api.prescribe(patient.patient_id, { report_id: reportId, content: { drugs: cleaned } });
      setDrugs([emptyDrug()]);
      setWriting(false);
      setMsg("처방을 저장했습니다. 환자 앱의 복약 관리에서 확인할 수 있습니다.");
      saved.reload(true);
    } catch (e) {
      setMsg(e.detail || e.message || "처방을 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  const valid = reportId && drugs.every((drug) =>
    drug.name.trim() && drug.dose.trim() && drug.times.trim() && Number(drug.days) > 0);

  return (
    <div className="prescription-draft">
      <p className="meta">저장 즉시 환자 앱의 복약 관리에 표시됩니다. 처방 일수는 약마다 따로 셉니다.</p>

      {saved.error && <p className="warnline">저장된 처방을 불러오지 못했습니다.</p>}
      {list.length > 0 && (
        <ul className="bf-rx">
          {list.map((rx, i) => (
            <li key={rx.prescription_id ?? i}>
              <span className="bf-rx-h">
                <b>{String(rx.prescribed_at ?? rx.created_at ?? "").slice(0, 10) || "날짜 없음"}</b>
                {rx.prescriber && <span className="note">{rx.prescriber}</span>}
              </span>
              {(rx.content?.drugs ?? []).map((d, j) => (
                <span className="bf-rx-d" key={j}>
                  <b>{d.name}</b>
                  {[d.dose, Array.isArray(d.times) ? d.times.join(", ") : d.times,
                    d.days ? `${d.days}일` : null, d.purpose].filter(Boolean).join(" · ")}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {blocked && <p className="note">판정 불일치(②)를 처분한 뒤 처방할 수 있습니다.</p>}
      {!blocked && !reportId && <p className="note">종합 리포트(③)가 생성된 뒤 처방을 저장할 수 있습니다.</p>}

      {!writing ? (
        <div className="card-foot split">
          <span className="note">{msg ?? (list.length ? `저장된 처방 ${list.length}건` : "아직 처방이 없습니다 — 약이 필요 없으면 건너뜁니다")}</span>
          <button className="btn ghost" onClick={() => setWriting(true)} disabled={blocked || !reportId}>
            + 새 처방
          </button>
        </div>
      ) : (
        <>
          {drugs.map((drug, index) => (
            <div className="prescription-drug" key={index}>
              <div className="prescription-drug-head">
                <b>약 {index + 1}</b>
                {drugs.length > 1 && <button className="edit-btn" onClick={() => remove(index)}>삭제</button>}
              </div>
              <div className="prescription-grid">
                <div className="field">
                  <label>약 이름 <span className="req">*</span></label>
                  <DrugNameInput
                    value={drug.name}
                    onChange={(value) => change(index, "name", value)}
                    onPick={(item) => pick(index, item)}
                  />
                </div>
                <div className="field">
                  <label>성분명</label>
                  <input value={drug.ingredient} onChange={(e) => change(index, "ingredient", e.target.value)} placeholder="예: 타목시펜시트르산염" />
                </div>
                <div className="field">
                  <label>1회 복용량 <span className="req">*</span></label>
                  <input value={drug.dose} onChange={(e) => change(index, "dose", e.target.value)} placeholder="예: 1정" />
                </div>
                <div className="field">
                  <label>복용 시간 <span className="req">*</span></label>
                  <input value={drug.times} onChange={(e) => change(index, "times", e.target.value)} placeholder="예: 09:00, 19:00" />
                </div>
                <div className="field">
                  <label>처방 일수 <span className="req">*</span></label>
                  <input type="number" min="1" value={drug.days} onChange={(e) => change(index, "days", e.target.value)} placeholder="일수" />
                </div>
                <div className="field">
                  <label>처방 목적</label>
                  <input value={drug.purpose} onChange={(e) => change(index, "purpose", e.target.value)} placeholder="환자 앱에 표시할 처방 목적" />
                </div>
              </div>
              <div className="field">
                <label>복용 안내</label>
                <textarea value={drug.how} onChange={(e) => change(index, "how", e.target.value)} placeholder="환자 앱에 표시할 복용 방법과 안내" />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>주의사항</label>
                <textarea value={drug.watch} onChange={(e) => change(index, "watch", e.target.value)} placeholder="이런 증상이 생기면 병원에 알리도록 — 환자 앱에 강조해서 표시된다" />
              </div>
            </div>
          ))}

          <div className="card-foot split prescription-actions">
            <button className="btn ghost sm" onClick={() => setDrugs((rows) => [...rows, emptyDrug()])}>+ 약 추가</button>
            <span className="note">{msg}</span>
            <button className="btn ghost" onClick={() => { setWriting(false); setDrugs([emptyDrug()]); }}>취소</button>
            <button className="btn" onClick={save} disabled={!valid || saving || blocked}>
              {saving ? "저장 중…" : "처방 저장"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/* ⑤ 환자 설명 → 잠금 해제.
 * ⚠ 09-28 — 칸 이름이 「의사 최종 소견」이었다. 실제로 받는 것은 **환자에게
 *   무엇을 어떻게 설명했나**이고, 저장하면 잠금 해제 조건 ③이 켜진다.
 *   소견은 ③의 의사 종합 소견이 맡는다 */
function ExplainForm({ report, onSaved, blocked, unlock }) {
  const [method, setMethod] = useState(report.explain_method ?? EXPLAIN_METHODS[0]);
  const [content, setContent] = useState(report.explain_content ?? "");
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
      setMsg("환자 설명이 기록되었습니다");
      unlock.reload(true);
      onSaved?.();
    } catch (e) {
      setMsg(e.detail || e.message || "환자 설명 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bf-block">
      {report.explained_at && (
        <p className="note">설명 기록 · {String(report.explained_at).replace("T", " ").slice(0, 16)}</p>
      )}
      <p className="section-label" style={{ marginTop: 0 }}>설명 방법</p>
      <div className="radio-group" style={{ flexDirection: "row" }}>
        {EXPLAIN_METHODS.map((m) => (
          <label className="radio-row" key={m} style={{ flex: 1, justifyContent: "center" }}>
            <input type="radio" name="explain_method" value={m} disabled={blocked}
              checked={method === m} onChange={() => setMethod(m)} />
            {m}
          </label>
        ))}
      </div>
      <div className="field">
        <label>설명 내용</label>
        <textarea value={content} disabled={blocked} onChange={(e) => setContent(e.target.value)}
                  placeholder="진단 · 치료 계획 · 예상 경과를 어떻게 설명했는지" />
      </div>
      <label className="check-row">
        <input type="checkbox" checked={confirmed} disabled={blocked}
          onChange={(e) => setConfirmed(e.target.checked)} />
        환자가 결과 및 치료 계획을 확인함
      </label>
      <div className="card-foot split">
        <span className="note">{msg ?? (blocked ? "판정 불일치(②)를 먼저 처분해 주세요" : null)}</span>
        <button className="btn" onClick={save} disabled={saving || blocked}>
          {saving ? "저장 중…" : "설명 기록 저장"}
        </button>
      </div>
      <section className="explain-lock" aria-label="환자 리포트 잠금">
        <p className="section-label">잠금 해제</p>
        <Body loading={unlock.loading && !unlock.data} error={unlock.error} onRetry={unlock.reload}>
          {unlock.data && (
            <LockPanel reportId={report.report_id} status={unlock.data}
              onUnlocked={() => { unlock.reload(true); onSaved?.(); }} />
          )}
        </Body>
      </section>
    </div>
  );
}

function LockPanel({ reportId, status, onUnlocked }) {
  const c = status.conditions ?? {};
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState(null);

  async function unlock() {
    setUnlocking(true);
    setError(null);
    try {
      await api.unlock(reportId);
      onUnlocked?.();
    } catch (e) {
      setError(e.detail || e.message || "잠금 해제에 실패했습니다.");
    } finally {
      setUnlocking(false);
    }
  }

  return (
    <div className={status.can_unlock ? "lock-panel unlocked" : "lock-panel"}>
      <span className="lock-icon" aria-hidden="true">{status.can_unlock ? "🔓" : "🔒"}</span>
      <p className="status">
        {status.can_unlock ? "조건을 모두 채웠습니다 — 풀 수 있습니다" : "환자 리포트가 잠겨 있습니다"}
      </p>
      <div className="cond-list">
        <Cond ok={c.all_finalized} label="① 전 레코드 확정" />
        <Cond ok={c.discordance_closed} label="② 대조 종결" />
        <Cond ok={c.explained} label="③ 대면 설명 완료" />
      </div>
      <button className="btn" disabled={!status.can_unlock || unlocking} onClick={unlock}>
        {unlocking ? "해제 중…" : "환자 리포트 열람 잠금 해제"}
      </button>
      {error && <p className="note err">{error}</p>}
      {!status.can_unlock && (
        <p className="hint">설명 기록 저장 후 환자 확인 체크 시 해제할 수 있습니다.</p>
      )}
    </div>
  );
}

function Cond({ ok, label }) {
  return (
    <div className="cond-row">
      <span>{label}</span>
      {ok ? <span className="check">✓</span> : <span className="pill wait">대기</span>}
    </div>
  );
}
