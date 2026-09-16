import { Btn } from "./Page";

/* 부르는 중 · 오류 · 본문을 한 모양으로 낸다.
 *
 * 오류는 code 를 같이 보여준다 — 「오류가 발생했습니다」만 뜨면 원인을
 * 못 찾는다.
 *
 * **trace_id 를 작게 붙인다.** 서버 쪽에서 로그를 찾을 때 이 값으로
 * 찾는다. 사람이 읽을 값은 아니지만 그대로 읽어 주면 바로 찾힌다.
 */
export function Body({ loading, error, onRetry, children }) {
  if (loading) {
    return <div className="slot big"><b>불러오는 중…</b></div>;
  }
  if (error) {
    return (
      <div className="slot big">
        <b>{error.code || `오류 ${error.status ?? ""}`}</b>
        <span>{error.detail || error.message}</span>
        <Btn onClick={onRetry}>다시 시도</Btn>
        {error.traceId && (
          <code className="trace" title="문의하실 때 이 값을 알려주세요">
            {error.traceId}
          </code>
        )}
      </div>
    );
  }
  return children;
}
