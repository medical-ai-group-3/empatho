import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Head, Body } from "../../../lib/Screen";
import ReviewViewer from "../components/ReviewViewer";
import AIModelResult from "../components/AIModelResult";

/* 화면 2 · 검사 종합 확인 ("/patients/:id/review")
 *
 * 정리본 §2-2: 좌(진료 이력, 접기 가능) · 중(뷰어) · 우(리포트 확인, 접기
 * 가능·탭 3개). 가운데 뷰어는 ReviewViewer(components/ReviewViewer.jsx)가
 * GET /patients/{id}/studies 를 받아 그린다 — 실제 이미지가 없는 모달리티는
 * 자동으로 "샘플 이미지 없음"을 보여준다.
 *
 * "수술 결정(임시)" 다리는 대기 화면(§1)에 있었는데, 여기가 생겼으니
 * 이 화면 헤더로 옮긴다 — 검사 결과를 다 보고 나서 수술을 결정하는
 * 흐름이 맞다. */
export default function Review() {
  const { id } = useParams();
  const nav = useNavigate();
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);
  const timeline = useApi(() => api.timeline(id), [id]);

  return (
    <>
      <Head title="검사 종합 확인" sub={patient ? `${patient.name} · ${patient.patient_number}` : ""}
        back={() => nav("/", { state: { advance: true, from: id } })}
        right={<button className="btn" onClick={() => nav(`/patients/${id}/decision`)}>수술 결정으로</button>} />
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {patient && <Inner patient={patient} timeline={timeline} />}
        </Body>
      </div>
    </>
  );
}

function Inner({ patient, timeline }) {
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  /* 뷰어가 지금 어느 모달리티(맘모/초음파/MRI/병리)를 보여주고 있는지 —
   * 오른쪽 "유방외과 리포트" 작성란이 이 값을 그대로 따라간다(검사
   * 종합 확인 화면의 핵심 요구사항). ReviewViewer가 매 렌더마다 새
   * 함수를 받으면 그 안의 자동 탭 선택 useEffect가 다시 도는 걸 막기
   * 위해 useCallback으로 감싼다. */
  const [currentModality, setCurrentModality] = useState(null);
  const handleModalityChange = useCallback((modality) => {
    setCurrentModality(modality);
  }, []);

  return (
    <div className="review-grid">
      <div className="card">
        <div className="panel-head">
          <h3>진료 이력</h3>
          <button className="collapse-btn" onClick={() => setLeftOpen((v) => !v)}>
            {leftOpen ? "접기" : "펼치기"}
          </button>
        </div>
        {leftOpen && (
          <Body loading={timeline.loading} error={timeline.error} onRetry={timeline.reload}>
            {timeline.data && <Timeline events={timeline.data} />}
          </Body>
        )}
      </div>

      <ReviewViewer
        patientId={patient.patient_id}
        lesions={patient.lesions ?? []}
        onModalityChange={handleModalityChange}
      />

      <div className="card">
        <div className="panel-head">
          <h3>리포트 확인</h3>
          <button className="collapse-btn" onClick={() => setRightOpen((v) => !v)}>
            {rightOpen ? "접기" : "펼치기"}
          </button>
        </div>
        {rightOpen && <ReportTabs patient={patient} currentModality={currentModality} />}
      </div>
    </div>
  );
}

function Timeline({ events }) {
  if (events.length === 0) {
    return <p style={{ fontSize: 13, color: "var(--muted)" }}>아직 기록이 없습니다</p>;
  }
  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div className="row" key={i}>
          <span className="dot" aria-hidden="true" />
          <p className="label">{e.label}</p>
          <p className="at">{e.at?.replace("T", " ").slice(0, 16)}</p>
          {e.detail && <p className="detail">{e.detail}</p>}
        </div>
      ))}
    </div>
  );
}

const REPORT_TABS = ["모달리티별 AI 리포트", "타 부서 의사 리포트", "유방외과 리포트"];

function ReportTabs({ patient, currentModality }) {
  const [tab, setTab] = useState(REPORT_TABS[0]);
  const report = patient.report;

  /* 유방외과 소견은 지금 뷰어가 보여주는 모달리티별로 따로 쓴다 —
   * MRI 탭에서 쓰던 걸 초음파로 넘어갔다가 다시 MRI로 돌아와도 그대로
   * 남아 있어야 하니, 탭 전환과 무관하게 여기(ReportTabs)에서
   * modality별 텍스트를 들고 있는다. */
  const [surgeonReports, setSurgeonReports] = useState({});

  return (
    <>
      <div className="tabs">
        {REPORT_TABS.map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "모달리티별 AI 리포트" && <AIModelResult aiModel={report.ai_model} />}

      {tab === "타 부서 의사 리포트" && (
        <div>
          {patient.other_reports?.length > 0 ? patient.other_reports.map((r, i) => (
            <div className="other-report" key={i}>
              <span className="dept">{r.dept}</span>
              <span className="author">{r.author}</span>
              <p className="summary">{r.summary}</p>
              <p className="at">{r.at?.replace("T", " ").slice(0, 16)}</p>
            </div>
          )) : <p style={{ fontSize: 13, color: "var(--muted)" }}>아직 리포트가 없습니다</p>}
        </div>
      )}

      {tab === "유방외과 리포트" && (
        <FinalReportForm
          report={report}
          modality={currentModality}
          text={currentModality ? (surgeonReports[currentModality] ?? "") : ""}
          onTextChange={(value) =>
            currentModality &&
            setSurgeonReports((prev) => ({ ...prev, [currentModality]: value }))
          }
        />
      )}
    </>
  );
}

function FinalReportForm({ report, modality, text, onTextChange }) {
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.saveFinalReport(report.report_id, { modality, doctor_summary: text });
      setMsg("저장되었습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      {modality && (
        <div className="row" style={{ marginBottom: 8 }}>
          <span className="k">현재 검사</span>
          <span className="v">{modality}</span>
        </div>
      )}
      <div className="field" style={{ marginBottom: 8 }}>
        <textarea
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          style={{ minHeight: 160 }}
          placeholder={
            modality
              ? `${modality} 검사에 대한 유방외과 소견을 작성해 주세요`
              : "유방외과 종합 소견을 작성해 주세요"
          }
        />
      </div>
      <div className="card-foot split">
        <span className="note">{msg}</span>
        <button className="btn ghost" onClick={save} disabled={saving || !modality}>
          {saving ? "저장 중…" : "리포트 저장"}
        </button>
      </div>
    </div>
  );
}
