import { useEffect, useId, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { REPORT_DEPT, SEX, label } from "../../../codes";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { useCan } from "../../../lib/Parts";
import { go } from "../../../nav";
import "../breast.css";   /* 유방외과 전용 — .breast 안에 갇혀 있다. 네 화면이 각자
                             끌고 온다: 주소로 곧장 들어와도 스타일이 빠지면 안 된다 */

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

/* 화면 3 · 치료 방침 결정 및 환자 설명 ("/patients/:id/decision")
 *
 * 3열 2행: (좌)AI·의사 종합 리포트 / (중)수술 여부·환자 처방 /
 * (우)환자 정보·의사 최종 소견. 환자 리포트 상태와 잠금 해제는 최종
 * 소견 카드 안에서 함께 처리한다.
 *
 * 잠금 해제 3조건(①전 레코드 확정 ②대조 종결 ③대면 설명 완료)은 서버가
 * 판단해서 GET /reports/{id}/unlock-status 로 내려준다 — 화면은 그 결과를
 * 그대로 보여주고 셋 다 참일 때만 [잠금 해제] 버튼을 켠다.
 *
 * 진료 이력의 치료 결정 · 리포트 · 결과 설명 · 처방 줄에서 오면 ?focus= 가
 * 붙는다(dept/breast/history.js). 그 칸(id="dec-…")으로 내려가 왼쪽 선으로
 * 짚는다. ⚠ 지난 결정 · 설명의 **그때 값**을 보여 주지는 못한다 — 서버가
 * 결정을 판독 행에 덮어쓰고(decision_*), 설명도 리포트 행에 덮어쓴다. */
export default function Decision() {
  const { id } = useParams();
  const nav = useNavigate();
  const [q] = useSearchParams();
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);

  return (
    /* 되돌릴 수 없는 결정을 저장하는 화면이다. **누구인지 안 보이면 안 된다** */
    <Page className="breast" crumb={["유방외과", "치료 방침"]}
            title="치료 방침" patient={patient}
            back={() => nav(go.breast.waiting(), { state: { advance: true, from: id } })}>
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {patient && <Inner patient={patient} onReload={reload} focus={q.get("focus")} />}
        </Body>
      </div>
    </Page>
  );
}

function Inner({ patient, onReload, focus }) {
  const report = patient.report;
  const reportId = report?.report_id ?? null;
  const reports = useApi(() => api.reports(patient.patient_id), [patient.patient_id]);
  const unlock = useApi(
    () => reportId ? api.unlockStatus(reportId) : Promise.resolve(null),
    [reportId],
  );

  /* 수술 결정은 assessment 한 건에 매달린다(models.py:675 — study 에 물려
   * 있지 patient 에 안 물려 있다). patient_id 로는 못 찾고, timeline 의
   * "판독" 이벤트가 assessment_id 를 실어 준다(2026-09-18, 다희님 —
   * feature/dahee 6774208). 이 환자의 가장 최근 판독을 결정 대상으로
   * 삼는다. */
  const timeline = useApi(() => api.timeline(patient.patient_id), [patient.patient_id]);
  const reads = (timeline.data ?? []).filter((e) => e.type === "판독" && e.assessment_id != null);
  const assessmentId = reads.length ? reads[reads.length - 1].assessment_id : null;

  /* 이력에서 골라 온 칸. Inner 는 환자가 온 뒤에 서므로 칸이 이미 있다.
     ⚠ 리포트 칸은 뒤늦게 차며 길어진다 — 가운데가 아니라 머리로 맞춘다 */
  const at = (key) => focus === key;
  useEffect(() => {
    if (focus) document.getElementById(`dec-${focus}`)?.scrollIntoView({ block: "start" });
  }, [focus]);

  /* 배치는 `docs/mockup/SurgeryDecision.html` — **두 단이다.**
     왼쪽이 «지금 하는 일»(결정·리포트·처방·소견), 오른쪽이 «보면서 하는
     것»(환자 정보·결정 기록). 전에는 세 단이었는데 저장 단추가 가운데 열
     하나에만 몰려 있어서 눈이 좌우로 계속 튀었다.

     ⚠ **목업의 「수술 계획」 칸(술식·측·수술 예정일·집도)은 못 만든다.**
       그 값을 받는 경로가 서버에 없다 — assessment 의 decision 은
       종류·가부·근거 셋뿐이고 수술 일정 자원이 따로 없다(8장).
       지어내지 않고, 있는 저장 경로 일곱을 그대로 둔다. */
  return (
    <>
      {patient.data_warnings?.length > 0 && (
        <p className="warnline">
          일부 자료를 불러오지 못했습니다: {patient.data_warnings.join(", ")}. 새로고침 후 다시 확인해 주세요.
        </p>
      )}
      <div className="decision-grid">
      <div className="dec-col">
        <DecisionForm assessmentId={assessmentId} assessmentIdLoading={timeline.loading}
                      here={at("decision")} />
        {/* 만든 뒤에도 생성 칸을 남긴다 — 전에는 리포트가 있으면 이 칸이
            사라져서 판독이 더 들어와도 다시 만들 길이 없었다 */}
        {report && <AiSummaryCard report={report} here={at("report")} />}
        <FinalReportCard patient={patient} reports={reports} onCreated={onReload} again={Boolean(report)}
                         here={!report && at("report")} />
        {report ? <DoctorSummaryCard report={report} /> : <PendingReportCard title="의사 종합 리포트" />}
        <PrescriptionDraft patient={patient} report={report} here={at("prescription")} />
      </div>

      <div className="dec-col">
        <PatientInfoCard patient={patient} />
        <PatientReportCard report={patient.patient_report} reports={reports} unlock={unlock}
                           here={at("patient-report")} />
        {report
          ? <ExplainForm report={report} onSaved={onReload} unlock={unlock} here={at("explain")} />
          : <PendingReportCard title="의사 최종 소견" here={at("explain")} />}
      </div>
      </div>
    </>
  );
}

/* 환자에게 공개되는 리포트를 결정 화면에서도 바로 확인한다. 기존에는
   리포트가 왼쪽 작성 카드 안에만 있어, 결정 기록과 환자 정보 아래에서
   최종 결과를 찾기 어려웠다. 최종 리포트가 없으면 확정된 검사별 리포트
   목록을 보여 주고, 잠금 상태는 서버의 unlock-status를 그대로 표시한다. */
/* 이력에서 골라 온 칸의 뿌리 속성 — id 는 스크롤 자리, here 는 표시 */
const spot = (key, here, cls = "card") => ({
  id: here ? `dec-${key}` : undefined,
  className: here ? `${cls} here` : cls,
});

function PatientReportCard({ report, reports, here = false }) {
  const stageReports = (reports.data ?? []).filter((row) => row.report_type === "stage");
  const content = report?.content_json ?? {};
  const title = report ? "최종 환자 리포트" : "환자 리포트 열람";
  const status = report ? (report.is_unlocked ? "열람 가능" : "잠금 상태") : "작성 대기";

  return (
    <div {...spot("patient-report", here, "card patient-report-card")}>
      <div className="card-head">
        <h3>{title}</h3>
        <span className={`pill ${report?.is_unlocked ? "ok" : report ? "wait" : "warn"}`}>{status}</span>
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
            <p className="section-label">종합 요약</p>
            <p className="card-text">{report.ai_summary || content.doctor_summary || "등록된 요약이 없습니다."}</p>
            {report.ai_evidence?.length > 0 && (
              <>
                <p className="section-label">주요 근거</p>
                <ul className="bullets compact">{report.ai_evidence.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul>
              </>
            )}
            <p className="note report-lock-note">잠금 해제 조건과 환자 공개 여부는 아래 환자 설명 카드에서 관리합니다.</p>
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

function PendingReportCard({ title, here = false }) {
  return (
    <div {...spot("explain", here)}>
      <div className="card-head"><h3>{title}</h3></div>
      <p className="card-text">아직 생성된 종합 리포트가 없습니다. 판독 확정 후 작성할 수 있습니다.</p>
    </div>
  );
}

function FinalReportCard({ patient, reports, onCreated, again = false, here = false }) {
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
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

  return (
    <div {...spot("report", here)}>
      <div className="card-head"><h3>{again ? "AI 종합 리포트 다시 만들기" : "AI 종합 리포트"}</h3></div>
      <p className="card-text">
        {again
          ? "판독이 더 들어왔으면 골라서 새로 만듭니다. 새 리포트가 위 칸에 뜹니다."
          : "확정된 검사 판독문을 선택해 최종 종합 리포트를 생성합니다."}
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
      <div className="card-foot"><button className="btn fill" onClick={create} disabled={busy || !effectiveSelected.length}>
        {busy ? "생성 중…" : again ? "다시 생성" : "최종 리포트 생성"}
      </button></div>
    </div>
  );
}

function AiSummaryCard({ report, here = false }) {
  return (
    <div {...spot("report", here)}>
      <div className="card-head">
        <h3>AI 종합 리포트</h3>
        <span className="pill" style={{ background: "var(--accent-weak)", color: "var(--accent)" }}>
          {/* 센 것은 모달리티가 아니라 묶은 판독 수다(source_ai_ids) */}
          {report.ai_modality_count ? `판독 ${report.ai_modality_count}건 통합` : "통합"}
        </span>
      </div>
      <p className="section-label">요약</p>
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
 * 는 이 필드만 본다(surgery.py:97-103) — doctor_summary 를 최상위로
 * 보내던 예전 코드는 그동안 아무 것도 저장하지 못하고 있었다. 모달리티별
 * 덮어쓰기(merge)는 서버가 처리하기로 했다 — 여기서는 그냥 이 모양대로
 * 보내기만 한다. */
function DoctorSummaryCard({ report }) {
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
    <div className="card">
      <div className="card-head">
        <h3>의사 종합 리포트</h3>
        {/* ⚠ doctor_summary_author 도 서버 Report 모델에 없는 필드다(목업
            전용). 지금 로그인한 의사 이름을 붙이려면 세션 쪽에서 가져와야
            하는데 그 경로가 아직 없어 일단 안 지우고 옵셔널 체이닝만
            건다 — 실서버에서는 빈 칸으로 보인다. */}
        <span className="person-chip" style={{ marginLeft: "auto" }}>
          <span className="avatar sm" aria-hidden="true">{report.doctor_summary_author?.[0]}</span>
          <span className="id">
            <b>{report.doctor_summary_author}</b>
            <span>유방외과</span>
          </span>
        </span>
      </div>
      <div className="field" style={{ marginBottom: 8 }}>
        <textarea value={text} onChange={(e) => setText(e.target.value)}
          style={{ minHeight: 110 }} placeholder="종합 소견을 작성해 주세요" />
      </div>
      <div className="card-foot split">
        <span className="note">{msg}</span>
        <button className="btn ghost" onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "리포트 저장"}
        </button>
      </div>
    </div>
  );
}

function DecisionForm({ assessmentId, assessmentIdLoading, here = false }) {
  /* ⚠ report.decision 은 서버에 없는 필드다(Report 모델엔 decision_*
   * 이 없다 — 그건 Assessment 쪽이다). 예전엔 여기서 그 값으로 초깃값을
   * 채웠는데, 있지도 않은 이전 결정을 읽는 척하던 것이라 뺐다. 저장된
   * 값을 다시 읽어오는 확정된 경로가 생기면 그때 채운다. */
  const [decisionValue, setDecisionValue] = useState(DECISIONS[0].v);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const may = useCan("breast.decision.save");

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.decide(assessmentId, {
        decision_type: "surgery", decision_value: decisionValue, decision_reason: reason,
      });
      setMsg("결정이 저장되었습니다");
    } catch (e) {
      setMsg(e.detail || e.message || "결정 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div {...spot("decision", here)}>
      <h3>수술 여부</h3>
      <div className="radio-group" style={{ marginTop: 12 }}>
        {DECISIONS.map((d) => (
          <label className="radio-row" key={d.v}>
            <input type="radio" name="decision_value" value={d.v}
              checked={decisionValue === d.v} disabled={!may.ok}
              onChange={() => setDecisionValue(d.v)} />
            {d.label}
          </label>
        ))}
      </div>
      <div className="field">
        <label>수술 관련 결정 사유</label>
        <textarea value={reason} disabled={!may.ok}
          onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="card-foot split">
        <span className="note">
          {msg ?? (!assessmentIdLoading && !assessmentId ? "판독 기록이 아직 없어 저장할 수 없습니다" : null)}
        </span>
        <button className="btn ghost" onClick={save} {...may.attrs}
          disabled={saving || !assessmentId || !may.ok}>
          {saving ? "저장 중…" : "결정 저장"}
        </button>
      </div>
    </div>
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

function PrescriptionDraft({ patient, report, here = false }) {
  const [drugs, setDrugs] = useState([emptyDrug()]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const saved = useApi(() => api.prescriptions(patient.patient_id), [patient.patient_id]);
  const reportId = report?.report_id ?? null;

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
    if (!reportId || saving || cleaned.some((drug) => !drug.name || !drug.dose || !drug.times.length || !drug.days)) return;
    setSaving(true); setMsg(null);
    try {
      await api.prescribe(patient.patient_id, { report_id: reportId, content: { drugs: cleaned } });
      setDrugs([emptyDrug()]);
      setMsg("처방을 저장했습니다. 환자 앱의 복약 관리에서 확인할 수 있습니다.");
      saved.reload();
    } catch (e) {
      setMsg(e.detail || e.message || "처방을 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  const valid = reportId && drugs.every((drug) =>
    drug.name.trim() && drug.dose.trim() && drug.times.trim() && Number(drug.days) > 0);

  return (
    <div {...spot("prescription", here, "card prescription-draft")}>
      <div className="card-head">
        <div>
          <h3>환자 처방</h3>
          <p className="meta">저장 즉시 환자 앱의 복약 관리에 표시됩니다. 처방 일수는 약마다 따로 셉니다.</p>
        </div>
      </div>

      {saved.data?.length > 0 && <p className="meta">저장된 처방 {saved.data.length}건</p>}
      {saved.error && <p className="warnline">저장된 처방을 불러오지 못했습니다.</p>}
      {!reportId && <p className="note">종합 리포트가 생성된 뒤 처방을 저장할 수 있습니다.</p>}

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
          </div>
          <div className="field">
            <label>처방 목적</label>
            <input value={drug.purpose} onChange={(e) => change(index, "purpose", e.target.value)} placeholder="환자 앱에 표시할 처방 목적" />
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
        <button className="btn" onClick={save} disabled={!valid || saving}>
          {saving ? "저장 중…" : "처방 저장"}
        </button>
      </div>
    </div>
  );
}

function ExplainForm({ report, onSaved, unlock, here = false }) {
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
      onSaved?.();
    } catch (e) {
      setMsg(e.detail || e.message || "환자 설명 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div {...spot("explain", here)}>
      <div className="card-head">
        <h3>의사 최종 소견</h3>
        <span className="meta">환자 설명</span>
      </div>
      <p className="section-label" style={{ marginTop: 0 }}>환자 설명 방법</p>
      <div className="radio-group" style={{ flexDirection: "row" }}>
        {EXPLAIN_METHODS.map((m) => (
          <label className="radio-row" key={m} style={{ flex: 1, justifyContent: "center" }}>
            <input type="radio" name="explain_method" value={m}
              checked={method === m} onChange={() => setMethod(m)} />
            {m}
          </label>
        ))}
      </div>
      <div className="field">
        <label>설명 내용</label>
        <textarea value={content} onChange={(e) => setContent(e.target.value)} />
      </div>
      <label className="check-row">
        <input type="checkbox" checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)} />
        환자가 결과 및 치료 계획을 확인함
      </label>
      <div className="card-foot split">
        <span className="note">{msg}</span>
        <button className="btn" onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "설명 기록 저장"}
        </button>
      </div>
      <section className="explain-lock" aria-label="환자 리포트 상태">
        <p className="section-label">환자 리포트 상태</p>
        <Body loading={unlock.loading} error={unlock.error} onRetry={unlock.reload}>
          {unlock.data && (
            <LockPanel reportId={report.report_id} status={unlock.data}
              onUnlocked={() => { unlock.reload(); onSaved?.(); }} />
          )}
        </Body>
      </section>
    </div>
  );
}

function PatientInfoCard({ patient }) {
  const sex = label(SEX, patient.sex) || "—";
  const age = patient.age != null ? `${patient.age}세` : "—";
  const birth = patient.birth_date || "—";
  const rows = [
    { k: "이름", v: patient.name },
    { k: "성별 / 나이", v: `${sex} / ${age} (${birth})` },
    { k: "등록번호", v: patient.patient_number },
    { k: "연락처", v: patient.phone },
    { k: "알레르기", v: patient.allergy },
    { k: "주치의", v: patient.primary_staff_name ? `${patient.primary_staff_name} 선생님` : null },
    { k: "내원 구분", v: patient.visit_type },
    { k: "검사 목적", v: patient.visit_purpose },
    { k: "간호 메모", v: patient.intake_note },
  ];

  return (
    <div className="card">
      <div className="card-head">
        <h3>환자 정보</h3>
      </div>
      <div className="pt-info">
        {rows.map((r) => (
          <div className="row" key={r.k}>
            <span className="k">{r.k}</span>
            <span className="v">{r.v || "—"}</span>
          </div>
        ))}
      </div>
      <div className="card-foot" style={{ marginTop: 14 }}><span className="note">접수·간호 기록을 기준으로 표시합니다.</span></div>
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
        {status.can_unlock ? "현재 열람 가능 (unlocked)" : "현재 열람 잠금 (locked)"}
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
