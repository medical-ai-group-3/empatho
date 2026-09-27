import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip } from "../../../lib/Parts";
import { MODALITY, label } from "../../../codes";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";
import ReviewViewer from "../components/ReviewViewer";

/* 유방외과 · 검사 종합 — 09-27 개편
 * ════════════════════════════════════════════════════════════════
 *
 * **영상과 병리를 나란히 놓고 한 번에 읽는 자리다.** 두 과가 각자 확정한
 * 것을 여기서 처음으로 맞대어 본다.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ 환자 · 나이/성별 · 번호 · 내원 · 의뢰 · 주치의   [엇갈림] [화상 보기] │
 *   ├─────────────────────────────┬────────────────────────────────┤
 *   │ 영상 판독  BI-RADS 4a        │ 병리 결과  B2                   │
 *   │  ▾ 09-23 유방촬영 · 4a       │  ▾ 09-27 검체 51 · B5           │
 *   │  ▸ 09-22 초음파 · 3          │  ▸ 09-23 검체 44 · B2           │
 *   └─────────────────────────────┴────────────────────────────────┘
 *   [화상 보기] → 팝업 뷰어. 탭 초음파 · 유방촬영 · MRI · 병리
 *
 * ⚠ 판독은 **한 건씩 접는다.** 전에는 소견문이 전부 펼쳐져 있어 화면이
 *   길었고, 병리 쪽은 펼치고 접을 방법이 없었다. 가장 최근 한 건만 편다.
 * ⚠ **일치·불일치를 색으로 말하지 않는다.** 글자와 soot 채움으로 가른다 —
 *   판독 영상 위에서 초록/빨강이 병변 표시와 싸운다(tokens.css 색 규칙).
 * ⚠ 유방외과는 판독 화면 권한이 없다. 영상 · 병리 이미지를 보는 길이
 *   이 팝업뿐이라 끊으면 안 된다.
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
  /* 판정은 Assessment · Specimen 표에서 온다(api.js 의 readings, 최신순).
     other_reports 는 LLM 소견문이라 등급이 안 들어 있다 */
  const readings = p.readings ?? { radiology: [], pathology: [] };
  const rad = readings.radiology ?? [];
  const pat = readings.pathology ?? [];
  const odd = p.open_discordance;
  const specimenIds = pat.map((r) => r.specimen_id).filter((x) => x != null);

  const radRows = rows(rad, of("영상"), "study_id",
    (r) => label(MODALITY, r.modality) || "영상");
  const patRows = rows(pat, of("병리"), "specimen_id",
    (r) => `검체 ${r.specimen_id}`);

  return (
    <div className="rev2">
      {p.data_warnings?.length > 0 && (
        <p className="warnline">
          일부 자료를 불러오지 못했습니다: {p.data_warnings.join(", ")}. 새로고침 후 다시 확인해 주세요.
        </p>
      )}

      <section className="rev-strip">
        <dl className="rev-who">
          <div className="rev-name"><dd>{H.nameOf(p)}</dd></div>
          {[
            ["나이/성별", H.who(p)],
            ["환자번호", H.noOf(p)],
            ["내원", p.visit_type],
            ["의뢰", p.visit_purpose],
            ["주치의", p.primary_staff_name],
          ].map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v ?? "—"}</dd></div>
          ))}
        </dl>
        {/* 일치 여부 — 서버가 불일치를 걸었는지로만 말한다. BI-RADS 와 B
            분류를 여기서 견주지 않는다 — 규칙이 서버와 두 곳이 된다 */}
        <div className={`rev-odd${odd ? " k1" : ""}`}>
          <i aria-hidden="true">{odd ? "⚠" : "✓"}</i>
          <span>
            <b>{odd ? "영상과 병리가 엇갈립니다" : "엇갈린 것이 없습니다"}</b>
            {odd && <em>{odd.violated_rule}</em>}
          </span>
          {odd && <Btn to={go.breast.discordance(odd.discordance_id)}>처분하기</Btn>}
        </div>
        <Btn kind="fill" onClick={() => setSeeing(true)}>화상 보기</Btn>
      </section>

      <div className="rev">
        <div className="rev-l">
          <Readings title="영상 판독" gradeLabel="BI-RADS" items={radRows}
                    lines={[["병변", lesionLine(p.lesions)]]} />
        </div>
        <div className="rev-r">
          <Readings title="병리 결과" gradeLabel="B" items={patRows} />
        </div>
      </div>

      {seeing && (
        <ImagePopup name={H.nameOf(p)} onClose={() => setSeeing(false)}>
          <ReviewViewer patientId={p.patient_id} lesions={p.lesions ?? []}
                        specimenIds={specimenIds} />
        </ImagePopup>
      )}
    </div>
  );
}

/* 판정과 소견문을 한 줄로 묶는다. 판정(v)이 본체이고, 같은 검사 · 검체의
   소견문(r)을 그 아래에 붙인다. 판정이 아직 없는 소견문도 버리지 않는다 */
function rows(readings, reports, key, what) {
  /* 리포트 응답은 FK 를 study · specimen 으로 준다(ModelSerializer) */
  const ref = (x) => x[key] ?? x[key.replace(/_id$/, "")];
  const used = new Set();
  const out = readings.map((v) => {
    const r = reports.filter((x) => ref(x) != null && String(ref(x)) === String(v[key]));
    r.forEach((x) => used.add(x));
    return { id: `${key}-${v[key]}`, at: v.at, what: what(v), grade: v.grade, note: v.note,
             summaries: r.map((x) => x.summary).filter(Boolean) };
  });
  reports.filter((x) => !used.has(x)).forEach((x, i) => out.push({
    id: `r-${x.report_id ?? i}`, at: null, what: x.dept ?? "판독", grade: null, note: null,
    summaries: [x.summary].filter(Boolean),
  }));
  return out;
}

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

/* 판독 칸 — 영상과 병리가 같은 모양을 쓴다. 한 건씩 접히고, 맨 위(가장
   최근) 한 건만 펴 둔다. 머리의 등급은 가장 최근 판정이다.
   ⚠ **칸을 없애지 않는다.** 한쪽이 아직 없어도 자리를 둔다. */
function Readings({ title, gradeLabel, items, lines = [] }) {
  const [open, setOpen] = useState(() => new Set(items[0] ? [items[0].id] : []));
  const top = items.find((x) => x.grade);
  const toggle = (id) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  return (
    <section className="rev-box">
      <header className="rev-box-h">
        <h3>{title}</h3>
        <span className="home-fill" />
        {top && <Chip tone="fill">{`${gradeLabel} ${top.grade}`}</Chip>}
        {items.length > 0 ? <Chip>확정</Chip> : <span className="hcard-k">아직 없습니다</span>}
      </header>
      {lines.some(([, x]) => x) && (
        <dl className="kv">
          {lines.filter(([, x]) => x).map(([k, x]) => (
            <div key={k}><dt>{k}</dt><dd>{x}</dd></div>
          ))}
        </dl>
      )}
      <ul className="rev-list">
        {items.map((x) => {
          const on = open.has(x.id);
          return (
            <li key={x.id} className={on ? "on" : undefined}>
              <button type="button" aria-expanded={on} onClick={() => toggle(x.id)}>
                <i aria-hidden="true">{on ? "▾" : "▸"}</i>
                <time>{H.day(x.at) ?? "—"}</time>
                <b>{x.what}</b>
                {x.grade && <span>{x.grade}</span>}
              </button>
              {on && (
                <div className="rev-list-b">
                  {/* 판독의가 쓴 소견이 먼저다. 소견문은 그것을 풀어 쓴 글이다 */}
                  {x.note && <p className="rev-find">{x.note}</p>}
                  {x.summaries.map((s, i) => <p className="rev-find muted" key={i}>{s}</p>)}
                  {!x.note && x.summaries.length === 0 && <p className="hcard-k">소견이 없습니다</p>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* 화상 보기 팝업 — 화면 위에 띄운다. Esc · 바깥 누르기 · ×로 닫는다 */
function ImagePopup({ name, onClose, children }) {
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  return (
    <div className="rev-pop-back" onClick={onClose}>
      <div className="rev-pop" role="dialog" aria-label={`화상 보기 · ${name}`}
           onClick={(e) => e.stopPropagation()}>
        <header>
          <b>화상 보기 · {name}</b>
          <button type="button" onClick={onClose} aria-label="닫기">×</button>
        </header>
        <div className="rev-pop-b breast">{children}</div>
      </div>
    </div>
  );
}
