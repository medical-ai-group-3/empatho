/* 한글 검색 — 치는 도중의 글자도 맞춘다.
 *
 * ⚠ 09-28 「ㄱ」 하나만 쳐도 목록이 0건이 됐다가 돌아와 깜빡였다. 입력기는
 *   글자를 다 짓기 전에 「ㄱ」 → 「기」 → 「김」을 차례로 보낸다. 그대로
 *   includes 로 거르면 「ㄱ」 · 「기」는 「김환자」에 안 맞는다.
 *
 *   · 홀로 선 자음(ㄱ)       → 그 자음으로 시작하는 모든 음절(가~깋)
 *   · 받침 없는 마지막 음절(기) → 그 초성 · 중성의 모든 음절(기~깋)
 *   그래서 「ㄱ」 「기」 「김」 모두 「김환자」에 맞고, 초성만(ㄱㅎㅈ)으로도 찾는다.
 */

const BASE = 0xac00;
const LAST = 0xd7a3;
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";

const esc = (c) => c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const range = (a, b) => `[${String.fromCharCode(a)}-${String.fromCharCode(b)}]`;

/* 검색어 → 정규식. 마지막 글자만 「짓는 중」일 수 있다 */
export function koPattern(q) {
  const s = String(q ?? "").trim().toLowerCase();
  if (!s) return null;
  const chars = [...s];
  const src = chars.map((ch, i) => {
    const ci = CHO.indexOf(ch);
    if (ci >= 0) return range(BASE + ci * 588, BASE + ci * 588 + 587);
    const code = ch.charCodeAt(0);
    const last = i === chars.length - 1;
    if (last && code >= BASE && code <= LAST && (code - BASE) % 28 === 0) {
      return range(code, code + 27);
    }
    return esc(ch);
  }).join("");
  return new RegExp(src);
}

export function koMatch(text, q) {
  const re = q instanceof RegExp ? q : koPattern(q);
  return !re || re.test(String(text ?? "").toLowerCase());
}

/* 서버로 보낼 검색어 — 서버는 includes 로만 거른다. 짓는 중인 끝 글자 ·
 * 홀로 선 자음이 있으면 그 앞까지만 보내고(없으면 안 보낸다) 나머지는
 * 화면이 koMatch 로 거른다. 안 그러면 「ㄱ」에 서버가 0건을 준다 */
export function koServerQuery(q) {
  const chars = [...String(q ?? "").trim()];
  const cut = chars.findIndex((ch, i) => {
    if (CHO.includes(ch)) return true;
    const code = ch.charCodeAt(0);
    return i === chars.length - 1 && code >= BASE && code <= LAST && (code - BASE) % 28 === 0;
  });
  const out = (cut < 0 ? chars : chars.slice(0, cut)).join("").trim();
  return out || undefined;
}
