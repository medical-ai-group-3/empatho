/* 할 일 · 인계 사항 — 저장하는 자리를 한 곳에 가둔다
 * ════════════════════════════════════════════════════════════════
 *
 * 지금은 이 브라우저에만 남는다. 서버에 `staff_note` 표가 생기면
 * **이 파일의 read · write 두 함수만** 바꾼다. 화면은 한 줄도 안 고친다.
 *
 *   지금        localStorage[`empatho.note.${kind}:${dept}`]
 *   나중        GET/POST /notes · PATCH/DELETE /notes/{id}
 *
 * 그래서 화면은 «어디에 저장되는가»를 모른다. 알면 옮길 때 화면까지
 * 같이 고쳐야 하고, 그러면 옮기는 값이 없다.
 *
 * ── 두 가지를 담는다 ──────────────────────────────────────────
 *   todo      내 할 일. 나만 본다
 *   handover  인계 사항. 그 과 전체가 본다 — 교대 메모지 환자 기록이 아니다
 *
 * ⚠ **환자 기록을 여기 담지 않는다.** 브라우저에만 있는 값이라 다른
 *   사람 화면에 안 보이고, 이 컴퓨터를 지우면 같이 사라진다.
 */

const PREFIX = "empatho.note";

/* 과마다 따로 둔다. 영상의학과 인계가 병리과 화면에 뜨면 안 된다 */
function keyOf(kind, dept) {
  return `${PREFIX}.${kind}:${dept}`;
}

/* ── 읽기 · 쓰기 — 옮길 때 여기 둘만 바꾼다 ────────────────────
 *
 * ⚠ **JSON 이 깨져도 화면이 죽지 않게 한다.** 손으로 고쳤거나 옛 판이
 *   남아 있을 수 있다. 못 읽으면 빈 목록으로 시작한다 — 메모 하나 때문에
 *   과 홈이 통째로 안 뜨면 안 된다.
 */
export function read(kind, dept) {
  try {
    const raw = localStorage.getItem(keyOf(kind, dept));
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

export function write(kind, dept, list) {
  try {
    localStorage.setItem(keyOf(kind, dept), JSON.stringify(list));
  } catch {
    /* 저장 공간이 찼거나 막혀 있다. 화면은 그대로 돌아야 한다 */
  }
}

/* ── 화면이 쓰는 것 ───────────────────────────────────────────
 * id 는 여기서 만든다. 서버로 옮기면 서버가 발번한다 — 그때도 화면은
 * `it.id` 만 보므로 안 고친다.
 */
export function add(kind, dept, body) {
  const text = String(body ?? "").trim();
  if (!text) return read(kind, dept);
  const list = [...read(kind, dept), {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    body: text,
    done: false,
    at: new Date().toISOString(),
  }];
  write(kind, dept, list);
  return list;
}

export function toggle(kind, dept, id) {
  const list = read(kind, dept).map(
    (it) => (it.id === id ? { ...it, done: !it.done } : it));
  write(kind, dept, list);
  return list;
}

export function remove(kind, dept, id) {
  const list = read(kind, dept).filter((it) => it.id !== id);
  write(kind, dept, list);
  return list;
}
