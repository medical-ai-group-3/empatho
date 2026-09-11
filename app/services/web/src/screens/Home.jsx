import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Calendar from "../lib/Calendar";
import ThemeButton from "../lib/ThemeButton";
import { Body, Head } from "../lib/Screen";
import { fmtDay, fmtWhen } from "../lib/when";

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
      {/* 홈은 돌아갈 위가 없다 — 여기만 화살표를 안 낸다.
          밝기 단추는 「내 정보」가 생기면 그리로 옮긴다 */}
      <Head title="홈" back={false} right={<ThemeButton />} />
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
      <p className="hello">
        {d.display_name} 님
        {d.last_visit_at && (
          <small>
            마지막 내원 {fmtDay(d.last_visit_at)}
            {d.last_visit_dept ? ` · ${d.last_visit_dept}` : ""}
          </small>
        )}
      </p>

      {/* ── 문진 — 맨 위. 다 쓰기 전에는 강조 바탕이다 ── */}
      <Link className={done ? "card go" : "card go accent"} to="/quest">
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
                      {next.modality_label || "검사 종류는 병원에서 정합니다"}
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

      <p className="note">
        이 앱의 안내는 진단서가 아닙니다. 최종 판단은 진료 때 의료진이 합니다.
      </p>
    </>
  );
}
