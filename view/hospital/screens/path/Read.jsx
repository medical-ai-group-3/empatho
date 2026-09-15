import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Chip, Fold, Save, Slide, Viewer } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";
import AiFindings from "./AiFindings";

/* 병리 3 · 판독  (명세 p.23)
 *
 * ── 초안에서 뺀 것 ───────────────────────────────────────────
 *   **상단 탭 다섯** — 전체 보기 · 조직 분할 · 세포 검출 · TIL 히트맵 ·
 *     분할 오버레이. 탭으로 나누는 대신 **원본 한 장에 마스크를 얹고
 *     투명도로 조절한다.** 나눠 보면 같은 자리를 다른 화면에서 봐야 해서
 *     「이 점이 저기 어디였지」가 생긴다
 *   **[AI 활성화]** — 1차 판독 게이트를 팀 결정으로 없앴다. AI 를 볼지
 *     말지는 접는 패널로 정한다
 *   **[병변 등록]** — 검체는 이미 병변에 묶여 있다(specimen.lesion_id
 *     NOT NULL). 병리가 새 병변을 만들 일이 없다
 *
 * ── 분석 중이 없다 ───────────────────────────────────────────
 * AI 는 업로드 화면에서 끝나고, 끝나야 여기로 올 수 있다.
 *
 * ── 패널 기본 상태 ───────────────────────────────────────────
 * AI 소견은 **접힘**, 의사 소견은 **펼침**. 판독은 내가 보고 내가 쓰는
 * 일이고 AI 는 참고라, 기본은 내 자리가 열려 있어야 한다.
 */
export default function Read() {
  const { id } = useParams();
  const { loading, data, error, reload } = useApi(() => api.read(id), [id]);
  return (
    <Page crumb={["병리과", "판독"]} title="병리 판독"
          sub="원본 조직 이미지 위에 AI 분할 마스크를 얹어 보고, 소견을 저장해 유방외과로 전송합니다."
          right={data && <Chip>{data.patient.name} · {data.specimen.no}</Chip>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

function Inner({ d }) {
  const nav = useNavigate();
  const [crop, setCrop] = useState(d.crops[0]?.id);
  const [mask, setMask] = useState(45);          // 마스크 투명도 — 저장 안 함
  const [full, setFull] = useState(false);
  const [f, setF] = useState(d.doctor ?? {});
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  /* 임시저장은 이 자리에 머문다. 저장은 유방외과로 나가는 것이라
     여기서 할 일이 끝난다 */
  async function draft() {
    setBusy(true);
    try { await api.draft(d.specimen.id, f); } finally { setBusy(false); }
  }
  async function finalize() {
    setBusy(true);
    try { await api.finalize(d.specimen.id, f); nav(go.list()); }
    finally { setBusy(false); }
  }

  return (
    <div className={`split wide ${full ? "full" : ""}`}>
      <div className="split-l">
        <Card pad={false}>
          <Viewer
            leftName="AI 소견" rightName="의사 소견"
            leftOpen={false} rightOpen              /* AI 는 접힘, 의사는 펼침 */
            tools={["⌖", "＋", "－", "✥", "⛶"].map((t, i) => (
              <button key={i} className="vtool" aria-label={`도구 ${i + 1}`}
                      onClick={i === 4 ? () => setFull(!full) : undefined}>{t}</button>
            ))}
            leftPanel={<AiFindings ai={d.ai} crops={d.crops} />}
            rightPanel={
              <>
                <label className="field">
                  <span>악성 / 양성 여부</span>
                  <div className="seg">
                    {d.options.diagnosis.map((o) => (
                      <button key={o.value} className={f.diagnosis === o.value ? "on" : ""}
                              onClick={() => set("diagnosis", o.value)}>{o.label}</button>
                    ))}
                  </div>
                </label>

                {/* ⚠ BI-RADS 가 아니다. BI-RADS 는 영상 체계이고
                    병리는 B 분류를 쓴다 */}
                <label className="field">
                  <span>등급 (B 분류)</span>
                  <select value={f.b_category ?? ""}
                          onChange={(e) => set("b_category", e.target.value)}>
                    <option value="">선택해주세요</option>
                    {d.options.b_category.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  <span>판독 소견</span>
                  <textarea value={f.finding_note ?? ""} rows={8}
                            onChange={(e) => set("finding_note", e.target.value)} />
                </label>

                <Save hint="저장하면 유방외과로 소견이 전송됩니다."
                      saveLabel="저장" busy={busy}
                      onDraft={draft} onSave={finalize} />
              </>
            }>
            <div className="vart" />
            {/* 탭 대신 이것 하나. 원본 위에 마스크를 얹고 투명도로 본다 */}
            <Slide label="마스크 투명도" value={mask} onChange={setMask} />
          </Viewer>
        </Card>
      </div>

      <aside className="split-r">
        <Fold title="검체 정보">
          <div className="ph">
            <span className="ava" aria-hidden="true">{d.patient.name[0]}</span>
            <div className="ph-tx">
              <b>{d.patient.name} <span className="src">({d.patient.sex}, {d.patient.age}세)</span></b>
              <span>{d.patient.patient_no}</span>
            </div>
          </div>
          <dl className="kv wide">
            <div><dt>검체번호</dt><dd>{d.specimen.no}</dd></div>
            <div><dt>검체 종류</dt><dd>{d.specimen.kind}</dd></div>
            <div><dt>채취 방식</dt><dd>{d.specimen.method}</dd></div>
            <div><dt>채취일시</dt><dd>{d.specimen.collected_at}</dd></div>
            <div><dt>병변 위치</dt><dd>{d.specimen.lesion}</dd></div>
          </dl>
          {d.imaging && (
            <>
              <h3 className="seck">영상의학과 판독 요약</h3>
              <dl className="kv wide">
                <div><dt>{d.imaging.modality}</dt><dd>{d.imaging.finding}</dd></div>
                <div><dt>BI-RADS</dt><dd>{d.imaging.birads}</dd></div>
              </dl>
            </>
          )}
        </Fold>

        <Fold title={`올린 크롭 ${d.crops.length}`}>
          <ul className="slides">
            {d.crops.map((c, i) => (
              <li key={c.id} className={crop === c.id ? "on" : undefined}>
                <button onClick={() => setCrop(c.id)}>크롭 {i + 1} · {c.name}</button>
              </li>
            ))}
          </ul>
        </Fold>
      </aside>
    </div>
  );
}
