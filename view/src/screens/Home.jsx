import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Calendar from "../lib/Calendar";
import Coach from "../lib/Coach";
import Tilly from "../lib/Tilly";
import { COACH_HOME } from "../lib/seen";
import { Body } from "../lib/Screen";
import { fmtDay, fmtWhen } from "../lib/when";
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
  { sel: '[data-coach="quest"]',
    title: "검사 전에 여기부터",
    body: "촬영 방법이 달라지는 것들을 미리 여쭙습니다. "
        + "다 채우지 않아도 답한 만큼 저장됩니다." },
  { sel: '[data-coach="bell"]',
    title: "새 안내문은 여기에",
    body: "검사 결과가 나오면 종에 표시가 붙습니다." },
  { sel: '[data-coach="tab-book"]',
    title: "방문 신청은 예약에서",
    body: "날짜와 시간만 고르시면 됩니다. 검사 종류는 병원이 정합니다." },
];

/* 문진 카드에 뭐라고 쓸지. status 는 not_started · in_progress · done 이다. */
function questLine(q) {
  if (q.status === "done") return "작성을 마쳤습니다";
  if (q.status === "in_progress") return `${q.answered} / ${q.total} 문항 작성`;
  return "아직 작성하지 않았습니다";
}

export default function Home() {
  const { loading, data, error, reload } = useApi(() => api.home());

  return (
    <>
      {/* 홈에는 제목줄이 없다. 「홈」이라고 적어 봐야 아무 정보도 아니고,
          그 자리를 인사와 알림에 내주는 편이 낫다. 뒤로가기도 없다 —
          돌아갈 위가 없다. */}
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </>
  );
}

function Inner({ d }) {
  const q = d.questionnaire ?? {};
  const done = q.status === "done";
  const pct = q.total ? Math.round((q.answered / q.total) * 100) : 0;
  const next = d.next_reservation;
  const cal = d.calendar;

  return (
    <>
      {/* 맨 위는 **아이콘만** 둔다. 이름은 아래 큰 인사가 맡는다 —
          브랜드 가이드의 홈이 인사를 크게 세우는 구조라, 작은 이름표와
          큰 인사가 같이 있으면 같은 말이 두 번 나온다 */}
      <div className="hbar">
        <Link className="icon" to="/notis" aria-label="알림" data-coach="bell">
          <Bell />
          {/* 몇 개인지보다 «있다»가 중요하다. 숫자를 안 쓴다 */}
          {d.new_reports?.length > 0 && <i className="new" />}
        </Link>
        <Link className="icon" to="/settings" aria-label="설정"><Gear /></Link>
      </div>

      {/* 큰 인사 + 틸리.
          alt 를 비운 것은 바로 옆에 같은 인사가 글로 있어서다 — 읽어 주는
          기계가 두 번 말하면 성가시다 */}
      <p className="hello-tx">
        <b>안녕하세요!</b>
        <span>{d.display_name} 님, 오늘도 건강한 하루예요</span>
      </p>

      {/* 틸리는 인사 **아래 가운데**에 크게 선다. 옆에 작게 두었더니
          「인사 옆 장식」이 되어 가이드의 첫인상과 달랐다 */}
      <div className="hello-tri" aria-hidden="true">
        <Tilly mood="hello" size="lg" alt="" />
      </div>

      <div className="tiles">
        <Link className="tile" to="/book">
          <i className="ic" aria-hidden="true">▦</i>
          <b>검사 일정</b>
          <small>날짜 신청 · 확인</small>
        </Link>
        <Link className="tile" to="/results">
          <i className="ic" aria-hidden="true">▤</i>
          <b>검사 결과</b>
          <small>안내문 받아 보기</small>
        </Link>
        {/* 아직 없는 기능은 **끈 채로** 두고 왜 못 누르는지 적는다 —
            눌리는데 아무 일도 안 나는 것이 제일 나쁘다 */}
        <div className="tile off" aria-disabled="true" title="준비 중입니다">
          <i className="ic" aria-hidden="true">✦</i>
          <b>치료 정보</b>
          <small>준비 중입니다</small>
        </div>
        <div className="tile off" aria-disabled="true" title="준비 중입니다">
          <i className="ic" aria-hidden="true">◈</i>
          <b>복약 관리</b>
          <small>준비 중입니다</small>
        </div>
      </div>

      {d.last_visit_at && (
        <p className="note">
          마지막 내원 <b>{fmtDay(d.last_visit_at)}</b>
          {deptSuffix(d.last_visit_dept)}
        </p>
      )}

      {/* ── 문진 — 맨 위. 다 쓰기 전에는 강조 바탕이다 ── */}
      <Link className={done ? "card go" : "card go accent"} to="/quest"
            data-coach="quest">
        <span className="tx">
          <span className="k">자가검진 문진{q.required ? " · 필수" : ""}</span>
          <span className="v">{questLine(q)}</span>
          {!done && q.hint && <span className="s">{q.hint}</span>}
          {!done && q.total > 0 && (
            <span className="prog"><i style={{ width: `${pct}%` }} /></span>
          )}
        </span>
        {done && <span className="pill ok">완료</span>}
        <span className="arw" aria-hidden="true">›</span>
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
            {!locked && <span className="arw" aria-hidden="true">›</span>}
          </>
        );
        return locked ? (
          <div key={r.report_id} className="card go">{inner}</div>
        ) : (
          <Link key={r.report_id} className="card go"
                to={`/reports/${r.report_id}`}>{inner}</Link>
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
                      {text({ ...next, modality: asModality(next.modality) },
                            "modality", MODALITY, "modality_label")
                        || "검사 종류는 병원에서 정합니다"}
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
              <Link className="more" to="/book">예약 →</Link>
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

/* 톱니 — 설정. 종과 같은 굵기·같은 모서리로 그려야 둘이 한 벌로 보인다. */
function Gear() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.9 19a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 5 8.9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9.5a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

/* 종 — 글자 대신 그린다. ⌂ ▤ 같은 기호에는 종이 없고, 이모지(🔔)는
   판마다 색이 달라서 무채색 아이콘 사이에서 혼자 튄다. */
function Bell() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
  );
}
