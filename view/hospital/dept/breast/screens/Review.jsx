import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { go } from "../../../nav";
import "../breast.css";   /* 유방외과 전용 — .breast 안에 갇혀 있다. 네 화면이 각자
                             끌고 온다: 주소로 곧장 들어와도 스타일이 빠지면 안 된다 */
import ReviewViewer from "../components/ReviewViewer";
import { MODALITY, label } from "../../../codes";
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
    <Page className="breast" crumb={["유방외과", "검사 종합 확인"]}
            title="검사 종합 확인"
            sub={patient ? `${patient.name} · ${patient.patient_number}` : ""}
            back={() => nav(go.breast.waiting(), { state: { advance: true, from: id } })}
            right={<button className="btn line" onClick={() => nav(go.breast.decision(id))}>수술 결정으로</button>}>
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {patient && <Inner patient={patient} timeline={timeline} />}
        </Body>
      </div>
    </Page>
  );
}

function Inner({ patient, timeline }) {
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  /* 뷰어가 지금 어느 모달리티를 보여주고 있는지. **서버 코드**다
     (mammo · us · mri) — saveReport 본문에 그대로 실려 나가므로 사람에게
     보여줄 때만 label(MODALITY, …) 을 거친다. codes.js 참고 —
   * 오른쪽 "유방외과 리포트" 작성란이 이 값을 그대로 따라간다(검사
   * 종합 확인 화면의 핵심 요구사항). ReviewViewer가 매 렌더마다 새
   * 함수를 받으면 그 안의 자동 탭 선택 useEffect가 다시 도는 걸 막기
   * 위해 useCallback으로 감싼다. */
  const [currentModality, setCurrentModality] = useState(null);
  const handleModalityChange = useCallback((modality) => {
    setCurrentModality(modality);
  }, []);

  return (
    <div
      className="review-grid"
      style={{
        "--left-w": leftOpen ? "minmax(190px,0.6fr)" : "34px",
        "--right-w": rightOpen ? "minmax(280px,1.1fr)" : "34px",
      }}
    >
      <div className={`card side-panel ${leftOpen ? "" : "collapsed"}`}>
        {leftOpen ? (
          <>
            <div className="panel-head"><h3>진료 이력</h3></div>
            <div className="timeline-scroll">
              <Body loading={timeline.loading} error={timeline.error} onRetry={timeline.reload}>
                {timeline.data && <Timeline events={timeline.data} />}
              </Body>
            </div>
          </>
        ) : (
          <span className="side-collapsed-label">진료 이력</span>
        )}
        <button
          type="button"
          className="side-toggle left"
          onClick={() => setLeftOpen((v) => !v)}
          aria-label={leftOpen ? "진료 이력 접기" : "진료 이력 펼치기"}
        >
          {leftOpen ? "‹" : "›"}
        </button>
      </div>

      <ReviewViewer
        patientId={patient.patient_id}
        lesions={patient.lesions ?? []}
        onModalityChange={handleModalityChange}
      />

      <div className={`card side-panel ${rightOpen ? "" : "collapsed"}`}>
        {rightOpen ? (
          <>
            <div className="panel-head"><h3>리포트 확인</h3></div>
            <ReportPanel patient={patient} currentModality={currentModality} />
          </>
        ) : (
          <span className="side-collapsed-label">리포트 확인</span>
        )}
        <button
          type="button"
          className="side-toggle right"
          onClick={() => setRightOpen((v) => !v)}
          aria-label={rightOpen ? "리포트 확인 접기" : "리포트 확인 펼치기"}
        >
          {rightOpen ? "›" : "‹"}
        </button>
      </div>
    </div>
  );
}

/* ⚠ 서버 PatientTimelineView(2026-09-18 확인)는 {at, type, detail,
 * assessment_id} 만 준다 — label 이 없다. type 자체가 이미 "촬영"·
 * "AI 분석 완료"·"판독"·"검체 채취"·"병리 확진" 같은 한글이라 그대로
 * 제목으로 쓴다. */
function Timeline({ events }) {
  if (events.length === 0) {
    return <p style={{ fontSize: 13, color: "var(--muted)" }}>아직 기록이 없습니다</p>;
  }
  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div className="row" key={i}>
          <span className="dot" aria-hidden="true" />
          <p className="label">{e.type}</p>
          <p className="at">{e.at?.replace("T", " ").slice(0, 16)}</p>
          {e.detail && <p className="detail">{e.detail}</p>}
        </div>
      ))}
    </div>
  );
}

/* 예전엔 이 세 리포트를 탭으로 갈아 끼웠는데, 그러면 "지금 보고 있는
 * 검사에 대한 AI/타부서 소견"과 "유방외과 리포트 작성"을 동시에 볼 수
 * 없었다 — 비교하려면 탭을 왔다 갔다 해야 했다. 세 구역을 세로로 고정
 * 배치하고 각자 내부 스크롤을 주면, AI·타부서 리포트(읽기 전용)는 위에
 * 계속 떠 있고 유방외과 리포트(현재 modality에 맞춰 쓰는 곳)만 아래서
 * 그때그때 바뀐다. */
function ReportPanel({ patient, currentModality }) {
  const report = patient.report;

  /* 유방외과 소견은 지금 뷰어가 보여주는 모달리티별로 따로 쓴다 —
   * MRI에서 쓰던 걸 초음파로 넘어갔다가 다시 MRI로 돌아와도 그대로
   * 남아 있어야 하니 modality별 텍스트를 따로 들고 있는다. 서버 저장분
   * (content_json.by_modality, 2026-09-18 다희님 확인)으로 초깃값을
   * 채운다 — 전엔 새로고침마다 빈 칸으로 시작해서 저장했던 게 안 보였다. */
  const [surgeonReports, setSurgeonReports] = useState(() => report?.content_json?.by_modality ?? {});

  if (!report) {
    return (
      <div className="report-stack">
        <ReportBlock title="리포트 확인" grow>
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            아직 생성된 검사 리포트가 없습니다. 영상 또는 병리 판독이 확정되면 표시됩니다.
          </p>
        </ReportBlock>
      </div>
    );
  }

  return (
    <div className="report-stack">
      <ReportBlock title="모달리티별 AI 리포트" fixed>
        <AIModelResult aiModel={report.ai_model} />
      </ReportBlock>

      <ReportBlock title="타 부서 의사 리포트" fixed>
        {patient.other_reports?.length > 0 ? patient.other_reports.map((r, i) => (
          <div className="other-report" key={i}>
            <span className="dept">{r.dept}</span>
            <span className="author">{r.author}</span>
            <p className="summary">{r.summary}</p>
            <p className="at">{r.at?.replace("T", " ").slice(0, 16)}</p>
          </div>
        )) : <p style={{ fontSize: 13, color: "var(--muted)" }}>아직 리포트가 없습니다</p>}
      </ReportBlock>

      {/* ⚠ 카드 제목에도 라벨을 거친다. 여기만 빠뜨려서 「유방외과 리포트 · us」
          처럼 서버 코드가 날것으로 보이고 있었다 — 탭과 안내문은 한글인데
          제목만 영문이라 같은 화면에서 두 말이 섞였다 */}
      <ReportBlock title={currentModality
                     ? `유방외과 리포트 · ${label(MODALITY, currentModality)}`
                     : "유방외과 리포트"} grow>
        <FinalReportForm
          report={report}
          modality={currentModality}
          text={currentModality ? (surgeonReports[currentModality] ?? "") : ""}
          onTextChange={(value) =>
            currentModality &&
            setSurgeonReports((prev) => ({ ...prev, [currentModality]: value }))
          }
        />
      </ReportBlock>
    </div>
  );
}

function ReportBlock({ title, fixed, grow, children }) {
  return (
    <section className={`report-block ${fixed ? "fixed" : ""} ${grow ? "grow" : ""}`}>
      <h4>{title}</h4>
      <div className="report-block-body">{children}</div>
    </section>
  );
}

function FinalReportForm({ report, modality, text, onTextChange }) {
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  /* ⚠ 2026-09-18 다희님 확인 — PUT /reports/{id}/ 는 content_json 만 본다
   * (surgery.py:97-103). { modality, doctor_summary } 를 최상위로 보내던
   * 건 그동안 서버 값을 하나도 안 바꾸고 있었다. 모달리티별로 서로
   * 덮어쓰지 않게 merge 하는 건 서버가 한다 — by_modality.{modality} 한
   * 칸만 보내면 된다. */
  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.saveReport(report.report_id, { content_json: { by_modality: { [modality]: text } } });
      setMsg("저장되었습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="field" style={{ flex: 1, minHeight: 0, marginBottom: 8 }}>
        <textarea
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          style={{ height: "100%", minHeight: 70, resize: "none" }}
          placeholder={
            modality
              ? `${label(MODALITY, modality)} 검사에 대한 유방외과 소견을 작성해 주세요`
              : "유방외과 종합 소견을 작성해 주세요"
          }
        />
      </div>
      <div className="card-foot split" style={{ flex: "0 0 auto" }}>
        <span className="note">{msg}</span>
        <button className="btn ghost" onClick={save} disabled={saving || !modality}>
          {saving ? "저장 중…" : "리포트 저장"}
        </button>
      </div>
    </div>
  );
}
