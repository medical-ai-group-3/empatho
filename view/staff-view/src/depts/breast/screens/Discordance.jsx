import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Head, Body } from "../../../lib/Screen";

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
    <>
      <Head title="영상-병리 불일치 처분"
        sub={data ? `${data.patient.name} · ${data.lesion.site}` : ""}
        back={() => nav("/")} />
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {data && <Inner d={data} onDisposed={() => nav("/", { state: { advance: true, from: data.patient.patient_id } })} />}
        </Body>
      </div>
    </>
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
      await api.disposeDiscordance(d.discordance_id, { disposition_type: type, disposition_reason: reason });
      onDisposed?.();
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="pill danger">불일치 · {d.flag_status === "open" ? "미해결" : "해결"}</span>
          <span style={{ fontSize: 13, color: "var(--muted)" }}>{d.lesion.lesion_id} · {d.lesion.size_mm}mm</span>
        </div>
        <p style={{ marginTop: 8, fontSize: 13.5 }}>{d.violated_rule}</p>
      </div>

      <div className="vs">
        <div className="side">
          <h3>영상의학과 판정</h3>
          <div className="kv"><span className="k">판정</span><span className="v">{d.radiology_reading.assessment}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">소견</span><span className="v">{d.radiology_reading.finding}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span className="k">판독의</span><span className="v">{d.radiology_reading.assessor}</span></div>
        </div>
        <div className="mid">VS</div>
        <div className="side">
          <h3>병리과 판정</h3>
          <div className="kv"><span className="k">판정</span><span className="v">{d.pathology_reading.assessment}</span></div>
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
