import { useState } from "react";
import { breast as api } from "../../../api";

/* 촬영 요청 팝업 — §3 수정요청: 촬영부위 입력란을 두지 않는다.
 * DB에 칸이 없고(exam_order 테이블), 안 받기로 확정된 사항이다.
 * 받는 것은 모달리티 · 검사 목적 · 요청의견서(order_note)다. */
const MODALITIES = [
  { value: "mammo", label: "맘모그래피" },
  { value: "us", label: "유방 초음파" },
  { value: "mri", label: "유방 MRI" },
];
const EXAM_PURPOSES = [
  { value: "screening", label: "선별검사" },
  { value: "diagnostic", label: "진단검사" },
];

export default function ExamOrderModal({ patient, onClose, onDone }) {
  const [modality, setModality] = useState(MODALITIES[0].value);
  const [examPurpose, setExamPurpose] = useState(EXAM_PURPOSES[0].value);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.examOrder({
        patient_id: patient.patient_id,
        modality,
        exam_purpose: examPurpose,
        order_note: note,
      });
      onDone?.();
    } catch (e) {
      setError(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>촬영 요청 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>검사 종류</label>
            <select value={modality} onChange={(e) => setModality(e.target.value)}>
              {MODALITIES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>검사 목적</label>
            <select value={examPurpose} onChange={(e) => setExamPurpose(e.target.value)}>
              {EXAM_PURPOSES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>요청의견서</label>
            <textarea value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="영상의학과에 전달할 소견을 적어 주세요" />
          </div>
          {error && <p className="field err">{error}</p>}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn" onClick={save} disabled={saving}>
            {saving ? "전송 중…" : "촬영 요청"}
          </button>
        </div>
      </div>
    </div>
  );
}
