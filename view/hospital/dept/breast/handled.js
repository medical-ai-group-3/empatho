/* 유방외과에서 다른 과로 넘긴 환자 — 오늘 대기 목록에서 숨긴다.
 *
 * 촬영 요청·검체 바인딩 API는 새 작업을 만들지만 기존 Patient의
 * `status=waiting`을 대기 목록에서 제외하는 상태 전환 API는 없다. 간호과의
 * 배정 후 숨김과 같은 운영 규칙을 적용해, 오늘 처리한 환자를 브라우저에
 * 기록한다. 서버에 handoff 상태가 생기면 이 파일만 서버 조회로 바꾸면 된다.
 */
const KEY = "empatho.breast.handed";

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return raw?.day === today() && Array.isArray(raw.ids) ? raw.ids : [];
  } catch {
    return [];
  }
}

function save(ids) {
  try { localStorage.setItem(KEY, JSON.stringify({ day: today(), ids })); }
  catch { /* 저장이 막혀도 현재 화면 동작은 유지한다 */ }
}

export function isHandled(patientId) {
  return load().some((id) => String(id) === String(patientId));
}

export function markHandled(patientId) {
  if (patientId == null) return;
  const ids = load().filter((id) => String(id) !== String(patientId));
  save([...ids, patientId]);
}
