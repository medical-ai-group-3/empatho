/* 새로고침 없이 따라가는 화면 — 바뀜 신호와 조용한 다시 부르기
 * ════════════════════════════════════════════════════════════════
 *
 * 09-29 「접수가 들어가거나 예약이 바뀌면 새로고침 없이 다음 단계 화면에 떠야 한다」.
 * 데이터 변경을 밀어 주는 길은 없다 — SSE(lib/live.js · notify 허브)는 «나에게 온
 * 알림»만 흘린다. 그래서 셋으로 메운다(③ 알림이 오면 lib/Top.jsx 가 emitChange).
 *
 *   ① 이 컴퓨터에서 무엇이든 저장되면(api.js 의 POST · PATCH · PUT · DELETE
 *      성공) emitChange() — 이 탭의 살아 있는 화면과 **같은 브라우저의 다른
 *      탭**(BroadcastChannel)이 곧바로 다시 부른다. 창구 한 대에서 접수 탭과
 *      대기 탭을 나란히 여는 경우가 가장 흔하다.
 *   ② 다른 컴퓨터가 바꾼 것은 주기로 — 화면이 보일 때만 LIVE_MS 마다.
 *      탭으로 돌아오거나(visibilitychange) 창을 누르면(focus) 바로 한 번.
 *      가려진 탭은 부르지 않는다 — 열어 둔 탭 수만큼 서버를 두드리지 않게.
 *
 * ⚠ 다시 부르기는 늘 **조용히**(useApi 의 reload(true)) — 뼈대 화면으로
 *   갈아 끼우면 읽던 줄 · 쓰던 칸이 사라진다.
 * ⚠ 입력 양식에는 켜지 않는다. 받아 온 값으로 칸을 채우는 화면은 다시
 *   부를 때 쓰던 글을 덮을 수 있다 — 목록 · 대기열 · 판에만 켠다.
 */

import { useEffect, useRef } from "react";

export const LIVE_MS = 15000;

const CHANNEL = "empatho.live";
const subs = new Set();
let bc = null;
try {
  bc = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(CHANNEL) : null;
  if (bc) bc.onmessage = () => fire();
} catch { bc = null; }

/* 저장이 몰려 와도(한 번 누름에 요청 셋) 한 번만 다시 부른다 */
let pending = null;
function fire() {
  if (pending) return;
  pending = setTimeout(() => {
    pending = null;
    subs.forEach((fn) => { try { fn(); } catch { /* 한 화면이 죽어도 나머지는 돈다 */ } });
  }, 250);
}

export function emitChange() {
  fire();
  try { bc?.postMessage(Date.now()); } catch { /* 채널이 닫혔다 — 이 탭만 */ }
}

export function onChange(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}

/* 보일 때만 주기로 + 돌아오면 바로 + 바뀜 신호에 바로.
   fn 은 조용한 다시 부르기여야 한다. ms 가 0 이면 주기는 끈다(신호만) */
export function useLive(fn, ms = LIVE_MS, on = true) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!on) return undefined;
    const go = () => { if (document.visibilityState !== "hidden") ref.current?.(); };
    const off = onChange(go);
    const t = ms > 0 ? setInterval(go, ms) : null;
    const vis = () => { if (document.visibilityState === "visible") go(); };
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("focus", go);
    return () => {
      off();
      if (t) clearInterval(t);
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("focus", go);
    };
  }, [ms, on]);
}
