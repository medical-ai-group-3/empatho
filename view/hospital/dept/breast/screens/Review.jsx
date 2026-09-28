import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { breast as api, currentAssessment } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip } from "../../../lib/Parts";
import { ArrangeBar, Panes, useArrange } from "../../../lib/Arrange";
import { MODALITY, BIRADS_LABEL, EXAM_PURPOSE, label, modality as asModality } from "../../../codes";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";
import ReviewViewer from "../components/ReviewViewer";
import ImagePopup from "../components/ImagePopup";
import ExamOrderModal from "../components/ExamOrderModal";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";
import { FlowBar } from "../components/Stepper";
import { PendingLine } from "../components/Results";
import { lesionText, pathExtras, receptors } from "../results";
import { markHandled } from "../handled";
import { flowOf } from "../flow";

/* 유방외과 · 환자 상세(옛 「검사 종합」) — 09-27 개편 · 09-28 흐름 붙임
 * ════════════════════════════════════════════════════════════════
 *
 * **영상과 병리를 나란히 놓고 한 번에 읽는 자리다.** 두 과가 각자 확정한
 * 것을 여기서 처음으로 맞대어 본다.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ 환자 · 나이/성별 · 번호 · 내원 · 의뢰 · 주치의   [엇갈림] [영상 확인] │
 *   │ ✓접수 ✓오더 ✓촬영 ✓판독 ●병리 …  다음 할 일 · 종합 리포트 [→]      │
 *   ├─────────────────────────────┬────────────────────────────────┤
 *   │ 영상 판독  BI-RADS 4a        │ 병리 결과  B5                   │
 *   │  ▾ 09-23 유방촬영 · 4a · 밀도 C│  ▾ 09-27 검체 51 · B5 · ER+ …  │
 *   ├─────────────────────────────┴────────────────────────────────┤
 *   │ 진행 중 오더 · AI 상태                                           │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │ [촬영 요청] [검체 등록]                    [리포트 · 방침으로 →] │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * ⚠ 판독은 **한 건씩 접는다.** 가장 최근 한 건만 편다.
 * ⚠ **일치·불일치를 색으로 말하지 않는다.** 글자와 soot 채움으로 가른다.
 * ⚠ 유방외과는 판독 화면 권한이 없다. 영상 · 병리 이미지를 보는 길이
 *   이 팝업뿐이라 끊으면 안 된다. 팝업은 **가장 최근 판독의 검사**로 연다 —
 *   전에는 뷰어가 촬영 시각만 보고 골라서, 판독이 없는 MRI 가 먼저 떴다.
 * ⚠ AI 악성 확률(malignancy_p)은 **안 싣는다** — 서버도 일부러 안 준다.
 *   병변 줄의 AI 값은 크기와 등급(birads_model)뿐이다.
 *
 * 진료 이력에서 들어오면(?study= · ?specimen=, dept/breast/history.js)
 * 그 건을 펴서 그 자리로 내려간다. 판독 줄에서 오면 ?assessment= 도 붙는다.
 * 그 판이 지금 판독이 아니면 영상 칸 위에 따로 보여 준다 — Version.
 */
export default function Review() {
  const { id } = useParams();
  const [q] = useSearchParams();
  const p = useApi(() => api.patient(id), [id]);
  /* 고른 한 건. 판독 줄 id(rows() 의 `${key}-${번호}`)와 같은 모양으로 둔다 */
  const focus = q.get("study") != null
    ? { key: "study_id", id: q.get("study"), assessment: q.get("assessment") }
    : q.get("specimen") != null ? { key: "specimen_id", id: q.get("specimen") }
    : null;
  /* 영상 · 병리 · 진행 중 오더 세 칸은 「배치 편집」으로 옮긴다(lib/Arrange.jsx).
     머리 띠 · 흐름 · 바닥 단추 줄은 못 박는다 */
  const lay = useArrange("breast.review", REV_BASE);

  return (
    <Page className="rev-page" crumb={["유방외과", "환자 상세"]}
          title="환자 상세" patient={p.data}
          right={(
            <>
              {p.data && <ArrangeBar lay={lay} />}
              {/* 제목이 「환자 상세」라 공용 환자 페이지는 그 중심인 히스토리 이름으로 */}
              <Btn to={go.patient(id)}>환자 기록</Btn>
              <Btn to={go.breast.waiting()}>대기 환자</Btn>
            </>
          )}>
      <Body loading={p.loading && !p.data} error={p.error} onRetry={p.reload}>
        {p.data && <Inner key={p.data.patient_id} pid={id} p={p.data} focus={focus} lay={lay}
                             onReload={() => p.reload(true)} />}
      </Body>
    </Page>
  );
}

/* 기본 — 영상 | 병리 나란히, 그 밑에 폭을 다 쓰는 진행 중 오더 줄(null) */
const REV_BASE = [["rad"], ["path"], ["run"]];
const REV_COLS = ["minmax(0, 1fr)", "minmax(0, 1fr)", null];

function Inner({ pid, p, focus, lay, onReload }) {
  const nav = useNavigate();
  const [seeing, setSeeing] = useState(false);
  const [modal, setModal] = useState(null);
  const [examModality, setExamModality] = useState(null);
  const line = useApi(() => H.soft(api.timeline(pid)), [pid]);
  const rx = useApi(() => api.prescriptions(pid).catch(() => undefined), [pid]);
  const flow = useMemo(() => flowOf({ p, timeline: H.rows(line.data), rx: rx.data }),
    [p, line.data, rx.data]);

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
    (r) => label(MODALITY, asModality(r.modality)) || "영상",
    (r) => [r.density ? `밀도 ${r.density}` : null].filter(Boolean));
  const specimenName = (r) => r.label ?? `검체 ${r.specimen_id}`;
  /* B 분류는 서버가 b2 로 준다 — 읽는 글자는 B2 */
  const patRows = rows(pat.map((r) => ({ ...r, grade: r.grade && String(r.grade).toUpperCase() })),
    of("병리"), "specimen_id", specimenName,
    (r) => [...pathExtras(r), ...receptors(r)]);
  /* 영상 칸의 「병변」 줄처럼 병리 칸 머리에 검체 ID 를 모아 둔다 */
  const specimenLine = pat.map((r) => (r.label ? `${r.label} (#${r.specimen_id})` : `#${r.specimen_id}`))
    .join(", ") || null;

  /* 이력에서 고른 건이 판독 줄에 없을 수 있다 — 찍기만 했거나 판독이 아직
     임시저장이거나(서버 timeline 은 draft 도 「판독」으로 준다), 검체를
     떼기만 하고 확진 전인 것. 그때는 없다고 적는다. 말없이 맨 위 건을
     펴 두면 「고른 게 이것」으로 읽힌다 */
  const want = focus ? `${focus.key}-${focus.id}` : null;
  /* 팝업이 열 검사 — 이력에서 고른 것, 없으면 가장 최근 판독의 검사 */
  const studyAt = focus?.key === "study_id" ? focus.id : (rad[0]?.study_id ?? null);
  const miss = (items, what) => (want && focus.key === what && !items.some((x) => x.id === want));
  const radMiss = miss(radRows, "study_id") && (
    <div className="rev-miss">
      <p className="hcard-k">선택한 검사(#{focus.id})는 아직 확정된 판독이 없습니다.</p>
      <Btn onClick={() => setSeeing(true)}>이 검사 영상 보기</Btn>
    </div>
  );
  /* 판 하나를 골라 왔으면 그 판을 먼저 본다. 지금 판이면 Version 이
     radMiss 로 물러난다 — 판독 줄에 그대로 있다 */
  const radTop = focus?.assessment
    ? <Version pid={pid} studyId={focus.id} assessmentId={focus.assessment}
               fallback={radMiss} onSee={() => setSeeing(true)} />
    : radMiss;
  const patMiss = miss(patRows, "specimen_id") && (
    <div className="rev-miss">
      <p className="hcard-k">선택한 검체(#{focus.id})는 아직 병리 확진 전입니다.</p>
    </div>
  );

  function run(n) {
    if (n?.act === "exam") { setExamModality(n.modality); setModal("exam"); }
    else if (n?.act === "specimen") setModal("specimen");
    else if (n?.to) nav(n.to);
    else if (n?.act) nav(go.breast.waiting());   /* 진료 완료 · 재진은 대기 환자에서 */
  }
  const sent = () => { markHandled(p.patient_id); setModal(null); onReload(); line.reload(true); };
  const key = flow.next?.key;
  const toDecision = ["report", "decision", "explain", "prescription"].includes(key) ? key : null;

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
            ["나이 · 성별", H.who(p)],
            ["환자번호", H.noOf(p)],
            ["내원", p.visit_type],
            /* 서버 코드(screening · diagnostic)를 그대로 찍던 자리 */
            ["의뢰", label(EXAM_PURPOSE, p.visit_purpose) || null],
            ["주치의", p.primary_staff_name],
            /* 값 없는 칸(내원 · 의뢰가 비는 재진)은 「—」로 자리를 먹지 않게 뺀다 */
          ].filter(([, v]) => v != null && v !== "").map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
        {/* 일치 여부 — 서버가 불일치를 걸었는지로만 말한다. BI-RADS 와 B
            분류를 여기서 견주지 않는다 — 규칙이 서버와 두 곳이 된다 */}
        <div className={`rev-odd${odd ? " k1" : ""}`}>
          <i aria-hidden="true">{odd ? "⚠" : "✓"}</i>
          <span>
            <b>{odd ? "영상과 병리 판정이 엇갈립니다" : "판정 불일치가 없습니다"}</b>
            {odd && <em>{odd.violated_rule}</em>}
          </span>
          {odd && <Btn to={go.breast.discordance(odd.discordance_id)}>처분하기</Btn>}
        </div>
        <Btn onClick={() => setSeeing(true)}>영상 확인</Btn>
      </section>

      <FlowBar flow={flow} run={run} />

      <div className="rev">
        <Panes lay={lay} className="rev-cols" paneClass="rev-pane" cols={REV_COLS}
               cards={{
                 /* key — 다른 건을 고르고 오면 접힘 상태를 새로 잡는다.
                    판(assessment)도 key 에 넣는다 — 지난 판에서 「현재 판독 보기」로
                    오면 같은 검사라도 새로 펴고 그 줄로 내려가야 한다 */
                 rad: (
                   <Readings key={`${want ?? "top"}-${focus?.assessment ?? ""}`} title="영상 판독" gradeLabel="BI-RADS" items={radRows}
                             focus={want} miss={radTop}
                             lines={[["병변", lesionLine(p.lesions)]]} />
                 ),
                 path: (
                   <Readings key={want ?? "top"} title="병리 결과" gradeLabel="" items={patRows}
                             focus={want} miss={patMiss}
                             lines={[["검체", specimenLine]]} />
                 ),
                 run: <Running p={p} events={H.rows(line.data)} />,
               }} />
        <footer className="bf-rev-f">
          <Btn kind={key === "exam" && flow.next.act === "exam" ? "fill" : "line"}
               onClick={() => run({ act: "exam", modality: flow.next?.modality })}>촬영 요청</Btn>
          <Btn kind={key === "exam" && flow.next.act === "specimen" ? "fill" : "line"}
               onClick={() => setModal("specimen")}>검체 등록</Btn>
          <span className="home-fill" />
          <span className="hcard-k">
            {toDecision ? `다음 할 일 · ${flow.next.label}` : "결과 확인을 마쳤다면"}
          </span>
          <Btn kind={toDecision ? "fill" : "line"} to={go.breast.decision(pid, toDecision)}>
            리포트 · 치료 방침으로 →
          </Btn>
        </footer>
      </div>

      {seeing && (
        <ImagePopup name={H.nameOf(p)} onClose={() => setSeeing(false)}>
          {/* 이력에서 검사를 골라 왔으면 그 검사로, 아니면 가장 최근 판독의 검사로 연다 */}
          <ReviewViewer patientId={p.patient_id} lesions={p.lesions ?? []}
                        specimenIds={specimenIds} studyId={studyAt} />
        </ImagePopup>
      )}

      {/* 팝업만 .breast 안에 — Waiting.jsx 와 같은 이유 */}
      {modal && (
        <div className="breast">
          {modal === "exam" && (
            <ExamOrderModal patient={p} initialModality={examModality}
                            onClose={() => setModal(null)} onDone={sent} />
          )}
          {modal === "specimen" && (
            <SpecimenBindingModal patient={p} onClose={() => setModal(null)} onDone={sent} />
          )}
        </div>
      )}
    </div>
  );
}

/* 둘째 줄 — 진행 중 오더 · AI 상태.
 * 결과가 **아직 안 온 것**을 모은다. 판독 칸은 확정된 것만 싣기 때문에,
 * 여기가 없으면 「요청해 둔 초음파가 어디 갔나」를 물을 자리가 없다.
 * AI 상태는 진료 이력의 「촬영」 · 「AI 분석 완료」 줄을 검사마다 맞춘다 —
 * 서버가 따로 주는 칸이 없다 */
function Running({ p, events }) {
  const shots = events.filter((e) => e.type === "촬영" && e.study_id != null);
  const aiDone = new Set(events.filter((e) => e.type === "AI 분석 완료")
    .map((e) => String(e.study_id ?? e.specimen_id)));
  const read = new Set((p.readings?.radiology ?? []).map((r) => String(r.study_id)));
  const confirmed = new Set([
    ...(p.readings?.pathology ?? []).map((r) => String(r.specimen_id)),
    ...events.filter((e) => e.type === "병리 확진").map((e) => String(e.specimen_id)),
  ]);
  const taken = events.filter((e) => e.type === "검체 채취" && !confirmed.has(String(e.specimen_id)));

  return (
    <section className="rev-box bf-run">
      <header className="rev-box-h">
        <h3>진행 중 오더 · AI 상태</h3>
      </header>
      <div className="bf-run-b">
        <div>
          <span className="bf-run-k">오더</span>
          <PendingLine orders={p.orders}
                       empty={taken.length ? null : <p className="hcard-k">결과를 기다리는 오더가 없습니다</p>} />
          {taken.length > 0 && (
            <p className="bf-pend">
              {taken.map((e) => (
                <Chip key={e.specimen_id} tone="dot">
                  검체 {e.detail ?? `#${e.specimen_id}`} · 병리 확진 대기
                </Chip>
              ))}
            </p>
          )}
        </div>
        <div>
          <span className="bf-run-k">AI</span>
          {shots.length === 0
            ? <p className="hcard-k">촬영 기록이 없습니다</p>
            : (
              <p className="bf-pend">
                {shots.map((e) => (
                  <Chip key={e.study_id} tone={aiDone.has(String(e.study_id)) ? "line" : "dot"}>
                    {label(MODALITY, asModality(e.modality ?? e.detail)) || "영상"} {H.day(e.at)}
                    {" · "}{aiDone.has(String(e.study_id)) ? "AI 완료" : "AI 분석 중"}
                    {read.has(String(e.study_id)) ? " · 판독 확정" : " · 판독 전"}
                  </Chip>
                ))}
              </p>
            )}
        </div>
      </div>
    </section>
  );
}

/* 판정과 소견문을 한 줄로 묶는다. 판정(v)이 본체이고, 같은 검사 · 검체의
   소견문(r)을 그 아래에 붙인다. 판정이 아직 없는 소견문도 버리지 않는다.
   extra — 줄 아래 칩(밀도 · 조직형 · 수용체) */
function rows(readings, reports, key, what, extra = () => []) {
  /* 리포트 응답은 FK 를 study · specimen 으로 준다(ModelSerializer) */
  const ref = (x) => x[key] ?? x[key.replace(/_id$/, "")];
  const used = new Set();
  const out = readings.map((v) => {
    const r = reports.filter((x) => ref(x) != null && String(ref(x)) === String(v[key]));
    r.forEach((x) => used.add(x));
    return { id: `${key}-${v[key]}`, at: v.at, what: what(v), grade: v.grade, note: v.note,
             extra: extra(v), summaries: r.map((x) => x.summary).filter(Boolean) };
  });
  reports.filter((x) => !used.has(x)).forEach((x, i) => out.push({
    id: `r-${x.report_id ?? i}`, at: null, what: x.dept ?? "판독", grade: null, note: null,
    extra: [], summaries: [x.summary].filter(Boolean),
  }));
  return out;
}

/* 판독의가 오탐으로 뺀 병변(is_false_positive)은 안 싣는다.
   p.lesions 는 환자 전체라 여러 검사 것이 섞인다 — 모달리티가 둘 이상이면
   어느 검사에서 나온 병변인지 앞에 붙인다. 글자는 Results.jsx lesionText */
function lesionLine(lesions) {
  const list = (Array.isArray(lesions) ? lesions : [lesions])
    .filter((l) => l && !l.is_false_positive);
  const mods = new Set(list.map((l) => asModality(l.modality)).filter(Boolean));
  return list.map((l) => lesionText(l, mods.size > 1)).filter(Boolean).join(", ") || null;
}

/* 판독 칸 — 영상과 병리가 같은 모양을 쓴다. 한 건씩 접히고, 맨 위(가장
   최근) 한 건만 펴 둔다. 머리의 등급은 가장 최근 판정이다.
   이력에서 고른 건(focus)이 있으면 그것도 펴고 그 줄로 내려간다.
   ⚠ **칸을 없애지 않는다.** 한쪽이 아직 없어도 자리를 둔다. */
function Readings({ title, gradeLabel, items, lines = [], focus = null, miss = null }) {
  const [open, setOpen] = useState(() => new Set(
    [items[0]?.id, items.some((x) => x.id === focus) ? focus : null].filter(Boolean)));
  const here = useRef(null);
  useEffect(() => {
    here.current?.scrollIntoView({ block: "center" });
  }, [focus]);
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
        {top && <Chip tone="fill">{gradeLabel ? `${gradeLabel} ${top.grade}` : top.grade}</Chip>}
        {items.length > 0 ? <Chip>확정 {items.length}건</Chip> : <span className="hcard-k">아직 없습니다</span>}
      </header>
      {lines.some(([, x]) => x) && (
        <dl className="kv">
          {lines.filter(([, x]) => x).map(([k, x]) => (
            <div key={k}><dt>{k}</dt><dd>{x}</dd></div>
          ))}
        </dl>
      )}
      {miss}
      <ul className="rev-list">
        {items.map((x) => {
          const on = open.has(x.id);
          const at = x.id === focus;
          return (
            <li key={x.id} ref={at ? here : undefined}
                className={[on && "on", at && "here"].filter(Boolean).join(" ") || undefined}
                aria-current={at || undefined}>
              <button type="button" aria-expanded={on} onClick={() => toggle(x.id)}>
                <i aria-hidden="true">{on ? "▾" : "▸"}</i>
                <time>{H.day(x.at) ?? "—"}</time>
                <b>{x.what}</b>
                {x.grade && <span>{x.grade}</span>}
              </button>
              {on && (
                <div className="rev-list-b">
                  {x.extra?.length > 0 && (
                    <span className="bf-rcp">{x.extra.map((c) => <Chip key={c}>{c}</Chip>)}</span>
                  )}
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

/* 이력에서 고른 판독 한 판.
 *
 * ⚠ 판독 줄은 검사마다 **지금 유효한 확정 한 판**뿐이다(api.js 의 readings).
 *   정정으로 덮인 판이나 초안을 골라 왔는데 지금 판을 펴 두면 「고른 게
 *   이것」으로 읽힌다 — 고른 판을 따로, 무엇인지 적어서 보여 준다.
 * ⚠ 판 목록은 ?assessment= 가 있을 때만 부른다. 검사마다 부르면 환자
 *   상세 한 번에 검사 수만큼 더 나간다.
 * 판독의 이름은 못 적는다 — 응답의 assessed_by 가 직원 번호뿐이다. */
function Version({ pid, studyId, assessmentId, fallback, onSee }) {
  const list = useApi(() => api.assessments(studyId), [studyId]);
  const here = useRef(null);
  const rows = list.data ?? [];
  const a = rows.find((x) => String(x.assessment_id) === String(assessmentId)) ?? null;
  const now = currentAssessment(rows);
  const same = a != null && now != null && String(now.assessment_id) === String(a.assessment_id);
  const show = a != null && !same;
  useEffect(() => {
    if (show) here.current?.scrollIntoView({ block: "center" });
  }, [show]);

  if (list.loading || list.error || !a) {
    return (
      <div className="rev-miss">
        <p className="hcard-k">
          {list.loading ? `선택한 판독(#${assessmentId})을 불러오는 중입니다.`
            : list.error ? "선택한 판독을 불러오지 못했습니다."
            : `선택한 판독(#${assessmentId})을 이 검사에서 찾지 못했습니다.`}
        </p>
        {list.error && <Btn onClick={list.reload}>다시 시도</Btn>}
      </div>
    );
  }
  if (same) return fallback;

  const what = a.read_stage === "draft" ? "임시저장"
    : a.superseded_by != null ? "이전 판독 · 대체됨" : "이전 판독";
  return (
    <div className="rev-miss rev-ver" ref={here} aria-current="true">
      <div className="rev-ver-h">
        <Chip tone={a.read_stage === "draft" ? "fill" : "line"}>{what}</Chip>
        <b>{a.category ? `BI-RADS ${label(BIRADS_LABEL, a.category)}` : "등급 없음"}</b>
        <time>{a.finalized_at ? String(a.finalized_at).replace("T", " ").slice(0, 16) : "확정 전"}</time>
      </div>
      <dl className="kv">
        {[
          ["권고", a.recommendation],
          ["대체한 판독", a.superseded_by != null ? `#${a.superseded_by}` : null],
          ["판독 번호", `#${a.assessment_id}`],
        ].filter(([, v]) => v).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {a.finding_note
        ? <p className="rev-find">{a.finding_note}</p>
        : <p className="hcard-k">소견이 없습니다</p>}
      <div className="rev-ver-f">
        <p className="hcard-k">
          {a.read_stage === "draft"
            ? "판독의가 아직 확정하지 않은 값입니다."
            : "지금 유효한 판독이 아닙니다."}
          {!now && " 이 검사는 아직 확정된 판독이 없습니다."}
        </p>
        {now
          ? <Btn to={go.breast.review(pid, { study: studyId })}>현재 판독 보기</Btn>
          : <Btn onClick={onSee}>이 검사 영상 보기</Btn>}
      </div>
    </div>
  );
}
