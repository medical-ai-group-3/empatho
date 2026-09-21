import { useState } from "react";
import { breast as api } from "../../../api";
import { MODALITY } from "../../../codes";

/* 촬영 요청 팝업 — §3 수정요청: 촬영부위 입력란을 두지 않는다.
 * DB에 칸이 없고(exam_order 테이블), 안 받기로 확정된 사항이다.
 * 받는 것은 촬영기구 · 요청의견서(order_note) 둘뿐 — 이었는데, 실제로
 * 시험해 보니 서버(ExamOrderRequestSerializer)가 이 셋을 요구한다:
 *
 *   patient_id     필수 — 그대로 맞음
 *   modality       필수 — 코드값(mammo·us·mri). "device": "맘모그래피"
 *                  라는 한글 기구 이름을 보내고 있어서 하나도 안 맞았다
 *   exam_purpose   필수 — 아예 안 보내고 있었다
 *   order_note     선택 — 그대로 맞음
 *
 * 그래서 [검사 오더]를 누르면 매번 VALIDATION_ERROR 였다(2026-09-18
 * 확인, 다희님도 같은 결론). modality 값은 codes.js의 서버 확정
 * 코드표를 그대로 쓴다 — 한글 라벨을 여기서 새로 짓지 않는다(코드표를
 * 한 곳에 모은 이유가 바로 이런 어긋남을 막으려는 것이었다).
 *
 * ⚠ exam_purpose(검진/진단)를 유방외과 의사가 이 화면에서 직접 고르는
 *   게 맞는지는 아직 팀 확인 전이다 — 당장 오더를 낼 방법이 없어서
 *   임시로 선택 칸을 둔다. 서버가 다른 값을 내려주거나 정해진 규칙이
 *   생기면 이 select를 그에 맞게 바꾼다. */
const MODALITIES = Object.entries(MODALITY).map(([id, label]) => ({ id, label }));
const PURPOSES = [
  { id: "screening",  label: "정기 검진" },
  { id: "diagnostic", label: "이상 소견 확인" },
];

export default function ExamOrderModal({ patient, initialModality, onClose, onDone }) {
  const [modality, setModality] = useState(initialModality ?? MODALITIES[0].id);
  const [purpose, setPurpose] = useState(PURPOSES[0].id);
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
        exam_purpose: purpose,
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
            <label>모달리티</label>
            <select value={modality} onChange={(e) => setModality(e.target.value)}>
              {MODALITIES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>검사 목적</label>
            <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
              {PURPOSES.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
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
