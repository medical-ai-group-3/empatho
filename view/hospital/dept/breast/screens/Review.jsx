import { useState } from "react";
import { useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip } from "../../../lib/Parts";
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
              <Btn to={go.breast.decision(id)}>치료 방침</Btn>
              <Btn to={go.breast.waiting()}>내 환자</Btn>
            </>
          )}>
      <Body loading={p.loading && !p.data} error={p.error} onRetry={p.reload}>
        {p.data && <Inner p={p.data} />}
      </Body>
    </Page>
  );
}
function Inner({ p }) {
  const [seeing, setSeeing] = useState(false);
  const rep = p.other_reports ?? [];
  const of = (want) => rep.filter((r) => (r.dept ?? "").includes(want));
  const rad = of("영상");
  const pat = of("병리");
  /* ⚠ **판정 그 자체를 여기서 처음으로 쓴다.** 위 other_reports 는 LLM
     소견문(narrative_text)이라 BI-RADS 도 B 분류도 안 들어 있다. 화면이
     「확정」 칩만 띄우고 정작 몇 등급인지를 못 보여 주던 자리다(09-23).
     판정은 Assessment · Specimen 표에 있고 api.js 의 readings 가 모은다.
     최신순이라 맨 앞이 이번 것이다 */
  const readings = p.readings ?? { radiology: [], pathology: [] };
  const radRead = readings.radiology?.[0] ?? null;
  const patRead = readings.pathology?.[0] ?? null;
  const odd = p.open_discordance;

  return (
    <div className="rev">
      {p.data_warnings?.length > 0 && (
        <p className="warnline">
          일부 자료를 불러오지 못했습니다: {p.data_warnings.join(", ")}. 새로고침 후 다시 확인해 주세요.
        </p>
      )}
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

        <Reading title="영상 판독" r={rad} v={radRead} gradeLabel="BI-RADS"
                 lines={[["병변", lesionLine(p.lesions)]]}
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

        <Reading title="병리 결과" r={pat} v={patRead} gradeLabel="B"
                 lines={[["검체", patRead?.specimen_id
                   ?? p.lesions?.find((l) => l.specimen_id)?.specimen_id]]} />
      </div>

      {seeing && (
        <section className="rev-see">
          <div className="breast">
            <ReviewViewer patientId={p.patient_id} lesions={p.lesions ?? []} />
          </div>
        </section>
      )}

    </div>
  );
}

/* 병변 한 줄 — 「좌상 외측 · 12mm」.
 *
 * ⚠ 전에는 l.site · l.size_mm 을 읽었는데 **서버에 그런 칸이 없다.**
 *   Lesion 표의 이름은 label · measured_size_mm · ai_size_mm 이라
 *   줄이 늘 「undefined · undefinedmm」 이었다(09-23 확인).
 * ⚠ 잰 값이 먼저다. AI 값은 사람이 확인하기 전의 값이라 뒤에 온다 —
 *   환자 상세(screens/Patient.jsx)가 쓰는 규칙과 같다.
 */
function lesionLine(lesions) {
  return (Array.isArray(lesions) ? lesions : [lesions])
    .filter(Boolean)
    .map((l) => {
      const site = l.label ?? l.site ?? null;
      const mm = l.measured_size_mm ?? l.ai_size_mm ?? null;
      return [site, mm != null ? `${mm}mm` : null].filter(Boolean).join(" · ");
    })
    .filter(Boolean).join(", ") || null;
}

/* 판독 한 칸 — 영상과 병리가 같은 모양을 쓴다.
 *
 *   r  리포트의 소견문 (LLM 이 쓴 글. 없을 수 있다)
 *   v  **판정** — BI-RADS 나 B 분류와 판독의가 쓴 소견. 이쪽이 본체다
 *
 * ⚠ **칸을 없애지 않는다.** 한쪽이 아직 없어도 자리를 둔다.
 * ⚠ 둘 중 하나만 있어도 칸을 채운다 — 전에는 소견문이 없으면(파이프라인이
 *   안 돌면) 판정이 멀쩡히 있어도 「아직 없습니다」였다(09-23).
 */
function Reading({ title, r, v = null, gradeLabel, lines = [], action }) {
  const reports = Array.isArray(r) ? r : (r ? [r] : []);
  const has = reports.length > 0 || Boolean(v);
  return (
    <section className="rev-box">
      <header className="rev-box-h">
        <h3>{title}</h3>
        <span className="home-fill" />
        {v?.grade && (
          <Chip tone="fill">
            {gradeLabel ? `${gradeLabel} ${v.grade}` : v.grade}
          </Chip>
        )}
        {has ? <Chip>확정</Chip> : <span className="hcard-k">아직 없습니다</span>}
      </header>
      {has && (
        <>
          <dl className="kv">
            {lines.filter(([, x]) => x).map(([k, x]) => (
              <div key={k}><dt>{k}</dt><dd>{x}</dd></div>
            ))}
            {/* 낸 사람·시각을 모르면 빈 줄을 그리지 않는다. 서버 리포트에
                발행 시각 칸이 없어(created_at 은 응답에서 빠진다) 늘
                빈 「판독 —」 이 남았다. 대신 어느 검사인지를 적는다 */}
            {reports.map((row, index) => row.dept && (
              <div key={`${row.report_id ?? row.dept}-${index}`}>
                <dt>판독</dt><dd>{row.dept}</dd>
              </div>
            ))}
          </dl>
          {/* 판독의가 쓴 소견이 먼저다. 소견문은 그것을 풀어 쓴 글이다 */}
          {v?.note && <p className="rev-find">{v.note}</p>}
          {reports.map((row, index) => row.summary && (
            <p className="rev-find muted" key={`${row.report_id ?? row.dept}-summary-${index}`}>
              {row.summary}
            </p>
          ))}
        </>
      )}
      {action && <div className="rowb">{action}</div>}
    </section>
  );
}
