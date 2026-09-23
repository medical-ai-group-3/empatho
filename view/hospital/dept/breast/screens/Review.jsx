import { useState } from "react";
import { useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip, useCan } from "../../../lib/Parts";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";
import ReviewViewer from "../components/ReviewViewer";

/* 유방외과 · 검사 종합 — `docs/mockup/SurgeryReview.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **영상과 병리를 나란히 놓고 한 번에 읽는 자리다.** 두 과가 각자 확정한
 * 것을 여기서 처음으로 맞대어 본다.
 *
 *   ┌ 1fr ───────────────────┬ 1fr ──────────────────┐
 *   │ 환자 정보               │ ✓ 영상과 병리가 일치   │
 *   │ 영상 판독               │ 병리 결과              │
 *   │  BI-RADS 4 · 소견       │  B2 · 진단 · 소견      │
 *   │  [영상 보기]            │                        │
 *   ├─────────────────────────┴────────────────────────┤
 *   │ 결정 입력 — 종류 · 가부 · 근거 · 공개 동의        │
 *   └──────────────────────────────────────────────────┘
 *
 * ⚠ **칸을 1px 선으로 가른다(4.5).** 목업은 카드를 띄우지만 그러면 칸마다
 *   안쪽 여백이 또 생긴다.
 * ⚠ **일치·불일치를 색으로 말하지 않는다.** 목업은 초록/빨강 배너다.
 *   우리는 글자와 soot 채움으로 가른다 — 판독 영상 위에서 그 색들이
 *   병변 표시와 싸운다(tokens.css 머리의 색 규칙).
 * ⚠ **목업에 뷰어가 없다.** 「영상 보기」가 다른 쪽으로 보내는 모양인데
 *   유방외과에는 판독 화면 권한이 없다. 그래서 그 단추로 **이 자리에서**
 *   뷰어를 편다 — 유방외과가 영상을 보는 유일한 길이라 끊으면 안 된다.
 */
export default function Review() {
  const { id } = useParams();
  const p = useApi(() => api.patient(id), [id]);

  return (
    <Page className="rev-page" crumb={["유방외과", "검사 종합"]}
          title="검사 종합" patient={p.data}
          right={(
            <>
              <Btn to={go.patient(id)}>환자 상세</Btn>
              <Btn to={go.breast.waiting()}>내 환자</Btn>
            </>
          )}>
      <Body loading={p.loading && !p.data} error={p.error} onRetry={p.reload}>
        {p.data && <Inner p={p.data} onSaved={() => p.reload(true)} />}
      </Body>
    </Page>
  );
}

function Inner({ p, onSaved }) {
  const [seeing, setSeeing] = useState(false);
  const rep = p.other_reports ?? [];
  const of = (want) => rep.find((r) => (r.dept ?? "").includes(want)) ?? null;
  const rad = of("영상");
  const pat = of("병리");
  const odd = p.open_discordance;

  return (
    <div className="rev">
      <div className="rev-l">
        <section className="rev-box">
          <h3>환자</h3>
          <dl className="kv">
            <div><dt>환자</dt><dd>{H.nameOf(p)}{H.who(p) && ` · ${H.who(p)}`}</dd></div>
            <div><dt>환자번호</dt><dd>{H.noOf(p) ?? "—"}</dd></div>
            <div><dt>내원</dt><dd>{p.visit_type ?? "—"}</dd></div>
            <div><dt>의뢰</dt><dd>{p.visit_purpose ?? "—"}</dd></div>
          </dl>
        </section>

        <Reading title="영상 판독" r={rad}
                 lines={[["병변", p.lesions?.[0]
                   && `${p.lesions[0].site} · ${p.lesions[0].size_mm}mm`]]}
                 action={(
                   <Btn onClick={() => setSeeing((v) => !v)}>
                     {seeing ? "영상 접기" : "영상 보기"}
                   </Btn>
                 )} />
      </div>

      <div className="rev-r">
        {/* 일치 여부 — 서버가 불일치를 걸었는지로만 말한다.
            ⚠ 우리가 BI-RADS 와 B 분류를 견주어 판단하지 않는다.
              그 규칙은 서버(rule_table_version)에 있고 화면이 흉내 내면
              규칙이 바뀔 때 두 곳이 어긋난다 */}
        <section className={`rev-flag${odd ? " k1" : ""}`}>
          <i aria-hidden="true">{odd ? "⚠" : "✓"}</i>
          <span>
            <b>{odd ? "영상과 병리가 엇갈립니다" : "엇갈린 것이 없습니다"}</b>
            {odd && <span className="hcard-k">{odd.violated_rule}</span>}
          </span>
          <span className="home-fill" />
          {odd && (
            <Btn to={go.breast.discordance(odd.discordance_id)}>처분하기</Btn>
          )}
        </section>

        <Reading title="병리 결과" r={pat}
                 lines={[["검체", p.lesions?.find((l) => l.specimen_id)?.specimen_id]]} />
      </div>

      {seeing && (
        <section className="rev-see">
          <div className="breast">
            <ReviewViewer patientId={p.patient_id} lesions={p.lesions ?? []} />
          </div>
        </section>
      )}

      <Decide p={p} onSaved={onSaved} />
    </div>
  );
}

/* 판독 한 칸 — 영상과 병리가 같은 모양을 쓴다.
   ⚠ **칸을 없애지 않는다.** 한쪽이 아직 없어도 자리를 둔다 */
function Reading({ title, r, lines = [], action }) {
  return (
    <section className="rev-box">
      <header className="rev-box-h">
        <h3>{title}</h3>
        <span className="home-fill" />
        {r ? <Chip>확정</Chip> : <span className="hcard-k">아직 없습니다</span>}
      </header>
      {r && (
        <>
          <dl className="kv">
            {lines.filter(([, v]) => v).map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
            {/* 낸 사람·시각을 모르면 빈 줄을 그리지 않는다. 서버 리포트에
                발행 시각 칸이 없어(created_at 은 응답에서 빠진다) 늘
                빈 「판독 —」 이 남았다. 대신 어느 검사인지를 적는다 */}
            {r.dept && <div><dt>판독</dt><dd>{r.dept}</dd></div>}
          </dl>
          <p className="rev-find">{r.summary}</p>
        </>
      )}
      {action && <div className="rowb">{action}</div>}
    </section>
  );
}

/* ── 결정 입력 ────────────────────────────────────────────────
 * ⚠ **두 가지를 저장한다.** 결정 자체는 `PATCH /assessments/{id}/decision`,
 *   환자에게 여는 것은 `PATCH /reports/{id}/explain` 이다. 목업은 한
 *   단추지만 서버는 두 곳이라, 동의 칸을 켰을 때만 둘째를 부른다.
 * ⚠ **어느 판독에 붙일지는 진료 이력이 안다** — 환자 응답에 assessment
 *   번호가 없다. timeline 의 「판독」 줄이 달고 온다.
 */
/* ⚠ **보내는 값은 서버 코드다.** 화면 글자를 그대로 보내면 안 된다 —
     서버 DECISION_TYPE 은 surgery·biopsy·imaging·rebiopsy 고
     DECISION_VALUE 는 yes·no·defer 다(models.py:79-80). 전에는 한글을
     `decision`·`reason` 이라는 없는 키로 보내서 **저장이 늘 실패했다**
     (서버가 받는 키는 decision_value·decision_reason 이다). */
const KINDS = [
  { v: "surgery",  label: "수술" },
  { v: "imaging",  label: "추적 관찰" },
  { v: "biopsy",   label: "추가 검사" },
  { v: "rebiopsy", label: "재조직검사" },
];
const GOES = [
  { v: "yes",   label: "진행" },
  { v: "defer", label: "보류" },
];

function Decide({ p, onSaved }) {
  const line = useApi(() => H.soft(api.timeline(p.patient_id)), [p.patient_id]);
  const aid = H.rows(line.data).filter((r) => r.assessment_id).at(-1)?.assessment_id ?? null;
  const rid = p.report?.report_id ?? null;

  const [kind, setKind] = useState(KINDS[0].v);
  const [goNo, setGoNo] = useState(GOES[0].v);
  const [why, setWhy] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const may = useCan("breast.decision.save");

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api.decide(aid, {
        decision_type: kind, decision_value: goNo, decision_reason: why,
      });
      /* 환자에게 여는 것은 설명 **방법**과 확인 여부다 — 서버가 받는
         것이 그 둘뿐이라(ReportExplainSerializer) 글은 여기로 안 간다.
         근거는 바로 위 decision_reason 에 이미 남는다. */
      if (open && rid) {
        await api.explain(rid, { explain_method: "대면", patient_confirmed: true });
      }
      setMsg("확정했습니다");
      onSaved?.();
    } catch (e) { setMsg(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="rev-dec">
      <header className="rev-box-h">
        <h3>결정 입력</h3>
        <span className="home-fill" />
        {msg && <span className="hcard-k">{msg}</span>}
      </header>

      <div className="rev-dec-b">
        <label className="rev-f">
          <span>결정 종류</span>
          <div className="work-seg" role="radiogroup" aria-label="결정 종류">
            {KINDS.map((k) => (
              <button type="button" key={k.v} role="radio" aria-checked={k.v === kind}
                      className={`work-opt${k.v === kind ? " on" : ""}`}
                      disabled={!may.ok} onClick={() => setKind(k.v)}>{k.label}</button>
            ))}
          </div>
        </label>

        <label className="rev-f narrow">
          <span>가부</span>
          <div className="work-seg narrow" role="radiogroup" aria-label="가부">
            {GOES.map((g) => (
              <button type="button" key={g.v} role="radio" aria-checked={g.v === goNo}
                      className={`work-opt${g.v === goNo ? " on" : ""}`}
                      disabled={!may.ok} onClick={() => setGoNo(g.v)}>{g.label}</button>
            ))}
          </div>
        </label>
      </div>

      <label className="rev-f">
        <span>근거 · 환자 설명</span>
        <textarea value={why} onChange={(e) => setWhy(e.target.value)}
                  rows={3} disabled={!may.ok} />
      </label>

      <div className="rev-f row">
        <label className="rev-ck">
          <input type="checkbox" checked={open} disabled={!may.ok || !rid}
                 onChange={(e) => setOpen(e.target.checked)} />
          <span>환자 앱에 결과를 엽니다</span>
        </label>
        <span className="home-fill" />
        {!aid && <span className="hcard-k">확정된 판독이 있어야 결정을 답니다</span>}
        {!rid && <span className="hcard-k">리포트가 없어 환자 앱은 못 엽니다</span>}
        <Btn kind="fill" onClick={save} {...may.attrs}
             disabled={busy || !aid || !may.ok}>
          {busy ? "확정하는 중…" : "결정 확정"}
        </Btn>
      </div>
    </section>
  );
}
