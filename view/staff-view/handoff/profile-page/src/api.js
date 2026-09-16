/* 서버를 부르는 층 — 화면은 여기만 쓴다. empatho-view/src/api.js 와 같은 규칙:
 * 상대 경로로만 부른다 — 개발은 vite mock/proxy, 배포는 nginx가 같은 주소를 받는다. */
export class ApiError extends Error {
  constructor(status, code, detail) {
    super(detail || code || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code || "UNKNOWN";
    this.detail = detail || "";
  }
}

async function call(path, { method = "GET", body, signal, headers } = {}) {
  if (!path.startsWith("/")) {
    throw new Error(`상대 경로여야 한다: ${path}`);
  }
  const res = await fetch(path, {
    method,
    signal,
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });

  if (res.status === 204) return null;

  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { /* 본문이 JSON 이 아닐 때 */ }
  }

  if (!res.ok) {
    throw new ApiError(res.status, data?.code, data?.detail || text.slice(0, 300));
  }
  return data;
}

export const get   = (p, o)       => call(p, { ...o, method: "GET" });
export const post  = (p, body, o) => call(p, { ...o, method: "POST", body });
export const put   = (p, body, o) => call(p, { ...o, method: "PUT", body });
export const patch = (p, body, o) => call(p, { ...o, method: "PATCH", body });

/* ── 화면이 부르는 것들 — 유방외과_제작_정리본.md §5 신설 엔드포인트 모음 그대로 ── */
export const api = {
  // 대기 큐 (화면 1)
  waitingPatients: () => get("/api/v1/patients?primary_staff=me&status=waiting"),
  patient:         (id) => get(`/api/v1/patients/${id}`),
  createExamOrder: (body) => post("/api/v1/exam-orders", body),
  openDiscordances: (patientId) =>
    get(`/api/v1/discordances?patient=${patientId}&status=open`),

  // 검체 바인딩 (팝업)
  lesions:        (patientId) => get(`/api/v1/lesions?patient=${patientId}`),
  createSpecimen: (body) => post("/api/v1/specimens", body),

  // 수술 결정 (화면 3)
  createAssessment:  (body) => post("/api/v1/assessments", body),
  explainReport:     (reportId, body) => patch(`/api/v1/reports/${reportId}/explain`, body),
  unlockStatus:      (reportId) => get(`/api/v1/reports/${reportId}/unlock-status`),
  unlockReport:      (reportId) => patch(`/api/v1/reports/${reportId}/unlock`, {}),

  // 불일치 처분 (화면 5)
  discordance:       (id) => get(`/api/v1/discordances/${id}`),
  disposeDiscordance: (id, body) => patch(`/api/v1/discordances/${id}/dispose`, body),

  // 검사 종합 확인 · 뷰어
  timeline:      (patientId) => get(`/api/v1/patients/${patientId}/timeline`),
  finalReport:   (patientId) => get(`/api/v1/reports?patient=${patientId}&type=final`),
  saveFinalReport: (reportId, body) => put(`/api/v1/reports/${reportId}`, body),
  studies: (patientId) => get(`/api/v1/patients/${patientId}/studies`),

  // 내 정보 · 설정 (상단바 프로필)
  me:       () => get("/api/v1/staff/me"),
  updateMe: (body) => put("/api/v1/staff/me", body),
  logout:   () => post("/api/v1/auth/logout"),
};
