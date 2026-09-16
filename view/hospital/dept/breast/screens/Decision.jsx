import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { go } from "../../../nav";
import "../breast.css";   /* 유방외과 전용 — .breast 안에 갇혀 있다. 네 화면이 각자
                             끌고 온다: 주소로 곧장 들어와도 스타일이 빠지면 안 된다 */

const DECISIONS = [
  { v: "surgery",    label: "수술 시행" },
  { v: "no_surgery", label: "수술하지 않음" },
  { v: "hold",       label: "보류" },
];
const EXPLAIN_METHODS = ["대면", "유선", "영상"];

/* 화면 3 · 수술 결정 및 환자 설명 ("/patients/:id/decision")
 *
 * 3열: (좌)AI·의사 종합 리포트 열람·작성 / (중)수술 여부·결정 사유 + 의사
 * 최종 소견·환자 설명 / (우)환자 정보 + 리포트 잠금 상태.
 *
 * 잠금 해제 3조건(①전 레코드 확정 ②대조 종결 ③대면 설명 완료)은 서버가
 * 판단해서 GET /reports/{id}/unlock-status 로 내려준다 — 화면은 그 결과를
 * 그대로 보여주고 셋 다 참일 때만 [잠금 해제] 버튼을 켠다. */
export default function Decision() {
  const { id } = useParams();
  const nav = useNavigate();
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);

  return (
    <Page className="breast" crumb={["유방외과", "수술 결정"]}
            title="수술 결정 및 환자 설명"
            sub={patient ? `${patient.name} · ${patient.patient_number}` : ""}
            back={() => nav(go.breast.waiting(), { state: { advance: true, from: id } })}>
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {patient && <Inner patient={patient} onReload={reload} />}
        </Body>
      </div>
    </Page>
  );
}

function Inner({ patient, onReload }) {
  const report = patient.report;
  const unlock = useApi(() => api.unlockStatus(report.report_id), [report.report_id]);

  return (
    <div className="cols3">
      <div>
        <div className="card">
          <div className="card-head">
            <h3>AI 종합 리포트</h3>
            <span className="pill" style={{ background: "var(--accent-weak)", color: "var(--accent)" }}>
              {report.ai_modality_count}개 모달리티 통합
            </span>
          </div>
          <p className="section-label">요약</p>
          <p className="card-text">{report.ai_summary || "아직 생성되지 않았습니다"}</p>
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

        <DoctorSummaryCard report={report} />
      </div>

      <div>
        <DecisionForm patientId={patient.patient_id} report={report} />
        <ExplainForm report={report} onSaved={onReload} />
      </div>

      <div>
        <PatientInfoCard patient={patient} />
        <div className="card">
          <h3>환자 리포트 상태</h3>
          <Body loading={unlock.loading} error={unlock.error} onRetry={unlock.reload}>
            {unlock.data && (
              <LockPanel reportId={report.report_id} status={unlock.data}
                onUnlocked={() => { unlock.reload(); onReload?.(); }} />
            )}
          </Body>
        </div>
      </div>
    </div>
  );
}

function DoctorSummaryCard({ report }) {
  const [text, setText] = useState(report.doctor_summary ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    try {
      await api.saveFinalReport(report.report_id, { doctor_summary: text });
      setMsg("저장되었습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>의사 종합 리포트</h3>
        <span className="person-chip" style={{ marginLeft: "auto" }}>
          <span className="avatar sm" aria-hidden="true">{report.doctor_summary_author[0]}</span>
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

function DecisionForm({ patientId, report }) {
  const [decisionType, setDecisionType] = useState(report.decision?.decision_type ?? "surgery");
  const [reason, setReason] = useState(report.decision?.decision_reason ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    try {
      await api.createAssessment({
        patient_id: patientId, decision_type: decisionType, decision_reason: reason,
      });
      setMsg("결정이 저장되었습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h3>수술 여부</h3>
      <div className="radio-group" style={{ marginTop: 12 }}>
        {DECISIONS.map((d) => (
          <label className="radio-row" key={d.v}>
            <input type="radio" name="decision_type" value={d.v}
              checked={decisionType === d.v} onChange={() => setDecisionType(d.v)} />
            {d.label}
          </label>
        ))}
      </div>
      <div className="field">
        <label>수술 관련 결정 사유</label>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="card-foot split">
        <span className="note">{msg}</span>
        <button className="btn ghost" onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "결정 저장"}
        </button>
      </div>
    </div>
  );
}

function ExplainForm({ report, onSaved }) {
  const [method, setMethod] = useState(report.explain_method ?? EXPLAIN_METHODS[0]);
  const [content, setContent] = useState(report.explain_content ?? "");
  const [confirmed, setConfirmed] = useState(report.patient_confirmed ?? false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    try {
      await api.explainReport(report.report_id, {
        explain_method: method, explain_content: content, patient_confirmed: confirmed,
      });
      setMsg("환자 설명이 기록되었습니다");
      onSaved?.();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
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
    </div>
  );
}

function PatientInfoCard({ patient }) {
  const [editing, setEditing] = useState(false);
  const [phone, setPhone] = useState(patient.phone ?? "");
  const [address, setAddress] = useState(patient.address ?? "");
  const [msg, setMsg] = useState(null);

  const rows = [
    { k: "이름", v: patient.name },
    { k: "성별 / 나이", v: `${patient.sex === "F" ? "Female" : "Male"} / ${patient.age}세 (${patient.birth_date})` },
    { k: "등록번호", v: patient.patient_number },
    { k: "Accession No.", v: patient.accession_no },
    { k: "연락처", v: phone, editable: true, onChange: setPhone },
    { k: "주소", v: address, editable: true, onChange: setAddress },
    { k: "주치의", v: `${patient.primary_staff_name} 선생님` },
    { k: "의뢰일", v: patient.referral_date },
    { k: "임상 정보", v: patient.clinical_note },
  ];

  return (
    <div className="card">
      <div className="card-head">
        <h3>환자 정보</h3>
        <button className="edit-btn" onClick={() => { setEditing((v) => !v); setMsg(null); }}>
          {editing ? "취소" : "수정"}
        </button>
      </div>
      <div className="pt-info">
        {rows.map((r) => (
          <div className="row" key={r.k}>
            <span className="k">{r.k}</span>
            {editing && r.editable ? (
              <input value={r.v} onChange={(e) => r.onChange(e.target.value)}
                style={{ flex: 1, border: "1px solid var(--line)", borderRadius: 6, padding: "4px 8px", fontSize: 13.5 }} />
            ) : (
              <span className="v">{r.v || "—"}</span>
            )}
          </div>
        ))}
      </div>
      <div className="card-foot split" style={{ marginTop: 14 }}>
        <span className="note">{msg ?? (editing ? "연락처·주소만 수정할 수 있습니다" : "읽기 전용")}</span>
        {editing && (
          <button className="btn ghost sm" onClick={() => { setEditing(false); setMsg("저장되었습니다"); }}>
            저장
          </button>
        )}
      </div>
    </div>
  );
}

function LockPanel({ reportId, status, onUnlocked }) {
  const c = status.conditions;
  const [unlocking, setUnlocking] = useState(false);

  async function unlock() {
    setUnlocking(true);
    try {
      await api.unlockReport(reportId);
      onUnlocked?.();
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
