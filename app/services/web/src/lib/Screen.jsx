import { useLocation, useNavigate } from "react-router-dom";

/* 화면 하나의 껍데기 — 머리말 · 로딩 · 오류 · 본문.
 *
 * ── 뒤로가기 규칙 ──────────────────────────────────────────────
 * **홈 말고는 다 있다.** 홈은 돌아갈 위가 없어서 화살표를 안 낸다
 * (<Head back={false} />).
 *
 * 누르면 브라우저 이력을 그대로 되짚는다 — 목록에서 왔든 알림에서
 * 왔든 **온 길로 돌아간다**. 돌아갈 곳을 화면마다 박지 않는다.
 *
 * 다만 이력이 없을 때가 있다. 알림 링크로 바로 들어오거나 새로고침을
 * 하면 이 화면이 첫 화면이라 되짚을 것이 없다 — 그때 nav(-1) 은 앱
 * 밖으로 나가 버리거나 아무 일도 안 한다. 그래서 «위로 갈 곳»을 하나
 * 받아 둔다(up). 기본은 홈이고, 안내문처럼 목록이 뚜렷한 화면은
 * up="/results" 를 준다.
 * ───────────────────────────────────────────────────────────── */
export function Head({ title, back = true, up = "/", right }) {
  const nav = useNavigate();
  const loc = useLocation();
  const orphan = loc.key === "default";   // 되짚을 이력이 없다

  return (
    <div className="top">
      {back && (
        <button
          className="back"
          aria-label="뒤로"
          onClick={() => (orphan ? nav(up, { replace: true }) : nav(-1))}
        >
          ‹
        </button>
      )}
      <h2>{title}</h2>
      {right && <div className="right">{right}</div>}
    </div>
  );
}

/* 로딩·오류·본문을 한 모양으로 낸다.
 * 오류는 code 를 같이 보여준다 — 「네트워크 오류」만 뜨면 원인을 못 찾는다. */
export function Body({ loading, error, onRetry, children }) {
  if (loading) {
    return (
      <div className="pane">
        <p className="note c" style={{ paddingTop: 40 }}>불러오는 중…</p>
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
  return <div className="pane">{children}</div>;
}
