import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Page, Card, Btn } from "../lib/Page";
import { Body, Empty } from "../lib/Body";
import { Chip, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { reception, breast, nursing, specimens } from "../api";
import { go } from "../nav";
import { can } from "../perm";
import * as H from "../dept/home";
import { historyDetail, historyTo, toDecision } from "../dept/breast/history";

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
 * **타임라인 줄을 누르면 그것이 열린다.** 서버가 줄마다 study_id ·
 *   specimen_id 를 같이 주기로 해서(2026-09-23) 무엇의 몇 번인지 안다.
 *   영상은 판독 화면으로, 검체는 병리 판독 화면으로 간다. 그 권한이 없는
 *   유방외과는 제 과의 환자 상세로 간다(dept/breast/history.js).
 *   ⚠ 번호가 없거나 그 화면을 볼 권한이 없으면 **누르는 자리로 만들지
 *     않는다.** 눌리는 것처럼 보이고 아무 일도 안 일어나는 쪽이 더 나쁘다.
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
              <History pid={id} events={data.timeline} />
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

  /* ⚠ 전에는 AI 사건과 촬영을 **«같은 날»로** 맞췄다. 그런데 서버가
     performed_at 을 아무도 안 채우고 있어서 비교의 한쪽이 늘 빈 글자였고 —
     AI 점이 어떤 환자에게도 영원히 「알 수 없음」이었다. 이제 촬영 시작이
     그 시각을 찍는다(서버 0022 로 옛 행도 백필).
     분석이 자정을 넘겨 끝나는 것도 있어서 «같은 날»이 아니라 «촬영 뒤»로 본다 */
  const shotAt = last.performed_at ? String(last.performed_at) : null;
  const aiDone = shotAt
    ? timeline.some((e) => e.type === "AI 분석 완료" && String(e.at) >= shotAt)
    : false;
  const read = last.read_status === "finalized" ? "done"
    : last.read_status === "draft" ? "going" : "none";

  /* 영상이 올라왔는가 — 서버가 목록 행에 image_count 를 실어 준다.
   *
   * ⚠ **performed_at 으로는 못 본다.** 그 칸은 «촬영 시작»에 찍히므로
   *   파일이 한 장도 없는 검사도 값을 갖는다 — 그걸로 보면 아무것도 안
   *   올라온 검사가 「촬영 완료」로 읽히고, 업로드로 가는 길이 사라진다.
   * ⚠ 옛 서버는 image_count 를 안 준다. 그때만 performed_at 으로 대신 본다 */
  const shot = last.image_count != null
    ? last.image_count > 0
    : Boolean(last.performed_at);

  const steps = [
    ["촬영", shot ? "done" : "going"],
    ["AI", aiDone ? "done" : "unsure"],
    ["판독", read],
  ];

  /* ── 다음 단계로 가는 길 ───────────────────────────────────
   *
   * **이 화면은 막다른 길이었다**(09-23 확인). 다섯 과의 홈이 줄을 누르면
   * 전부 여기로 보내는데, 여기서 나가는 링크가 한 개도 없었다 — 판독을
   * 이어 하려면 메뉴로 나갔다 과 목록을 거쳐 다시 들어와야 했다.
   *
   * 갈 곳은 이 화면이 이미 손에 쥐고 있었다. 검사 번호도 진행 상태도
   * 위에서 점을 찍느라 다 읽고 있다 — 글자로만 찍고 링크를 안 걸었다.
   *
   * ⚠ **권한이 없으면 안 띄운다.** 간호과 사람에게 판독 단추를 보여 주고
   *   눌러야 Locked 를 만나게 하면, 눌러 보고 나서야 아는 꼴이다. */
  const studyId = last.study_id ?? last.id ?? null;
  const next = [];
  if (studyId != null) {
    if (!shot && can("radiology.upload.view")) {
      next.push(["업로드", go.radiology.upload(studyId)]);
    } else if (shot && can("radiology.read.view")) {
      next.push(["판독 화면", go.radiology.read(studyId)]);
    }
  }

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
      {next.length > 0 && (
        <div className="stack top" style={{ justifyContent: "flex-end" }}>
          {next.map(([label, to]) => (
            <Btn key={label} kind="line" to={to}>{label}</Btn>
          ))}
        </div>
      )}
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
  "치료 결정": "결", "리포트": "리", "결과 설명": "설", "처방": "처",
};

/* 줄 하나가 어디로 가나. 갈 곳이 없으면 null 을 돌려주고, 부르는 쪽이
   그냥 글자로 그린다 — 못 여는 것을 눌리게 만들지 않는다.
   ⚠ 유방외과는 판독 화면 둘 다 권한이 없어서 이 히스토리가 **한 줄도 안
     눌렸다**(09-28 사용자 지적). 제 과의 환자 상세가 같은 결과(확정 판독 ·
     병리)를 다 들고 있으니 그리로 보낸다 — 그 건을 펴서 연다 */
function eventTo(e, may, pid) {
  /* ⚠ 치료 결정은 study_id 를 싣는다 — 번호보다 먼저 본다. 영상 · 병리
     사람에게는 서버가 이 줄들을 안 주지만, 와도 판독 화면으로 새지 않게 */
  if (toDecision(e)) return may.decision ? historyTo(pid, e) : null;
  if (e.specimen_id != null && may.pathology) return go.pathology.read(e.specimen_id);
  if (e.study_id != null && may.radiology) return go.radiology.read(e.study_id);
  if (may.breast) return historyTo(pid, e);
  return null;
}

function History({ pid, events }) {
  const [only, setOnly] = useState(null);
  /* 권한은 화면마다 다르다 — 유방외과는 판독 화면을 못 연다.
     못 여는 사람에게는 누르는 자리로 안 보이게 한다. */
  const may = {
    radiology: useCan("radiology.read.view").ok,
    pathology: useCan("pathology.read.view").ok,
    breast: useCan("breast.review.view").ok,
    decision: useCan("breast.decision.view").ok,
  };

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
            {list.map((e, i) => {
              const to = eventTo(e, may, pid);
              const say = historyDetail(e);
              const body = (
                <>
                  <i className="pevent-m" aria-hidden="true">{MARK[e.type] ?? "·"}</i>
                  <time>{H.at(e.at)}</time>
                  <b>{e.type}</b>
                  {say && <span>{say}</span>}
                  {to && <span className="pevent-go" aria-hidden="true">›</span>}
                </>
              );
              return to
                ? <Link className="pevent on" key={`${day}-${i}`} to={to}>{body}</Link>
                : <p className="pevent" key={`${day}-${i}`}>{body}</p>;
            })}
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
