import { Btn } from "./Page";

/* 부르는 중 · 오류 · 본문을 한 모양으로 낸다.
 * 오류는 code 를 같이 보여준다 — 「오류가 발생했습니다」만 뜨면 원인을
 * 못 찾는다. */
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
      </div>
    );
  }
  return children;
}
