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
 *
 * ── studies 는 객체다 ─────────────────────────────────────────
 * `[{study_id, modality, label}, …]` 로 목록과 상세가 **같은 모양**이다.
 * 전에는 목록만 문자열 배열이었는데, 그러면 나중에 「이 검사 사진 보기」
 * 를 붙일 때 목록에서 study_id 를 못 찾아 상세를 한 번 더 불러야 한다.
 *
 * 화면에 내는 것은 label 뿐이다. modality('mammo')는 기계가 읽는 말이라
 * 환자에게 보여주지 않는다 — 그 자리에 「유방촬영술」이 있다.
 */
/* 검사 이름만 뽑아 「유방촬영술 · 유방초음파」로 잇는다.
   label 이 빠진 것은 버린다 — 「유방촬영술 ·  · 혈액검사」처럼 가운데가
   빈 줄이 나오느니 그 칸이 없는 편이 낫다. */
const labels = (studies) =>
  (studies || []).map((s) => s.label).filter(Boolean).join(" · ");

export default function Results() {
  const { loading, data, error, reload } = useApi(() => api.results());

  return (
    <>
      <Head title="검사 결과" />
      <Body loading={loading} error={error} onRetry={reload}>
        <div className="list">
          {/* ?. 를 items 에도 붙인다. data 가 없을 때만 막으면, 자료는
              왔는데 items 가 안 온 경우에 여기서 터진다 */}
          {data?.items?.map((r) => {
            const locked = r.lock_status === "locked";
            const inner = (
              <>
                <span className="dt">
                  {(r.visit_date || "").replaceAll("-", ".")}
                </span>
                <span className="tx">
                  <b>{r.title}</b>
                  <span>
                    {locked ? r.locked_hint : labels(r.studies)}
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
