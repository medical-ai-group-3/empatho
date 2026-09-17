import { useState } from "react";
import { specimens } from "../api";
import { useApi } from "./useApi";
import { Body } from "./Body";
import { Facts, Table } from "./Parts";

/* 검체 바인딩 팝업 — 간호과·유방외과 공용 컴포넌트(간호과 명세 §2-4:
 * "유방외과와 같은 컴포넌트다 — 부서별로 새로 만들지 않는다"). 띄우는
 * 자리만 다르다 — 유방외과는 1장 [검체 신청], 간호과는 1장 [검체 바인딩].
 *
 * ⚠ 예전엔 이 컴포넌트가 dept/breast/components/ 안에 있으면서 존재하지
 *   않는 api.createSpecimen()을 불렀고(죽은 코드), breast.css(.breast
 *   스코프 전용) 클래스에 얹혀 있어서 간호과에서는 스타일이 아예 안
 *   먹었다. hospital/lib/로 옮기고 실제 엔드포인트(api.js의 specimens)와
 *   hospital.css 공용 .modal-* 클래스로 다시 짰다.
 *
 * 필드명은 간호과 명세 §3 DB 컬럼 그대로 — specimen_label(UK) ·
 * specimen_type · guidance_route · collected_at. 표적 병변 선택은
 * lesion_id NOT NULL(Hard Stop)이라 필수다. */
const TYPES = [
  { value: "core_needle", label: "core needle biopsy" },
  { value: "vacuum_assisted", label: "vacuum-assisted biopsy" },
  { value: "excisional", label: "excisional (절제 생검)" },
];
const GUIDES = [
  { value: "ultrasound", label: "초음파 유도" },
  { value: "stereotactic", label: "정위 유도(스테레오택틱)" },
  { value: "mri", label: "MRI 유도" },
  { value: "localization", label: "촉지 유도" },
];

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export default function SpecimenBindingModal({ patient, onClose, onDone }) {
  const { loading, data, error, reload } =
    useApi(() => specimens.lesionsByPatient(patient.patient_id), [patient.patient_id]);
  const lesions = (data?.items ?? []).filter((l) => l.patient_id === patient.patient_id);

  const [lesionId, setLesionId] = useState(null);
  const [label, setLabel] = useState("");
  const [type, setType] = useState(TYPES[0].value);
  const [guide, setGuide] = useState(GUIDES[0].value);
  const [collectedAt, setCollectedAt] = useState(nowLocal());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  async function save() {
    if (!lesionId) { setSaveError("표적 병변을 선택해 주세요"); return; }
    setSaving(true);
    setSaveError(null);
    try {
      await specimens.bind({
        patient_id: patient.patient_id,
        lesion_id: lesionId,
        specimen_label: label,
        specimen_type: type,
        guidance_route: guide,
        collected_at: collectedAt,
      });
      onDone?.();
    } catch (e) {
      setSaveError(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>검체 바인딩 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <Facts items={[
            ["환자", `${patient.name} (${patient.age}세 · ${patient.sex})`],
            ["환자번호", patient.patient_number],
          ]} />

          <div>
            <p className="muted small" style={{ marginBottom: 8 }}>표적 병변 선택 (필수)</p>
            <Body loading={loading} error={error} onRetry={reload}>
              <Table
                cols={[
                  { key: "site", label: "위치" },
                  { key: "size", label: "크기" },
                  { key: "birads", label: "BI-RADS" },
                ]}
                rows={lesions.map((l) => ({
                  id: l.lesion_id,
                  site: l.site,
                  size: `${l.size_mm}mm`,
                  birads: l.birads ?? "—",
                }))}
                value={lesionId}
                onPick={setLesionId}
              />
            </Body>
          </div>

          <div className="fields">
            <label className="field">
              <span>검체 라벨</span>
              <input value={label} onChange={(e) => setLabel(e.target.value)}
                placeholder="예: S-20260915-001" />
            </label>
            <label className="field">
              <span>검체 유형</span>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span>유도 방식</span>
              <select value={guide} onChange={(e) => setGuide(e.target.value)}>
                {GUIDES.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span>채취 일시</span>
              <input type="datetime-local" value={collectedAt}
                onChange={(e) => setCollectedAt(e.target.value)} />
            </label>
          </div>
          {saveError && <p className="warnline">⚠ {saveError}</p>}
        </div>
        <div className="modal-foot">
          <span className="hint" style={{ marginRight: "auto" }}>등록하면 병리과로 전달됩니다.</span>
          <button className="btn line" onClick={onClose}>취소</button>
          <button className="btn fill" onClick={save} disabled={saving || !lesionId}>
            {saving ? "등록 중…" : "등록"}
          </button>
        </div>
      </div>
    </div>
  );
}
