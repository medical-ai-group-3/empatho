import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, useCan } from "../../../lib/Parts";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";
import ExamOrderModal from "../components/ExamOrderModal";
import CloseVisitModal from "../components/CloseVisitModal";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";

/* 유방외과 · 내 환자 — `docs/mockup/Surgery.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **이 과의 본진이다.** 집는 절차가 없다 — 주치의로 배정된 환자가 곧
 * 큐다. 그래서 고르고 · 읽고 · 정하는 것이 한 화면에서 끝난다.
 *
 *   ┌ 300px ──┬ 1fr ───────────────────┬ 330px ──┬ 248px ─┐
 *   │ 내 환자  │ 김민지  47 · 여          │ 진료 이력│ 상용구 │
 *   │ [탭]     │ ⚠ 판정 불일치 · 처분하기 │  09-21  │        │
 *   │  · 김민지│ ┌영상 판독─┬병리 판독─┐  │  09-11  │ 수술   │
 *   │  · 이서준│ └──────────┴──────────┘  │  09-09  │ 추가…  │
 *   │          │ 치료 방침 결정            │         │        │
 *   │          │ [촬영][검체][종결] [저장] │         │        │
 *   └──────────┴──────────────────────────┴─────────┴────────┘
 *
 * ⚠ **경과 시간을 안 쓴다.** 목업 줄 끝의 `1h52m` `27′` 은 서버가 주지
 *   않는다. 환자 목록 응답에는 시각 자체가 없다.
 * ⚠ **칸을 카드로 띄우지 않는다.** 네 단을 1px 선으로 가른다(4.5).
 * ⚠ **색으로 뜻을 나르지 않는다.** 목업은 BI-RADS 를 빨강·노랑·초록으로
 *   칠하지만 우리는 글자로 적는다. 판독 등급은 색 여섯 단계가 아니라
 *   읽어야 하는 값이다.
 */
export default function Waiting() {
  const list = useApi(() => api.waiting(), []);
  const [tab, setTab] = useState("all");
  const [pick, setPick] = useState(null);
  const [modal, setModal] = useState(null);

  const rows = H.rows(list.data);
  const odd = useMemo(() => rows.filter((r) => r.has_open_discordance), [rows]);
  const shown = tab === "odd" ? odd : rows;
  const picked = shown.some((r) => r.patient_id === pick)
    ? pick : (shown[0]?.patient_id ?? null);

  const detail = useApi(
    () => (picked ? api.patient(picked) : Promise.resolve(null)), [picked]);

  function next() {
    const i = shown.findIndex((r) => r.patient_id === picked);
    if (i >= 0 && shown.length > 0) setPick(shown[(i + 1) % shown.length].patient_id);
  }

  return (
    <Page className="surgery-page" crumb={["유방외과", "내 환자"]}
          title="내 환자"
          right={<Btn to={go.breast.patients()}>환자 목록</Btn>}>
      <div className="sgy">
        <Queue state={list} rows={shown} all={rows} odd={odd}
               tab={tab} onTab={setTab} pick={picked} onPick={setPick} />

        <div className="sgy-mid">
          {!picked
            ? <Empty title="배정된 환자가 없습니다" />
            : (
              <Body loading={detail.loading && !detail.data} error={detail.error}
                    onRetry={detail.reload}>
                {detail.data && (
                  <Mid p={detail.data} onNext={next} onOpen={setModal}
                       onDone={() => { detail.reload(true); list.reload(true); }} />
                )}
              </Body>
            )}
        </div>

        <History id={picked} />
        <Phrases />
      </div>

      {/* ⚠ **팝업만 .breast 안에 넣는다.** breast.css 는 --ink · --line-2 ·
          --gap 을 제 값으로 덮어쓴다(그 파일 머리에 적혀 있다). 쪽 전체를
          .breast 로 열면 새로 짠 이 화면이 hospital 토큰 대신 저쪽 팔레트를
          조용히 집어 간다 — 팝업 셋은 아직 저 규칙으로 그려져서 그것만 싼다 */}
      {modal && detail.data && (
        <div className="breast">
          {modal === "exam" && (
            <ExamOrderModal patient={detail.data} onClose={() => setModal(null)}
                            onDone={() => { setModal(null); detail.reload(true); }} />
          )}
          {modal === "specimen" && (
            <SpecimenBindingModal patient={detail.data} onClose={() => setModal(null)}
                                  onDone={() => { setModal(null); detail.reload(true); }} />
          )}
          {modal === "close" && (
            <CloseVisitModal patient={detail.data} onClose={() => setModal(null)}
                             onDone={() => { setModal(null); next(); list.reload(true); }} />
          )}
        </div>
      )}
    </Page>
  );
}

/* ── 왼쪽 300px — 내 환자 ──────────────────────────────────────
 * 목업의 탭은 「대기 / 결정 대기 / 불일치」 셋인데 둘만 만들었다.
 *
 * ⚠ **「대기」와 「결정 대기」를 가를 수가 없다.** 서버는 `?primary_staff=me`
 *   를 보면 status 를 **안 보고 바로 돌려준다** —
 *
 *       PatientViewSet.get_queryset()
 *           if primary_staff_param == "me":
 *               return qs.filter(primary_staff=staff)   ← 여기서 끝
 *
 *   그래서 `waiting()` 과 `patients()` 가 **같은 줄**을 준다. 탭 둘을
 *   만들어 놓고 같은 목록을 보여 주면 거짓말이라 하나로 합쳤다.
 *   「결정 대기」는 영상·병리가 다 끝났는지 알아야 하는데 그건 환자마다
 *   workflow 를 따로 불러야 나온다 — 목록 한 장에 못 담는다(8장 10번).
 *
 * ⚠ **`patients()` 가 아니라 `waiting()` 을 부른다.** 둘이 같은 줄을
 *   주는데 `has_open_discordance` 는 `status=waiting` 쪽에만 붙어 온다.
 *   `patients()` 로 받으면 불일치 탭이 **말없이 늘 0** 이 된다.
 */
const TABS = [
  { key: "all", label: "내 환자" },
  { key: "odd", label: "불일치" },
];

function Queue({ state, rows, all, odd, tab, onTab, pick, onPick }) {
  const count = { all: all.total ?? all.length, odd: odd.length };
  return (
    <aside className="sgy-q">
      <header className="sgy-q-h">
        <h2>내 환자</h2>
        <div className="sgy-tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab"
                    aria-selected={t.key === tab}
                    className={`sgy-tab${t.key === tab ? " on" : ""}`}
                    onClick={() => onTab(t.key)}>
              {t.label} <i>{count[t.key]}</i>
            </button>
          ))}
        </div>
      </header>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}
            empty={rows.length === 0
              && <Empty title={tab === "odd" ? "엇갈린 건이 없습니다" : "배정된 환자가 없습니다"} />}>
        <div className="sgy-q-b">
          {rows.map((r) => (
            <button type="button" key={r.patient_id}
                    className={`sgy-row${r.patient_id === pick ? " on" : ""}`}
                    onClick={() => onPick(r.patient_id)}>
              <span className="sgy-row-1">
                <i className={`sgy-dot${r.has_open_discordance ? " k1" : ""}`}
                   aria-hidden="true" />
                <b>{H.nameOf(r)}</b>
                {H.who(r) && <span>{H.who(r)}</span>}
              </span>
              <span className="sgy-row-2">
                {H.noOf(r) && <i>{H.noOf(r)}</i>}
                <span>{r.has_open_discordance ? "판정 불일치" : (r.status ?? "")}</span>
              </span>
            </button>
          ))}
        </div>
      </Body>
    </aside>
  );
}

/* ── 가운데 — 고른 환자 ───────────────────────────────────────── */
function Mid({ p, onNext, onOpen, onDone }) {
  const d = p.open_discordance;
  const rep = p.other_reports ?? [];
  const pick = (want) => rep.find((r) => (r.dept ?? "").includes(want)) ?? null;

  return (
    <>
      <header className="sgy-head">
        <span className="sgy-ava" aria-hidden="true">{H.nameOf(p)[0]}</span>
        <span className="sgy-who">
          <span className="sgy-1">
            <b>{H.nameOf(p)}</b>
            {H.who(p) && <span>{H.who(p)}</span>}
          </span>
          <span className="sgy-2">
            {[H.noOf(p), p.visit_type].filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="home-fill" />
        {H.some(p.family_history) && <Chip>가족력 {H.some(p.family_history)}</Chip>}
        {H.some(p.allergy) && <span className="pb-warn"><i aria-hidden="true">⚠</i>{H.some(p.allergy)}</span>}
      </header>

      {/* ⚠ 되돌릴 수 없는 갈림길이라 맨 위에 둔다 — 영상과 병리가 엇갈린
          채로 치료 방침을 정하면 안 된다 */}
      {d && (
        <Link to={go.breast.discordance(d.discordance_id)} className="sgy-odd">
          <i aria-hidden="true">⚠</i>
          <span><b>판정 불일치</b> · {d.violated_rule}</span>
          <span className="home-fill" />
          <b>처분하기 →</b>
        </Link>
      )}

      <div className="sgy-reads">
        <Read title="영상 판독" r={pick("영상")} to={go.breast.review(p.patient_id)} />
        <Read title="병리 판독" r={pick("병리")} to={go.breast.review(p.patient_id)} />
      </div>

      <Decide p={p} onDone={onDone} />

      <div className="sgy-foot">
        <Btn onClick={() => onOpen("exam")}>촬영 요청</Btn>
        <Btn onClick={() => onOpen("specimen")}>검체 등록</Btn>
        <Btn onClick={() => onOpen("close")}>이상 없음 · 종결</Btn>
        <span className="home-fill" />
        <Btn onClick={onNext}>다음 환자 →</Btn>
        <Btn kind="fill" to={go.breast.review(p.patient_id)}>검사 종합</Btn>
      </div>
    </>
  );
}

/* 영상·병리 한 칸씩.
   ⚠ **칸을 없애지 않는다.** 한쪽이 아직 없어도 자리를 둔다 — 없어진
     칸을 보면 「이 환자는 병리를 안 했다」가 아니라 「화면이 깨졌다」로
     읽힌다 */
function Read({ title, r, to }) {
  return (
    <section className="sgy-read">
      <header>
        <h3>{title}</h3>
        <span className="home-fill" />
        {H.day(r?.at) && <time>{H.day(r.at)}</time>}
      </header>
      {!r
        ? <p className="hcard-k">아직 없습니다</p>
        : (
          <>
            <p className="sgy-read-b">{r.summary}</p>
            <footer>
              <span className="hcard-k">{r.author}</span>
              <span className="home-fill" />
              <Btn to={to}>자세히</Btn>
            </footer>
          </>
        )}
    </section>
  );
}

/* ── 치료 방침 결정 ────────────────────────────────────────────
 * ⚠ **되돌릴 수 없다.** 결정은 지워지지 않고 새 결정으로만 덮는다.
 * ⚠ **어느 판독에 붙일지는 진료 이력이 안다.** `PATCH /assessments/{id}/
 *   decision` 이 assessment 하나를 집어야 하는데, 환자 응답에는 그 번호가
 *   없다. `/patients/{id}/timeline` 의 「판독」 줄이 `assessment_id` 를
 *   달고 온다 — 가장 최근 것에 붙인다.
 */
const KINDS = ["수술", "조직검사", "추가 영상", "재조직검사"];
const VALUES = ["예", "아니오", "보류"];

function Decide({ p, onDone }) {
  const line = useApi(() => H.soft(api.timeline(p.patient_id)), [p.patient_id]);
  const aid = H.rows(line.data)
    .filter((r) => r.assessment_id).at(-1)?.assessment_id ?? null;

  const [kind, setKind] = useState(KINDS[0]);
  const [value, setValue] = useState(VALUES[0]);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const may = useCan("breast.decision.save");

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api.decide(aid, { decision_type: kind, decision: value, reason: why });
      setMsg("남겼습니다");
      onDone?.();
    } catch (e) { setMsg(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="sgy-dec">
      <header>
        <h3>치료 방침 결정</h3>
        <span className="home-fill" />
        {msg && <span className="hcard-k">{msg}</span>}
      </header>

      <div className="sgy-seg" role="radiogroup" aria-label="결정 종류">
        {KINDS.map((k) => (
          <button type="button" key={k} role="radio" aria-checked={k === kind}
                  className={`sgy-opt${k === kind ? " on" : ""}`}
                  onClick={() => setKind(k)}>{k}</button>
        ))}
      </div>

      <div className="sgy-dec-b">
        <div className="sgy-seg narrow" role="radiogroup" aria-label="결정">
          {VALUES.map((v) => (
            <button type="button" key={v} role="radio" aria-checked={v === value}
                    className={`sgy-opt${v === value ? " on" : ""}`}
                    onClick={() => setValue(v)}>{v}</button>
          ))}
        </div>
        <textarea value={why} onChange={(e) => setWhy(e.target.value)}
                  rows={2} placeholder="결정 사유" aria-label="결정 사유"
                  disabled={!may.ok} />
      </div>

      <div className="rowb">
        {/* ⚠ 붙일 판독이 없으면 저장할 데가 없다. 왜 못 누르는지 적는다 */}
        {!aid && <span className="hcard-k">확정된 판독이 있어야 결정을 답니다</span>}
        <Btn kind="fill" onClick={save} {...may.attrs}
             disabled={busy || !aid || !may.ok}>
          {busy ? "남기는 중…" : "결정 저장"}
        </Btn>
      </div>
    </section>
  );
}

/* ── 330px — 진료 이력 ─────────────────────────────────────────
   `/patients/{id}/timeline` 이 이 칸의 전부다. 최근 것이 위로 온다 */
function History({ id }) {
  const line = useApi(
    () => (id ? H.soft(api.timeline(id)) : Promise.resolve([])), [id]);
  const rows = [...H.rows(line.data)].reverse();

  return (
    <section className="sgy-hist">
      <header className="bcol-h">
        <i className="hdot ring" aria-hidden="true" />
        <b>진료 이력</b>
        <em>{rows.length}</em>
      </header>
      <div className="sgy-hist-b">
        {rows.length === 0
          ? <p className="hcard-k hpad">아직 없습니다</p>
          : rows.map((r, i) => (
            <article className="sgy-ev" key={`${r.at}-${i}`}>
              <div className="sgy-ev-h">
                <time>{H.day(r.at)}</time>
                <Chip>{r.type}</Chip>
              </div>
              {r.detail && <p>{r.detail}</p>}
            </article>
          ))}
      </div>
    </section>
  );
}

/* ── 248px — 결정 사유 상용구 ──────────────────────────────────
 * ⚠ **서버가 주는 값이 아니다.** 상용구를 저장하는 경로가 없다 — 화면에
 *   박아 둔 글이고, 누르면 사유 칸에 **붙는 게 아니라** 글자를 고르는
 *   수고를 던다. 사람마다 다르게 쓰고 싶으면 서버에 자리가 있어야 한다
 *   (8장). 목업의 세 묶음을 그대로 옮겼다.
 */
const PHRASES = [
  ["수술", ["단일 병변, 유방보존술 가능", "다발성 병변으로 전절제 고려"]],
  ["추가 검사", ["병변 범위 평가 위해 MRI 시행", "표적 미포함 의심, 재조직검사"]],
  ["보류 · 추적", ["환자 상의 후 재내원", "6개월 추적 관찰"]],
];

function Phrases() {
  return (
    <section className="sgy-say">
      <header className="bcol-h">
        <i className="hdot ring" aria-hidden="true" />
        <b>결정 사유 상용구</b>
      </header>
      <div className="sgy-say-b">
        {PHRASES.map(([group, items]) => (
          <div className="sgy-grp" key={group}>
            <span className="sgy-grp-k">{group}</span>
            {items.map((it) => (
              <p className="sgy-p" key={it}>{it}</p>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
