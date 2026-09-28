import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Card, Page } from "../lib/Page";
import { Chip, Locked, Save, readable } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { can } from "../perm";
import { currentAssessment } from "../api";

/* ═══ 5장 · 판독 정정 ════════════════════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   이미 확정해서 유방외과로 나간 판독을 고친다. 판독 화면(확정된 검사)의
 *   [판독 정정]으로 들어온다.
 *
 * **옛 값은 지워지지 않는다.**
 *   영상의학과  새 assessment 행을 만들고 옛 행의 superseded_by 가 그것을
 *               가리킨다 — 「최근 1건」이 아니라 **전부** 남는다.
 *   병리과      정정 경로가 없다(확정 사양서 §8-2). 이 화면을 안 쓴다.
 *
 * **사유 없이는 못 고친다.**  정정 사유 · 등급 · 판독문 셋 다 필수다.
 *   decision_reason  왜 고치는지. **이력에만** 남는다. 250자
 *   category         등급(영상은 BI-RADS)
 *   finding_note     고쳐 쓴 판독문. **유방외과로 나간다**. 1000자
 *   ⚠ 250자 — 서버 요청 본문 상한 문제로 화면에서 막는다(서버가 고쳐져도 맞는 값)
 *
 * **자리 (09-28 재배치)**
 *   왼쪽  기존 판독(지금 유효한 한 판) · 판독 이력(정정 사슬) · 검사
 *   오른쪽  사유* → 등급* → 판독문* → 저장. ⚠ 저장이 스크롤 밑으로 숨지
 *           않게 오른쪽 칸 안에 둔다(1600×950 에서 한 화면)
 *   ⚠ 「주요 이미지」 회색 상자는 뺐다 — 영상이 아니라 빈 틀이었다.
 *     영상을 다시 봐야 하면 판독 화면으로 돌아간다.
 */

export default function AmendScreen({ cfg }) {
  const c = cfg.amend;
  const { id } = useParams();

  if (!can(c.need.view)) {
    return (
      <Page crumb={[cfg.name, c.title]} title={c.title}>
        <Locked what={c.title} />
      </Page>
    );
  }
  return <Load cfg={cfg} id={id} />;
}

function Load({ cfg, id }) {
  const c = cfg.amend;
  const { loading, data, error, reload } = useApi(() => cfg.api.read(id), [id]);

  return (
    /* ⚠ 환자 띠를 단다 — 판정을 고치는 자리라 누구인지 늘 보여야 한다 */
    <Page crumb={[cfg.name, cfg.read.title, c.title]} title={c.title}
          patient={data?.patient}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner cfg={cfg} id={id} d={data} />}
      </Body>
    </Page>
  );
}

/* 판 한 줄을 한 모양으로. 실서버(AssessmentSerializer)와 옛 목업
   (amend_history 꼴 — amended_at · reported_by · amend_reason)을 같이 받는다 */
function norm(h) {
  return {
    id: h.assessment_id ?? h.id ?? null,
    at: h.finalized_at ?? h.amended_at ?? null,
    who: h.assessed_by_name ?? h.reported_by
      ?? (h.assessed_by != null ? `직원 #${h.assessed_by}` : null),
    why: h.decision_reason ?? h.amend_reason ?? null,
    category: h.category ?? null,
    note: h.finding_note ?? "",
    stage: h.read_stage ?? "final",
    superseded: h.superseded_by ?? null,
  };
}

function Inner({ cfg, id, d }) {
  const c = cfg.amend;

  /* 판 목록 — 늘 따로 부른다(GET /assessments?study=). 판독 응답에 실린
     history 는 옛 서버 · 목업 모양이라 부르지 못할 때만 쓴다 */
  const far = useApi(
    () => (cfg.api.history ? cfg.api.history(id) : Promise.resolve([])),
    [id],
  );
  const fetched = Array.isArray(far.data) ? far.data : far.data?.results ?? far.data?.items ?? [];
  const raw = fetched.length > 0 ? fetched : (c.history?.(d) ?? []);

  /* 지금 유효한 판 — 확정 중 superseded_by 가 없는 것. 정정 API 는 이 판의
     assessment_id 를 받는다. 못 찾으면 저장을 막는다 — 번호가 우연히 맞는
     다른 판을 고치면 안 된다 */
  const cur = currentAssessment(raw.filter((h) => h.assessment_id != null)) ?? null;
  const assessmentId = cur?.assessment_id
    ?? (d.current_assessment?.read_stage === "final" ? d.current_assessment.assessment_id : null);
  const now = cur ? norm(cur) : (fetched.length === 0 && d.doctor?.finding_note
    ? norm({ ...d.doctor, read_stage: "final" }) : null);
  const history = raw.map(norm)
    .filter((h) => h.stage === "final")
    .sort((a, b) => String(b.at ?? "").localeCompare(String(a.at ?? "")));

  return (
    <div className="amend">
      <div className="amend-cols">
        <div className="amend-l">
          <Card title="기존 판독" right={<Chip tone="line">읽기 전용</Chip>}>
            <Body loading={far.loading} error={null}>
              {now ? (
                <div className="ro">
                  <div><h3>{c.categoryLabel}</h3><p>{c.categoryText ? c.categoryText(now.category) : now.category ?? "—"}</p></div>
                  {/* 병리처럼 진단 칸이 있는 과만 — 설정이 켠다 */}
                  {c.diagnosisRow && <div><h3>진단</h3><p>{d.doctor?.diagnosis_label ?? "—"}</p></div>}
                  <div><h3>판독문</h3><p>{now.note || "—"}</p></div>
                  <p className="muted small">
                    {[now.who, now.at && `확정 ${readable(now.at)}`].filter(Boolean).join(" · ") || "판독의 · 확정 시각 없음"}
                  </p>
                </div>
              ) : <p className="muted">확정된 판독을 찾지 못했습니다.</p>}
            </Body>
          </Card>

          <Card title={`판독 이력 ${history.length}판`}>
            {history.length === 0 && <p className="muted">이전 판이 없습니다.</p>}
            <ol className="hist">
              {history.map((h, i) => (
                <li key={h.id ?? i}>
                  <div className="hist-h">
                    <b>{readable(h.at) ?? "—"} · {c.categoryText ? c.categoryText(h.category) : h.category}</b>
                    <span>
                      {h.who}
                      {h.superseded == null && h.id != null && <Chip tone="dot">현재</Chip>}
                    </span>
                  </div>
                  {h.why && <p className="why">정정 사유 — {h.why}</p>}
                  <p>{h.note}</p>
                </li>
              ))}
            </ol>
          </Card>

          {c.Info && <Card title="검사"><c.Info d={d} cfg={cfg} /></Card>}
        </div>

        {/* 판 목록이 온 뒤에 폼을 세운다 — 판독문 첫 값이 지금 판의 글이다 */}
        <Card title="정정 내용" className="amend-form">
          <Body loading={far.loading} error={null}>
            <Form cfg={cfg} id={id} d={d} seed={now?.note ?? ""} assessmentId={assessmentId} />
          </Body>
        </Card>
      </div>
    </div>
  );
}

function Form({ cfg, id, d, seed, assessmentId }) {
  const c = cfg.amend;
  const nav = useNavigate();
  const [f, setF] = useState({ decision_reason: "", category: "", finding_note: seed });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const ready = f.decision_reason.trim() && f.category && f.finding_note.trim();
  /* 선택지는 목록이거나, 검사에 따라 갈리면 함수다 — 영상 MRI 는 4, 맘모 · 초음파는 4a~4c */
  const categories = typeof c.categories === "function" ? c.categories(d) : c.categories;

  async function save() {
    if (!assessmentId) { setMsg("정정할 확정 판독 ID를 찾을 수 없습니다."); return; }
    setBusy(true); setMsg(null);
    /* 정정 뒤에는 판독 화면으로 — 새 판이 확정 판독으로 떠 있는 것을 본다 */
    try { await cfg.api.amend(assessmentId, f); nav(cfg.go.read(id)); }
    catch (e) { setMsg(e.detail || "정정 저장에 실패했습니다."); setBusy(false); }
  }

  return (
    <>
      {/* 왜 고치는지. 이력에만 남고 유방외과로는 안 나간다 */}
      <label className="field">
        <span>정정 사유 <i className="req">*</i></span>
        <textarea value={f.decision_reason} maxLength={250} rows={2}
                  placeholder="예: 확대 촬영 추가 판독 반영"
                  onChange={(e) => set("decision_reason", e.target.value)} />
        <span className="count">{f.decision_reason.length} / 250 · 이력에만 남습니다</span>
      </label>

      <label className="field">
        <span>{c.categoryLabel} <i className="req">*</i></span>
        <select value={f.category} onChange={(e) => set("category", e.target.value)}>
          <option value="">선택하세요</option>
          {categories.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>수정 후 판독문 <i className="req">*</i></span>
        <textarea className="lg" value={f.finding_note} rows={7} maxLength={1000}
                  placeholder="유방외과로 나갈 판독문을 고쳐 씁니다"
                  onChange={(e) => set("finding_note", e.target.value)} />
        <span className="count">{f.finding_note.length} / 1000 · 유방외과로 나갑니다</span>
      </label>

      {msg && <div className="notice">{msg}</div>}

      {/* ⚠ 왼쪽 단추는 **임시저장이 아니다.** 정정은 사유까지 갖춰야 성립해서
          반쯤 써 둔 상태를 남길 자리가 없다. 판독 화면으로 돌아갈 뿐이다 */}
      <Save
        hint={c.saveHint}
        onDraft={() => nav(cfg.go.read(id))}
        onSave={save}
        busy={busy}
        canSave={Boolean(ready && assessmentId)}
        draftLabel="판독 화면으로"
        draftNeed={cfg.read.need.view}
        saveNeed={c.need.save}
        saveLabel="정정 저장"
      />
      {!assessmentId && <p className="muted small">정정할 확정 판독 ID를 찾지 못해 저장할 수 없습니다.</p>}
      {assessmentId && !ready && <p className="muted small">정정 사유 · {c.categoryLabel} · 판독문을 모두 채워야 저장할 수 있습니다. 「판독 화면으로」는 여기 쓴 것을 남기지 않습니다.</p>}
    </>
  );
}
