import { useSyncExternalStore } from "react";

/* 최근 본 환자 — **브라우저에 남기지 않는다**
 * ════════════════════════════════════════════════════════════════
 *
 * 판독실 PC 는 공용이다. `localStorage` 는 로그아웃해도, 창을 닫아도
 * 남는다. 거기에 환자 이름과 번호를 적어 두면 다음 사람이 그대로 본다.
 *
 * 그래서 **메모리에만** 둔다. 탭을 새로 고치면 사라진다 —
 * **안 남는 것이 기능이다.** 옮길 자리를 찾지 말 것.
 *
 * ⚠ lib/notes.js 와 헷갈리지 말 것. 저쪽은 내가 쓴 글이라 남아야 하고,
 *   이쪽은 남의 개인정보라 남으면 안 된다.
 */

const MAX = 8;

let list = [];
const subs = new Set();

/* 환자 하나를 봤다고 알린다. 같은 환자를 또 열면 맨 앞으로 올린다 */
export function seen(patient) {
  const id = patient?.id ?? patient?.patient_id;
  const name = patient?.name;
  if (id == null || !name) return;

  const row = { id, name, no: patient.no ?? null, what: patient.what ?? null };
  const rest = list.filter((r) => r.id !== id);
  /* 같은 참조를 그대로 두면 useSyncExternalStore 가 안 깨운다 —
     늘 새 배열을 만든다 */
  list = [row, ...rest].slice(0, MAX);
  subs.forEach((fn) => fn());
}

function subscribe(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}

function read() {
  return list;
}

export function useRecent() {
  return useSyncExternalStore(subscribe, read, read);
}
