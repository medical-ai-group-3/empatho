/* 로그인 토큰을 들고 있는 자리.
 * ────────────────────────────────────────────────────────────────
 *
 * **여기는 토큰만 맡는다.** 로그인한 사람(이름 · 과 · perms)은 perm.js 가
 * 들고 있고 useMe() 로 읽는다. 둘을 한 곳에 담으면 「권한이 바뀌었나」와
 * 「로그인이 풀렸나」가 같은 상태 변화로 보인다.
 *
 * ── 어디에 두나 ───────────────────────────────────────────────
 * sessionStorage 다. **탭을 닫으면 사라진다.**
 *
 *   localStorage   새로고침도 버티고 브라우저를 닫아도 남는다. 업무 화면을
 *                  켜 둔 채 자리를 비우면 그대로 열려 있다
 *   메모리         새로고침마다 다시 로그인이라 개발이 안 된다
 *   sessionStorage 새로고침은 버티고, 탭을 닫으면 끝난다  ← 이것
 *
 * 다른 스크립트가 읽어 갈 수 있는 것은 localStorage 와 같지만, 남아 있는
 * 시간이 탭 수명으로 줄어든다. 운영 정책이 정해지면 아래 load · save
 * **둘만** 고치면 된다.
 */
import { useSyncExternalStore } from "react";
import { setToken } from "../api";

const KEY = "empatho_staff_token";

function load() {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;              // 사생활 보호 모드 등에서 막힐 수 있다
  }
}

function save(t) {
  try {
    if (t) sessionStorage.setItem(KEY, t);
    else sessionStorage.removeItem(KEY);
  } catch { /* 못 써도 이번 세션은 돈다 */ }
}

let token = load();
let refresh = null;
const subs = new Set();

/* 새로고침으로 다시 뜬 경우 — 저장해 둔 토큰을 api 층에 도로 끼운다.
   이것을 빠뜨리면 사람은 로그인돼 보이는데 요청마다 401 이 난다. */
if (token) setToken(token);

function set(next, nextRefresh = null) {
  token = next;
  refresh = nextRefresh;
  setToken(token);
  save(token);
  for (const fn of subs) fn();
}

/* 로그인 성공.
   ⚠ 갱신(refresh) 엔드포인트가 아직 백엔드에 없다. 생기면 여기 담아 둔
     값으로 부른다 — 없으면 access 가 30 분에 만료되고 화면이 통째로
     로그인으로 돌아간다. */
export const signIn = ({ access, refresh: r }) => set(access, r);
export const signOut = () => set(null);

export const refreshToken = () => refresh;

/* 로그인했나. 토큰이 있느냐로만 본다 — 화면이 스스로 「로그인함」을 적어
   두고 그걸 믿으면, 만료된 뒤에도 화면은 열리고 요청만 하나씩 실패한다. */
export function useSignedIn() {
  return useSyncExternalStore(
    (fn) => { subs.add(fn); return () => subs.delete(fn); },
    () => Boolean(token),
    () => false,
  );
}
