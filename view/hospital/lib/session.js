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
import { setToken, setOnRefreshed, setOnAuthLost } from "../api";
import { purgeLocalNotes } from "./notes";

const KEY = "empatho_staff_token";

function load() {
  try {
    const saved = sessionStorage.getItem(KEY);
    /* Authorization 값에 비 ASCII 문자가 있으면 fetch가 요청을 보내기
       전에 예외를 낸다. 예전 목업이 한글 로그인 아이디를 그대로 넣어
       남긴 세션은 로그인 화면으로 되돌려 복구한다. */
    if (saved && !/^[\x00-\x7F]+$/.test(saved)) {
      sessionStorage.removeItem(KEY);
      return null;
    }
    return saved;
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
const subs = new Set();

/* 새로고침으로 다시 뜬 경우 — 저장해 둔 토큰을 api 층에 도로 끼운다.
   이것을 빠뜨리면 사람은 로그인돼 보이는데 요청마다 401 이 난다. */
if (token) setToken(token);

function set(next) {
  token = next;
  setToken(token);
  save(token);
  for (const fn of subs) fn();
}

/* 로그인 성공.
 *
 * ⚠⚠ 2026-09-18 — docs/backend-api-reference.md §1 과 이 파일이 서로
 *   반대로 말하고 있다. 문서는 "로그인이 refresh_token 을 httpOnly 쿠키로
 *   내려주고 POST /token/refresh 가 이미 있다"고 적혀 있는데, 바로 아래
 *   주석(2026-09-17 자)은 "본문에 access·refresh 가 둘 다 온다, 쿠키
 *   자리는 없다"고 반대로 적혀 있다. 둘 중 하나가 낡은 것이다 — 실 서버로
 *   직접 확인하기 전엔 섣불리 코드를 안 바꾼다(본문 모델로 짜여 있는 지금
 *   코드는 서버가 쿠키 모델이어도 최소한 깨지진 않는다, refresh 를 그냥
 *   안 쓰게 될 뿐이다). 확인되면 이 파일의 refreshToken/getRefresh 를
 *   걷어내고 쿠키만 믿는 쪽으로 정리할 것.
 *
 * ⚠ **들었던 것과 다르다** (2026-09-17, empatho-app 의 Django 를 직접
 *   보고 확인). 「refresh 는 httpOnly 쿠키로만 내려온다」고 적어 두었던
 *   것이 사실이 아니었다 —
 *
 *     core/api/views.py  login() → Response(issue_pair(account))
 *     core/api/auth.py   issue_pair() → { access, refresh }
 *
 *   **본문에 둘 다 온다.** Set-Cookie 를 심는 자리가 서버 어디에도 없다.
 *
 *   그래서 refresh 를 여기서 받아 둔다. 다만 **저장소에는 안 넣는다** —
 *   메모리에만 둔다. 갱신 경로(`/token/refresh`)가 서버에 아직 없어서
 *   지금은 쓸 데가 없고, 쓸 데 없는 장기 토큰을 sessionStorage 에
 *   남겨 두는 것은 공용 PC 에서 그냥 손해다. 경로가 생기면 api.js 의
 *   refreshAccess() 가 이것을 실어 보내게 고친다.
 */
let refreshToken = null;
export const getRefresh = () => refreshToken;

/* ⚠ 09-29 계정이 바뀌는 모든 자리에서 예전 브라우저 메모(할 일 · 스티키 글)를
   지운다 — 키에 계정이 없어 다음 사람에게 보였다(lib/notes.js). 앱을 처음
   불러올 때도 한 번(아래) */
purgeLocalNotes();

export const signIn = ({ access, refresh }) => {
  purgeLocalNotes();
  refreshToken = refresh ?? null;
  set(access);
};
export const signOut = () => {
  purgeLocalNotes();
  refreshToken = null;
  set(null);
};

/* api 층이 401 을 받고 조용히 갱신했을 때, 새 access 를 저장소에도 반영한다.
   안 하면 새로고침에 **옛 토큰**이 되살아나 바로 401 이 난다.
   api.js 가 이 파일을 import 하면 서로 물리므로 이쪽에서 등록한다 */
setOnRefreshed((access) => set(access));

/* 토큰이 끊기면(갱신 실패) 세션을 비운다 → Gate 가 로그인 화면으로. */
setOnAuthLost(() => { purgeLocalNotes(); set(null); });

/* 로그인했나. 토큰이 있느냐로만 본다 — 화면이 스스로 「로그인함」을 적어
   두고 그걸 믿으면, 만료된 뒤에도 화면은 열리고 요청만 하나씩 실패한다. */
export function useSignedIn() {
  return useSyncExternalStore(
    (fn) => { subs.add(fn); return () => subs.delete(fn); },
    () => Boolean(token),
    () => false,
  );
}
