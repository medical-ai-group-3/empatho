/* 「09-21 10:11」 — 해를 뺀 짧은 일시. 해가 올해가 아니면 「25-09-21」
   처럼 해 끝 두 자리를 앞에 둔다(몇 해 전 검사를 올해로 읽지 않게).
   시각이 없거나 00:00 이면 날짜만 */
export function shortAt(value, now = new Date()) {
  if (!value) return null;
  const s = String(value);
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?/);
  if (!m) return s.slice(0, 16);
  const day = m[1] === String(now.getFullYear()) ? `${m[2]}-${m[3]}` : `${m[1].slice(2)}-${m[2]}-${m[3]}`;
  return m[4] && m[4] !== "00:00" ? `${day} ${m[4]}` : day;
}
