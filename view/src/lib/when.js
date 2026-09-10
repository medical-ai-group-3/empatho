/* 시각을 사람 말로 바꾸는 자리. 화면마다 따로 쓰면 조금씩 달라진다.
 *
 * 서버는 +09:00 이 붙은 ISO 를 준다. 브라우저가 기기 시간대로 옮겨서
 * 보여준다 — 국내 사용자에게는 그대로 KST 다.
 */
export const WDS = ["일", "월", "화", "수", "목", "금", "토"];

const p = (n) => String(n).padStart(2, "0");

/** 2026.09.03 */
export function fmtDay(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`;
}

/** 9월 15일(월) 14:00 */
export function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일(${WDS[d.getDay()]}) `
       + `${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** "1978-04-21" → 1978.04.21
 *
 * 날짜만 있는 문자열이라 **new Date 에 넣지 않는다**(아래 fmtDateKey 와
 * 같은 이유). 여기서는 요일도 필요 없으니 글자만 바꾼다.
 */
export function fmtDayKey(key) {
  if (!key) return "";
  return key.replaceAll("-", ".");
}

/** "2026-09-17" → 9월 17일(목)
 *
 * 날짜만 있는 문자열은 **직접 쪼갠다.** new Date("2026-09-17") 은 UTC
 * 자정으로 읽혀서, 시간대가 UTC 서쪽이면 하루 앞 날짜가 나온다.
 */
export function fmtDateKey(key) {
  if (!key) return "";
  const [y, m, d] = key.split("-").map(Number);
  return `${m}월 ${d}일(${WDS[new Date(y, m - 1, d).getDay()]})`;
}
