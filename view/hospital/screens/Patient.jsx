import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Page, Card } from "../lib/Page";
import { Body, Empty } from "../lib/Body";
import { Chip } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { reception, breast, nursing, specimens } from "../api";
import * as H from "../dept/home";

/* 환자 상세 — 모든 과가 같은 화면을 본다 (6.5)
 * ════════════════════════════════════════════════════════════════
 *
 * 과 바깥 주소다(`/hospital/patients/:id`). 어디서 와도 같은 화면이라
 * 과별 설정(cfg)을 안 받는다 — 받으면 과마다 다른 것이 생긴다.
 *
 *   왼쪽    이번 방문의 진행 · 병변 크기 변화 · 문진
 *   가운데  전체 히스토리 — GET /patients/{id}/timeline 하나로
 *   오른쪽  이전 담당의 소견 · 리포트 · 추적 일정 · 동의
 *
 * ⚠ **4.4 의 「왼쪽 레일」과 다르다.** 4.4 표는 이 화면의 왼쪽을 전체
 *   히스토리로 적었지만 6.5 는 가운데로 적었다. 화면별 절인 6.5 를 따른다 —
 *   히스토리가 이 화면의 본체라 가장 넓은 가운데가 맞다.
 *
 * ⚠ **타임라인 줄을 누를 수 없다.** 서버가 이벤트마다 `{at, type, detail}`
 *   만 주고 무엇의 몇 번인지를 안 준다(판독만 assessment_id 가 있다).
 *   눌러도 무엇을 열지 알 수 없어서 누르는 자리로 만들지 않았다 —
 *   눌리는 것처럼 보이고 아무 일도 안 일어나는 쪽이 더 나쁘다(8장 11번).
 */
export default function Patient() {
  const { id } = useParams();

  const { loading, error, data, reload } = useApi(() => Promise.all([
    reception.detail(id),
    H.soft(breast.timeline(id)),
    H.soft(breast.studies(id)),
    H.soft(specimens.lesionsByPatient(id)),
    H.soft(nursing.followups()),
  ]).then(([p, timeline, studies, lesions, follow]) => ({
    p,
    timeline: H.rows(timeline),
    studies: H.rows(studies),
    lesions: H.rows(lesions),
    /* 추적은 환자로 거르는 조건이 없다 — 전부 받아 여기서 고른다.
       쪽 나눔이 없는 응답이라(뷰가 배열을 그대로 준다) 조용히 빠지지 않는다 */
    follow: H.rows(follow).filter((f) => String(f.patient) === String(id)),
  })), [id]);

  const p = data?.p;
  const pii = p?.pii ?? {};

  return (
    <Page crumb={["환자"]} title={pii.name ?? p?.patient_number ?? "환자"}
          patient={p}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <div className="pcols">
            <div className="pcol">
              <Visit studies={data.studies} timeline={data.timeline} />
              <Lesions lesions={data.lesions} studies={data.studies} />
              <Survey patient={p} />
            </div>

            <div className="pcol">
              <History events={data.timeline} />
            </div>

            <div className="pcol">
              <Opinions />
              <Report />
              <Followups items={data.follow} />
              <Consent />
            </div>
          </div>
        )}
      </Body>
    </Page>
  );
}

/* ── 왼쪽 위 — 이번 방문이 어디까지 왔나 ──────────────────────
 * 가장 최근 검사 하나를 본다. 「이번 방문」을 서버가 따로 묶어 주지 않아
 * 마지막 검사가 곧 지금이다.
 *
 * ⚠ AI 는 검사 목록에 없다. 타임라인에 「AI 분석 완료」 이벤트가 오면 그걸
 *   쓰고, 없으면 **점을 비운다** — ○ 는 「아직 안 했다」는 말이라 확인한
 *   사람만 할 수 있다.
 */
const DOT = { done: "●", going: "◐", none: "○" };

function Visit({ studies, timeline }) {
  const last = studies[0] ?? null;
  if (!last) {
    return (
      <Card title="이번 방문">
        <Empty title="검사 기록이 없습니다" />
      </Card>
    );
  }

  const aiDone = timeline.some((e) => e.type === "AI 분석 완료"
    && String(e.at).slice(0, 10) === String(last.performed_at ?? "").slice(0, 10));
  const read = last.read_status === "finalized" ? "done"
    : last.read_status === "draft" ? "going" : "none";

  const steps = [
    ["촬영", last.performed_at ? "done" : "going"],
    ["AI", aiDone ? "done" : "unsure"],
    ["판독", read],
  ];

  return (
    <Card title="이번 방문" right={<span className="src">{H.at(last.performed_at)}</span>}>
      <p className="pvisit-h">
        {last.modality && <Chip tone="fill">{last.modality}</Chip>}
        <span>{String(last.performed_at ?? "").slice(0, 10)}</span>
      </p>
      <p className="psteps">
        {steps.map(([name, state]) => (
          <span key={name} className={`pstep ${state}`}
                title={state === "unsure" ? "이 목록으로는 알 수 없습니다" : undefined}>
            <i aria-hidden="true">{DOT[state] ?? ""}</i>{name}
          </span>
        ))}
      </p>
    </Card>
  );
}

/* ── 왼쪽 가운데 — 병변 크기 변화 ─────────────────────────────
 * 같은 이름(label)의 병변을 검사 날짜순으로 이어 놓는다. 「8mm → 12mm」가
 * 눈에 보여야 한다는 것이 4.4 의 요구다.
 *
 * ⚠ 판독의가 잰 값(measured_size_mm)을 먼저 쓴다. 없으면 AI 값(ai_size_mm).
 *   초음파는 mm 로 못 바꿔서 px 만 오는데(pixel_spacing 이 없다) **단위가
 *   다른 값을 한 표에 섞지 않는다** — px 는 px 라고 적는다.
 */
function Lesions({ lesions, studies }) {
  const rows = useMemo(() => {
    const dateOf = new Map(studies.map((s) => [String(s.study_id ?? s.id), s.performed_at]));
    const live = lesions.filter((l) => !l.is_false_positive);
    const by = new Map();
    for (const l of live) {
      /* 이름이 없으면 자리(site)로 부른다 — 「병변 L-3001」보다 「좌측
         상외측」이 사람이 읽는 말이다 */
      const key = l.label || l.site || `병변 ${l.lesion_index ?? l.lesion_id}`;
      const mm = l.measured_size_mm ?? l.ai_size_mm ?? l.size_mm;
      const px = l.measured_size_px ?? l.ai_size_px;
      const list = by.get(key) ?? [];
      list.push({
        id: l.lesion_id,
        at: dateOf.get(String(l.study)) ?? null,
        size: mm != null ? `${mm}mm` : px != null ? `${px}px` : null,
      });
      by.set(key, list);
    }
    return [...by].map(([label, list]) => ({
      label,
      list: list.sort((a, b) => String(a.at).localeCompare(String(b.at))),
    }));
  }, [lesions, studies]);

  return (
    <Card title="병변 크기 변화">
      {rows.length === 0
        ? <Empty title="기록된 병변이 없습니다" />
        : rows.map((r) => (
          <div className="plesion" key={r.label}>
            <b>{r.label}</b>
            <span className="plesion-run">
              {r.list.map((it, i) => (
                <span key={it.id}>
                  {i > 0 && <i aria-hidden="true">→</i>}
                  <time>{String(it.at ?? "").slice(0, 10) || "날짜 없음"}</time>
                  <em>{it.size ?? "크기 없음"}</em>
                </span>
              ))}
            </span>
          </div>
        ))}
    </Card>
  );
}

/* ── 왼쪽 아래 — 문진 ─────────────────────────────────────────
 * ⚠ **문항 이름이 없다.** questionnaire 는 `{form_version, answers:{코드: 값}}`
 *   인데 코드를 사람 말로 바꾸는 표(8장 3번의 questionnaire/v1.yaml)가 아직
 *   없다. 코드를 그대로 적는다 — 없는 이름을 지어내지 않는다.
 */
function Survey({ patient }) {
  const q = patient?.questionnaire;
  const answers = q?.answers && typeof q.answers === "object" ? q.answers : null;
  const keys = answers ? Object.keys(answers) : [];

  return (
    <Card title="문진"
          right={q?.form_version && <span className="src">{q.form_version}</span>}>
      {keys.length === 0
        ? <Empty title="받은 문진이 없습니다" />
        : (
          <dl className="kv">
            {keys.map((k) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{String(answers[k])}</dd>
              </div>
            ))}
          </dl>
        )}
    </Card>
  );
}

/* ── 가운데 — 전체 히스토리 ───────────────────────────────────
 * 날짜별로 묶고 종류로 거른다. 기호는 글자 한 자다(4.4) — 색을 안 쓴다.
 */
const MARK = {
  "촬영": "촬", "AI 분석 완료": "AI", "판독": "판",
  "검체 채취": "검", "병리 확진": "병",
};

function History({ events }) {
  const [only, setOnly] = useState(null);

  const kinds = useMemo(
    () => [...new Set(events.map((e) => e.type))], [events]);

  const days = useMemo(() => {
    const keep = only ? events.filter((e) => e.type === only) : events;
    const by = new Map();
    /* 서버가 오래된 것부터 준다. 화면은 최신순이 기본이다(4.4) */
    for (const e of [...keep].reverse()) {
      const day = String(e.at ?? "").slice(0, 10);
      const list = by.get(day) ?? [];
      list.push(e);
      by.set(day, list);
    }
    return [...by];
  }, [events, only]);

  return (
    <Card title="전체 히스토리" className="phistory"
          right={(
            <span className="sorts">
              <button type="button" className={`pill${only ? "" : " on"}`}
                      onClick={() => setOnly(null)}>전체</button>
              {kinds.map((k) => (
                <button type="button" key={k}
                        className={`pill${only === k ? " on" : ""}`}
                        onClick={() => setOnly(k)}>{k}</button>
              ))}
            </span>
          )}>
      {days.length === 0
        ? <Empty title="남은 기록이 없습니다" />
        : days.map(([day, list]) => (
          <section className="pday" key={day}>
            <h3>{day || "날짜 없음"}</h3>
            {list.map((e, i) => (
              <p className="pevent" key={`${day}-${i}`}>
                <i className="pevent-m" aria-hidden="true">{MARK[e.type] ?? "·"}</i>
                <time>{H.at(e.at)}</time>
                <b>{e.type}</b>
                {e.detail && <span>{e.detail}</span>}
              </p>
            ))}
          </section>
        ))}
    </Card>
  );
}

/* ── 오른쪽 — 서버가 아직 안 주는 칸 셋 ───────────────────────
 * 칸을 없애지 않는다. 없애면 배치가 달라지고, 나중에 값이 생겼을 때
 * 자리를 다시 찾아야 한다. 무엇이 없어서 비었는지만 적는다.
 */
function Opinions() {
  return (
    <Card title="이전 담당의 소견">
      {/* ⚠ timeline 의 판독 이벤트가 주는 detail 은 **판정 등급**(4B)이지
          소견 문장이 아니다. 누가 썼는지도 안 온다. 6.5 가 이 화면의
          핵심이라고 한 칸인데 지금은 채울 값이 없다 */}
      <Empty title="아직 없습니다" />
    </Card>
  );
}

function Report() {
  return (
    <Card title="리포트">
      {/* ⚠ 서버에 GET /reports?patient= 가 있는데 api.js 에 경로가 없다.
          새 경로는 8장에 적고 여기서 더하지 않는다 */}
      <Empty title="아직 없습니다" />
    </Card>
  );
}

function Consent() {
  return (
    <Card title="동의">
      {/* ⚠ 동의는 서버에 표도 경로도 없다 */}
      <Empty title="아직 없습니다" />
    </Card>
  );
}

function Followups({ items }) {
  return (
    <Card title="추적 일정" right={items.length > 0 && <span className="src">{items.length}회차</span>}>
      {items.length === 0
        ? <Empty title="잡힌 추적이 없습니다" />
        : (
          <ul className="pfollow">
            {items.map((f) => (
              <li key={f.followup_id ?? `c-${f.patient}`}>
                <span>
                  {f.round_no}회차
                  {f.due_at && ` · ${String(f.due_at).slice(0, 10)}`}
                  {f.call_result && ` · ${f.call_result}`}
                </span>
              </li>
            ))}
          </ul>
        )}
    </Card>
  );
}
