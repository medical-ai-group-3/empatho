import { useState } from "react";
import { breast as api } from "../../../api";

/* 검체 바인딩 팝업 — 간호과와 완전히 같은 컴포넌트를 재사용하는 것이
 * 원칙이다(§2-4). 간호과 쪽 구현이 아직 이 저장소에 없어 지금은 동일
 * 스펙으로 새로 만들어 둔다 — 나중에 간호과 컴포넌트가 생기면 그쪽으로
 * 교체한다.
 *
 * 구성: 환자정보+검체정보 / 표적 병변 선택 / 검체 등록(라벨·유형·유도방식·채취일시)
 * 담당자 지정(assigned_to)은 없다 — "완료되면 사라진다"는 규칙이라 누가
 * 집는지는 안 받는다. */
const TYPES = ["core needle biopsy", "vacuum-assisted biopsy", "FNA(세침흡인)"];
const GUIDES = ["초음파 유도", "정위 유도(스테레오택틱)", "MRI 유도", "촉지 유도"];

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export default function SpecimenBindingModal({ patient, onClose, onDone }) {
  const openLesions = (patient.lesions || []).filter((l) => !l.specimen_id);
  const [lesionId, setLesionId] = useState(openLesions[0]?.lesion_id ?? "");
  const [label, setLabel] = useState("");
  const [type, setType] = useState(TYPES[0]);
  const [guide, setGuide] = useState(GUIDES[0]);
  const [collectedAt, setCollectedAt] = useState(nowLocal());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    if (!lesionId) { setError("표적 병변을 선택해 주세요"); return; }
    setSaving(true);
    setError(null);
    try {
      await api.createSpecimen({
        patient_id: patient.patient_id,
        lesion_id: lesionId,
        label,
        specimen_type: type,
        guidance: guide,
        collected_at: collectedAt,
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
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>검체 바인딩</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="card">
            <h3>환자정보</h3>
            <div className="split" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <div className="kv"><span className="k">이름</span><span className="v">{patient.name}</span></div>
              <div className="kv"><span className="k">환자번호</span><span className="v">{patient.patient_number}</span></div>
              <div className="kv"><span className="k">나이/성별</span><span className="v">{patient.age}세 · {patient.sex}</span></div>
              <div className="kv"><span className="k">요청검사·연관영상</span>
                <span className="v">{(patient.lesions || []).map((l) => l.site).join(", ") || "—"}</span></div>
            </div>
          </div>

          <div className="card">
            <h3>표적 병변 선택</h3>
            {openLesions.length === 0 ? (
              <p style={{ color: "var(--muted)", fontSize: 13 }}>
                검체가 필요한 병변이 없습니다 — 모두 등록되었습니다.
              </p>
            ) : (
              <table className="list">
                <thead><tr><th></th><th>병변</th><th>위치</th><th>크기</th></tr></thead>
                <tbody>
                  {openLesions.map((l) => (
                    <tr key={l.lesion_id} className={lesionId === l.lesion_id ? "on" : ""}
                        onClick={() => setLesionId(l.lesion_id)}>
                      <td><input type="radio" checked={lesionId === l.lesion_id} readOnly /></td>
                      <td>{l.lesion_id}</td>
                      <td>{l.site}</td>
                      <td>{l.size_mm}mm</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <h3>검체 등록</h3>
            <div className="field">
              <label>라벨</label>
              <input value={label} onChange={(e) => setLabel(e.target.value)}
                placeholder="예: A-1" />
            </div>
            <div className="field">
              <label>유형</label>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="field">
              <label>유도방식</label>
              <select value={guide} onChange={(e) => setGuide(e.target.value)}>
                {GUIDES.map((g) => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            <div className="field">
              <label>채취일시</label>
              <input type="datetime-local" value={collectedAt}
                onChange={(e) => setCollectedAt(e.target.value)} />
            </div>
            {error && <p className="field err">{error}</p>}
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn" onClick={save} disabled={saving || openLesions.length === 0}>
            {saving ? "등록 중…" : "검체 등록"}
          </button>
        </div>
      </div>
    </div>
  );
}
