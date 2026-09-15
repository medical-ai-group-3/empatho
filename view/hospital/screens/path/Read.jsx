import { useState } from "react";
import { api } from "../../api";
import AiPanel from "../../lib/AiPanel";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Chip, Modal, Save, Viewer, Zoom } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";

/* 병리 23 · 판독
 *
 * WSI 위에 AI 분할을 겹쳐 보고, 병변을 등록한 뒤 소견을 저장해
 * 유방외과로 보낸다.
 *
 * ── 화면이 셋으로 갈린 이유 ──────────────────────────────────
 *   왼쪽  이 검체가 무엇인가          — 바뀌지 않는 사실
 *   가운데 실제로 보는 것              — 영상
 *   오른쪽 기계가 말한 것 / 내가 쓰는 것 — 둘을 **나란히** 둔다
 *
 * AI 소견과 의사 소견이 위아래로 겹치면 어느 것이 누구 말인지 흐려진다.
 * 양쪽 끝에 두고 각각 접을 수 있게 했다 — 영상만 크게 보고 싶을 때가
 * 있고, 그때 패널이 사라지지 않고 손잡이로 남는다.
 *
 * ── AI 패널은 손으로 그리지 않는다 ───────────────────────────
 * lib/AiPanel 이 상태 다섯을 가른다(대기 · 분석 중 · 검출 없음 ·
 * 불러오지 못함 · 완료). 화면마다 따로 그리면 **어느 하나가 「정상」이라고
 * 쓰게 된다.** 검출 0건은 「없다」가 아니라 「못 찾았다」이고, 그 둘을
 * 가르는 것이 이 시스템에서 제일 중요한 한 가지다.
 */
export default function Read() {
  const id = new URLSearchParams(location.search).get("case") ?? "current";
  const { loading, data, error, reload } = useApi(() => api.read(id), [id]);

  return (
    <Page crumb={["병리과", "판독"]} title="병리 판독"
          badge={data?.ai ? "AI 분석 완료" : undefined}
          sub="WSI 위에 AI 분할 결과를 겹쳐 보고, 병변을 등록한 뒤 소견을 저장해 유방외과로 전송합니다."
          right={data && <Chip>{data.patient.name} · {data.patient.specimen_no}</Chip>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

const LAYERS = [
  { key: "tumor",  label: "종양 영역 (AI)" },
  { key: "stroma", label: "기질 영역 (AI)" },
  { key: "til",    label: "TIL (CD3+ 추정)" },
  { key: "other",  label: "기타 세포" },
];

function Inner({ d }) {
  const [slide, setSlide] = useState(d.slides[0]?.id);
  const [zoom, setZoom]   = useState(d.slides[0]?.zoom ?? 40);
  const [tab, setTab]     = useState("전체 보기");
  const [on, setOn]       = useState(() =>
    Object.fromEntries(LAYERS.map((l) => [l.key, l.key !== "other"])));
  const [open, setOpen]   = useState(false);
  const [form, setForm]   = useState(d.doctor ?? {});
  const [busy, setBusy]   = useState(false);

  const save = (fn) => { setBusy(true); fn(d.id, form).finally(() => setBusy(false)); };
  const set  = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <>
      <div className="split wide">
        <div className="split-l">
          <Card pad={false}>
            <Viewer
              leftName="AI 접기" rightName="의사 접기"
              tabs={["전체 보기", "조직 분할", "세포 검출", "TIL 히트맵", "분할 오버레이"]
                .map((t) => (
                  <button key={t} className={`pill ${tab === t ? "on" : ""}`}
                          onClick={() => setTab(t)}>{t}</button>
                ))}
              tools={["⌖", "＋", "－", "✥", "✎", "⛶"].map((t, i) =>
                <button key={i} className="vtool" aria-label={`도구 ${i + 1}`}>{t}</button>)}
              leftPanel={
                <AiPanel r={d.ai}
                         onLocate={() => setTab("분할 오버레이")}
                         onFalsePositive={(l) => api.flagFalse(d.id, l.id)} />
              }
              rightPanel={
                <>
                  <div className="rowb">
                    <Btn onClick={() => setOpen(true)}>＋ 병변 등록</Btn>
                  </div>

                  <label className="field">
                    <span>악성 / 양성 여부</span>
                    <div className="seg">
                      {["악성", "양성", "경계성"].map((v) => (
                        <button key={v} className={form.malignancy === v ? "on" : ""}
                                onClick={() => set("malignancy", v)}>{v}</button>
                      ))}
                    </div>
                  </label>

                  <label className="field">
                    <span>조직학적 진단</span>
                    <select value={form.diagnosis ?? ""}
                            onChange={(e) => set("diagnosis", e.target.value)}>
                      <option value="">선택해주세요</option>
                      {d.options.diagnosis.map((o) => <option key={o}>{o}</option>)}
                    </select>
                  </label>

                  <div className="grid2">
                    <label className="field">
                      <span>핵 등급</span>
                      <select value={form.grade ?? ""}
                              onChange={(e) => set("grade", e.target.value)}>
                        <option value="">선택</option>
                        {d.options.grade.map((o) => <option key={o}>{o}</option>)}
                      </select>
                    </label>
                    <label className="field">
                      <span>HER2</span>
                      <select value={form.her2 ?? ""}
                              onChange={(e) => set("her2", e.target.value)}>
                        <option value="">선택</option>
                        {d.options.her2.map((o) => <option key={o}>{o}</option>)}
                      </select>
                    </label>
                  </div>

                  <label className="field">
                    <span>판독 소견</span>
                    <textarea value={form.note ?? ""} rows={6}
                              onChange={(e) => set("note", e.target.value)} />
                  </label>

                  <Save hint="저장하면 유방외과로 소견이 전송됩니다." busy={busy}
                        onDraft={() => save(api.draftRead)}
                        onSave={() => save(api.saveRead)} />
                </>
              }>
              <div className="vart">
                <div className="vmeta">
                  {zoom}x ({d.mpp} μm/px) — {d.scalebar}
                </div>
                <div className="vfloat">
                  <div className="layers">
                    {LAYERS.map((l) => (
                      <label key={l.key}>
                        <input type="checkbox" checked={on[l.key]}
                               onChange={(e) => setOn((s) => ({ ...s, [l.key]: e.target.checked }))} />
                        <i className="sw" aria-hidden="true" />
                        {l.label}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              <Zoom value={zoom} onChange={setZoom} />
            </Viewer>
          </Card>

          {/* AI 가 무엇을 보고 그렇게 말했는지. 근거 없이 숫자만 내면
              판독의가 반박할 방법이 없다 */}
          <Card title="AI 근거 이미지">
            <div className="thumbs">
              {d.evidence.map((e) => (
                <span className="thumb lg" key={e.label}>
                  <i aria-hidden="true" />{e.label}
                </span>
              ))}
            </div>
          </Card>
        </div>

        <aside className="split-r">
          <Card title="환자 정보">
            <div className="ph">
              <span className="ava" aria-hidden="true">{d.patient.name[0]}</span>
              <div className="ph-tx">
                <b>{d.patient.name} <span className="src">({d.patient.sex}, {d.patient.age}세)</span></b>
                <span>{d.patient.patient_no}</span>
              </div>
            </div>
            <dl className="kv wide">
              <div><dt>검체번호</dt><dd>{d.patient.specimen_no}</dd></div>
              <div><dt>검체 종류</dt><dd>{d.patient.kind}</dd></div>
              <div><dt>표적 병변</dt><dd>{d.patient.target}</dd></div>
              <div><dt>의뢰과</dt><dd>{d.patient.from_dept}</dd></div>
              <div><dt>검사 상태</dt><dd><Chip tone="dot">{d.state}</Chip></dd></div>
            </dl>
          </Card>

          <Card title={`슬라이드 목록 (${d.slides.length})`}>
            <ul className="slides">
              {d.slides.map((s, i) => (
                <li key={s.id} className={slide === s.id ? "on" : undefined}>
                  <button onClick={() => { setSlide(s.id); setZoom(s.zoom); }}>
                    {i + 1}. {s.label}
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          {d.linked && (
            <Card title="연관 영상">
              <dl className="kv">
                <div><dt>{d.linked.modality}</dt><dd>{d.linked.note}</dd></div>
                <div><dt>검사일</dt><dd>{d.linked.at}</dd></div>
              </dl>
            </Card>
          )}
        </aside>
      </div>

      <Modal open={open} title="병변 등록"
             sub="뷰어에서 영역을 지정하고 소견을 답니다."
             onClose={() => setOpen(false)}
             foot={<><Btn onClick={() => setOpen(false)}>취소</Btn>
                     <Btn kind="fill" onClick={() => setOpen(false)}>등록</Btn></>}>
        <label className="field">
          <span>병변 이름</span>
          <input placeholder="예) L1 · 좌측 상외측" />
        </label>
        <label className="field">
          <span>소견</span>
          <textarea placeholder="이 병변에 대한 소견을 입력하세요." />
        </label>
      </Modal>
    </>
  );
}
