/* 「이 기기에서 한 번 봤나」를 기억한다. 웰컴과 코치마크가 쓴다.
 *
 * 서버에 둘 값이 아니다. 계정이 아니라 **기기**의 사정이고, 웰컴은
 * 로그인 전에 판단해야 해서 물어볼 데도 없다.
 *
 * localStorage 는 없을 수 있다. 사생활 보호 창이나 쿠키를 막아 둔
 * 브라우저에서는 읽기만 해도 예외가 난다.
 *
 * ⚠ 못 읽으면 **본 것으로 친다.** 반대로 하면 그런 브라우저에서는 앱을
 *   열 때마다 소개와 안내가 다시 뜬다 — 한 번도 안 보는 것보다 매번
 *   보는 쪽이 나쁘다.
 */
export function seen(key) {
  try { return localStorage.getItem(key) === "1"; } catch { return true; }
}

export function markSeen(key) {
  try { localStorage.setItem(key, "1"); } catch { /* 이번 방문에만 적용된다 */ }
}

/* 설정에서 「앱 사용법 다시 보기」를 눌렀을 때만 지운다. 첫 사용 안내를
   매번 되살리지 않으면서, 필요할 때는 사용자가 직접 다시 볼 수 있다. */
export function clearSeen(key) {
  try { localStorage.removeItem(key); } catch { /* 저장소를 못 쓰면 다음 화면에서 보이지 않는다 */ }
}

export const WELCOME = "empatho.welcome_seen";
/* 틸리 소개를 더한 새 안내는 기존 안내를 본 기기에도 한 번 보여 준다. */
export const COACH_HOME = "empatho.coach_home_v2";

export const welcomeSeen = () => seen(WELCOME);
export const markWelcomeSeen = () => markSeen(WELCOME);
