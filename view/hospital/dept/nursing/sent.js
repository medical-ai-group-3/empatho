/* 유방외과로 보낸 오더 — 오늘 것만 기억한다
 * ════════════════════════════════════════════════════════════════
 *
 * [유방외과 큐로 보내기] 는 환자의 primary_staff 만 바꾼다. 오더의 status 는
 * 그대로 requested 라서 내원 대기 목록(`status=requested&visited=yes`)이
 * 그 사람을 **계속 다시 준다.** 보냈는데 줄에 남아 있으면 창구에서 또 보낸다.
 *
 * 서버가 배정된 오더를 거르는 조건(또는 상태 하나)을 줄 때까지 화면이
 * 보낸 오더 번호를 적어 두고 목록에서 뺀다. 접수 현황판의 「외래 진료」
 * 칸도 이것을 센다.
 *
 * ⚠ **오더 번호와 환자 번호만 남긴다.** 이름·전화는 안 적는다 — 공용 PC 라
 *   다음 사람이 본다(lib/recent.js 와 같은 까닭).
 * ⚠ 날짜가 바뀌면 통째로 비운다. 어제 보낸 오더는 오늘 목록에 없다.
 */
const KEY = "empatho.nursing.sent";

const todayKey = () => {
  const n = new Date();
  return `${n.getFullYear()}-${n.getMonth() + 1}-${n.getDate()}`;
};

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (raw?.day === todayKey() && Array.isArray(raw.list)) return raw.list;
  } catch { /* 못 읽으면 빈 것으로 */ }
  return [];
}

function save(list) {
  try { localStorage.setItem(KEY, JSON.stringify({ day: todayKey(), list })); }
  catch { /* 못 적어도 이 화면이 사는 동안은 아래 목록이 기억한다 */ }
}

let mem = load();

/* 보냈다고 적는다 */
export function markSent(orderId, patientId, staffId) {
  mem = [...sentList().filter((r) => String(r.order) !== String(orderId)),
    { order: orderId, patient: patientId ?? null, staff: staffId ?? null }];
  save(mem);
}

/* 오늘 보낸 것 전부 */
export function sentList() {
  const stored = load();
  if (stored.length) mem = stored;
  return mem;
}

/* 이 줄(오더)이 이미 보낸 것인가 */
export function isSent(row) {
  const id = row?.exam_order_id ?? row?.id;
  return sentList().some((r) => String(r.order) === String(id));
}
