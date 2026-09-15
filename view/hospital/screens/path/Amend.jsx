import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Fold, Save } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";

/* 병리 5 · 판독 정정  (명세 p.25)
 *
 * ── 새 행을 만들지 않는다 ────────────────────────────────────
 * 영상의학과는 새 assessment 행을 만들고 옛 행이 superseded_by 로 그것을
 * 가리킨다. **병리는 그 방식을 못 쓴다.**
 *
 *   specimen 은 **물건 자체**다. 판독을 고친다고 검체가 둘이 되지 않는다.
 *   새 행을 만들면 — 용기 라벨(specimen_label)이 물리적으로 하나뿐이라
 *   UK 가 깨지고, 자동 대조(discordance_flag)가 옛 행을 가리킨 채 남는다.
 *
 * 그래서 옛 값을 **specimen.amend_history(JSONB) 배열에 밀어넣고** 본
 * 컬럼을 덮는다. 대조 링크가 안 깨지고 표도 안 늘어난다.
 *
 * 「최근 1건」이 아니라 **전부** 남는다.
 *
 * ── 셋 다 필수인 이유 ────────────────────────────────────────
 * 「b2 → b4」만 남으면 나중에 왜 바뀌었는지 아무도 모른다. 면역염색
 * 결과가 나와서인지, 처음에 잘못 본 것인지는 전혀 다른 일이다.
 */
export default function Amend() {
  const { id } = useParams();
  const { loading, data, error, reload } = useApi(() => api.read(id), [id]);
  return (
    <Page crumb={["환자 목록", "환자 상세", "기존 판독 조회", "판독 정정"]}
          title="판독 정정" badge="이력 보존"
          sub="이미 확정한 병리 판독을 확인하고, 정정 내용을 입력합니다.">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

function Inner({ d }) {
  const nav = useNavigate();
  const prev = d.report;
  const [f, setF] = useState({
    amend_reason: "", b_category: "", finding_note: "", diagnosis: prev?.diagnosis ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [crop, setCrop] = useState(0);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const ready = f.amend_reason.trim() && f.b_category && f.finding_note.trim();

  async function send(draft) {
    setBusy(true);
    try {
      if (draft) await api.draft(d.specimen.id, f);
      else { await api.amend(d.specimen.id, f); nav(go.list()); }
    } finally { setBusy(false); }
  }

  return (
    <>
      <Card className="callout">
        <b>정정된 판독은 기존 판독의 수정 이력을 남기며, 이전 판독 내용은 모두 보존됩니다.</b>
      </Card>

      <div className="grid3">
        <Card title="환자 기본 정보">
          <dl className="kv">
            <div><dt>환자명</dt><dd>{d.patient.name} ({d.patient.sex}, {d.patient.age}세)</dd></div>
            <div><dt>환자번호</dt><dd>{d.patient.patient_no}</dd></div>
            <div><dt>검체번호</dt><dd>{d.specimen.no}</dd></div>
            <div><dt>검사명</dt><dd>{d.specimen.kind}</dd></div>
            <div><dt>채취일시</dt><dd>{d.specimen.collected_at}</dd></div>
            <div><dt>병리의</dt><dd>{prev?.reported_by ?? "—"}</dd></div>
          </dl>
        </Card>

        <Card title="주요 이미지" right={<span className="src">크롭 조직 이미지</span>}>
          <div className="vart" style={{ minHeight: "var(--thumb-lg)" }} />
          <div className="thumbs">
            {d.crops.map((c, i) => (
              <button className={`thumb ${crop === i ? "on" : ""}`} key={c.id}
                      onClick={() => setCrop(i)}>
                <i aria-hidden="true" />크롭 {i + 1}
              </button>
            ))}
          </div>
        </Card>

        <Card title="정정 사유">
          <label className="field">
            <span>정정 사유 <i className="req">*</i></span>
            <textarea value={f.amend_reason} maxLength={500}
                      placeholder="예) 면역염색 결과 반영에 따른 등급 변경"
                      onChange={(e) => set("amend_reason", e.target.value)} />
            <span className="count">{f.amend_reason.length} / 500</span>
          </label>
          {/* 세부 분류가 곧 b_category 다 — 명세대로 드롭다운 */}
          <label className="field">
            <span>세부 분류 (B 분류) <i className="req">*</i></span>
            <select value={f.b_category}
                    onChange={(e) => set("b_category", e.target.value)}>
              <option value="">선택해주세요</option>
              {d.options.b_category.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>세부 소견 <i className="req">*</i></span>
            <textarea value={f.finding_note} maxLength={1000}
                      placeholder="정정 사유에 대한 상세 내용을 입력해주세요."
                      onChange={(e) => set("finding_note", e.target.value)} />
            <span className="count">{f.finding_note.length} / 1000</span>
          </label>
        </Card>
      </div>

      <div className="grid2">
        <Card title="기존 판독 내용">
          {prev ? (
            <>
              <p className="by src">확정 {prev.finalized_at} · {prev.reported_by}</p>
              <div className="readout">
                <div><h3>[확진]</h3><p>{prev.diagnosis}</p></div>
                <div><h3>[등급]</h3><p>{prev.b_category}</p></div>
                <div><h3>[소견]</h3><p>{prev.finding_note}</p></div>
              </div>

              {/* 「최근 1건」이 아니라 전부다 */}
              {d.amend_history?.length > 0 && (
                <Fold title={`이전 판독 전문 ${d.amend_history.length}건`} open={false}>
                  <div className="readout">
                    {d.amend_history.map((h, i) => (
                      <div key={i}>
                        <h3>[{h.finalized_at} · {h.reported_by}]</h3>
                        <p>{h.diagnosis} · {h.b_category}</p>
                        <p>{h.finding_note}</p>
                        <p className="by">정정 사유 — {h.amend_reason} ({h.amended_at})</p>
                      </div>
                    ))}
                  </div>
                </Fold>
              )}
            </>
          ) : (
            <p className="note">확정된 판독이 없습니다. 정정할 것이 없습니다.</p>
          )}
        </Card>

        <Card title="정정 판독 내용 (수정 후)" right={<Btn>템플릿 불러오기</Btn>}>
          <label className="field">
            <span>확진</span>
            <div className="seg">
              {d.options.diagnosis.map((o) => (
                <button key={o.value} className={f.diagnosis === o.value ? "on" : ""}
                        onClick={() => set("diagnosis", o.value)}>{o.label}</button>
              ))}
            </div>
          </label>
          <div className="rte">
            <div className="rte-bar">
              {["B", "I", "U", "S"].map((t) => <button key={t} aria-label={t}>{t}</button>)}
              <i className="div" aria-hidden="true" />
              {["≔", "≕", "▤", "→"].map((t, i) =>
                <button key={i} aria-label={`서식 ${i + 1}`}>{t}</button>)}
            </div>
            <textarea className="lg" value={f.finding_note}
                      placeholder="정정된 판독 내용을 입력해주세요."
                      onChange={(e) => set("finding_note", e.target.value)} />
          </div>
          <Save hint="저장 시 유방외과에 정정 알림이 전송되고, 자동 대조가 다시 돕니다."
                busy={busy || !ready || !prev}
                onDraft={() => send(true)} onSave={() => send(false)} />
        </Card>
      </div>
    </>
  );
}
