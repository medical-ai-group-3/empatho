import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Chip, Fold, Locked, Save, readable } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { can } from "../perm";

/* ═══ 5장 · 판독 정정 ════════════════════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   이미 확정해서 유방외과로 나간 판독을 고친다. 4장에서 들어온다.
 *
 * **옛 값은 지워지지 않는다.**
 *   병리과  specimen.amend_history (JSONB) 에 옛 값을 밀어넣는다.
 *           검체는 물건이라 행을 늘릴 수 없다 — specimen_label 이
 *           유일 키이고, 대조 플래그가 옛 행을 가리킨 채 남는다
 *   영상의학과  새 assessment 행을 만들고 옛 행의 superseded_by 가
 *           그것을 가리킨다
 *   어느 쪽이든 「최근 1건」이 아니라 **전부** 남는다.
 *
 * **사유 없이는 못 고친다.**
 *   정정 사유 · 세부 분류 · 세부 소견 셋 다 필수다. 사유가 없으면
 *   나중에 왜 바뀌었는지 아무도 모른다.
 *
 * ── 입력이 셋이다 (2026-09-16 확정) ─────────────────────────
 *   decision_reason  왜 고치는지. **이력에만** 남는다. 250자
 *   category         등급. 병리는 B 분류, 영상은 BI-RADS
 *   finding_note     고쳐 쓴 판독문. **유방외과로 나간다**. 1000자
 *
 * 정정 사유는 판정 표의 decision_reason 칸에 따로 저장된다.
 * finding_note 앞에 붙이지 않는다.
 *
 * ⚠ 250자다. 요청 본문 상한이 500자로 잡혀 있어 251~500자를 보내면
 *   지금은 500 이 난다(앱 서버 수정 대기). 그래서 **화면에서 250자로
 *   막는다** — 서버가 고쳐져도 250 이 맞는 값이라 그대로 두면 된다.
 *
 * 명세 초안에는 긴 칸이 둘이었는데(「세부 소견」과 「정정 판독 내용」)
 * **같은 것을 두 번 적어 둔 것**이었다. 하나로 합치고, 아래쪽
 * 「기존 ↔ 정정」 나란히 보기 자리에 두었다. 고치면서 옛 판독을 옆에
 * 놓고 보는 것이 이 화면의 목적이라 그 자리가 맞다.
 *
 * 저장되는 곳
 *   병리   specimen.amend_history (JSONB) 안에 amend_reason 으로 들어간다
 *   영상   새 assessment 행. 정정 사유를 담을 칸은 아직 정해지지 않았다
 *          — 요청 본문은 둘을 따로 보낸다
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
    /* ⚠ **환자 띠를 단다.** 환자 하나를 다루는 화면이라 누구인지
       안 보이면 안 된다 — 판정을 고치는 자리다.
       ⚠ 위에 있던 설명 문구는 뺐다(9장). 같은 말을 저장 줄이 이미
         한다 — 「옛 판독은 지워지지 않습니다」 */
    <Page crumb={[cfg.name, cfg.list.title, c.title]} title={c.title}
          patient={data?.patient}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner cfg={cfg} id={id} d={data} />}
      </Body>
    </Page>
  );
}

function Inner({ cfg, id, d }) {
  const c = cfg.amend;
  const nav = useNavigate();
  const prev = d.doctor ?? {};

  /* 이전 판독 이력을 어디서 받나 — 과마다 다르다.
   *
   *   병리   검체 안에 들어 있다 (amend_history JSONB). 따로 안 부른다
   *   영상   별도 행이라 판독 응답에 실려 오기도 하고 안 오기도 한다
   *
   * 안 실려 오면 **따로 부른다.** GET /assessments?study={id} 가
   * api.js 에 진작 있었는데 아무도 안 불러서, 이력이 비어 보이면
   * 「정정한 적 없음」으로 읽히고 있었다. 서버를 기다릴 일이 아니었다. */
  const inline = c.history(d) ?? [];
  const needFetch = inline.length === 0 && Boolean(cfg.api.history);
  const far = useApi(
    () => (needFetch ? cfg.api.history(id) : Promise.resolve(null)),
    [id, needFetch],
  );
  const history = inline.length > 0
    ? inline
    : (Array.isArray(far.data)
      ? far.data
      : far.data?.results ?? far.data?.items ?? []);

  /* 정정 API는 study_id가 아니라 assessment_id를 받는다.
     확정된 판독 중 아직 superseded_by가 없는 현재 판독만 대상으로
     삼는다. ID가 없으면 저장을 막아 숫자가 우연히 맞는 다른 판정을
     정정할 가능성을 없앤다. */
  const assessmentId = (
    d.current_assessment?.read_stage === "final"
      ? d.current_assessment.assessment_id
      : null
  ) ?? history.find((a) => a.read_stage === "final" && !a.superseded_by)?.assessment_id
    ?? null;

  const [f, setF] = useState({
    decision_reason: "",
    category: "",
    finding_note: prev.finding_note ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const ready = f.decision_reason.trim() && f.category && f.finding_note.trim();
  /* 선택지는 과마다 목록이거나, 검사에 따라 갈리면 함수다 — 영상은
     MRI 면 4(세분 없음), 맘모 · 초음파면 4a~4c */
  const categories = typeof c.categories === "function" ? c.categories(d) : c.categories;

  async function save() {
    if (!assessmentId) {
      setMsg("정정할 확정 판독 ID를 찾을 수 없습니다.");
      return;
    }
    setBusy(true); setMsg(null);
    try { await cfg.api.amend(assessmentId, f); nav(cfg.go.list()); }
    catch (e) { setMsg(e.detail || "정정 저장에 실패했습니다."); setBusy(false); }
  }

  return (
    <div className="amend">
      {/* ── 위 · 무엇을 고치는가 ───────────────────────────── */}
      <div className="grid3">
        <Card title="환자 정보">
          <c.Info d={d} cfg={cfg} />
        </Card>

        <Card title={c.imageTitle}>
          <div className="vart small" />
          <ul className="thumbs">
            {(d.images ?? []).map((im, i) => (
              <li key={im.id ?? i}><span className="thumb" aria-hidden="true" />{im.name}</li>
            ))}
            {(d.images ?? []).length === 0 && <li className="none">이미지가 없습니다</li>}
          </ul>
        </Card>

        <Card title="정정 내용">
          {/* 왜 고치는지. 이력에만 남고 유방외과로는 안 나간다 */}
          <label className="field">
            <span>정정 사유 <i className="req">*</i></span>
            <textarea value={f.decision_reason} maxLength={250} rows={4}
                      placeholder="예: 추가 면역염색 결과 반영"
                      onChange={(e) => set("decision_reason", e.target.value)} />
            <span className="count">{f.decision_reason.length} / 250</span>
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

          <p className="muted small">
            정정 사유는 이력에만 남습니다. 판독문 본문은 아래 「정정 판독 내용」에 씁니다.
          </p>
        </Card>
      </div>

      {/* ── 아래 · 전과 후 ──────────────────────────────────── */}
      <div className="grid2">
        <Card title="기존 판독 내용" right={<Chip tone="line">읽기 전용</Chip>}>
          <div className="ro">
            <div><h3>[진단]</h3><p>{prev.diagnosis_label ?? "—"}</p></div>
            <div><h3>[{c.categoryLabel}]</h3><p>{prev.category_label ?? "—"}</p></div>
            <div><h3>[소견]</h3><p>{prev.finding_note ?? "—"}</p></div>
          </div>

          <Fold title={`이전 판독 전문 보기 (${history.length}건)`} open={false}>
            {history.length === 0 && <p className="muted">이전 정정 이력이 없습니다.</p>}
            <ol className="hist">
              {history.map((h, i) => (
                <li key={i}>
                  <div className="hist-h">
                    <b>{readable(h.amended_at ?? h.finalized_at)}</b>
                    <span>{h.reported_by}</span>
                  </div>
                  {h.amend_reason && <p className="why">사유 — {h.amend_reason}</p>}
                  <p>{h.finding_note}</p>
                </li>
              ))}
            </ol>
          </Fold>
        </Card>

        <Card title="정정 판독 내용"
              right={<Btn kind="ghost" disabled title="불러올 템플릿이 아직 정해지지 않았습니다">템플릿 불러오기</Btn>}>
          <label className="field">
            <span>수정 후 판독문 <i className="req">*</i></span>
            <textarea className="lg" value={f.finding_note} rows={12} maxLength={1000}
                      placeholder="유방외과로 나갈 판독문을 고쳐 씁니다"
                      onChange={(e) => set("finding_note", e.target.value)} />
            <span className="count">{f.finding_note.length} / 1000</span>
          </label>
        </Card>
      </div>

      {msg && <div className="notice">{msg}</div>}

      {/* ⚠ 왼쪽 단추는 **임시저장이 아니다.** 이 화면에는 임시저장이
          없다 — 정정은 사유까지 갖춰야 성립하는 것이라 반쯤 써 둔
          상태를 남길 자리가 없다. 하는 일은 판독 화면으로 돌아가는
          것뿐이고, 여기 쓴 것은 남지 않는다. 이름으로 그렇게 말한다 */}
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
      <p className="muted small">
        「판독 화면으로」는 저장하지 않고 돌아갑니다. 여기 쓰신 내용은 남지 않습니다.
      </p>
      {!assessmentId && <p className="muted small">정정할 확정 판독 ID를 찾지 못해 저장할 수 없습니다.</p>}
      {assessmentId && !ready && <p className="muted small">정정 사유 · {c.categoryLabel} · 정정 판독 내용을 모두 채워야 저장할 수 있습니다.</p>}
    </div>
  );
}
