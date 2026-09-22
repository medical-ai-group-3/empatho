import { useState } from "react";
import { specimens } from "../api";
import { useApi } from "./useApi";
import { Facts } from "./Parts";
import { SEX, label } from "../codes";

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
 * specimen_type · guidance_route · collected_at. 표적 병변은 DB의
 * lesion_id NOT NULL(Hard Stop)이라 필수다. 실서버에 병변 목록 조회가
 * 아직 없으므로, 목록 선택 대신 병변 번호를 직접 적을 수 있게 둔다. */
/* 서버 enum: ["core_needle", "surgical"] — specimen.specimen_type 에 CHECK 이
   걸려 있어 이 둘 말고는 저장이 거부된다.

   진공보조생검(VABB)은 바늘 생검이라 core_needle 로 들어간다. 「어떻게
   겨냥했나」는 아래 guidance_route 가 따로 들고 있어서(정위·초음파 유도)
   그 정보는 잃지 않는다. 라벨에 적어 두어 고르는 사람이 헷갈리지 않게 한다. */
const TYPES = [
  { value: "core_needle", label: "중심 침 생검 (core needle · 진공보조 포함)" },
  { value: "surgical", label: "수술적 생검 (절제 생검)" },
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

  const [lesionId, setLesionId] = useState("");
  /* codes.js의 label()을 가리지 않게 검체 라벨 상태는 별도 이름을 쓴다.
     같은 이름이면 첫 렌더에서 성별 표기를 만들 때 문자열을 함수처럼
     호출하게 되어 팝업 자체가 열리지 않는다. */
  const [specimenLabel, setSpecimenLabel] = useState("");
  const [type, setType] = useState(TYPES[0].value);
  const [guide, setGuide] = useState(GUIDES[0].value);
  const [collectedAt, setCollectedAt] = useState(nowLocal());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  async function save() {
    const numericLesionId = Number(lesionId);
    if (!Number.isInteger(numericLesionId) || numericLesionId <= 0) {
      setSaveError("표적 병변 번호를 입력해 주세요");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await specimens.bind({
        patient_id: patient.patient_id,
        lesion_id: numericLesionId,
        specimen_label: specimenLabel,
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
            ["환자", `${patient.name} (${patient.age}세 · ${label(SEX, patient.sex)})`],
            ["환자번호", patient.patient_number],
          ]} />

          <label className="field">
            <span>표적 병변 번호 (필수)</span>
            <input type="number" min="1" inputMode="numeric" list="known-lesions"
              value={lesionId} onChange={(e) => setLesionId(e.target.value)}
              placeholder="병변 번호를 직접 입력" />
            {lesions.length > 0 && (
              <datalist id="known-lesions">
                {lesions.map((l) => (
                  <option key={l.lesion_id} value={l.lesion_id}>
                    {`${l.site ?? "위치 미상"} · ${l.size_mm ?? "—"}mm`}
                  </option>
                ))}
              </datalist>
            )}
            <small className="hint">
              {loading
                ? "등록된 병변을 불러오는 중입니다. 번호를 직접 입력해도 됩니다."
                : error
                  ? "병변 목록을 불러오지 못했습니다. 표적 병변 번호를 직접 입력해 등록하세요."
                  : "병변 번호를 입력하면 해당 병변에 검체가 연결됩니다."}
            </small>
          </label>

          <div className="fields">
            <label className="field">
              <span>검체 라벨</span>
              <input value={specimenLabel} onChange={(e) => setSpecimenLabel(e.target.value)}
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
          <button className="btn line" onClick={onClose}>취소</button>
          <button className="btn fill" onClick={save} disabled={saving || !lesionId}>
            {saving ? "등록 중…" : "등록"}
          </button>
        </div>
      </div>
    </div>
  );
}
