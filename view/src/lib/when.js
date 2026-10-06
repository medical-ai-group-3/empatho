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

/** 알림 목록의 왼쪽 칸 — 오늘 10:24 · 어제 · 9.8
 *
 * 알림은 **언제 왔는지가 먼 것일수록 덜 중요하다.** 오늘 온 것은 몇 시에
 * 왔는지가 궁금하고, 지난달 것은 날짜만 알면 된다. 그래서 가까울수록
 * 자세히 적는다.
 *
 * 「3시간 전」처럼 흐르는 말은 안 쓴다. 화면을 열어 둔 채로 시간이
 * 지나면 틀린 말이 되고, 다시 그리기 전까지 그대로 남는다.
 */
export function fmtStamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();

  // 날짜만 떼어 견준다. 시각까지 넣고 빼면 «23시간 전»이 어제가 된다
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
  const diff = Math.round((day(now) - day(d)) / 86400000);

  if (diff === 0) return `${p(d.getHours())}:${p(d.getMinutes())}`;
  if (diff === 1) return "어제";
  return `${d.getMonth() + 1}.${d.getDate()}`;
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
