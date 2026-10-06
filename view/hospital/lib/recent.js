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

/* 환자 하나를 봤다고 알린다. 같은 환자를 또 열면 맨 앞으로 올린다.
 *
 * ⚠ **id 는 반드시 환자 번호(patient id)여야 한다.** 검사 id · 검체 id ·
 *   오더 id 를 넣으면 두 가지가 같이 깨진다 — 같은 환자를 다른 화면에서
 *   열었을 때 아래 중복 제거가 안 걸려 칩이 두세 개로 늘어나고, 번호가
 *   겹치는 순간 **남의 환자를 덮어쓴다.** PatientBar 는 진짜 환자 번호를
 *   같은 목록에 넣기 때문에 섞이면 바로 부딪힌다.
 *
 *   과 홈이 줄마다 들고 있는 id 는 study · specimen · exam_order 것이라
 *   그대로 쓰면 안 된다 — 홈은 따로 실어 둔 `pid` 를 준다(lib/Home.jsx).
 */
export function seen(patient) {
  const id = patient?.id ?? patient?.patient_id;
  const name = patient?.name;
  if (id == null || !name) return;

  /* ⚠ 쓰는 쪽 · 담는 쪽 · 읽는 쪽 세 자리의 칸 이름이 전부 달랐다 —
     홈이 `why` 로 넣고 여기가 `what` 으로 담고 화면이 다시 `why` 를
     읽어서, 「왜 열었는지」 라벨이 한 번도 안 나왔다(09-23 확인).
     과들이 적어 둔 「판독」·「검체 접수」·「문진 · 배정」이 전부 죽은
     글자였다. `why` 하나로 맞춘다 */
  const row = { id, name, no: patient.no ?? null, why: patient.why ?? null };
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
