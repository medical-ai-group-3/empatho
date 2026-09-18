import { useState } from "react";
import { breast as api } from "../../../api";

/* 촬영 요청 팝업 — §3 수정요청: 촬영부위 입력란을 두지 않는다.
 * DB에 칸이 없고(exam_order 테이블), 안 받기로 확정된 사항이다.
 * 받는 것은 촬영기구 · 요청의견서(order_note) 둘뿐이다. */
const DEVICES = ["맘모그래피", "유방 초음파", "유방 MRI"];

export default function ExamOrderModal({ patient, onClose, onDone }) {
  const [device, setDevice] = useState(DEVICES[0]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.examOrder({
        patient_id: patient.patient_id,
        device,
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
            <label>촬영기구</label>
            <select value={device} onChange={(e) => setDevice(e.target.value)}>
              {DEVICES.map((d) => <option key={d} value={d}>{d}</option>)}
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
