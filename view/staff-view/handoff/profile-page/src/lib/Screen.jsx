/* 화면 하나의 껍데기 — 머리말 · 로딩 · 오류 · 본문.
 * back은 함수(onClick 핸들러)로 받는다 — 그냥 브라우저 히스토리(-1)로
 * 돌아가면 "다음 환자로 자동 넘어가기"(location.state.advance) 같은
 * 화면별 로직을 못 실어서, 어디로/무슨 상태로 갈지는 호출부가 정한다.
 * 목록 자체인 화면(대기 환자)은 back을 안 준다 — 더 갈 위가 없다. */
export function Head({ title, sub, back, right }) {
  return (
    <div className="shead">
      {back && (
        <button className="back-btn" aria-label="뒤로" onClick={back}>‹</button>
      )}
      <div className="tx">
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {right && <div className="right">{right}</div>}
    </div>
  );
}

export function Body({ loading, error, onRetry, children }) {
  if (loading) {
    return (
      <div className="pane">
        <div className="empty">
          <i className="ic" aria-hidden="true">◍</i>
          <p>불러오는 중…</p>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="pane">
        <div className="card flag">
          <span className="k">{error.code || "오류"}</span>
          <span className="s">{error.detail || error.message}</span>
        </div>
        <button className="btn ghost" onClick={onRetry}>다시 시도</button>
      </div>
    );
  }
  return <>{children}</>;
}
