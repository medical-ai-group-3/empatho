import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";

/* 06 · 검사 결과
 *
 * **내원 한 번에 안내문 하나다.** 묶는 일은 병원에서 끝나 있고 서버가
 * report_type='final' 인 것만 준다 — 화면은 묶지 않는다.
 *
 * lock_status 가 'locked' 면 누를 수 없다. 대면 설명 전이라 열람이
 * 막혀 있다.
 */
export default function Results() {
  const { loading, data, error, reload } = useApi(() => api.results());

  return (
    <>
      <Head title="검사 결과" />
      <Body loading={loading} error={error} onRetry={reload}>
        <div className="list">
          {data?.items.map((r) => {
            const locked = r.lock_status === "locked";
            const inner = (
              <>
                <span className="dt">{r.visit_date.replaceAll("-", ".")}</span>
                <span className="tx">
                  <b>{r.title}</b>
                  <span>
                    {locked ? r.locked_hint : r.studies.join(" · ")}
                  </span>
                </span>
                {locked ? (
                  <span className="pill read">잠김</span>
                ) : r.read_at ? (
                  <span className="pill read">읽음</span>
                ) : (
                  <span className="pill new">새 안내</span>
                )}
              </>
            );
            // 잠긴 것은 링크가 아니다. 눌러도 갈 곳이 없어야 한다.
            return locked ? (
              <div key={r.report_id}>{inner}</div>
            ) : (
              <Link key={r.report_id} to={`/reports/${r.report_id}`}>
                {inner}
              </Link>
            );
          })}
        </div>
        <p className="note">{data?.note}</p>
      </Body>
    </>
  );
}
