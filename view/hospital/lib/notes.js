/* 할 일 · 스티키 메모 — 예전 브라우저 저장을 치우는 자리
 * ════════════════════════════════════════════════════════════════
 *
 * ⚠ 09-29 서버로 옮겼다(GET/POST/PATCH/DELETE /me/notes — personal_note).
 *   전에는 localStorage[`empatho.note.${kind}:${dept}`] 에 두었는데 키에
 *   **계정이 없어서** 같은 컴퓨터에서 같은 과로 들어온 다른 사람(새로 가입한
 *   계정까지)에게 앞 사람의 「나만 볼 수 있음」 할 일이 그대로 보였다.
 *   스티키 메모 글(hospital.stickyMemo.v1 의 text)도 같은 사정이었다.
 *
 * 남은 옛 값은 **서버로 옮기지 않고 지운다** — 누가 쓴 것인지 알 수 없다.
 * 부르는 곳: 앱을 처음 불러올 때 · 로그인 · 로그아웃 · 세션 끊김(lib/session.js).
 *
 * 스티키 메모의 위치 · 크기 · 펼침은 이 기기 화면에 맞춘 값이라 남긴다.
 * 글만 뺀다.
 */

const PREFIX = "empatho.note.";
const STICKY = "hospital.stickyMemo.v1";

export function purgeLocalNotes() {
  try {
    const drop = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i);
      if (k && k.startsWith(PREFIX)) drop.push(k);
    }
    drop.forEach((k) => localStorage.removeItem(k));

    const raw = localStorage.getItem(STICKY);
    if (raw) {
      const s = JSON.parse(raw);
      if (s && typeof s === "object" && "text" in s) {
        delete s.text;
        localStorage.setItem(STICKY, JSON.stringify(s));
      }
    }
  } catch {
    /* 저장소가 막혀 있거나 값이 깨졌다 — 깨진 스티키 값은 통째로 버린다 */
    try { localStorage.removeItem(STICKY); } catch { /* 그래도 못 하면 둔다 */ }
  }
}
