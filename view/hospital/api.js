/* 서버를 부르는 자리. **fetch 는 여기 말고 쓰지 않는다.**
 *
 * 이 파일이 곧 Django 에 요청할 목록이다. 화면이 필요로 하는 것이 늘면
 * 여기부터 고치고 목업(mock/hospital.json)을 맞춘다.
 *
 * ── 왜 /api/v1/hospital 인가 ──────────────────────────────────
 * 환자 앱과 같은 서버를 쓰지만 **보는 사람이 다르다.** 환자는 자기
 * 자료만 보고, 직원은 남의 자료를 본다 — 권한 판정이 다른 계층이다.
 * 주소를 갈라 두면 그 경계가 주소에 드러나고, 목업도 로그인 상태를
 * 따로 기억할 수 있다(가짜 API 의 쿠키가 갈린다).
 *
 * ⚠ Django 에 아직 이 경로가 없다. 확정되면 여기 한 곳만 맞추면 된다.
 */
const BASE = "/api/v1/hospital";

async function req(method, path, body) {
  const r = await fetch(BASE + path, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  let data = null;
  try { data = await r.json(); } catch { /* 본문이 없을 수 있다 */ }
  if (!r.ok) throw Object.assign(new Error(r.statusText), { status: r.status, ...data });
  return data;
}
const get  = (p)    => req("GET", p);
const post = (p, b) => req("POST", p, b);
const put  = (p, b) => req("PUT", p, b);

export const api = {
  /* 21 · 검체 바인딩 대기 */
  specimens:       ()        => get("/pathology/specimens"),
  specimen:        (id)      => get(`/pathology/specimens/${id}`),
  acceptSpecimen:  (id)      => post(`/pathology/specimens/${id}/accept`),
  rejectSpecimen:  (id, why) => post(`/pathology/specimens/${id}/reject`, { reason: why }),

  /* 24 · 전체 환자 목록 */
  cases:           ()        => get("/pathology/cases"),
  caseDetail:      (id)      => get(`/pathology/cases/${id}`),

  /* 22 · 슬라이드 업로드 */
  upload:          (id)      => get(`/pathology/cases/${id}/upload`),
  analyze:         (id)      => post(`/pathology/cases/${id}/analyze`),

  /* 23 · 판독 */
  read:            (id)      => get(`/pathology/cases/${id}/read`),
  saveRead:        (id, b)   => put(`/pathology/cases/${id}/read`, b),
  draftRead:       (id, b)   => put(`/pathology/cases/${id}/read/draft`, b),
  /* 판독의가 AI 검출을 반박하는 자리. 되먹임이 쌓여야 다음 판이 나아진다 */
  flagFalse:       (id, les) => post(`/pathology/cases/${id}/read/false-positive`, { lesion_id: les }),

  /* 25 · 판독 정정 — **덮어쓰지 않는다.** 새 행으로 쌓인다 */
  amendSource:     (id)      => get(`/pathology/cases/${id}/amend`),
  saveAmend:       (id, b)   => post(`/pathology/cases/${id}/amend`, b),
};
