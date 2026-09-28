import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Calendar from "../lib/Calendar";
import Coach from "../lib/Coach";
import Tilly from "../lib/Tilly";
import { COACH_HOME } from "../lib/seen";
import { Body } from "../lib/Screen";
import Icon from "../lib/Icon";
import { fmtDay, fmtWhen, WDS } from "../lib/when";
import { deptSuffix } from "../lib/dept";
import { MODALITY, modality as asModality, text } from "../lib/codes";

/* 03 · 홈
 *
 * 위에서부터 **문진 → 새 안내문 → 달력** 이다. 순서가 곧 우선순위다.
 *   · 문진은 검사 전에 반드시 받아야 하는 것이라 맨 위다.
 *   · 안내문은 «새 것이 있을 때만» 나온다. 없으면 자리도 없다.
 *   · 달력은 보기만 한다. 예약은 예약 화면에서 한다.
 *
 * 빠른 이동 단추(결과·일정·챗봇) 줄은 없앴다 — 아래 탭에 같은 것이
 * 늘 떠 있어서 같은 길을 두 번 낸 셈이었다.
 */

/* 처음 한 번만 뜨는 안내. 셋을 넘기지 않는다 — 열 개를 이어 붙이면
   결국 슬라이드와 같은 것이 되고, 같은 이유로 넘겨진다. */
const COACH = [
  {
    sel: '[data-coach="chatbot"]',
    title: "안녕하세요, 틸리예요",
    body:
      "저는 안내 챗봇이자 앱 사용을 돕는 건강 파트너예요. " +
      "검사 안내문에 나온 낱말이나 다음에 할 일을 함께 살펴볼 수 있어요.",
  },
  {
    sel: '[data-coach="quest"]',
    title: "검사 전에 여기부터",
    body:
      "촬영 방법이 달라지는 것들을 미리 여쭙습니다. " +
      "다 채우지 않아도 답한 만큼 저장됩니다.",
  },
  {
    sel: '[data-coach="bell"]',
    title: "새 안내문은 여기에",
    body: "검사 결과가 나오면 종에 표시가 붙습니다.",
  },
  {
    sel: '[data-coach="tab-book"]',
    title: "방문 신청은 예약에서",
    body: "날짜와 시간만 고르시면 됩니다. 검사 종류는 병원이 정합니다.",
  },
];

/* 날씨처럼 외부 정보에 기대지 않고, 이미 병원이 가진 일정만 쓴다.
   내일 예약은 가장 가까운 행동이라 날짜보다 먼저 알려 준다. */
function visitOrdinal(n) {
  if (n === 1) return "첫";
  if (n === 2) return "두 번째";
  if (n === 3) return "세 번째";
  return `${n}번째`;
}

/* 이름만 색을 달리 칠하려고 { name, rest } 로 돌려준다(09-28 홈 인사 카드) */
function visitGreeting(home) {
  const name = home.display_name || "환자";
  const visits = Number(home.visit_count);

  if (Number.isFinite(visits) && visits > 0) {
    return { name, rest: `${visitOrdinal(visits)} 방문예정이에요.`, upcoming: true };
  }
  return { name, rest: "방문 일정을 확인해봐요." };
}

function todayLabel() {
  const now = new Date();
  return `${now.getMonth() + 1}월 ${now.getDate()}일(${WDS[now.getDay()]})`;
}

/* 문진 카드에 뭐라고 쓸지. status 는 not_started · in_progress · done 이다. */
function questLine(q) {
  if (q.status === "done") return "자가검진 작성 완료!";
  if (q.status === "in_progress") return `${q.answered} / ${q.total} 문항 작성`;
  return "아직 작성하지 않았습니다";
}

export default function Home() {
  const { loading, data, error, reload } = useApi(() => api.home());
  // 홈의 다음 복용은 처방 원본에서 읽는다. 홈 응답에 복용 기록을 복제하면
  // 체크한 직후 두 화면의 값이 서로 어긋날 수 있다.
  const prescriptions = useApi(() => api.prescriptions());

  return (
    <>
      {/* 홈에는 제목줄이 없다. 「홈」이라고 적어 봐야 아무 정보도 아니고,
          그 자리를 인사와 알림에 내주는 편이 낫다. 뒤로가기도 없다 —
          돌아갈 위가 없다. */}
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} prescriptions={prescriptions.data} />}
      </Body>
    </>
  );
}

function Inner({ d, prescriptions }) {
  const visit = visitGreeting(d);
  const q = d.questionnaire ?? {};
  const done = q.status === "done";
  const pct = q.total ? Math.round((q.answered / q.total) * 100) : 0;
  const next = d.next_reservation;
  const cal = d.calendar;
  const newReport = d.new_reports?.find((r) => r.lock_status !== "locked");
  const nextMedication = findNextMedication(prescriptions);
  const todayTasks = [
    nextMedication,
    !done && {
      to: "/quest",
      icon: "help",
      image: "exam_results_icon.png",
      title: questLine(q),
      detail: q.hint || "검사 전에 문진을 마쳐 주세요",
    },
    next && {
      to: "/book",
      icon: "calendar",
      image: "exam_schedule_icon.png",
      title: `다음 예약 ${fmtWhen(next.scheduled_at)}`,
      detail: next.place || "예약 장소를 확인해 주세요",
    },
    newReport && {
      to: `/reports/${newReport.report_id}`,
      icon: "results",
      title: "새 안내문을 확인해 주세요",
      detail: newReport.title,
    },
  ]
    .filter(Boolean)
    .slice(0, 3);

  return (
    <>
      {/* 맨 위는 **아이콘만** 둔다. 이름은 아래 큰 인사가 맡는다 —
          브랜드 가이드의 홈이 인사를 크게 세우는 구조라, 작은 이름표와
          큰 인사가 같이 있으면 같은 말이 두 번 나온다 */}
      {/* 09-28 리뉴얼 — 블러시 그라데이션 머리(hero) 위에 알림 · 설정 · 인사,
          틸리는 인사 카드 **뒤**에서 내다본다(카드가 아래를 살짝 가린다).
          인사 카드는 머리 아래쪽에 반쯤 걸쳐 올린다 */}
      <section className="hero">
        <i className="hero-dot" aria-hidden="true" />
        <div className="hbar">
          <Link className="icon" to="/notis" aria-label="알림" data-coach="bell">
            <Bell />
            {/* 몇 개인지보다 «있다»가 중요하다. 숫자를 안 쓴다 */}
            {d.new_reports?.length > 0 && <i className="new" />}
          </Link>
          <Link className="icon" to="/settings" aria-label="설정">
            <Gear />
          </Link>
        </div>
        <h1 className="hero-t">안녕하세요!</h1>
        <p className="hero-s">오늘도 건강한 하루 보내세요</p>
        <span className="hero-tilly" aria-hidden="true">
          <Tilly mood="hi" size="lg" alt="" />
        </span>
      </section>

      <div className="hello-card">
        <div className="hello-row">
          <span className="badge">{todayLabel()}</span>
          {visit.upcoming && <span className="badge strong">방문 예정</span>}
        </div>
        <p className="hello-visit"><em>{visit.name}</em> 님, {visit.rest}</p>
        {d.last_visit_at && (
          <p className="hello-last">
            마지막 내원 {fmtDay(d.last_visit_at)}{deptSuffix(d.last_visit_dept)}
          </p>
        )}
        <div className="tipbox">
          <span className="tip-ic" aria-hidden="true"><Bulb /></span>
          <span>
            <small>오늘의 건강 한마디</small>
            <b>식후 약은 꼭 식후에 드세요.</b>
          </span>
        </div>
      </div>

      {d.today_visit?.active && <TodayVisit visit={d.today_visit} />}
      {todayTasks.length > 0 && <TodayTasks tasks={todayTasks} />}

      <div className="quick-head">
        <Icon name="sparkle" />
        <b>빠른 메뉴</b>
      </div>
      <div className="tiles">
        {/* 09-28 리뉴얼 — 네 칸 모두 같은 연핑크 타일 · 선 아이콘(색 규칙 1) */}
        <Link className="tile" to="/book">
          <span className="ic"><Icon name="calendar" /></span>
          <span><b>검사 일정</b><small>{next ? `다음 ${fmtMD(next.scheduled_at)}` : "예약 확인"}</small></span>
        </Link>
        <Link className="tile" to="/results">
          <span className="ic"><Icon name="results" /></span>
          <span><b>검사 결과</b><small>리포트 확인</small></span>
        </Link>
        <Link className="tile" to="/meds">
          <span className="ic"><Icon name="pill" /></span>
          <span><b>복약 관리</b><small>복약 기록</small></span>
        </Link>
        <Link className="tile" to="/hospitals">
          <span className="ic"><Icon name="hospital" /></span>
          <span><b>병원 찾기</b><small>길 안내</small></span>
        </Link>
      </div>


      {/* ── 문진 — 맨 위. 다 쓰기 전에는 강조 바탕이다 ── */}
      <Link
        className={done ? "card go quest-card" : "card go accent quest-card"}
        to="/quest"
        data-coach="quest"
      >
        <span className="tx">
          <span className="k">자가검진 문진{q.required ? " · 필수" : ""}</span>
          <span className="v">{questLine(q)}</span>
          {!done && q.hint && <span className="s">{q.hint}</span>}
          {!done && q.total > 0 && (
            <span className="prog">
              <i style={{ width: `${pct}%` }} />
            </span>
          )}
        </span>
        {!done && (
          <img
            className="quest-pop"
            src="/tilly/tily_pop.png"
            alt=""
            aria-hidden="true"
          />
        )}
        {done && <span className="pill ok">완료</span>}
      </Link>

      {/* ── 새 안내문 — 있을 때만 ──
          잠긴 것은 링크가 아니다. 대면 설명 전이라 열 수 없다. */}
      {d.new_reports?.map((r) => {
        const locked = r.lock_status === "locked";
        const inner = (
          <>
            <span className="tx">
              <span className="k">새 안내문</span>
              <span className="v">{r.title}</span>
              <span className="s">
                {r.issued_at ? fmtDay(r.issued_at) : ""}
                {r.issued_by_name ? ` · ${r.issued_by_name} 판독` : ""}
              </span>
            </span>
            <span className={locked ? "pill read" : "pill new"}>
              {locked ? "잠김" : "새 안내"}
            </span>
            {!locked && <Icon className="arw" name="chevronRight" />}
          </>
        );
        return locked ? (
          <div key={r.report_id} className="card go">
            {inner}
          </div>
        ) : (
          <Link
            key={r.report_id}
            className="card go"
            to={`/reports/${r.report_id}`}
          >
            {inner}
          </Link>
        );
      })}

      {/* ── 달력 — 보기만 한다 ── */}
      {cal && (
        <Calendar
          month={cal.month}
          marks={cal.marks}
          footer={
            <>
              <span className="tx">
                {next ? (
                  <>
                    <b>다음 {fmtWhen(next.scheduled_at)}</b>
                    <span>
                      {/* 신청 단계에서는 검사 종류가 아직 없다. 병원이 정한다 */}
                      {text(
                        { ...next, modality: asModality(next.modality) },
                        "modality",
                        MODALITY,
                        "modality_label",
                      ) || "검사 종류는 병원에서 정합니다"}
                      {next.place ? ` · ${next.place}` : ""}
                    </span>
                  </>
                ) : (
                  <>
                    <b>예정된 예약이 없습니다</b>
                    <span>방문을 신청하시면 병원에서 확인해 드립니다</span>
                  </>
                )}
              </span>
              <Link className="more" to="/book">
                예약 <Icon name="arrowRight" />
              </Link>
            </>
          }
        />
      )}

      {/* ── 바로가기 ──
          ⚠ **아래 탭에 있는 것은 여기 두지 않는다.** 결과·예약·상담은
            탭과 떠 있는 단추로 늘 닿으므로, 같은 길을 두 번 내면 화면만
            길어진다. 전에 이 자리를 한 번 걷어냈던 이유가 그것이다.

            그래서 남는 것이 「탭에 없고 아직 만들지도 않은」 둘이다.
            브랜드 가이드의 홈에 있던 항목을 자리만 먼저 잡아 둔다 —
            **끈 채로** 두고 왜 못 누르는지 적는다. 기능이 생기면 off 를
            떼고 to 를 넣으면 된다 */}
      <p className="note">
        이 앱의 안내는 진단서가 아닙니다. 최종 판단은 진료 때 의료진이 합니다.
      </p>

      {/* 처음 홈에 들어온 사람에게 셋만 짚어 준다. 소개 슬라이드를
          대신하는 자리다 — 슬라이드는 감이 없어서 건너뛰지만, 이건
          그 자리를 보고 있을 때 말한다 */}
      <Coach seenKey={COACH_HOME} steps={COACH} />
    </>
  );
}

/* 메뉴 이름이 아이콘의 뜻을 이미 말해 주므로 장식 이미지로 처리한다. */
function MenuIcon({ file }) {
  return (
    <img
      className="menu-icon"
      src={`/tilly/${file}`}
      alt=""
      aria-hidden="true"
    />
  );
}

function TodayTasks({ tasks }) {
  return (
    <section className="today-tasks" aria-labelledby="today-tasks-title">
      <div className="today-tasks-head">
        <img
          className="today-tasks-tilly"
          src="/tilly/alram.png"
          alt=""
          aria-hidden="true"
        />
        <b id="today-tasks-title">오늘의 할 일</b>
        <span>{tasks.length}개</span>
      </div>
      <div className="today-tasks-list">
        {tasks.map((task) => (
          <Link key={task.to} to={task.to}>
            <span className="today-task-icon">
              {task.image ? (
                <img
                  className="today-task-image"
                  src={`/tilly/${task.image}`}
                  alt=""
                  aria-hidden="true"
                />
              ) : (
                <Icon name={task.icon} />
              )}
            </span>
            <span className="today-task-text">
              <b>{task.title}</b>
              <span>{task.detail}</span>
            </span>
            <Icon className="arw" name="chevronRight" />
          </Link>
        ))}
      </div>
    </section>
  );
}

/* 접수 뒤에만 오는 당일 동선이다. 내부 처리 단계 대신 환자가 실제로
   움직여야 하는 다음 장소 하나만 보여 준다. */
function TodayVisit({ visit }) {
  return (
    <section className="today-visit" aria-labelledby="today-visit-title">
      <span className="today-visit-icon">
        <img
          className="today-visit-tilly"
          src="/tilly/hospital_finder_icon.png"
          alt=""
          aria-hidden="true"
        />
      </span>
      <span className="today-visit-text">
        <span className="k" id="today-visit-title">
          오늘 병원 안내
        </span>
        <b>다음 진료: {visit.next_location}</b>
        {visit.note && <span>{visit.note}</span>}
      </span>
    </section>
  );
}

/* 복용 기록이 없는 회차만 고른다. 이미 지난 시각이면 「다음」이라고
   속이지 않고 복용 확인이 필요하다고 말한다. */
function findNextMedication(prescriptions) {
  const pending = (prescriptions?.items ?? [])
    .filter((rx) => rx.status !== "ended")
    .flatMap((rx) =>
      (rx.drugs ?? []).flatMap((g) =>
        (g.today ?? []).filter((t) => !t.log_id).map((t) => ({ g, t })),
      ),
    )
    .sort((a, b) => a.t.time.localeCompare(b.t.time));
  if (!pending.length) return null;

  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const asMinutes = (time) => {
    const [hour, minute] = time.split(":").map(Number);
    return hour * 60 + minute;
  };
  const item =
    pending.find(({ t }) => asMinutes(t.time) >= minutes) ?? pending[0];
  const upcoming = asMinutes(item.t.time) >= minutes;

  return {
    to: "/meds",
    icon: "pill",
    image: "medication_icon.png",
    title: upcoming ? `다음 복용 ${item.t.time}` : `${item.t.time} 복용 확인`,
    detail: `${item.g.name} · ${item.g.dose}`,
  };
}

/* 톱니 — 설정. 종과 같은 굵기·같은 모서리로 그려야 둘이 한 벌로 보인다. */
/* 건강 한마디 전구 — 선 아이콘(stroke 1.9) */
function Bulb() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
         strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
      <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1V17h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z" />
    </svg>
  );
}

/* 10.02 */
function fmtMD(iso) {
  const t = new Date(iso);
  return `${String(t.getMonth() + 1).padStart(2, "0")}.${String(t.getDate()).padStart(2, "0")}`;
}

function Gear() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.9 19a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 5 8.9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9.5a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

/* 종 — 글자 대신 그린다. ⌂ ▤ 같은 기호에는 종이 없고, 이모지(🔔)는
   판마다 색이 달라서 무채색 아이콘 사이에서 혼자 튄다. */
function Bell() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
  );
}
