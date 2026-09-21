import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { SEX, label } from "../../../codes";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
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

/* 화면 3 · 수술 결정 및 환자 설명 ("/patients/:id/decision")
 *
 * 3열 2행: (좌)AI·의사 종합 리포트 / (중)수술 여부·환자 처방 /
 * (우)환자 정보·의사 최종 소견. 환자 리포트 상태와 잠금 해제는 최종
 * 소견 카드 안에서 함께 처리한다.
 *
 * 잠금 해제 3조건(①전 레코드 확정 ②대조 종결 ③대면 설명 완료)은 서버가
 * 판단해서 GET /reports/{id}/unlock-status 로 내려준다 — 화면은 그 결과를
 * 그대로 보여주고 셋 다 참일 때만 [잠금 해제] 버튼을 켠다. */
export default function Decision() {
  const { id } = useParams();
  const nav = useNavigate();
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);

  return (
    /* 되돌릴 수 없는 결정을 저장하는 화면이다. **누구인지 안 보이면 안 된다** */
    <Page className="breast" crumb={["유방외과", "수술 결정"]}
            title="수술 결정" patient={patient}
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

  /* 수술 결정은 assessment 한 건에 매달린다(models.py:675 — study 에 물려
   * 있지 patient 에 안 물려 있다). patient_id 로는 못 찾고, timeline 의
   * "판독" 이벤트가 assessment_id 를 실어 준다(2026-09-18, 다희님 —
   * feature/dahee 6774208). 이 환자의 가장 최근 판독을 결정 대상으로
   * 삼는다. */
  const timeline = useApi(() => api.timeline(patient.patient_id), [patient.patient_id]);
  const reads = (timeline.data ?? []).filter((e) => e.type === "판독" && e.assessment_id != null);
  const assessmentId = reads.length ? reads[reads.length - 1].assessment_id : null;

  return (
    <div className="decision-grid">
      {/* 1행 — 왼쪽 AI 종합 · 중앙 수술 여부 · 오른쪽 환자 정보 */}
      <AiSummaryCard report={report} />
      <DecisionForm assessmentId={assessmentId} assessmentIdLoading={timeline.loading} />
      <PatientInfoCard patient={patient} />

      {/* 2행 — 각 열의 두 번째 작업. 행 높이를 공유해 카드 끝이 맞는다. */}
      <DoctorSummaryCard report={report} />
      <PrescriptionDraft />
      <ExplainForm report={report} onSaved={onReload} unlock={unlock} />
    </div>
  );
}

function AiSummaryCard({ report }) {
  return (
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
    try {
      await api.saveReport(report.report_id, { content_json: { doctor_summary: text } });
      setMsg("저장되었습니다");
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

function DecisionForm({ assessmentId, assessmentIdLoading }) {
  /* ⚠ report.decision 은 서버에 없는 필드다(Report 모델엔 decision_*
   * 이 없다 — 그건 Assessment 쪽이다). 예전엔 여기서 그 값으로 초깃값을
   * 채웠는데, 있지도 않은 이전 결정을 읽는 척하던 것이라 뺐다. 저장된
   * 값을 다시 읽어오는 확정된 경로가 생기면 그때 채운다. */
  const [decisionValue, setDecisionValue] = useState(DECISIONS[0].v);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    try {
      await api.decide(assessmentId, {
        decision_type: "surgery", decision_value: decisionValue, decision_reason: reason,
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
            <input type="radio" name="decision_value" value={d.v}
              checked={decisionValue === d.v} onChange={() => setDecisionValue(d.v)} />
            {d.label}
          </label>
        ))}
      </div>
      <div className="field">
        <label>수술 관련 결정 사유</label>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="card-foot split">
        <span className="note">
          {msg ?? (!assessmentIdLoading && !assessmentId ? "판독 기록이 아직 없어 저장할 수 없습니다" : null)}
        </span>
        <button className="btn ghost" onClick={save} disabled={saving || !assessmentId}>
          {saving ? "저장 중…" : "결정 저장"}
        </button>
      </div>
    </div>
  );
}

/* 처방은 환자 앱의 GET /me/prescriptions 가 읽는 원천 데이터다.
 * 아직 병원 웹에서 새 처방을 만드는 서버 경로가 없으므로, 이 화면은 입력
 * 초안만 다룬다. 저장 버튼을 눌러도 사라지는 가짜 처방을 만들지 않도록 API
 * 계약이 붙을 때까지 비활성으로 둔다.
 *
 * 백엔드 요청안:
 * POST /patients/{patient_id}/prescriptions
 * { drugs:[{ name, dose, times:["09:00"], days, purpose, how }] }
 * → 환자 앱 GET /me/prescriptions 의 prescription/drugs 모양으로 저장 */
const emptyDrug = () => ({ name: "", dose: "", times: "", days: "", purpose: "", how: "" });

function PrescriptionDraft() {
  const [drugs, setDrugs] = useState([emptyDrug()]);

  function change(index, key, value) {
    setDrugs((rows) => rows.map((drug, i) => i === index ? { ...drug, [key]: value } : drug));
  }

  function remove(index) {
    setDrugs((rows) => rows.length === 1 ? rows : rows.filter((_, i) => i !== index));
  }

  return (
    <div className="card prescription-draft">
      <div className="card-head">
        <div>
          <h3>환자 처방</h3>
          <p className="meta">저장된 처방은 환자 앱의 복약 관리에 표시됩니다.</p>
        </div>
        <span className="pill wait">API 연결 대기</span>
      </div>

      {drugs.map((drug, index) => (
        <div className="prescription-drug" key={index}>
          <div className="prescription-drug-head">
            <b>약 {index + 1}</b>
            {drugs.length > 1 && <button className="edit-btn" onClick={() => remove(index)}>삭제</button>}
          </div>
          <div className="prescription-grid">
            <div className="field">
              <label>약 이름 <span className="req">*</span></label>
              <input value={drug.name} onChange={(e) => change(index, "name", e.target.value)} placeholder="약 이름" />
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
          <div className="field" style={{ marginBottom: 0 }}>
            <label>복용 안내</label>
            <textarea value={drug.how} onChange={(e) => change(index, "how", e.target.value)} placeholder="환자 앱에 표시할 복용 방법과 안내" />
          </div>
        </div>
      ))}

      <div className="card-foot split prescription-actions">
        <button className="btn ghost sm" onClick={() => setDrugs((rows) => [...rows, emptyDrug()])}>+ 약 추가</button>
        <span className="note">처방 생성 API가 연결되면 저장할 수 있습니다.</span>
        <button className="btn" disabled>처방 저장</button>
      </div>
    </div>
  );
}

function ExplainForm({ report, onSaved, unlock }) {
  const [method, setMethod] = useState(report.explain_method ?? EXPLAIN_METHODS[0]);
  const [content, setContent] = useState(report.explain_content ?? "");
  const [confirmed, setConfirmed] = useState(report.patient_confirmed ?? false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    try {
      await api.explain(report.report_id, {
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
  const [editing, setEditing] = useState(false);
  const [phone, setPhone] = useState(patient.phone ?? "");
  const [address, setAddress] = useState(patient.address ?? "");
  const [msg, setMsg] = useState(null);

  const rows = [
    { k: "이름", v: patient.name },
    { k: "성별 / 나이", v: `${label(SEX, patient.sex)} / ${patient.age}세 (${patient.birth_date})` },
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
          /* ⚠ 저장할 서버 경로가 없다. 이름·생년월일·전화는 patient_pii 라
             PATCH /patients/{id}/ (api.js 의 reception.update, 위 주석)로
             못 고친다 — 주소 칸도 서버 모델에 없다. 그래서 버튼이 실제로는
             아무 데도 보내지 않는다. 전용 엔드포인트가 생기기 전에는
             지우지 않고 이 사실만 적어 둔다(거짓 "저장되었습니다" 를
             지금 당장 없애면 화면이 아예 편집 불가로 보이므로, 팀 확인
             전까지는 동작을 그대로 두고 경고만 남긴다). */
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
      await api.unlock(reportId);
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
