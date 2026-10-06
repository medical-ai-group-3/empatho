import { useState } from "react";
import { specimens } from "../api";
import { useApi } from "./useApi";
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
  { value: "core_needle", label: "중심 침 생검 (진공보조 생검 포함)" },
  { value: "surgical", label: "수술적 생검 (절제 생검)" },
];
const GUIDES = [
  { value: "ultrasound", label: "초음파 유도" },
  { value: "stereotactic", label: "정위 유도 (유방촬영 유도)" },
  { value: "mri", label: "MRI 유도" },
  { value: "localization", label: "위치 표지 유도" },
];

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export default function SpecimenBindingModal({ patient, onClose, onDone }) {
  const { loading, data, error, reload } =
    useApi(() => specimens.lesionsByPatient(patient.patient_id), [patient.patient_id]);
  /* ⚠ 2026-09-27 — /lesions/ 는 봉투({count,results})로 온다. items 만 읽어
     목록이 늘 비었다. 환자 칸도 patient_id 가 아니라 patient(FK) 다 — 서버가
     ?patient= 로 이미 거르지만, 한 번 더 거를 때 이름이 틀려 전부 빠졌다 */
  const all = Array.isArray(data) ? data : (data?.results ?? data?.items ?? []);
  /* 오진(위양성)으로 표시한 병변은 뺀다 — 거기에 검체를 달 일은 없다 */
  const lesions = all.filter(
    (l) => String(l.patient ?? l.patient_id) === String(patient.patient_id)
      && !l.is_false_positive);

  const [lesionId, setLesionId] = useState("");
  const [type, setType] = useState(TYPES[0].value);
  const [guide, setGuide] = useState(GUIDES[0].value);
  const [collectedAt, setCollectedAt] = useState(nowLocal());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  const preview = labelPreview(collectedAt, patient,
    lesions.find((l) => String(l.lesion_id) === String(lesionId)));

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
        /* 라벨은 보내지 않는다 — 서버가 S-{채취일}-{환자번호}-{병변} 으로 만든다(09-28) */
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
      <div className="modal wide spec-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>검체 등록 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {/* 09-28(최종) 환자 · 환자번호 두 줄 표(kv)가 이름표 폭에 눌려 붙어 보였다 —
              라벨과 같이 대조할 값 셋(이름 · 나이 성별 · 환자번호)을 한 띠에 */}
          <div className="spec-who" aria-label="환자">
            <b>{patient.name ?? "이름 없음"}</b>
            {/* 나이·성별이 비어 오면 「null세」가 찍혔다 — 있는 것만 */}
            {whoText(patient) && <span>{whoText(patient)}</span>}
            <span className="home-fill" />
            <span className="spec-who-k">환자번호</span>
            <b className="num">{patient.patient_number ?? "—"}</b>
          </div>

          <label className="field">
            <span>표적 병변 (필수)</span>
            {/* 09-28 — 번호를 직접 치게 하던 것을 이 환자의 검사에서 나온 병변 목록으로 바꿨다.
                유방외과 · 간호과 어디서도 병변 번호를 알 길이 없었다 */}
            <select value={lesionId} onChange={(e) => setLesionId(e.target.value)}
                    disabled={loading || lesions.length === 0}>
              <option value="">{loading ? "병변 목록을 불러오는 중…" : lesions.length ? "병변을 선택하세요" : "등록된 병변이 없습니다"}</option>
              {lesions.map((l) => (
                <option key={l.lesion_id} value={l.lesion_id}>{lesionText(l)}</option>
              ))}
            </select>
            <small className="hint">
              {error
                ? <>병변 목록을 불러오지 못했습니다.{" "}
                    <button type="button" className="resv-jump" onClick={() => reload()}>다시 불러오기</button></>
                : !loading && lesions.length === 0
                  ? "이 환자의 검사에서 나온 병변이 없습니다. 영상 판독에서 병변을 등록해야 검체를 연결할 수 있습니다."
                  : "이 환자가 받은 검사에서 나온 병변입니다."}
            </small>
          </label>

          {/* 유형 · 유도 · 일시는 한 줄 셋 — 라벨은 병변 · 일시로 정해지는 **결과**라
              맨 아래 폭 전체에 둔다(예전엔 입력칸 넷 사이에 섞여 고치는 칸처럼 보였다) */}
          <div className="fields spec-fields">
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

          {/* ⚠ 09-28(최종) 읽기 전용 입력칸에 안내 글을 값처럼 넣어 두어 「병변을
              선택하면…」이 라벨인 줄 보였다. 칸이 아니라 **보여 주는 값**이다 —
              병변을 고르기 전에는 흐린 안내만 */}
          <div className="field">
            <span>검체 라벨 (자동 생성)</span>
            {preview
              ? <output className="spec-label num" aria-live="polite">{preview}</output>
              : <p className="spec-label off">표적 병변을 선택하면 표시됩니다</p>}
            <small className="hint">등록하면 이 이름으로 정해집니다. 같은 날 같은 병변에 검체가 이미 있으면 뒤에 -2가 붙습니다.</small>
          </div>
          {saveError && <p className="warnline">⚠ {saveError}</p>}
        </div>
        <div className="modal-foot">
          <button className="btn line" onClick={onClose}>취소</button>
          <button className="btn fill" onClick={save} disabled={saving || !lesionId}>
            {saving ? "등록하는 중…" : "등록"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* 목록 한 줄 — 이름 · 검사 · 검사일 · 크기 · 모델 등급 */
function lesionText(l) {
  const MOD = { mammo: "유방촬영", us: "초음파", mri: "MRI" };
  const size = l.measured_size_mm ?? l.ai_size_mm;
  return [
    /* 검사 이름은 바로 뒤에 따로 적는다 — 「초음파 병변 1 · 초음파」로 두 번 나왔다 */
    l.label || `병변 ${l.lesion_index != null ? l.lesion_index + 1 : l.lesion_id}`,
    MOD[l.modality] ?? l.modality,
    l.study_date,
    size != null && `${Number(size).toFixed(1)}mm`,
    l.birads_model && `BI-RADS ${l.birads_model}`,
    l.lesion_source === "manual" && "직접 등록",
  ].filter(Boolean).join(" · ");
}

function whoText(p) {
  return [p.age != null && `${p.age}세`, label(SEX, p.sex)].filter(Boolean).join(" · ");
}

/* 서버가 만들 라벨을 미리 보인다(views/surgery.py specimen_label_for 와 같은 규칙).
   같은 날 같은 병변에 이미 검체가 있으면 서버가 -2, -3 을 붙인다 */
function labelPreview(collectedAt, patient, l) {
  if (!l) return null;
  const day = String(collectedAt ?? "").slice(0, 10).replaceAll("-", "");
  const part = (l.label || (l.modality && l.lesion_index != null
    ? `${l.modality.toUpperCase()}-${l.lesion_index + 1}` : `L${l.lesion_id}`))
    .replace(/[^A-Za-z0-9-]/g, "").slice(0, 16);
  return `S-${day}-${patient.patient_number ?? ""}-${part}`;
}
