import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Chip } from "./Parts";
import { go } from "../nav";
import * as H from "../dept/home";

/* 오늘 현황판 — 칸 넷을 가로로, 환자가 왼쪽에서 오른쪽으로 흐른다
 * ════════════════════════════════════════════════════════════════
 *
 * 09-28 간호과 **접수 화면에서 홈으로 옮겼다.** 접수 화면은 찾기 · 문진 ·
 * 배정을 하는 자리이고, 「지금 누가 어디 있나」는 홈에서 한눈에 봐야
 * 한다는 말을 들었다. 같은 때 「오늘 종결」 칸을 뺐다 — 끝난 사람은 볼
 * 일이 없고 칸 하나만큼 나머지가 좁아졌다.
 *
 *   접수 대기   내원 대기 목록 중 문진이 아직 없는 사람
 *   간호 · 문진  내원 대기 목록 중 문진을 낸 사람(배정 차례)
 *   검사 진행   today-status 의 영상 쪽 stage
 *   외래 진료   today-status 의 stage_code outpatient — 간호가 이 오더를
 *               유방외과로 보냈고(handed_at) 아직 검사·종결로 안 넘어간 사람
 *
 * ⚠ 앞 둘은 today-status 가 아니라 **내원 대기 목록(waitingArrived)**을
 *   쓴다. today-status 는 둘을 「접수 대기」 하나로 뭉쳐 주고, 따로 세면
 *   접수 화면 목록과 숫자가 어긋난다. 보낸 사람은 앞 둘에서 빠지고 외래
 *   칸으로 간다.
 * ⚠ **경과 시간을 안 쓴다.** 서버가 주지 않는 값이다. 요청 시각만 적는다.
 * ⚠ **stage 는 서버가 쓰는 말 그대로** 둔다. 옮겨 부르면 서버가 단계를
 *   하나 늘렸을 때 그 줄이 어느 칸에도 안 들어간다.
 */
const EXAM_STAGE = ["영상의학과 대기", "영상의학과 촬영중", "AI 분석중"];
const CLOSED_STAGE = ["completed", "cancelled"];

/* 칸 앞에 번호를 단다 — 환자가 거치는 순서 그대로 왼쪽에서 오른쪽으로
   읽히게(09-28 「난잡하다 · 검진 순서대로」). 「도착 예정」은 부르는 쪽이
   예약(booked)을 줄 때만 선다 */
const LANES = [
  { key: "booked", title: "도착 예정" },
  { key: "checkin", title: "접수 대기" },
  { key: "nurse", title: "간호 · 문진" },
  { key: "exam", title: "검사 진행" },
  { key: "clinic", title: "외래 진료" },
];

/* 빈 칸의 말 — 칸마다 그 칸이 기다리는 것을 말한다(전부 「대기 중인 환자가
   없습니다」이면 검사 · 진료 칸에서 뜻이 어긋났다) */
const EMPTY = {
  booked: "오늘 남은 예약이 없습니다",
  checkin: "문진을 기다리는 환자가 없습니다",
  nurse: "배정을 기다리는 환자가 없습니다",
  exam: "검사 중인 환자가 없습니다",
  clinic: "진료를 기다리는 환자가 없습니다",
};

export default function StageBoard({ today = [], arrived = [], booked = null }) {
  const moved = (r) => EXAM_STAGE.includes(r.stage) || CLOSED_STAGE.includes(r.stage);
  /* 앞 두 칸은 누르면 접수 화면에서 그 오더를 골라 둔 채로 연다 — 문진 확인 ·
     배정을 거기서 한다. 뒤 두 칸은 환자 상세로 */
  const intake = (r) => `${go.nursing.intake()}?order=${r.exam_order_id ?? r.id}`;
  const patient = (r) => (r.patient_id != null ? go.patient(r.patient_id) : null);

  const cols = {
    /* 오늘 예약했고 아직 안 온 사람. 시각이 지난 사람은 칩을 달아 먼저
       눈에 띄게 — 전화할 사람이다. 누르면 접수 화면에서 찾아 둔 채로 연다 */
    booked: (booked ?? []).map((r) => {
      const late = H.isPast(r.scheduled_at);
      return {
        ...r,
        time: H.at(r.scheduled_at),
        flag: late ? "시간 지남" : null,
        stage: late ? "미내원 · 연락 필요" : `예약 ${H.at(r.scheduled_at) ?? "시간 미정"}`,
        to: `${go.nursing.intake()}?find=${encodeURIComponent(H.noOf(r) ?? H.nameOf(r))}`,
      };
    }),
    /* 보낸 사람은 서버가 이미 뺐다(waitingArrived 의 handed=none) */
    checkin: arrived.filter((r) => !r.questionnaire)
      .map((r) => ({ ...r, stage: "문진 대기", to: intake(r) })),
    nurse: arrived.filter((r) => r.questionnaire)
      .map((r) => ({ ...r, stage: "문진 완료 · 배정 대기", to: intake(r) })),
    exam: today.filter((r) => EXAM_STAGE.includes(r.stage))
      .map((r) => ({ ...r, to: patient(r) })),
    /* ⚠ 09-27 — outpatient 는 **오더의 handed_at** 으로 갈린다(서버). 예전
       처럼 주치의 유무로 보지 않아 재진 환자가 보내기 전에 여기 오지 않는다 */
    clinic: today.filter((r) => !moved(r)
      && (r.stage_code === "outpatient" || r.handed_at))
      .map((r) => ({ ...r, stage: "유방외과 진료 대기", to: patient(r) })),
  };

  const lanes = LANES.filter((l) => l.key !== "booked" || booked);

  return (
    <div className="board" style={{ "--board-cols": lanes.length }}>
      {lanes.map((col, i) => (
        <Lane key={col.key} n={i + 1} col={col} rows={cols[col.key]} />
      ))}
    </div>
  );
}

/* 칸 하나 — 줄이 칸 높이를 넘으면 칸 안에서 굴리고, **바닥에 「아래로 n명 더」를
 * 띄운다.** 09-28(최종) 칸 높이가 못 박혀 있어 1600 창에서 간호 · 문진 · 외래
 * 칸의 마지막 줄이 반쯤 잘린 채 멈춰 있었다 — 더 있다는 것이 안 보였다.
 * 누르면 한 칸만큼 내린다. 다 보이면 사라진다.
 */
function Lane({ n, col, rows }) {
  const box = useRef(null);
  const [more, setMore] = useState(0);
  const measure = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const bottom = el.scrollTop + el.clientHeight;
    /* 아래 끝이 보이는 영역 밖에 있는 줄만 센다(반쯤 걸친 줄도 「더」다) */
    const hidden = [...el.children].filter((c) => c.offsetTop + c.offsetHeight > bottom + 2).length;
    setMore(hidden);
  }, []);
  useEffect(() => {
    measure();
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure, rows.length]);

  return (
    <section className="bcol">
      <header className="bcol-h">
        <i className="bcol-n" aria-hidden="true">{n}</i>
        <b>{col.title}</b>
        <em>{rows.length}</em>
      </header>
      <div className="bcol-b" ref={box} onScroll={measure}>
        {rows.length === 0
          ? <p className="hcard-k hpad">{EMPTY[col.key]}</p>
          : rows.map((r) => <BRow key={r.exam_order_id ?? r.id ?? r.patient_id} row={r} />)}
      </div>
      {more > 0 && (
        <button type="button" className="bcol-more"
                onClick={() => box.current?.scrollBy({ top: box.current.clientHeight * 0.8, behavior: "smooth" })}>
          아래로 {more}명 더 <span aria-hidden="true">↓</span>
        </button>
      )}
    </section>
  );
}

/* 환자 줄 — 세 줄(5.2)
 *
 *   시연환자03  62 · 여  [재진] ········ 13:54
 *   P-0003   앱 접수 · 확인 필요
 *   ● 촬영  ◐ AI  ○ 판독
 *
 * ⚠ 둘째 줄이 비는 칸이 있다 — `today-status` 응답에 환자번호·나이·성별이
 *   안 온다(8장 9번).
 */
function BRow({ row }) {
  const nav = useNavigate();
  const steps = H.stageSteps(row.stage);
  const open = row.to ? {
    role: "button", tabIndex: 0,
    onClick: () => nav(row.to),
    onKeyDown: (e) => { if (e.key === "Enter") nav(row.to); },
  } : {};
  return (
    <article className="brow" {...open}>
      <div className="brow-1">
        <b>{H.nameOf(row)}</b>
        {H.who(row) && <span className="brow-who">{H.who(row)}</span>}
        {row.visit_type && <Chip>{row.visit_type}</Chip>}
        {row.flag && <Chip tone="fill">{row.flag}</Chip>}
        <span className="home-fill" />
        {(row.time ?? H.at(row.visited_at)) && <time>{row.time ?? H.at(row.visited_at)}</time>}
      </div>
      {(H.noOf(row) || row.stage) && (
        <p className="brow-2">
          {H.noOf(row) && <i>{H.noOf(row)}</i>}
          <span>{row.stage}</span>
        </p>
      )}
      {steps && <Steps steps={steps} />}
    </article>
  );
}

const DOT = { done: "●", going: "◐", none: "○" };

function Steps({ steps }) {
  return (
    <p className="brow-3">
      {steps.map(([name, state]) => (
        <span key={name} className={`pstep ${state}`}
              title={state === "unsure" ? "이 목록으로는 알 수 없습니다" : undefined}>
          <i aria-hidden="true">{DOT[state] ?? ""}</i>{name}
        </span>
      ))}
    </p>
  );
}
