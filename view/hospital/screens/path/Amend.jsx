import { useState } from "react";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Save } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";

/* 병리 25 · 판독 정정
 *
 * 이미 저장한 판독을 확인하고 정정 내용을 입력한다.
 *
 * ── 덮어쓰지 않는다 ──────────────────────────────────────────
 * 정정은 **새 행으로 쌓인다.** 기존 판독은 그대로 남고, 무엇을 왜 고쳤는지가
 * 함께 기록된다. 판독 기록에서 「누가 언제 무엇을 바꿨나」가 지워지면 안
 * 되는 것이라, 화면도 그 구조를 그대로 보여준다 — 왼쪽에 기존, 오른쪽에
 * 새로 쓰는 것.
 *
 * 그래서 api.saveAmend 는 PUT 이 아니라 POST 다. 같은 것을 고치는 게
 * 아니라 새 것을 더하는 것이다.
 *
 * ── 사유가 필수인 이유 ───────────────────────────────────────
 * 「HER2 2+ → 3+」만 남으면 나중에 왜 바뀌었는지 아무도 모른다. FISH
 * 결과가 나와서인지, 처음에 잘못 본 것인지는 **전혀 다른 일**이다.
 * 셋 다 필수로 둔다 — 사유 · 세부 분류 · 세부 소견.
 */
export default function Amend() {
  const id = new URLSearchParams(location.search).get("case") ?? "current";
  const { loading, data, error, reload } = useApi(() => api.amendSource(id), [id]);

  return (
    <Page crumb={["환자 목록", "환자 상세", "기존 판독 조회", "판독 정정"]}
          title="판독 정정" badge="이력 보존"
          sub="이미 작성하여 저장한 병리 판독을 확인하고, 정정 내용을 입력합니다.">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

function Inner({ d }) {
  const [f, setF] = useState({ reason: "", category: "", detail: "", text: "" });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const ready = f.reason.trim() && f.category && f.detail.trim() && f.text.trim();

  return (
    <>
      <Card className="callout">
        <b>정정된 판독은 기존 판독의 수정 이력을 남기며, 이전 판독 내용은 모두 보존됩니다.</b>
      </Card>

      <div className="grid3">
        <Card title="환자 기본 정보">
          <dl className="kv">
            <div><dt>환자명</dt><dd>{d.patient.name} ({d.patient.sex}, {d.patient.age}세)</dd></div>
            <div><dt>검체번호</dt><dd>{d.patient.specimen_no}</dd></div>
            <div><dt>검체 종류</dt><dd>{d.patient.kind} · {d.patient.site}</dd></div>
            <div><dt>판독일시</dt><dd>{d.prev.at}</dd></div>
            <div><dt>담당의</dt><dd>{d.prev.by}</dd></div>
            <div><dt>슬라이드</dt><dd>{d.slides.map((s) => s.label).join(" / ")}</dd></div>
          </dl>
        </Card>

        <Card title="주요 이미지" right={<span className="src">기존 판독 시 참조된 영역</span>}>
          <div className="vart" style={{ minHeight: "var(--thumb-lg)" }} />
          <div className="thumbs">
            {d.refs.map((r, i) => (
              <span className={`thumb ${i === 0 ? "on" : ""}`} key={r}>
                <i aria-hidden="true" />{r}
              </span>
            ))}
          </div>
        </Card>

        <Card title="정정 사유">
          <label className="field">
            <span>정정 사유 <i className="req">*</i></span>
            <textarea value={f.reason} maxLength={500}
                      placeholder="예) FISH 결과 반영에 따른 HER2 상태 변경, 핵 등급 수정 등"
                      onChange={(e) => set("reason", e.target.value)} />
            <span className="count">{f.reason.length} / 500</span>
          </label>
          <label className="field">
            <span>세부 분류 <i className="req">*</i></span>
            <select value={f.category} onChange={(e) => set("category", e.target.value)}>
              <option value="">선택해주세요</option>
              {d.categories.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="field">
            <span>세부 소견 <i className="req">*</i></span>
            <textarea value={f.detail} maxLength={1000}
                      placeholder="정정 사유에 대한 상세 내용을 입력해주세요."
                      onChange={(e) => set("detail", e.target.value)} />
            <span className="count">{f.detail.length} / 1000</span>
          </label>
        </Card>
      </div>

      <div className="grid2">
        <Card title="기존 판독 내용" right={<Btn>이전 판독 전문 보기</Btn>}>
          <p className="by src">작성일 {d.prev.at} · {d.prev.by}</p>
          <div className="readout">
            {d.prev.sections.map((s) => (
              <div key={s.head}>
                <h3>[{s.head}]</h3>
                {s.lines.length === 1
                  ? <p>{s.lines[0]}</p>
                  : <ul>{s.lines.map((l) => <li key={l}>{l}</li>)}</ul>}
              </div>
            ))}
          </div>
        </Card>

        <Card title="정정 판독 내용 (수정 후)" right={<Btn>템플릿 불러오기</Btn>}>
          <div className="rte">
            <div className="rte-bar">
              {["B", "I", "U", "S"].map((t) => <button key={t} aria-label={t}>{t}</button>)}
              <i className="div" aria-hidden="true" />
              {["≔", "≕", "▤", "→", "🔗", "⛶"].map((t, i) =>
                <button key={i} aria-label={`서식 ${i + 1}`}>{t}</button>)}
            </div>
            <textarea className="lg" value={f.text}
                      placeholder="정정된 판독 내용을 입력해주세요."
                      onChange={(e) => set("text", e.target.value)} />
          </div>
          <Save hint="저장 시 유방외과에 정정 알림이 전송됩니다."
                busy={busy || !ready}
                onDraft={() => { setBusy(true); api.saveAmend(d.id, { ...f, draft: true }).finally(() => setBusy(false)); }}
                onSave={() => { setBusy(true); api.saveAmend(d.id, f).finally(() => setBusy(false)); }} />
        </Card>
      </div>
    </>
  );
}
