import { Btn } from "./Page";

/* 네 가지 상태 — 모든 목록·상세가 갖춰야 한다
 * ────────────────────────────────────────────────────────────────
 *
 *   불러오는 중  자리를 지키는 뼈대. 화면이 통째로 사라지면 안 된다
 *   비었음       왜 비었는지 + 다음에 할 일
 *   오류         무엇이 실패했는지 + [다시 시도]
 *   권한 없음    무슨 권한이 필요한지 (Parts.jsx 의 Locked)
 *
 * 오류는 code 를 같이 보여준다 — 「오류가 발생했습니다」만 뜨면 원인을
 * 못 찾는다.
 *
 * **trace_id 를 작게 붙인다.** 서버 쪽에서 로그를 찾을 때 이 값으로
 * 찾는다. 사람이 읽을 값은 아니지만 그대로 읽어 주면 바로 찾힌다.
 *
 * ⚠ **빈 목록을 오류로 위장하지 않고, 오류를 빈 목록으로 위장하지도
 *   않는다.** 둘은 다른 일이다 — 하나는 없는 것이고 하나는 못 본 것이다.
 */
export function Body({ loading, error, onRetry, empty, children, skeleton = "list" }) {
  if (loading) return <Skeleton kind={skeleton} />;

  if (error) {
    return (
      <div className="state">
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

  /* 비었음은 **부르는 쪽이 판단한다.** 무엇이 비었는지는 화면만 안다 —
     「검체가 없습니다」가 아니라 「접수 대기 중인 검체가 없습니다」여야
     하는데, 그 문장을 여기서 지어낼 수가 없다 */
  if (empty) return empty === true ? <Empty /> : empty;

  return children;
}

/* ── 비었음 ───────────────────────────────────────────────────
   왜 비었는지 말하고, 할 수 있는 다음 일을 준다. */
export function Empty({ title = "아직 아무것도 없습니다", hint, action }) {
  return (
    <div className="state">
      <b>{title}</b>
      {hint && <span>{hint}</span>}
      {action}
    </div>
  );
}

/* ── 불러오는 중 ──────────────────────────────────────────────
 *
 * **움직이는 반짝임을 두지 않는다.** 판독실에서 하루 종일 보는 화면이라
 * 무엇이든 계속 움직이면 피로하다. 자리만 지킨다.
 *
 * 화면 모양대로 뼈대가 다르다 — 목록은 줄이 여럿, 상세는 덩어리 하나.
 */
export function Skeleton({ kind = "list", rows = 6 }) {
  if (kind === "none") return null;
  if (kind === "block") {
    return (
      <div className="sk" aria-busy="true" aria-label="불러오는 중">
        <i className="sk-line w60" /><i className="sk-block" />
      </div>
    );
  }
  return (
    <div className="sk" aria-busy="true" aria-label="불러오는 중">
      {Array.from({ length: rows }, (_, i) => (
        <span className="sk-row" key={i}>
          <i className="sk-line w40" /><i className="sk-line w70" />
        </span>
      ))}
    </div>
  );
}
