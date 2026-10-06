import { useLocation, useNavigate } from "react-router-dom";
import Logo from "./Logo";
import Icon from "./Icon";
import Tilly from "./Tilly";

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
/* sub — 09-28 리뉴얼. 부제가 있으면 블러시 그라데이션 큰 머리(hero)로 낸다.
   탭 화면(결과 · 예약 · 내 정보)이 쓴다. 없으면 예전 작은 머리말 그대로 */
export function Head({ title, back = true, up = "/", right, sub }) {
  const nav = useNavigate();
  const loc = useLocation();
  const orphan = loc.key === "default";   // 되짚을 이력이 없다

  return (
    <div className={sub ? "top hero-top" : "top"}>
      {back && (
        <button
          className="back"
          aria-label="뒤로"
          onClick={() => (orphan ? nav(up, { replace: true }) : nav(-1))}
        >
          <Icon name="chevronRight" className="back-icon" />
        </button>
      )}
      {sub
        ? <div className="hero-tx"><h2>{title}</h2><p>{sub}</p></div>
        : <h2>{title}</h2>}
      {/* 오른쪽 끝에 작은 로고. 제목 옆에 붙이면 제목과 겨루고, 왼쪽은
          뒤로가기 자리다 — 남는 자리는 여기뿐이다.
          right 가 있는 화면에서는 양보한다. 한 자리에 둘을 밀어 넣으면
          둘 다 작아진다 */}
      {right ? <div className="right">{right}</div>
             : !sub && <Logo size="sm" />}
      {sub && <i className="hero-dot" aria-hidden="true" />}
    </div>
  );
}

/* 로딩·오류·본문을 한 모양으로 낸다.
 * 오류는 code 를 같이 보여준다 — 「네트워크 오류」만 뜨면 원인을 못 찾는다.
 *
 * ⚠ **여기 넣는 자식은 Body 가 무엇을 낼지 고르기 전에 이미 만들어진다.**
 *   loading 이 true 라 「불러오는 중」만 나오는 순간에도 자식은 만들어져
 *   있다. 그래서 이렇게 쓰면 첫 그림에서 터진다:
 *
 *     <Body loading={loading}>
 *       <p>{data.name}</p>        ← data 는 아직 null
 *     </Body>
 *
 *   터지면 React 가 트리를 통째로 내린다 — 머리말도 뒤로가기도 같이
 *   사라져서 **하얀 화면**만 남는다. 실제로 안내문 화면이 그랬다.
 *
 *   그러니 자료를 읽는 부분은 부품으로 빼고 이렇게 막는다:
 *
 *     <Body loading={loading}>{data && <Inner d={data} />}</Body>
 *
 *   부품 안에서는 자료가 있다고 믿고 써도 된다. `?.` 를 줄줄이 다는
 *   것보다 이 편이 낫다 — 물음표를 하나 빠뜨리면 같은 일이 또 난다. */
export function Body({ loading, error, onRetry, children }) {
  if (loading) {
    return (
      <div className="pane">
        {/* 가운데에 세운다. 위쪽에 한 줄만 붙여 두면 화면이 잘못 뜬
            것처럼 보인다 */}
        <div className="empty">
          <Tilly mood="loading" size="loading" alt="" />
          <p>불러오는 중…</p>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="pane">
        <div className="empty error-state">
          {/* tily_error.png 가 아직 없으면 Tilly가 조용히 자리를 비운다.
              이미지가 추가되는 즉시 같은 자리에서 보인다. */}
          <Tilly mood="error" size="lg" alt="" />
          <div className="card flag">
            <span className="k">{error.code || "오류"}</span>
            <span className="s">{error.detail || error.message || "불러오지 못했습니다."}</span>
          </div>
          <p>인터넷 연결을 확인한 뒤 다시 시도해 주세요.</p>
        </div>
        <button className="btn ghost" onClick={onRetry}>다시 시도</button>
      </div>
    );
  }
  return <div className="pane">{children}</div>;
}
