/* 유방외과에서 다른 과로 넘긴 환자 — 오늘 「결과 대기」 묶음으로 내린다.
 *
 * 촬영 요청·검체 바인딩 API는 새 작업을 만들지만 기존 Patient의
 * `status=waiting`을 대기 목록에서 빼는 상태 전환 API는 없다. 그래서 오늘
 * 넘긴 환자를 브라우저에 적어 두고 대기 환자 화면이 그 줄을 목록 아래
 * 접힌 「결과 대기」 묶음으로 옮긴다.
 *
 * ⚠ 09-28 — 전에는 **그날 하루 숨겼다.** 같은 날 판독이 돌아와도 그 환자가
 *   목록에 안 떠서 결과를 못 보고 넘겼다. 이제 숨기지 않는다 — 묶음은 늘
 *   보이고, 결과가 돌아오면(서버 worklist 의 next_step 이 wait_results 가
 *   아니게 되거나, 고른 환자의 흐름이 대기를 벗어나면) unmark 로 위로 올린다.
 * ⚠ 서버 worklist 가 있으면 이 파일은 안 쓰인다 — 서버가 결과 대기를 센다.
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

/* 결과가 돌아왔다 — 묶음에서 빼서 대기 줄로 올린다 */
export function unmarkHandled(patientId) {
  if (patientId == null || !isHandled(patientId)) return;
  save(load().filter((id) => String(id) !== String(patientId)));
}
