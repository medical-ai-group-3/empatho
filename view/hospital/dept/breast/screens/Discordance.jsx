import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { go } from "../../../nav";
import "../breast.css";   /* 유방외과 전용 — .breast 안에 갇혀 있다. 네 화면이 각자
                             끌고 온다: 주소로 곧장 들어와도 스타일이 빠지면 안 된다 */

/* 화면 5 · 영상-병리 불일치 처분 ("/discordances/:id")
 *
 * breast.html 레퍼런스에 이 화면이 통째로 빠져 있어(정리본 §2-5) 명세서
 * 서술만으로 새로 설계했다. 병변별 영상의학과 판정 vs 병리과 판정을
 * VS 레이아웃으로 비교하고, 처분(재생검/절제/관찰)과 사유를 받아 저장한다.
 *
 * 화면 쪽 수정요청 반영:
 *   · [수용] 버튼 제거 — "관찰" 하나만 남긴다
 *   · 불일치 상태 SEV1 배지 제거
 *
 * 처분은 유방외과만 할 수 있는 단독 권한(CanDisposeDiscordance)이라는
 * 전제 위에서 만들었다 — 목업에는 권한 분기를 따로 두지 않는다.
 * closed_at 이 찍혀야 화면3의 "② 대조 종결" 조건이 참이 된다. */
const DISPOSITIONS = [
  { v: "rebiopsy", label: "재생검" },
  { v: "excision", label: "절제" },
  { v: "no_action", label: "관찰" },
];

export default function Discordance() {
  const { id } = useParams();
  const nav = useNavigate();
  const { loading, data, error, reload } = useApi(() => api.discordance(id), [id]);

  return (
    <Page className="breast" crumb={["유방외과", "판정 불일치 처분"]}
            title="영상-병리 불일치 처분"
            sub={data ? `${data.patient.name} · ${data.lesion.site}` : ""}
            back={() => nav(go.breast.waiting())}>
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {data && <Inner d={data} onDisposed={() => nav(go.breast.waiting(), { state: { advance: true, from: data.patient.patient_id } })} />}
        </Body>
      </div>
    </Page>
  );
}

function Inner({ d, onDisposed }) {
  const [type, setType] = useState(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    if (!type) { setErr("처분을 선택해 주세요"); return; }
    if (!reason.trim()) { setErr("처분 사유는 필수입니다"); return; }
    setSaving(true);
    setErr(null);
    try {
      await api.dispose(d.discordance_id, { disposition_type: type, disposition_reason: reason });
      onDisposed?.();
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="card discordance-summary">
        <div className="card-head">
          <div>
            <span className="pill danger">불일치 · {d.flag_status === "open" ? "미해결" : "해결"}</span>
            <h3>{d.patient.name} · 영상-병리 대조</h3>
          </div>
          <span className="meta">{d.lesion.lesion_id} · {specimenId(d)}</span>
        </div>
        <div className="discordance-patient-info">
          <span>병변 위치 <b>{d.lesion.site}</b></span>
          <span>병변 크기 <b>{d.lesion.size_mm}mm</b></span>
          <span>검체 <b>{specimenId(d)}</b></span>
        </div>
        <div className="discordance-compare" aria-label="영상과 병리 판정 비교">
          <ComparisonGrade label="영상 판정" value={birads(d.radiology_reading)} />
          <span className="discordance-vs" aria-hidden="true">↔</span>
          <ComparisonGrade label="병리 판정" value={bCategory(d.pathology_reading)} />
        </div>
        <div className="discordance-reason">
          <span>불일치 사유</span>
          <b>{d.violated_rule}</b>
        </div>
      </div>

      <div className="vs">
        <div className="side">
          <h3>영상의학과 판정</h3>
          <div className="kv"><span className="k">BI-RADS</span><span className="v">{birads(d.radiology_reading)}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">상세 판정</span><span className="v">{d.radiology_reading.assessment}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">소견</span><span className="v">{d.radiology_reading.finding}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">판독의</span><span className="v">{d.radiology_reading.assessor}</span></div>
        </div>
        <div className="mid">VS</div>
        <div className="side">
          <h3>병리과 판정</h3>
          <div className="kv"><span className="k">B 분류</span><span className="v">{bCategory(d.pathology_reading)}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">상세 판정</span><span className="v">{d.pathology_reading.assessment}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">소견</span><span className="v">{d.pathology_reading.finding}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">판독의</span><span className="v">{d.pathology_reading.assessor}</span></div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>처분 결정</h3>
        <div style={{ display: "flex", gap: 8 }}>
          {DISPOSITIONS.map((opt) => (
            <button key={opt.v}
              className={type === opt.v ? "btn" : "btn ghost"}
              onClick={() => setType(opt.v)}>
              {opt.label}
            </button>
          ))}
        </div>
        <div className="field" style={{ marginTop: 14 }}>
          <label>처분 사유 <span className="req">*</span></label>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="근거 없이 처분하면 추적이 안 됩니다 — 사유를 적어 주세요" />
        </div>
        {err && <p className="field err">{err}</p>}
        <button className="btn" onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "저장"}
        </button>
      </div>
    </>
  );
}

function ComparisonGrade({ label, value }) {
  return (
    <span className="discordance-grade">
      <span>{label}</span>
      <b>{value}</b>
    </span>
  );
}

function birads(reading = {}) {
  if (reading.birads != null) return `BI-RADS ${String(reading.birads).toUpperCase()}`;
  return reading.assessment?.match(/BI-RADS\s*([0-9]+[a-c]?)/i)?.[0]?.toUpperCase()
    ?? reading.assessment
    ?? "—";
}

function bCategory(reading = {}) {
  if (reading.b_category != null) return String(reading.b_category).toUpperCase();
  return reading.assessment?.match(/B[1-5]/i)?.[0]?.toUpperCase()
    ?? reading.assessment
    ?? "—";
}

function specimenId(d) {
  return d.specimen?.specimen_id ?? d.specimen_id ?? d.lesion?.specimen_id ?? "검체 정보 없음";
}
