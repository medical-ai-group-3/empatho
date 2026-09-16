/* 서버를 부르는 자리 — 화면에서 fetch 를 직접 쓰지 않는다
 * ────────────────────────────────────────────────────────────────
 *
 * 목업에서 실제 서버로 갈아탈 때 **고칠 곳은 ⚠ 표시한 셋뿐이다.**
 *   ⚠1  BASE        주소 앞머리
 *   ⚠2  unwrap()    응답 봉투를 벗기는 방식
 *   ⚠3  setToken()  로그인 토큰을 넣는 자리
 *
 * 2026-09-15 최일운님 회신 반영분
 *   · 직원용 접두 경로를 따로 두지 않는다. 실제 서버는 그냥 /api/v1 이다.
 *     /reports 는 직원과 환자가 **같은 경로**를 쓰고 서버 권한
 *     (MatrixPermission own_only) 으로만 갈린다
 *   · 대기 큐가 분리되어 있다. GET /specimens/queue (전체 목록은 /specimens)
 *   · GET /ai-results 는 진행 상태 하나로 나간다
 *     { status: "queued"|"running"|"done"|"failed", pct: 0~100 }
 *
 * 2026-09-16 최일운님 회신 반영분
 *   · 응답 봉투 **확정**
 *       성공  { success:true,  data:…,   error:null, trace_id:"01JB2K…" }
 *       실패  { success:false, data:null,
 *               error:{ code, message, details }, trace_id:"01JB2K…" }
 *     trace_id 는 헤더 X-Trace-Id 에도 온다. 오류 화면에 작게 띄운다 —
 *     서버 쪽에서 로그를 찾을 때 이 값으로 찾는다
 *   · 배정 충돌은 409 + ALREADY_ASSIGNED. 영상·병리 공용이다
 *   · 영상 대기 큐도 /exam-orders/queue 로 통일
 *
 * 2026-09-16 2차 회신 반영분
 *   · 영상 판독 조회에 **과 이름이 앞에 붙는다** — /radiology/studies/{id}/read
 *     ⚠ 업로드 조회도 붙는지는 아직 답을 못 받았다. 아래 RAD 한 줄로 뺐다
 *   · **병리는 판독 조회 경로가 없다.** 상세(GET /specimens/{id})와
 *     업로드 조회를 합쳐 쓴다 — dept/pathology.jsx 의 read 참고
 *   · 저장 파일 목록은 **업로드 조회에만** 있다. 판독 화면이 한 번 더 부른다
 *   · 정정 사유는 판정 표의 decision_reason (250자)
 *
 * 2026-09-16 3차 · 다희님(병리) 경로표 대조 결과
 *   · 에러 코드 철자를 명세표대로 맞췄다 — FORBIDDEN 이 아니라 ROLE_FORBIDDEN
 *   · 큐는 **서버가 안 걸러 준다.** ?status=bound&assigned=none 을 우리가 담는다
 *   · 슬래시는 **목록·생성에만** 붙는다. 나머지는 지금처럼 안 붙이는 게 맞다
 *   · 진행 상태는 status 가 맞다. run_status 는 서버 DB 컬럼명이라 안 나온다
 *   · POST /tickets 는 **있다** (다희님 문서에서 빠졌던 것)
 *
 *   ⚠ 아직 서버에 없다 — «만드는 중» 이라고 회신받았다. 생기기 전에는
 *     실서버(npm run dev)로 화면이 안 뜬다. 목업에는 셋 다 있다
 *       GET /me                      없으면 main.jsx 의 Boot 에서 앱이 멈춘다
 *       GET /specimens/{id}          1·3·4·5장
 *       GET /specimens/{id}/upload   2·3장 (올린 파일 목록은 여기에만 있다)
 */

/* ⚠1 ── 주소 앞머리 ───────────────────────────────────────────
 *
 * 목업일 때만 /api/v1/hospital 을 쓴다. 이건 **목업 서버를 환자 앱
 * 목업과 갈라놓기 위한 것**이지 실제 서버 규격이 아니다.
 * 실제 서버는 /api/v1 하나다.
 *
 * .env.local 의 VITE_API_BASE 로 덮을 수 있다. 코드는 안 고쳐도 된다.
 */
const MOCK = "/api/v1/hospital";
const REAL = "/api/v1";

const BASE =
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.MODE === "mock" ? MOCK : REAL);

/* ⚠3 ── 토큰 ─────────────────────────────────────────────────
 * 메모리에만 둔다. localStorage 에 넣지 않는다 — 다른 스크립트가
 * 읽어갈 수 있고, 로그아웃해도 안 지워진다.
 */
let token = null;
export const setToken = (t) => { token = t; };

/* ⚠2 ── 응답 봉투 ────────────────────────────────────────────
 * 성공·실패 둘 다 한 겹이다.
 *
 *   { success: true,  data: …,    error: null,  trace_id: "01JB2K…" }
 *   { success: false, data: null, error: { code, message, details },
 *     trace_id: "01JB2K…" }
 *
 * 화면은 봉투를 모른다. 여기서 벗겨서 알맹이만 넘긴다.
 */
function unwrap(o) {
  return o && typeof o === "object" && "data" in o ? o.data : o;
}

/* 오류를 한 모양으로 만든다 — { status, code, detail, fields, traceId }
 *
 * 서버 이름과 화면 이름이 다르다. **여기 한 곳에서만 바꿔 준다** —
 * 화면 스무 곳이 message 인지 detail 인지 신경 쓰게 하지 않는다.
 *
 *   error.message  →  detail   사람에게 보여주는 문장
 *   error.details  →  fields   칸별 오류
 *
 * traceId 는 오류 화면에 작게 띄운다. 본문에 없으면 헤더에서 줍는다. */
function unwrapError(o, status, statusText, traceId) {
  const e = o?.error ?? null;
  return Object.assign(
    new Error(e?.message || statusText || "요청에 실패했습니다"),
    {
      status,
      code: e?.code ?? null,
      detail: e?.message ?? null,
      fields: e?.details ?? null,
      traceId: o?.trace_id ?? traceId ?? null,
    },
  );
}

/* 서버가 쓰는 error.code 목록 — 2026-09-16 다희님 명세표 그대로다.
 *
 * ⚠ 이름을 마음대로 줄이지 않는다. 전에 ROLE_FORBIDDEN 을 FORBIDDEN 으로
 *   적어 뒀었는데, 이러면 e.code 비교가 **조용히 안 걸린다**. 오류가 나는
 *   게 아니라 그냥 분기를 안 타서, 화면에서는 아무 일도 안 일어난 것처럼
 *   보인다. 서버가 보내는 철자를 그대로 적는다.
 *
 * NETWORK 만 우리가 만든 것이다 — 서버에 닿지도 못한 경우라 서버가 코드를
 * 줄 수가 없다. call() 의 catch 에서 붙인다. */
export const ERR = {
  VALIDATION_ERROR: "VALIDATION_ERROR",   // 400 · 입력값 문제 (fields 를 본다)
  UNAUTHENTICATED:  "UNAUTHENTICATED",    // 401 · 토큰 없음/만료
  ROLE_FORBIDDEN:   "ROLE_FORBIDDEN",     // 403 · 권한 없음
  NOT_FOUND:        "NOT_FOUND",          // 404 · 대상 없음
  ALREADY_ASSIGNED: "ALREADY_ASSIGNED",   // 409 · 다른 사람이 먼저 집었다
  NETWORK:          "NETWORK",            // status 0 · 서버에 못 닿았다 (우리가 만든 것)
};

async function call(method, path, body) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : null),
        ...(token ? { Authorization: `Bearer ${token}` } : null),
      },
      body: body ? JSON.stringify(body) : undefined,
      credentials: "include",
    });
  } catch (e) {
    /* 서버에 닿지도 못했다. 브라우저 기본 문구("Failed to fetch")가
       화면에 그대로 뜨지 않게 우리 모양으로 바꾼다 */
    throw Object.assign(new Error("서버에 연결하지 못했습니다"), {
      status: 0, code: ERR.NETWORK, detail: e?.message ?? null,
      fields: null, traceId: null,
    });
  }

  const traceId = res.headers.get("X-Trace-Id");
  if (res.status === 204) return null;

  let payload = null;
  try { payload = await res.json(); } catch { /* 본문 없음 */ }

  if (!res.ok) throw unwrapError(payload, res.status, res.statusText, traceId);

  /* 상태는 200 인데 봉투가 실패라고 말하는 경우도 받아 둔다 */
  if (payload && payload.success === false) {
    throw unwrapError(payload, res.status, res.statusText, traceId);
  }
  return unwrap(payload);
}

const get   = (p)    => call("GET", p);
const post  = (p, b) => call("POST", p, b);
const put   = (p, b) => call("PUT", p, b);
const patch = (p, b) => call("PATCH", p, b);

function qs(o = {}) {
  const e = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? `?${new URLSearchParams(e)}` : "";
}

/* ── 로그인한 사람 ────────────────────────────────────────────
 * perms 배열이 여기 실려 온다. perm.js 의 setMe() 에 넣어 쓴다.
 *
 * updateMe 는 **본인이 고칠 수 있는 것만** 보낸다 — 이름 · 이메일 ·
 * 연락처 · 알림 설정. 소속 · 사번 · 직책 · 권한은 관리자 몫이라 화면에서
 * 읽기 전용으로 띄우고 여기로 안 보낸다.
 *
 * 부분 갱신이라 PUT 이 아니라 **PATCH 가 맞는 모양**이지만, staff-view 가
 * 이미 PUT 으로 쓰고 있어서 맞춰 둔다. 서버가 정해지면 한 줄만 고친다.
 */
export const me = () => get("/me");
export const updateMe = (b) => put("/me", b);

/* ── 로그아웃 ────────────────────────────────────────────────
 *
 * ⚠ **경로가 아직 명세에 없다.** 다희님 병리 경로표(9/16)에 로그인은
 *   POST /api/v1/login 으로 있는데 로그아웃이 빠져 있다. 짝이 맞게
 *   /logout 으로 둔다 — staff-view 가 쓰던 /auth/logout 은 /auth 접두가
 *   로그인 쪽에 없어서 혼자 튄다. 확정되면 이 한 줄만 고친다.
 *
 * 서버를 부르는 것이 **핵심이다.** 화면에서 토큰만 버리면 브라우저에서만
 * 사라지고 서버 쪽 refresh 토큰은 만료까지 살아 있어서, 실제로는
 * 로그아웃이 안 된 상태가 된다.
 *
 * 서버가 실패해도 토큰은 버린다. 「로그아웃을 눌렀는데 로그인된 채로
 * 남는」 것이 제일 나쁘다 — 공용 PC 에서 자리를 뜬 뒤다.
 */
export async function logout() {
  try {
    return await post("/logout");
  } finally {
    setToken(null);
  }
}

/* ── 병리과 ───────────────────────────────────────────────────
 * 판독 단위는 검체(specimen) 다. */
export const path = {
  /* ⚠ 서버는 큐를 **기본 필터 없이** 준다 (2026-09-16 다희님 확인).
     이 두 조건을 안 담으면 이미 남이 집어간 검체까지 대기 큐에 뜬다.
     기본값이 아니라 **우리가 정하는 조건**이라 여기 적어 둔다 */
  queue:      ()       => get(`/specimens/queue${qs({ status: "bound", assigned: "none" })}`),
  specimen:   (id)     => get(`/specimens/${id}`),
  assign:     (id)     => patch(`/specimens/${id}/assign`),

  uploadInfo: (id)     => get(`/specimens/${id}/upload`),
  ticket:     (b)      => post("/tickets", b),   /* lib/files.js 가 쓴다 */
  analyze:    (id)     => post(`/specimens/${id}/ai-results`),
  progress:   (id)     => get(`/ai-results${qs({ specimen: id })}`),

  /* ⚠ 병리는 판독 조회 경로가 없다. 상세와 업로드 조회를 합쳐 쓴다 —
     dept/pathology.jsx 의 read 참고. 경로가 생기면 여기 한 줄 추가하고
     그쪽 합치는 코드를 지우면 된다 */
  draft:      (id, b)  => put(`/specimens/${id}/draft`, b),
  finalize:   (id, b)  => patch(`/specimens/${id}/finalize`, b),

  /* ⚠ 슬래시가 붙는다. **목록·생성만** 그렇다 (2026-09-16 확인).
     queue·assign·upload·draft·finalize·amend 는 슬래시가 없는 게 맞다.
     Django APPEND_SLASH 가 GET 은 301 로 넘겨 주지만 POST 는 그 과정에서
     본문이 날아가므로, 붙는 자리는 처음부터 붙여 둔다 */
  list:       (o = {}) => get(`/specimens/${qs(o)}`),
  amend:      (id, b)  => post(`/specimens/${id}/amend`, b),
};

/* ── 영상의학과 ───────────────────────────────────────────────
 * 판독 단위는 검사(study) 다. 대기 큐는 오더(exam_order) 를 본다.
 *
 * ⚠ 과 이름 접두 — 판독 조회가 /radiology/studies/{id}/read 다.
 *   나머지 경로에도 붙는지 답을 못 받아서 **한 줄로 빼 두었다.**
 *   전부 붙는다면 아래 RAD 를 쓰는 자리를 늘리면 되고, 판독 조회만
 *   붙는 것이면 지금 그대로다.
 */
const RAD = "/radiology";

export const rad = {
  /* 병리와 같은 모양으로 통일됐다 (2026-09-16 확인).
     명세에 질의로 적혀 있던 것은 통일 전 표기다 */
  queue:      ()       => get("/exam-orders/queue"),
  order:      (id)     => get(`/exam-orders/${id}`),
  assign:     (id)     => patch(`/exam-orders/${id}/assign`),

  uploadInfo: (id)     => get(`/studies/${id}/upload`),
  ticket:     (b)      => post("/tickets", b),
  complete:   (id)     => patch(`/exam-orders/${id}/complete`),
  analyze:    (id)     => post(`/studies/${id}/ai-results`),
  progress:   (id)     => get(`/ai-results${qs({ study: id })}`),
  retake:     (b)      => post("/exam-orders", b),

  read:       (id)     => get(`${RAD}/studies/${id}/read`),
  draft:      (id, b)  => put(`/studies/${id}/assessment/draft`, b),
  finalize:   (id, b)  => patch(`/studies/${id}/finalize`, b),

  addLesion:  (b)      => post("/lesions", b),
  falsePos:   (id)     => patch(`/lesions/${id}`, { is_false_positive: true }),

  study:      (id)     => get(`/studies/${id}`),
  list:       (o = {}) => get(`/studies${qs(o)}`),
  history:    (id)     => get(`/assessments${qs({ study: id })}`),
  amend:      (id, b)  => post(`/assessments/${id}/amend`, b),
};

/* 부서 key 로 골라 쓴다 — 공통 화면들이 이걸로 갈라 부른다 */
export const byDept = { pathology: path, radiology: rad };

export const apiInfo = { base: BASE, mock: BASE === MOCK };
