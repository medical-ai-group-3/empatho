/* 앱을 열 때 잠깐 뜨는 화면.
 *
 * **일부러 기다리게 하지 않는다.** 이 화면은 로그인 확인(/api/v1/me)이
 * 도는 동안을 덮는 것이지, 보여주려고 시간을 끄는 것이 아니다.
 *
 * 다만 너무 빨리 지나가면 «뭔가 번쩍했다»로만 남는다. 그래서 최소 시간을
 * 둔다(RequireAuth 의 MIN_MS). 확인이 그보다 오래 걸리면 그만큼 더 머문다.
 */
import Logo from "../lib/Logo";

export default function Splash() {
  return (
    <div className="app">
      <div className="splash">
        <Logo size="lg" />
        <p className="tag">조기 발견이, 더 많은 내일을 만듭니다.</p>
        <span className="bar" aria-hidden="true"><i /></span>
        {/* 화면을 읽어 주는 기계에는 «불러오는 중»이라고만 말한다.
            로고를 읽어 줘 봐야 도움이 안 된다 */}
        <span className="sr">불러오는 중</span>
      </div>
    </div>
  );
}
