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

/* ── access 만료 시 조용히 갱신 ────────────────────────────────
 *
 * access 는 30분이고 판독은 한 건에 20~30분씩 걸린다. 저장을 누르는
 * 순간이 딱 경계라, 그냥 두면 **써 둔 소견이 날아간다.** 401 을 받으면
 * 한 번 갱신하고 원래 요청을 다시 보낸다.
 *
 *   POST /api/v1/token/refresh   본문 없음 → { access }
 *
 * ⚠ **본문에 refresh 를 싣지 않는다.** 서버가 httpOnly 쿠키에서 직접
 *   읽는다. 그래서 JS 는 refresh 값을 아예 모른다 — credentials:"include"
 *   가 쿠키를 실어 보내는 것이 전부다. 그게 빠지면 쿠키가 안 가서
 *   갱신이 401 로 떨어진다 (전에 났던 사고다).
 *
 * 한 번에 하나만 돈다. 화면 여러 곳이 동시에 401 을 맞아도 갱신은 한 번만
 * 부르고 나머지는 그 결과를 기다린다 — 안 그러면 갱신을 네댓 번 부른다.
 */
let refreshing = null;

/* 갱신된 access 를 저장소에도 반영해야 한다. 그 일은 lib/session.js 가
   하는데 그쪽이 이 파일을 import 하고 있어서, 여기서 부르면 서로 물린다.
   그래서 session.js 가 자기를 등록하고 여기서는 부르기만 한다. */
let onRefreshed = null;
export const setOnRefreshed = (fn) => { onRefreshed = fn; };

async function refreshAccess() {
  refreshing ??= (async () => {
    try {
      const d = await call("POST", "/token/refresh", undefined, { noRetry: true });
      const next = d?.access ?? null;
      if (!next) return null;
      setToken(next);
      onRefreshed?.(next);
      return next;
    } catch {
      return null;               /* 갱신도 실패 — 다시 로그인하는 수밖에 없다 */
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/* 갱신을 시도하면 안 되는 경로. 로그인·로그아웃은 애초에 토큰이 없거나
   버리는 중이고, 갱신 자신에게 갱신을 걸면 무한히 돈다 */
const NO_RETRY = new Set(["/login", "/logout", "/token/refresh"]);

async function call(method, path, body, opt = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : null),
        ...(token ? { Authorization: `Bearer ${token}` } : null),
      },
      body: body ? JSON.stringify(body) : undefined,
      /* ⚠ 빼지 말 것. refresh 가 httpOnly 쿠키에 있어서 이게 없으면
         쿠키가 안 실린다 — 로그인도 갱신도 못 한다 */
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

  /* 401 — access 가 만료됐다. 한 번 갱신하고 그대로 다시 보낸다.
     갱신도 실패하면 아래로 흘려보내 평소대로 401 오류가 되게 한다 */
  if (res.status === 401 && !opt.noRetry && !NO_RETRY.has(path)) {
    const next = await refreshAccess();
    if (next) return call(method, path, body, { noRetry: true });
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

/* ── 로그인 ───────────────────────────────────────────────────
 * 경로를 다희님 브랜치에서 확인했다 — 맞는 것은 /login 이다.
 * 환자 앱(src/api.js)이 쓰는 /auth/login 은 백엔드에 없는 경로다.
 *
 *   POST /api/v1/login  { login_id, password }  →  { access }
 *
 * ⚠ **본문에 refresh 가 없다** (2026-09-16 백엔드 확인). refresh 는
 *   Set-Cookie 로만 내려온다 — httpOnly · Secure · SameSite=None.
 *   JS 가 못 읽는 자리라 우리가 들고 있을 것이 없다. 앞뒤 화면이
 *   다른 origin 이라 Lax 가 아니라 None 이고, 그래서 Secure 가 필수다.
 *
 * 받은 access 는 lib/session.js 가 setToken() 에 끼운다.
 * ⚠ 응답에 role · perms 가 없다. 그건 아래 me() 가 가져온다. */
export const login = (loginId, password) =>
  post("/login", { login_id: loginId, password });

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
 * 경로는 POST /api/v1/logout 이 맞다 (2026-09-16 백엔드 확인).
 *
 * ⚠ **지금 이 로그아웃은 절반만 한다.** 서버가 refresh 쿠키를 지울 뿐
 *   서버 쪽 refresh 토큰 자체를 무효화하지 않는다 — 폐기 저장소(Redis)가
 *   들어와야 성립하고, 그건 이번 판 범위 밖이라고 회신받았다.
 *   그래서 **쿠키를 손에 넣은 사람은 14일 동안 계속 쓸 수 있다.**
 *   공용 PC 를 쓰는 화면이라 팀에서 따로 정해야 할 사안이다.
 *
 * 서버를 부르는 것이 **핵심이다.** 화면에서 토큰만 버리면 브라우저에서만
 * 사라지고 서버 쪽 refresh 토큰은 만료까지 살아 있어서, 실제로는
 * 로그아웃이 안 된 상태가 된다.
 *
 * 서버가 실패해도 토큰은 버린다. 「로그아웃을 눌렀는데 로그인된 채로
 * 남는」 것이 제일 나쁘다 — 공용 PC 에서 자리를 뜬 뒤다.
 *
 * ⚠ 여기서 버리는 것은 **이 파일이 들고 있는 토큰뿐이다.** 저장소
 *   (sessionStorage)는 lib/session.js 가 들고 있다. 화면은 이것과 함께
 *   session.js 의 signOut() 도 불러야 한다 — 안 그러면 새로고침에
 *   토큰이 되살아난다. 여기서 session.js 를 부르지 않는 이유는 그쪽이
 *   이 파일을 import 하고 있어서 서로 물리기 때문이다.
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
  /* ⚠ 상세에도 슬래시가 붙는다 (2026-09-16 다희님이 직접 요청을 넣어
     확인). 전에 「병리는 상세에 슬래시가 없다」고 들었던 것이 틀렸다 —
     슬래시 없이 부르면 그냥 404 다.

     걱정했던 「PATCH 가 301 을 타면서 본문이 사라진다」는 일어나지
     않는다. 이 API 는 맨 뒤에 캐치올 라우트가 있어서 APPEND_SLASH
     리다이렉트 자체가 안 일어난다. 슬래시를 빠뜨리면 늘 깔끔한 404 다.

     ⚠ 아래 custom action 들(queue·assign·upload·draft·finalize·amend)은
       「슬래시 없음」으로 들었는데, 그 확인도 같은 회신에서 나온 것이라
       되물어 두었다. DRF 라우터는 @action 에도 슬래시를 붙이는 것이
       기본이라 함께 확인이 필요하다. */
  specimen:   (id)     => get(`/specimens/${id}/`),
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
  /* ⚠ 서버는 큐를 **기본 필터 없이** 준다 (2026-09-16 다희님 확인).
     병리와 같은 사정인데 값이 다르다 — 영상은 status=ordered 다.
     안 담으면 이미 촬영·배정이 끝난 건까지 대기 큐에 섞인다.

     ⚠ 다희님 회신에 이 경로가 두 가지로 적혀 있었다. 표에는
       GET /exam-orders/queue, 접두 설명에는 radiology/queue 다.
       어느 쪽인지 되물어 두었고, 답이 올 때까지 표 쪽을 따른다 —
       지금까지 쓰던 것이고 목업도 그 모양이다. */
  queue:      ()       => get(`/exam-orders/queue${qs({ status: "ordered", assigned: "none" })}`),
  order:      (id)     => get(`/exam-orders/${id}`),
  assign:     (id)     => patch(`/exam-orders/${id}/assign`),

  /* ⚠ **Study 를 만드는 유일한 경로다** (2026-09-16 확인).
     오더를 집은 뒤 여기를 부르면 그때 Study 행이 생기고 study_id 가
     돌아온다. 이걸 안 부르면 study_id 를 받을 데가 없어서, 업로드·판독이
     오더 id 를 study id 자리에 쓰게 된다 — 실제로 그 상태였다.

     집기(assign) 다음에 부른다. 순서를 바꾸면 두 사람이 동시에 눌렀을 때
     둘 다 Study 를 만들어 놓고 한쪽만 409 로 떨어져 고아 행이 남는다. */
  start:      (id)     => post(`${RAD}/queue/${id}/start-study`),

  /* ⚠ **과 이름이 붙는다.** /studies/{id}/upload 가 아니라
     /radiology/studies/{id}/upload 다 (2026-09-16 정정). 판독 조회와
     같은 자리에 있다. 전에 「판독 조회만 붙는다」고 들었던 것이 틀렸다. */
  uploadInfo: (id)     => get(`${RAD}/studies/${id}/upload`),
  ticket:     (b)      => post("/tickets", b),
  complete:   (id)     => patch(`/exam-orders/${id}/complete`),
  analyze:    (id)     => post(`/studies/${id}/ai-results`),
  progress:   (id)     => get(`/ai-results${qs({ study: id })}`),
  retake:     (b)      => post("/exam-orders", b),

  read:       (id)     => get(`${RAD}/studies/${id}/read`),
  draft:      (id, b)  => put(`/studies/${id}/assessment/draft`, b),
  finalize:   (id, b)  => patch(`/studies/${id}/finalize`, b),

  /* ⚠ 여기 넷만 슬래시가 붙는다 (2026-09-16 다희님이 경로를 콕 집어 주심).
     ⚠ 다만 회신 안에 모순이 있어 되물어 두었다 — 「병리와 같은 규칙,
       목록·생성만」이라고 하시면서 정작 상세(/studies/{id}/)와
       수정(/lesions/{id}/)을 같이 적으셨다. 병리는 상세에 슬래시가 없다.

       **PATCH 가 걸리면 조용히 깨진다.** Django APPEND_SLASH 는 슬래시가
       모자라면 301 로 넘겨 주는데, 그 과정에서 본문이 사라진다. falsePos 가
       200 을 받고도 아무것도 안 바뀌는 모양이 된다.
       일단 적어 주신 그대로 따른다. */
  addLesion:  (b)      => post("/lesions/", b),
  falsePos:   (id)     => patch(`/lesions/${id}/`, { is_false_positive: true }),

  study:      (id)     => get(`/studies/${id}/`),
  list:       (o = {}) => get(`/studies/${qs(o)}`),
  history:    (id)     => get(`/assessments${qs({ study: id })}`),
  amend:      (id, b)  => post(`/assessments/${id}/amend`, b),
};

/* ── 유방외과 ─────────────────────────────────────────────────
 * 판독 단위가 없다. **환자가 단위다.**
 *
 * 병리·영상과 결이 다르다 — 집는 절차가 없고(주치의로 배정된 환자가 곧
 * 큐다) 파일을 올리는 단계도 없다. 대신 다른 과로 일을 **내보내는** 쪽이다:
 *   검사 오더  → 영상의학과 대기 큐에 오더가 생긴다
 *   검체 바인딩 → 병리과 대기 큐에 검체가 생긴다
 * 그래서 queue/upload/read/amend 이름을 억지로 맞추지 않는다.
 *
 * 2026-09-16 — staff-view/src/api.js 에서 옮겨 왔다. 그쪽은 봉투를 안
 * 벗기는 자체 call() 을 쓰고 있었는데, 여기 call() 은 벗겨서 준다.
 * 화면은 그대로 두고 이 층만 갈아 끼우면 된다. */
export const breast = {
  /* 1장 · 대기 환자 */
  waiting:      ()   => get(`/patients${qs({ primary_staff: "me", status: "waiting" })}`),
  patient:      (id) => get(`/patients/${id}`),
  examOrder:    (b)  => post("/exam-orders", b),
  openDiscords: (pid) => get(`/discordances${qs({ patient: pid, status: "open" })}`),

  /* 검체 바인딩 (팝업) — 병리과 대기 큐로 넘어간다 */
  lesions:      (pid) => get(`/lesions${qs({ patient: pid })}`),
  bindSpecimen: (b)  => post("/specimens", b),

  /* 2장 · 검사 종합 확인 */
  timeline:     (pid) => get(`/patients/${pid}/timeline`),
  studies:      (pid) => get(`/patients/${pid}/studies`),
  finalReport:  (pid) => get(`/reports${qs({ patient: pid, type: "final" })}`),

  /* 3장 · 수술 결정 */
  assess:       (b)  => post("/assessments", b),
  saveReport:   (rid, b) => put(`/reports/${rid}`, b),
  explain:      (rid, b) => patch(`/reports/${rid}/explain`, b),
  unlockStatus: (rid) => get(`/reports/${rid}/unlock-status`),
  unlock:       (rid) => patch(`/reports/${rid}/unlock`, {}),

  /* 4장 · 판정 불일치 처분 */
  discordance:  (id) => get(`/discordances/${id}`),
  dispose:      (id, b) => patch(`/discordances/${id}/dispose`, b),
};

/* 부서 key 로 골라 쓴다 — 공통 화면들이 이걸로 갈라 부른다 */
/* ── 원무과 ───────────────────────────────────────────────────
 * 경로를 다희님 구현에 맞췄다. 명세는 POST /exam-orders 하나였는데
 * 동사별로 갈라 두셨다 — 접수 · 예약 · 촬영요청이 하는 일이 달라서
 * 그쪽이 맞다.
 *
 * ⚠ search 는 q 가 없으면 서버가 **빈 목록**을 준다(qs.none()). 전체
 *   환자를 실수로 긁지 않게 한 것이라 화면도 빈 검색어를 안 보낸다.
 */
export const reception = {
  search:      (q)  => get(`/patients${qs({ q })}`),
  register:    (b)  => post("/patients/register", b),
  checkIn:     (b)  => post("/exam-orders/checkin", b),
  todayStatus: ()   => get("/patients/today-status"),

  /* 예약 캘린더 — 한 달 치를 한 번에 받는다. 조회 전용이다.
     GET /exam-orders 는 한 경로에서 메서드로 갈린다(urls.py 의
     _exam_orders_dispatch). GET 은 ExamOrderQueryView.list 로 간다.

     ⚠ **끝 경계에 시각을 붙여야 한다.** 서버가 이렇게 거른다 —

         qs.filter(scheduled_at__lte=p["scheduled_to"])

       scheduled_at 은 DateTimeField 라 scheduled_to=2026-09-30 은
       «30일 00:00:00» 이 된다. 그대로 보내면 **그 달 마지막 날 예약이
       통째로 빠진다.** 날짜만 넘겨받아 여기서 시각을 붙인다.

     ⚠ ordering 을 안 주면 서버 기본값이 visited_at 이다. 달력인데
       내원 시각 순으로 와서 날짜별로 묶을 수가 없다. */
  schedule: (from, to) =>
    get(`/exam-orders${qs({
      scheduled_from: `${from}T00:00:00`,
      scheduled_to:   `${to}T23:59:59`,
      ordering:       "scheduled_at",
    })}`),

  /* ── 3장 환자 목록 · 예약 ────────────────────────────────────
   *
   * ⚠ **검색어가 없으면 서버가 빈 목록을 준다.**
   *
   *     if not q and not status_param:
   *         return qs.none()
   *
   *   그런데 status_param 은 «있는지»만 보고 **걸지는 않는다** — 아래로
   *   내려가도 status 로 거르는 줄이 없다. 그래서 아무 값이나 status 에
   *   넣으면 전체 목록이 온다. 목록 화면이 첫 그림에서 비지 않으려면
   *   지금은 이 길뿐이다.
   *   → 다희님께 «목록 전체를 받는 공식 방법»을 요청해 두었다. 생기면
   *     아래 ALL 을 그것으로 바꾼다. */
  list:   (p)      => get(`/patients${qs(p)}`),
  detail: (id)     => get(`/patients/${id}/`),
  /* ⚠ 여기로는 **이름·생년월일·전화를 못 고친다.** 그 셋은 patient_pii 에
     있고 PatientSerializer 는 patient 표만 다룬다 (상세의 pii 는 읽기 전용).
     고칠 수 있는 것은 성별 · 출생연도 · 알레르기 둘 · 주치의다 */
  update: (id, b)  => patch(`/patients/${id}/`, b),

  /* 같은 환자의 예약을 전부 본다 — 같은 날 중복 예약을 잡으려고 */
  ordersOf: (id)   => get(`/exam-orders${qs({ patient: id, ordering: "scheduled_at" })}`),

  /* [예약 완료]. **원무는 날짜만 정한다** — modality · exam_purpose ·
     ordered_by 는 안 보낸다. 서버도 그 셋을 안 받는다
     (ExamOrderScheduleSerializer 는 patient_id · scheduled_at 둘뿐) */
  reserve: (b)     => post("/exam-orders/schedule", b),
};

/* 검색어 없이 목록 전체를 받는 열쇠 — 위 list 의 ⚠ 참고 */
export const ALL_PATIENTS = { status: "all" };

/* ── 4장 예약 확인 (앱 신청분) ──────────────────────────────────
 *
 * 3장과 다르다.
 *   3장  원무가 새로 만든다      POST /exam-orders/schedule
 *   4장  앱 신청을 확정한다      PATCH /exam-orders/{id}/confirm
 *
 * 거르는 조건 둘 다 서버가 받는다 (ExamOrderQueryView) —
 *   status=requested   아직 확정 안 된 신청
 *   visited=none       visited_at 이 빈 것. 차 있으면 이미 창구에 온
 *                      환자라 예약 확인이 아니라 간호 큐로 간다
 */
reception.requests = () =>
  get(`/exam-orders${qs({
    status: "requested", visited: "none", ordering: "scheduled_at",
  })}`);

/* [예약 확인]. **날짜만 보낸다.**
 *
 * ⚠ 지금 서버는 modalities · exam_purpose · ordered_by 를 **필수로** 받고
 *   그게 없으면 VALIDATION_ERROR 를 낸다. 팀 결정은 「원무는 날짜만 확정」
 *   이라 반대다 — 명세가 반대로 적혀 그대로 구현된 것이고, scheduled_at 만
 *   받도록 바뀔 예정이다. 그때까지 이 호출은 **목업에서만** 돈다.
 *
 * ⚠ 확정하면 order_status 가 **scheduled** 가 된다. ordered 가 아니다 —
 *   검사 종류가 정해져야 ordered 이고 그건 유방외과 몫이다. 값이 새로
 *   느는 것이라 DB 쪽은 따로 간다.
 */
reception.confirm = (id, scheduledAt) =>
  patch(`/exam-orders/${id}/confirm`, { scheduled_at: scheduledAt });

export const byDept = { pathology: path, radiology: rad, breast, reception };

export const apiInfo = { base: BASE, mock: BASE === MOCK };
