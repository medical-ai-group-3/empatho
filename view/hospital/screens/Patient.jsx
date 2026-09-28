import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Page, Card, Btn } from "../lib/Page";
import { Body, Empty } from "../lib/Body";
import { Chip, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import SpecimenBindingModal from "../lib/SpecimenBindingModal";
import { reception, breast, nursing, specimens } from "../api";
import { DESK, go, homeDept } from "../nav";
import {
  AUDIENCE, EXAM_PURPOSE, MODALITY, ORDER_STATUS, REPORT_DEPT, REPORT_TYPE,
  label, modality as modalityCode,
} from "../codes";
import * as H from "../dept/home";
import { historyDetail, historyTo, toDecision } from "../dept/breast/history";

/* 환자 상세 — 모든 과가 같은 화면을 본다 (6.5)
 * ════════════════════════════════════════════════════════════════
 *
 * 과 바깥 주소다(`/hospital/patients/:id`). 어디서 와도 같은 화면이라
 * 과별 설정(cfg)을 안 받는다 — 받으면 과마다 다른 것이 생긴다.
 * 과마다 다른 것은 **머리의 단추 줄** 하나다(Actions) — 권한으로 고른다.
 *
 *   머리    간호 [접수][예약 잡기][추적 콜][검체 바인딩] · 유방외과
 *           [검사 종합][치료 방침] · 영상 · 병리 [판독 화면]
 *   왼쪽    오늘 방문(today-status) + 최근 검사 · 병변 크기 변화 · 문진
 *   가운데  전체 히스토리 — GET /patients/{id}/timeline 하나로
 *   오른쪽  최근 확정 판독 · 리포트 · 추적 일정 · 예약·방문 이력
 *
 * ⚠ **영상 뷰어는 두지 않는다**(09-23 결정). 영상 티켓(tile)을 간호과가
 *   못 받아 빈 뷰어 · 403 이 된다 — 영상은 유방외과 화면에서 본다.
 * ⚠ 「동의」 칸은 뺐다(09-28). 직원에게는 동의를 읽는 권한도 경로도 없어
 *   영영 빈 칸이었다. 「이전 담당의 소견」도 채울 값(소견 문장 · 쓴 사람)이
 *   안 와서 「최근 확정 판독」(타임라인의 판정)으로 바꿨다.
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
  const [binding, setBinding] = useState(false);
  /* ⚠ 유방외과는 리포트 목록을 **부르지 않는다.** 서버가 유방외과의
     GET /reports?patient= 를 「유방외과 열람」으로 남긴다(views/surgery.py
     list → viewed.mark) — 이 화면을 스쳐 가기만 해도 영상 · 병리 목록에
     「열람」이 찍힌다. 유방외과에게는 타임라인의 리포트 줄만 보이고 읽는
     것은 [검사 종합]에서 한다(ReportCard) */
  const surgery = homeDept()?.key === "breast";

  const { loading, error, data, reload } = useApi(() => Promise.all([
    reception.detail(id),
    H.soft(breast.timeline(id)),
    H.soft(breast.studies(id)),
    H.soft(specimens.lesionsByPatient(id)),
    H.soft(nursing.followupsOf(id)),
    H.soft(reception.ordersOf(id)),
    H.soft(reception.todayStatus()),
    surgery ? null : H.soft(breast.reports(id)),
  ]).then(([p, timeline, studies, lesions, follow, orders, today, reports]) => ({
    p,
    timeline: H.rows(timeline),
    /* 번호 없는 줄(목업의 「병리」 가짜 검사)은 검사가 아니다 — 최근 검사로 안 뜨게 */
    studies: newestFirst(H.rows(studies).filter((s) => (s.study_id ?? s.id) != null)),
    lesions: H.rows(lesions),
    /* ⚠ ?patient= 를 모르는 서버는 전체를 준다 — 여기서 한 번 더 거른다.
       전에는 `f.patient` 만 봤는데 목업 · 후보 줄은 patient_id 로 와서
       한 줄도 안 남거나, 둘 다 없는 줄이 「undefined」끼리 맞았다 */
    follow: H.rows(follow).filter((f) => same(f.patient ?? f.patient_id, id)),
    orders: H.rows(orders).filter((o) => o.patient == null || same(o.patient, id)),
    /* today-status 는 오늘 온 사람 전부다 — 이 사람 줄만. 여러 건이면 마지막 */
    today: H.rows(today).filter((r) => same(r.patient_id ?? r.patient, id)).at(-1) ?? null,
    reports: reports == null ? null : H.rows(reports),
  })), [id]);

  const p = data?.p;
  const pii = p?.pii ?? {};

  return (
    <Page crumb={["환자"]} title={pii.name ?? p?.patient_number ?? "환자"}
          patient={p}
          right={data && <Actions pid={id} data={data} onBind={() => setBinding(true)} />}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <div className="pcols">
            <div className="pcol">
              <Visit today={data.today} studies={data.studies} timeline={data.timeline} />
              <Lesions lesions={data.lesions} studies={data.studies} />
              <Survey patient={p} />
            </div>

            <div className="pcol">
              <History pid={id} events={data.timeline} />
            </div>

            <div className="pcol">
              <Readings pid={id} events={data.timeline} />
              <ReportCard pid={id} reports={data.reports} events={data.timeline} />
              <Followups pid={id} items={data.follow} />
              <Orders items={data.orders} />
            </div>
          </div>
        )}
      </Body>
      {binding && p && (
        <SpecimenBindingModal patient={p} onClose={() => setBinding(false)}
                              onDone={() => { setBinding(false); reload(); }} />
      )}
    </Page>
  );
}

/* 번호 비교 — 숫자 · 글자로 섞여 온다. 없는 쪽은 안 맞는 것으로 본다
   (「undefined」 === 「undefined」 로 남의 줄이 붙지 않게) */
function same(a, b) {
  return a != null && b != null && String(a) === String(b);
}

/* 검사 목록을 최신순으로. 서버는 -performed_at(빈 것은 뒤)로 주지만
   옛 서버 · 목업은 오래된 것부터라 studies[0] 이 첫 검사가 됐다 */
function newestFirst(list) {
  const out = [...list].sort((a, b) => {
    const x = a.performed_at ? String(a.performed_at) : "";
    const y = b.performed_at ? String(b.performed_at) : "";
    if (x !== y) return !x ? 1 : !y ? -1 : y.localeCompare(x);
    return Number(b.study_id ?? b.id ?? 0) - Number(a.study_id ?? a.id ?? 0);
  });
  Object.defineProperty(out, "total", { value: list.total ?? out.length });
  return out;
}

/* 마지막 검체 — 타임라인의 검체 채취 · 병리 확진 줄이 번호를 싣는다 */
function lastSpecimen(events) {
  const hit = [...events].reverse().find((e) => e.specimen_id != null);
  return hit?.specimen_id ?? null;
}

/* 영상이 올라왔는가 — 서버가 목록 행에 image_count 를 실어 준다.
 * ⚠ **performed_at 으로는 못 본다.** 그 칸은 «촬영 시작»에 찍히므로
 *   파일이 한 장도 없는 검사도 값을 갖는다 — 그걸로 보면 아무것도 안
 *   올라온 검사가 「촬영 완료」로 읽히고, 업로드로 가는 길이 사라진다.
 * ⚠ 옛 서버는 image_count 를 안 준다. 그때만 performed_at 으로 대신 본다 */
function isShot(study) {
  return study.image_count != null ? study.image_count > 0 : Boolean(study.performed_at);
}

/* ── 머리 — 과별 단추 줄 ──────────────────────────────────────
 *
 * **이 화면은 막다른 길이었다**(09-23 확인). 다섯 과의 홈이 줄을 누르면
 * 전부 여기로 보내는데, 여기서 나가는 링크가 거의 없었다.
 *
 * ⚠ **권한이 없으면 안 띄운다.** 눌러야 Locked 를 만나는 단추는 눌러 보고
 *   나서야 아는 꼴이다. 열쇠는 가는 화면의 need(nav.js)와 같게 건다 —
 *   간호 화면은 DESK(원무 · 간호 어느 열쇠든).
 * ⚠ 오른쪽 위(머리)에 둔다. 오른쪽 아래는 목업 띠 · 메모가 뜨는 자리다 */
function Actions({ pid, data, onBind }) {
  const desk = useCan(DESK).ok;
  const bind = useCan("specimen.bind").ok;
  const review = useCan("breast.review.view").ok;
  const decide = useCan("breast.decision.view").ok;
  const radRead = useCan("radiology.read.view").ok;
  const radUp = useCan("radiology.upload.view").ok;
  const pathRead = useCan("pathology.read.view").ok;

  const acts = [];
  if (desk) {
    /* 접수 화면은 ?find= 로 그 사람을 찾아 둔 채 연다 — 접수는 사람이 누른다 */
    const find = H.noOf(data.p ?? {}) ?? data.p?.pii?.name;
    acts.push(["접수", `${go.nursing.intake()}${find ? `?find=${encodeURIComponent(find)}` : ""}`]);
    acts.push(["예약 잡기", go.nursing.reservations(pid)]);
    acts.push(["추적 콜", go.nursing.followups(pid)]);
  }
  if (review) acts.push(["검사 종합", go.breast.review(pid)]);
  if (decide) acts.push(["치료 방침", go.breast.decision(pid)]);

  /* 영상 — 최근 검사. 아직 안 올라왔으면 업로드, 올라왔으면 판독 */
  const last = data.studies.find((s) => (s.study_id ?? s.id) != null);
  const studyId = last ? (last.study_id ?? last.id) : null;
  if (studyId != null) {
    if (!isShot(last) && radUp) acts.push(["업로드", go.radiology.upload(studyId)]);
    else if (isShot(last) && radRead) acts.push(["판독 화면", go.radiology.read(studyId)]);
  }
  /* 병리 — 최근 검체 */
  const spec = lastSpecimen(data.timeline);
  if (spec != null && pathRead) acts.push(["판독 화면", go.pathology.read(spec)]);

  if (acts.length === 0 && !bind) return null;
  return (
    <div className="stack">
      {acts.map(([name, to], i) => (
        <Btn key={`${name}-${i}`} kind={i === 0 ? "fill" : "line"} to={to}>{name}</Btn>
      ))}
      {bind && <Btn kind="line" type="button" onClick={onBind}>검체 바인딩</Btn>}
    </div>
  );
}

/* ── 왼쪽 위 — 오늘 방문 ──────────────────────────────────────
 * 오늘 접수한 방문이 지금 어느 단계인가 — GET /patients/today-status 의
 * 이 사람 줄(stage). 그 아래에 최근 검사 하나의 진행 점.
 *
 * ⚠ 전에는 「이번 방문」을 **최근 검사**로 대신했다. 오늘 오지 않은
 *   사람도 몇 달 전 검사가 「이번 방문」으로 떴다. 오늘 방문은 today-status
 *   만 말할 수 있다 — 줄이 없으면 「오늘 접수 없음」이다.
 * ⚠ AI 는 검사 목록에 없다. 타임라인에 「AI 분석 완료」 이벤트가 오면 그걸
 *   쓰고, 없으면 **점을 비운다** — ○ 는 「아직 안 했다」는 말이라 확인한
 *   사람만 할 수 있다.
 */
const DOT = { done: "●", going: "◐", none: "○" };

function Visit({ today, studies, timeline }) {
  const last = studies[0] ?? null;
  const stage = today ? (today.stage_detail || today.stage) : null;
  const todaySteps = today ? H.stageSteps(today.stage) : null;

  return (
    <Card title="오늘 방문"
          right={today?.visited_at && <span className="src">{H.at(today.visited_at)} 접수</span>}>
      {today ? (
        <>
          <p className="pvisit-h">
            <Chip tone="fill">{stage}</Chip>
            {today.primary_staff_name && <span>주치의 {today.primary_staff_name}</span>}
          </p>
          {todaySteps && <Steps steps={todaySteps} />}
        </>
      ) : (
        <p className="pvisit-h"><span>오늘 접수한 방문이 없습니다</span></p>
      )}

      <p className="pvisit-sub">최근 검사</p>
      {last
        ? <LastStudy last={last} timeline={timeline} />
        : <p className="pvisit-h"><span>검사 기록이 없습니다</span></p>}
    </Card>
  );
}

function Steps({ steps }) {
  return (
    <p className="psteps">
      {steps.map(([name, state]) => (
        <span key={name} className={`pstep ${state}`}
              title={state === "unsure" ? "이 목록으로는 알 수 없습니다" : undefined}>
          <i aria-hidden="true">{DOT[state] ?? ""}</i>{name}
        </span>
      ))}
    </p>
  );
}

function LastStudy({ last, timeline }) {
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
  const mod = label(MODALITY, modalityCode(last.modality));

  return (
    <>
      <p className="pvisit-h">
        {mod && <Chip tone="line">{mod}</Chip>}
        <span>{String(last.performed_at ?? "").slice(0, 10) || "촬영 전"}</span>
      </p>
      <Steps steps={[
        ["촬영", isShot(last) ? "done" : "going"],
        ["AI", aiDone ? "done" : "unsure"],
        ["판독", read],
      ]} />
    </>
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

/* 권한은 화면마다 다르다 — 유방외과는 판독 화면을 못 연다.
   못 여는 사람에게는 누르는 자리로 안 보이게 한다. */
function useMay() {
  return {
    radiology: useCan("radiology.read.view").ok,
    pathology: useCan("pathology.read.view").ok,
    breast: useCan("breast.review.view").ok,
    decision: useCan("breast.decision.view").ok,
  };
}

/* 이력 한 줄 — 히스토리 · 최근 확정 판독 · 리포트(유방외과)가 같이 쓴다.
   withDay — 날짜로 안 묶는 칸이라 시각 대신 날짜(09-12)를 적는다 */
function EventRow({ e, to, withDay = false }) {
  const say = historyDetail(e);
  const body = (
    <>
      <i className="pevent-m" aria-hidden="true">{MARK[e.type] ?? "·"}</i>
      <time>{withDay ? H.day(e.at) : H.at(e.at)}</time>
      <b>{e.type}</b>
      {say && <span>{say}</span>}
      {to && <span className="pevent-go" aria-hidden="true">›</span>}
    </>
  );
  return to
    ? <Link className="pevent on" to={to}>{body}</Link>
    : <p className="pevent">{body}</p>;
}

function History({ pid, events }) {
  const [only, setOnly] = useState(null);
  const may = useMay();

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
              <EventRow key={`${day}-${i}`} e={e} to={eventTo(e, may, pid)} />
            ))}
          </section>
        ))}
    </Card>
  );
}

/* ── 오른쪽 위 — 최근 확정 판독 ─────────────────────────────
 * 타임라인의 확정 판독(영상 BI-RADS) · 병리 확진 줄을 최신순으로 넷.
 * ⚠ **쓴 사람은 안 적는다.** 판독 줄에는 assessed_by 번호뿐이라 이름을
 *   모른다 — 예전 「이전 담당의 소견」 칸이 영영 비었던 이유다.
 * ⚠ 초안(read_stage=draft)은 뺀다. 아직 남에게 보일 값이 아니다 */
function Readings({ pid, events }) {
  const may = useMay();
  const list = useMemo(() => [...events]
    .filter((e) => (e.type === "판독" && e.read_stage !== "draft") || e.type === "병리 확진")
    .reverse()
    .slice(0, 4), [events]);

  return (
    <Card title="최근 확정 판독">
      {list.length === 0
        ? <Empty title="확정된 판독이 없습니다" />
        : list.map((e, i) => <EventRow key={i} e={e} to={eventTo(e, may, pid)} withDay />)}
    </Card>
  );
}

/* ── 리포트 ───────────────────────────────────────────────────
 * GET /reports?patient= — 검사별 판독문(stage)과 종합 리포트(final).
 * ⚠ 유방외과는 reports 가 null 로 온다(부르지 않았다 — 위 Patient 참고).
 *   타임라인의 리포트 줄로 목록만 보이고, 여는 것은 [검사 종합]이다 */
function ReportCard({ pid, reports, events }) {
  if (reports == null) {
    const list = events.filter((e) => e.type === "리포트").reverse();
    return (
      <Card title="리포트" right={list.length > 0 && <span className="src">{list.length}건</span>}>
        {list.length === 0
          ? <Empty title="발급된 리포트가 없습니다" />
          : list.slice(0, 4).map((e, i) => <EventRow key={i} e={e} withDay />)}
        <div className="stack top">
          <Btn kind="line" to={go.breast.review(pid)}>검사 종합에서 보기</Btn>
        </div>
      </Card>
    );
  }

  const list = [...reports].sort((a, b) =>
    String(reportAt(b) ?? "").localeCompare(String(reportAt(a) ?? "")));
  const SHOW = 6;
  return (
    <Card title="리포트" right={list.length > 0 && <span className="src">{list.length}건</span>}>
      {list.length === 0
        ? <Empty title="발급된 리포트가 없습니다" />
        : (
          <ul className="pfollow">
            {list.slice(0, SHOW).map((r, i) => (
              <li key={r.report_id ?? i} className="prow">
                <span>{String(reportAt(r) ?? "").slice(0, 10) || "날짜 없음"} · {reportName(r)}</span>
                {locked(r) && <Chip tone="line">잠김</Chip>}
              </li>
            ))}
            {list.length > SHOW && <li className="src">외 {list.length - SHOW}건</li>}
          </ul>
        )}
    </Card>
  );
}

const reportAt = (r) => r.issued_at ?? r.finalized_at ?? r.created_at ?? null;
const locked = (r) => r.lock_status === "locked" || r.locked === true;
/* 판독문 이름 — Report 에는 title 이 없다. 종합은 종류 · 대상, 검사별은
   낸 소켓(REPORT_DEPT)으로 부른다 */
function reportName(r) {
  const type = r.report_type ?? r.type;
  if (type === "final") {
    return [label(REPORT_TYPE, type), label(AUDIENCE, r.audience)].filter(Boolean).join(" · ");
  }
  return REPORT_DEPT[String(r.socket_id)] || label(REPORT_TYPE, type) || "리포트";
}

/* ── 추적 일정 ────────────────────────────────────────────────
 * GET /followups/?patient= . 후보(회차 없음)는 「추적 후보」로 적는다 */
function Followups({ pid, items }) {
  const desk = useCan(DESK).ok;
  const rounds = items.filter((f) => f.status !== "candidate");
  return (
    <Card title="추적 일정"
          right={rounds.length > 0 && <span className="src">{rounds.length}회차</span>}>
      {items.length === 0
        ? <Empty title="잡힌 추적이 없습니다" />
        : (
          <ul className="pfollow">
            {items.map((f, i) => (
              <li key={f.followup_id ?? f.id ?? i}>
                <span>
                  {f.status === "candidate" ? "추적 후보 · 회차 없음" : `${f.round_no ?? "?"}회차`}
                  {f.due_at && ` · ${String(f.due_at).slice(0, 10)}`}
                  {f.call_result && ` · ${f.call_result}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      {desk && items.length > 0 && (
        <div className="stack top">
          <Btn kind="line" to={go.nursing.followups(pid)}>추적 관리에서 보기</Btn>
        </div>
      )}
    </Card>
  );
}

/* ── 예약 · 방문 이력 ─────────────────────────────────────────
 * GET /exam-orders?patient= — 예약한 날 · 온 날. 「안 옴」은 예약 날이
 * 지났는데 내원(visited_at)이 없고 취소도 아닌 것이다.
 * ⚠ 서버가 안 옴을 따로 안 준다 — 두 값(예약일 · 내원)을 견줄 뿐이다 */
function noShow(o) {
  if (o.visited_at || o.order_status === "cancelled" || !o.scheduled_at) return false;
  return String(o.scheduled_at).slice(0, 10) < H.iso(new Date());
}

function Orders({ items }) {
  const list = [...items].sort((a, b) =>
    String(b.scheduled_at ?? b.ordered_at ?? "").localeCompare(String(a.scheduled_at ?? a.ordered_at ?? "")));
  const miss = list.filter(noShow).length;
  const SHOW = 6;
  return (
    <Card title="예약 · 방문 이력"
          right={list.length > 0 && (
            <span className="src">{list.length}건{miss > 0 && ` · 안 옴 ${miss}`}</span>
          )}>
      {list.length === 0
        ? <Empty title="예약 기록이 없습니다" />
        : (
          <ul className="pfollow">
            {list.slice(0, SHOW).map((o, i) => {
              const what = label(MODALITY, modalityCode(o.modality))
                || label(EXAM_PURPOSE, o.exam_purpose) || "검사 미정";
              const state = o.visited_at ? `내원 ${H.at(o.visited_at)}` : label(ORDER_STATUS, o.order_status);
              return (
                <li key={o.exam_order_id ?? i} className="prow">
                  <span>
                    {String(o.scheduled_at ?? o.ordered_at ?? "").slice(0, 10) || "날짜 없음"}
                    {` · ${what}`}{state && ` · ${state}`}
                  </span>
                  {noShow(o) && <Chip tone="line">안 옴</Chip>}
                </li>
              );
            })}
            {list.length > SHOW && <li className="src">외 {list.length - SHOW}건</li>}
          </ul>
        )}
    </Card>
  );
}
