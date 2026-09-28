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
 *   · 영상 대기 큐는 거른 목록이다 — /exam-orders?status=ordered&assigned=none
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
import { EXAM_PURPOSE, MODALITY, REPORT_DEPT, label, modality as modalityCode } from "./codes";

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
 *   POST /api/v1/token/refresh   → { access }
 *
 * ⚠ **이 경로가 아직 서버에 없다** (2026-09-17, empatho-app 의
 *   core/api/urls.py 로 확인. health · tickets · login 셋뿐이다).
 *   그래서 아래 갱신은 지금 늘 실패하고, 조용히 401 로 흘러간다.
 *
 * ⚠ 그리고 **refresh 는 쿠키가 아니라 본문에 온다.** 로그인 응답이
 *   `{ access, refresh }` 다(auth.py 의 issue_pair). 전에 여기 적어
 *   두었던 「httpOnly 쿠키로만 내려온다」가 틀렸다.
 *   경로가 생기면 lib/session.js 의 getRefresh() 를 실어 보내도록
 *   아래 본문 자리를 채운다 — 지금은 규격을 몰라 비워 둔다.
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

/* 갱신도 실패해 세션이 끝났을 때 부른다. session.js 가 로그아웃을 걸어
   Gate 가 로그인 화면으로 되돌린다 — 죽은 에러 카드에 갇히지 않게. */
let onAuthLost = null;
export const setOnAuthLost = (fn) => { onAuthLost = fn; };

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

/* 슬래시 하나 때문에 조용히 깨지는 것을 **우리 쪽에서 막는다**
 * ────────────────────────────────────────────────────────────────
 * Django APPEND_SLASH 는 슬래시가 모자라면 301 로 넘겨 준다. GET 은
 * 따라가면 그만이지만 POST·PATCH·PUT 은 **넘어가는 과정에서 본문이
 * 사라진다** — 화면은 200 을 받고도 아무것도 안 바뀐다. 판독 확정이
 * 여기 걸리면 「저장했습니다」를 보고 나가는데 서버엔 안 남는다.
 *
 * 어느 경로에 슬래시가 붙는지 아직 답을 못 받았는데(api 머리말 참고),
 * **답을 기다릴 필요가 없다.** redirect:"manual" 로 두면 넘김이
 * 일어났다는 것만은 알 수 있다. 그때 슬래시를 뒤집어 한 번 더 보낸다.
 *
 * ⚠ 다시 보내도 두 번 적용될 일이 없다 — 넘김이 일어났다는 것은
 *   **첫 요청이 아무것도 안 바꿨다**는 뜻이기 때문이다.
 *
 * 규격이 확정되면 이 분기는 한 번도 안 타게 되고, 그때 지우면 된다. */
function flipSlash(path) {
  const [p, q = ""] = path.split("?");
  const next = p.endsWith("/") ? p.slice(0, -1) : `${p}/`;
  return q ? `${next}?${q}` : next;
}

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
      /* 쿠키를 실어 보낸다. 지금 서버가 심는 쿠키는 없지만(위 갱신
         주석 참고 — refresh 는 본문에 온다) 관리자 화면 열기가
         세션 쿠키를 받아야 해서 필요하다. 빼면 그쪽이 깨진다 */
      credentials: "include",
      /* 넘김을 우리가 받는다. 브라우저에 맡기면 본문이 조용히 날아간다 */
      redirect: "manual",
    });
  } catch (e) {
    /* 서버에 닿지도 못했다. 브라우저 기본 문구("Failed to fetch")가
       화면에 그대로 뜨지 않게 우리 모양으로 바꾼다 */
    throw Object.assign(new Error("서버에 연결하지 못했습니다"), {
      status: 0, code: ERR.NETWORK, detail: e?.message ?? null,
      fields: null, traceId: null,
    });
  }

  /* 넘김을 맞았다 — 슬래시가 모자라거나 남는다. 뒤집어 한 번만 더.
     본문도 Location 도 못 읽는(opaqueredirect) 응답이라 status 는 0 이다 */
  if ((res.type === "opaqueredirect" || res.status === 301 || res.status === 308)
      && !opt.noSlash) {
    return call(method, flipSlash(path), body, { ...opt, noSlash: true });
  }

  /* 401 — access 가 만료됐다. 한 번 갱신하고 그대로 다시 보낸다.
     갱신도 실패하면 아래로 흘려보내 평소대로 401 오류가 되게 한다 */
  if (res.status === 401 && !opt.noRetry && !NO_RETRY.has(path)) {
    const next = await refreshAccess();
    if (next) return call(method, path, body, { noRetry: true });
    /* 갱신도 실패 = 세션이 끝났다. 로그인 화면으로 보낸다 */
    onAuthLost?.();
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
const del   = (p)    => call("DELETE", p);

/* ⚠ 서버 목록은 한 쪽 20건이다(DefaultPagination). 창구 화면들은 **줄을 다
   보여 줘야** 해서 한 번에 넉넉히 받는다 — 스물한 번째 환자가 화면에서
   사라지던 자리(내원 대기 · 예약 판)에 싣는다. ?page_size= 는 서버가 받는다 */
const PAGE_ALL = 500;

function qs(o = {}) {
  const e = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? `?${new URLSearchParams(e)}` : "";
}

/* ── 로그인 ───────────────────────────────────────────────────
 * 경로를 다희님 브랜치에서 확인했다 — 맞는 것은 /login 이다.
 * (2026-09-17 empatho-app 의 core/api/urls.py 로 재확인. 환자 앱도
 *  같은 문으로 들어간다 — 계정이 한 표라 role 로만 갈린다. src/api.js
 *  가 쓰던 /auth/login 은 그래서 지웠다)
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

/* 직원·환자 공용 알림. router 목록은 서버 설정에 따라 배열 또는
   {count, results}로 올 수 있어 화면에는 항상 배열만 넘긴다. */
export const notifications = () => get("/notifications/").then(unwrapList);
export const acknowledgeNotification = (id) =>
  patch(`/notifications/${id}/`, { acknowledged: true });

/* 알림이 가리키는 것(ref_type · ref_id)을 풀어 환자·검사 번호를 얻는다 —
   종에서 누른 알림을 제 화면으로 보내려고(lib/Top.jsx 의 noticeTo).
   ⚠ 직원 알림에는 patient 칸이 비어 온다(Notification 의 수신자 CHECK —
     환자 아니면 직원, 하나만). 그래서 가리키는 행을 한 번 더 읽는다.
   ⚠ report 는 **상세(retrieve)** 로 읽는다. 목록(?patient=)은 유방외과가
     부르면 「유방외과 열람」을 남긴다(views/surgery.py list → viewed.mark).
   ⚠ assessment 는 상세 경로가 없다 — 최근 판독 목록에서 번호로 찾는다.
     방금 확정된 알림이라 맨 앞 쪽에 있다 */
export const noticeRef = {
  report:   (id) => get(`/reports/${id}/`),
  specimen: (id) => get(`/specimens/${id}/`),
  study:    (id) => get(`/studies/${id}/`),
  assessment: (id) => get(`/assessments${qs({ page_size: 100 })}`)
    .then((raw) => unwrapList(raw).find((a) => String(a.assessment_id) === String(id)) ?? null),
};

/* 로그인한 사람만 보는 개인 메모. 할 일과 스티키 메모는 저장 방식만
   다를 뿐 같은 API를 쓰므로 여기 하나로 모은다. */
export const notes = {
  list:   (type) => get(`/me/notes${qs({ type })}`).then(unwrapList),
  /* ⚠ 서버 시리얼라이저는 종류를 **본문**의 note_type 에서 읽는다. 주소에만
     실어서는 400 이었다(09-27 확인 — 이 경로가 한 번도 안 쓰여 몰랐다) */
  create: (type, content) => post(`/me/notes${qs({ type })}`, { note_type: type, content }),
  update: (id, content) => patch(`/me/notes/${id}`, { content }),
  remove: (id) => del(`/me/notes/${id}`),
};

/* ── 관리자 화면 열기 ─────────────────────────────────────────
 *
 * 관리자가 로그인을 두 번 하지 않게 하는 자리다.
 *
 *   [관리자 화면 열기] → POST /admin-session → 새 탭으로 /admin/
 *
 * Django admin 의 인증 주체는 auth_user 이고 우리 API 의 주체는 account 라
 * 서로 모른다. 이 요청이 그 사이를 잇는다 — 서버가 role 을 확인하고
 * **세션 쿠키를 심어 준다.** 돌려받는 값은 열 주소 하나뿐이다.
 *
 * ⚠ 쿠키를 받아야 하므로 credentials 가 실려야 한다. call() 이 모든 요청에
 *   credentials:"include" 를 이미 붙이므로 여기서 따로 할 일은 없다.
 *
 * ⚠ **응답을 받은 뒤에 열어야 한다.** 먼저 열면 세션이 아직 없어서
 *   Django 로그인 화면이 뜬다 — 아무도 비밀번호를 모르는 계정이라 거기서
 *   막힌다.
 */
export const adminSession = () => post("/admin-session");

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

/* ⚠ 2026-09-19 확인 — SpecimenSerializer 가 exclude=AUDIT_FIELDS 인
 * 맨몸 ModelSerializer 라 모델 컬럼 이름 그대로 나간다(services/django
 * core/serializers/pathology.py). dept/pathology.jsx 다섯 장이 기대하는
 * patient_name·age·sex·specimen_no·kind·method 는 죄다 없고, 대신
 * specimen_id·patient(FK id)·specimen_label·specimen_type·
 * guidance_route 로 온다 — 영상의학과 radOrderRow() 처럼 이름만 바꿔
 * 될 자리가 아니라 patient 는 아예 **다른 테이블 id 라 조인이 필요하다.**
 * 이 화면들은 원래 병리 서버 응답이 patient_name 등을 직접 준다고
 * (목업 그대로) 믿고 있었다 — 그래서 실서버에서는 환자 이름·나이·성별
 * 칸이 통째로 비어 있었다.
 *
 * 병리 서버에 검체 목록에 환자 정보를 얹어 주는 별도 경로가 없어서
 * (breast.waiting() 도 같은 사정으로 patients/ 를 직접 부른다) 검체
 * 한 건마다 GET /patients/{id}/ 를 한 번 더 불러 합친다 — dept/
 * pathology.jsx 의 read() 가 이미 Promise.all 로 두 응답을 합치던
 * 것과 같은 자리다.
 *
 * site(병변 위치)·radiology_summary·guide_images·other_specimens·
 * viewed_at 은 Specimen·Lesion 모델 어디에도 없다 — 실제로 있는지
 * 아직 확인 못 했다. 없는 조인을 지어내지 않고 그대로 비워 둔다
 * (있으면 화면이 알아서 숨긴다, 다섯 장 다 ?? 로 방어돼 있다). */
/* ⚠ 09-28 — **줄마다 환자를 부르지 않는다.** 목록 20줄이면 /patients/{id}/
   가 스무 번 나갔다(홈이 30초마다 다시 부르니 분당 수십 번). 서버가 이름 ·
   나이 · 성별(+ 새 서버는 patient_number)을 싣고 있으면 그대로 쓰고, **빠진
   것이 있을 때만** 부른다. 같은 환자는 한 번만(want.cache).
     목록  이름이 없을 때만
     상세  늘 (한 건이라 싸다) — 판독 화면이 생년월일 · 알레르기를 쓴다 */
async function pathSpecimenRow(raw = {}, want = {}) {
  const patientId = raw.patient;
  const missing = !raw.patient_name || want.full;
  const fetchPatient = () => get(`/patients/${patientId}/`).then(normalizePatient).catch(() => null);
  let patient = null;
  if (patientId != null && missing) {
    const key = String(patientId);
    if (want.cache && !want.cache.has(key)) want.cache.set(key, fetchPatient());
    patient = await (want.cache ? want.cache.get(key) : fetchPatient());
  }
  const finalized = raw.finalized ?? Boolean(raw.finalized_at);
  return {
    ...raw,
    id: raw.specimen_id ?? raw.id,
    /* ⚠ 서버(SpecimenSerializer)가 patient_name · age · sex 를 이미 싣는다.
       전에는 그것을 위 조회 결과로 덮었는데, 병리과는 /patients/{id}/ 가
       막히거나 비어 목록 이름이 「환자 #id (null/)」로 떴다 — 준 것을 먼저 쓴다 */
    patient_name: raw.patient_name || patient?.name || (patientId == null ? "" : `환자 #${patientId}`),
    age: raw.age ?? patient?.age ?? null,
    sex: raw.sex || patient?.sex || "",
    patient_no: raw.patient_number ?? raw.patient_no ?? patient?.patient_number ?? "",
    birth: raw.birth ?? patient?.birth_date ?? null,
    phone: raw.phone ?? patient?.phone ?? null,
    /* ⚠ 환자를 안 불렀으면 모른다 — 「없음」으로 찍지 않는다 */
    allergy: raw.allergy ?? (patient ? (patient.has_allergy ? (patient.allergy_note || "있음") : "없음") : null),
    specimen_no: raw.specimen_label ?? raw.specimen_no,
    kind: raw.specimen_type ?? raw.kind,
    method: raw.guidance_route ?? raw.method,
    finalized,
    /* 판독 단계 — ⚠ accession_status 로는 못 가른다. 서버 enum 이
       unbound · bound · accessioned 셋뿐이라 「판독 완료」를 말할 칸이 없다.
       누가 집었는지(assigned_to)와 확정 시각으로 센다 */
    read_state: finalized ? "final" : raw.assigned_to != null ? "reading" : "waiting",
  };
}

/* 목록 줄 여럿 — 같은 환자는 한 번만 부른다 */
function pathRows(rows) {
  const cache = new Map();
  return Promise.all(rows.map((r) => pathSpecimenRow(r, { cache })));
}

function pathUploadFile(raw = {}) {
  const bytes = raw.byte_size;
  return {
    ...raw,
    id: raw.storage_object_id ?? raw.id,
    name: raw.name ?? raw.object_key ?? `파일 ${raw.storage_object_id ?? ""}`,
    size: typeof bytes === "number" ? `${(bytes / 1048576).toFixed(1)} MB` : "",
    w: raw.w ?? raw.width_px,
    h: raw.h ?? raw.height_px,
    image: raw.image ?? (raw.object_key ? { key: raw.object_key } : null),
  };
}

export const path = {
  /* ⚠ 서버는 큐를 **기본 필터 없이** 준다 (2026-09-16 다희님 확인).
     이 두 조건을 안 담으면 이미 남이 집어간 검체까지 대기 큐에 뜬다.
     기본값이 아니라 **우리가 정하는 조건**이라 여기 적어 둔다 */
  /* ⚠ 2026-09-18 다희님 확인(feature/dahee) — 봉투 언랩. Queue.jsx 가
   * data.items/data.total 을 기대하는데(공용 화면, rad.queue()와 같은
   * 계약) 여기는 서버 페이지네이션 봉투({count,results,…})를 그대로
   * 주고 있었다 — 판독 단위를 검체 하나로 잡는 병리과 큐가 실서버에서
   * 크래시 나던 자리다. */
  queue:      ()       => get(`/specimens/queue${qs({ status: "bound", assigned: "none" })}`)
    .then(async (raw) => {
      const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
      const items = await pathRows(rows);
      return { ...raw, items, total: raw?.count ?? raw?.total ?? items.length };
    }),
  /* ⚠ 상세에도 슬래시가 붙는다 (2026-09-16 다희님이 직접 요청을 넣어
     확인). 전에 「병리는 상세에 슬래시가 없다」고 들었던 것이 틀렸다 —
     슬래시 없이 부르면 그냥 404 다.

     걱정했던 「PATCH 가 301 을 타면서 본문이 사라진다」는 일어나지
     않는다. 이 API 는 맨 뒤에 캐치올 라우트가 있어서 APPEND_SLASH
     리다이렉트 자체가 안 일어난다. 슬래시를 빠뜨리면 늘 깔끔한 404 다.

     ⚠ 아래 custom action 들(queue·assign·upload·draft·finalize)은
       서버 코드로 확인했다 — 이들은 @action 이 아니라 core/urls.py 의
       명시 path() 라서 **슬래시가 없다.** 끝 슬래시가 붙는 것은 router 에
       등록된 것들뿐이다 (patients · studies · lesions · reports ·
       followups · reservations · visits/today · me/reservation-requests). */
  specimen:   (id)     => get(`/specimens/${id}/`).then((s) => pathSpecimenRow(s, { full: true })),
  assign:     (id)     => patch(`/specimens/${id}/assign`),

  /* 영상 대조 — 이 검체가 겨눈 병변(Specimen.lesion)과 그 검사의 최신 확정
     BI-RADS. 큐에서 한 건을 고를 때만 부른다(두 번).
     ⚠ 병리 계정이 /lesions · /assessments 를 못 읽는 배포도 있다 — 그때는
       null 이고, 화면이 target_snapshot · radiology_summary 로 물러난다 */
  correlation: async (s) => {
    const lid = s?.lesion ?? s?.lesion_id;
    if (lid == null || typeof lid === "object") return null;
    const lesion = await get(`/lesions/${lid}/`).catch(() => null);
    if (!lesion) return null;
    const sid = lesion.study ?? lesion.study_id;
    const a = sid == null ? null
      : await rad.history(sid).then(currentAssessment).catch(() => null);
    return {
      lesion, study: sid ?? null,
      modality: lesion.modality ?? null,
      category: a?.category ?? null,
      finalized_at: a?.finalized_at ?? null,
    };
  },

  /* 열린 판정 불일치. ⚠ 목록 경로에 끝 슬래시가 없다(breast 와 같은 자리).
     병리 권한으로 못 읽으면 빈 목록 — 홈 · 목록의 「불일치」가 0 으로 보인다 */
  openDiscordances: () => get(`/discordances${qs({ status: "open" })}`).then(unwrapList),

  /* 업로드 화면은 파일 목록 응답만으로는 환자·검체 정보를 채울 수
     없다. 영상 업로드 화면처럼 상세 응답과 업로드 응답을 합쳐서
     공통 Upload.jsx 가 기대하는 {files, patient_name, ...} 모양으로
     정규화한다. 기존에는 upload 응답의 specimen_id/uploads 만 그대로
     넘겨 환자 정보가 undefined 로 보이고, 파일 목록도 화면 계약과
     어긋났다. */
  uploadInfo: async (id) => {
    const [specimen, raw] = await Promise.all([
      get(`/specimens/${id}/`).then((s) => pathSpecimenRow(s)),
      get(`/specimens/${id}/upload`),
    ]);
    const uploads = raw?.uploads ?? raw?.files ?? [];
    return {
      ...raw,
      ...specimen,
      files: uploads.map(pathUploadFile),
      specimen_id: specimen.id,
    };
  },
  ticket:     (b)      => post("/tickets", b),   /* lib/files.js 가 쓴다 */
  analyze:    (id)     => post(`/specimens/${id}/ai-results`),
  progress:   (id)     => get(`/ai-results${qs({ specimen: id })}`),
  /* 09-26 확인 — PatientTimelineView(GET /patients/{id}/timeline)는
     resource="patient"라 매트릭스에 PATHOLOGY: R이 이미 있고, 검체
     채취·병리 확진 이벤트도 실제로 내려준다(specimen_id 포함). rad·
     breast의 timeline과 같은 서버 경로 — "병리에는 timeline이 없다"는
     예전 확인이 지금은 틀렸다. */
  timeline:   (pid)    => get(`/patients/${pid}/timeline`),

  /* ⚠ 병리는 판독 조회 경로가 없다. 상세와 업로드 조회를 합쳐 쓴다 —
     dept/pathology.jsx 의 read 참고. 경로가 생기면 여기 한 줄 추가하고
     그쪽 합치는 코드를 지우면 된다 */
  draft:      (id, b)  => put(`/specimens/${id}/draft`, b),
  finalize:   (id, b)  => patch(`/specimens/${id}/finalize`, b),

  /* ⚠ 슬래시가 붙는다. **목록·생성만** 그렇다 (2026-09-16 확인).
     queue·assign·upload·draft·finalize 는 슬래시가 없는 게 맞다.
     Django APPEND_SLASH 가 GET 은 301 로 넘겨 주지만 POST 는 그 과정에서
     본문이 날아가므로, 붙는 자리는 처음부터 붙여 둔다 */
  /* ⚠ 봉투 언랩 — List.jsx 가 data.items/data.total 을 기대한다(위 queue
   * 와 같은 자리). */
  /* 거르기 — assigned=me · finalized=yes|no (새 서버). 옛 서버는 모르는
     질의를 그냥 무시하고 전부 준다 — 화면이 한 번 더 거른다(lib/Filters) */
  list:       (o = {}) => get(`/specimens/${qs(o)}`).then(async (raw) => {
    const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
    const items = await pathRows(rows);
    return { ...raw, items, total: raw?.count ?? raw?.total ?? items.length };
  }),
  /* 판독 화면(3장)의 「영상 대조」 칸 — 검체가 매달린 병변과 그 검사의 판정.
     병리 권한으로 못 읽으면 부르는 쪽이 target_snapshot 으로 버틴다 */
  lesion:      (id)     => get(`/lesions/${id}/`),
  assessments: (study)  => get(`/assessments${qs({ study })}`).then(unwrapList),
  /* 「확정 → 다음 건」용 가벼운 목록 — 행마다 환자를 더 부르지 않는다 */
  rows:        (o = {}) => get(`/specimens/${qs(o)}`).then(unwrapList),
  /* ⚠ POST /specimens/{id}/amend 는 서버에 없다 (확정 사양서 §8-2 —
     병리 결과 정정 경로를 두지 않기로 함. views/pathology.py 상단
     docstring 참고). 예전엔 여기 amend() 가 있었는데 지웠다 — 부르면
     404 만 나던 죽은 경로였다. */
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

/* 영상의학과 백엔드 원본 응답을 공용 화면 계약으로 변환한다.
 * main 브랜치(9858a55 align radiology screens with API responses)에서
 * 가져왔다 — dahee는 316da61에서 갈라진 뒤 이 레이어가 없었다. Read·
 * Amend 화면이 d.patient / d.unit / d.ai 를 그대로 기대하고 있어서
 * (dept/radiology.jsx), 여기 없이는 둘 다 "Cannot read properties of
 * undefined (reading 'name')"로 죽는다. */
function radPatient(source = {}, order = {}) {
  const patientId = source.patient_id ?? source.patient ?? order.patient_id ?? order.patient;
  return {
    id: patientId ?? null,
    name: source.patient_name ?? order.patient_name ?? source.patient?.name
      ?? order.patient?.name ?? (patientId == null ? "" : `환자 #${patientId}`),
    age: source.age ?? order.age ?? source.patient?.age ?? order.patient?.age ?? null,
    sex: source.sex ?? order.sex ?? source.patient?.sex ?? order.patient?.sex ?? "",
    no: source.patient_no ?? source.patient_number ?? order.patient_no
      ?? order.patient_number ?? source.patient?.patient_number
      ?? order.patient?.patient_number ?? "",
    contrast_allergy: source.contrast_allergy ?? order.contrast_allergy
      ?? ((source.has_allergy ?? order.has_allergy) ? (source.allergy_note
        ?? order.allergy_note ?? true) : null),
  };
}

/* 검사명 — 서버에 이름 칸이 없어 목적 코드(screening·diagnostic)가
   그대로 화면에 찍혔다. 모달리티와 목적을 한글로 묶는다 */
function examName(purpose, mod) {
  if (!purpose) return "";
  const m = MODALITY[modalityCode(mod)];
  return [m, label(EXAM_PURPOSE, purpose)].filter(Boolean).join(" · ");
}

function radOrderRow(raw = {}) {
  const patient = radPatient(raw);
  return {
    ...raw,
    id: raw.exam_order_id ?? raw.id,
    patient_id: patient.id,
    patient_name: patient.name,
    patient_no: patient.no,
    age: patient.age,
    sex: patient.sex,
    contrast_allergy: patient.contrast_allergy,
    device: raw.device ?? raw.device_name ?? "",
    exam_name: raw.exam_name ?? examName(raw.exam_purpose, raw.modality),
    purpose: raw.purpose ?? raw.order_note ?? "",
    finalized: raw.finalized ?? raw.order_status === "completed",
  };
}

function radFile(raw = {}) {
  const bytes = raw.byte_size ?? raw.size;
  const size = typeof bytes === "number"
    ? `${(bytes / 1048576).toFixed(1)} MB`
    : (raw.size ?? "");
  const image = raw.image ?? (raw.sop_instance_uid
    ? { sop: raw.sop_instance_uid }
    : raw.orthanc_series_id
      ? { series: raw.orthanc_series_id }
      : raw.object_key
        ? { key: raw.object_key }
        : null);
  return {
    ...raw,
    id: raw.storage_object_id ?? raw.id,
    name: raw.name ?? raw.sop_instance_uid ?? raw.series_uid ?? `파일 ${raw.storage_object_id ?? ""}`,
    size,
    w: raw.w ?? raw.width_px,
    h: raw.h ?? raw.height_px,
    image,
  };
}

/* 맘모 뷰 이름 — 파일의 laterality(left·right) · view_position(CC·MLO) */
function radViewName(file) {
  const lat = { left: "L", right: "R", l: "L", r: "R" }[String(file.laterality ?? "").toLowerCase()];
  const view = String(file.view_position ?? "").trim().toUpperCase();
  return lat && view ? `${lat}-${view}` : null;
}

function radSeries(files = []) {
  const groups = new Map();
  files.forEach((file) => {
    /* ⚠ 맘모 네 뷰는 한 시리즈(series_uid)로 올 수 있다 — 시리즈로만 묶으면
       「촬영 뷰 1」 한 줄에 UID 가 이름으로 찍혔다. 좌우·방향이 있으면
       뷰마다 따로 세우고 R-CC 처럼 부른다 */
    const view = radViewName(file);
    const key = view
      ? `${file.series_uid ?? file.orthanc_series_id ?? ""}:${view}`
      : file.series_uid ?? file.orthanc_series_id ?? file.id;
    const group = groups.get(key) ?? {
      id: key,
      name: view ?? file.series_uid ?? file.series_role ?? file.name,
      count: 0,
      files: [],
    };
    group.count += 1;
    group.files.push(file);
    groups.set(key, group);
  });
  return [...groups.values()].map((group) => ({
    ...group,
    w: group.files[0]?.w,
    h: group.files[0]?.h,
    image: group.files[0]?.image ?? null,
  }));
}

function radAi(raw, modality) {
  if (!raw) return null;
  /* AiResult.result 는 추론 서버의 응답 봉투다.
     { result: { ...실제 판독값 } } 형태를 한 겹만 벗기면 봉투를 AI
     소견 컴포넌트에 넘기게 되고, summary·lesions·lesion_found가 전부
     undefined라 분석이 끝나도 화면이 비어 보인다. 실데이터와 목업 모두
     받도록 안쪽 판독값까지 안전하게 꺼낸다. */
  const envelope = raw.result && typeof raw.result === "object" ? raw.result : raw;
  const result = envelope.result && typeof envelope.result === "object"
    ? envelope.result
    : envelope;
  const shape = result.shape ?? {};
  const grade = result.grade ?? {};
  const reliability = result.mask_reliability ?? {};
  return {
    ...result,
    modality: result.modality ?? envelope.modality ?? modality,
    abstained: result.abstained ?? envelope.abstained ?? raw.abstained,
    abstain_reason: result.abstain_reason ?? envelope.reason ?? envelope.abstain_reason ?? raw.abstain_reason,
    run_status: raw.run_status ?? envelope.run_status ?? result.run_status,
    ai_result_id: raw.ai_result_id ?? envelope.ai_result_id ?? result.ai_result_id,
    /* 어느 저장 파일에 돌린 결과인가 — 초음파는 장마다 결과가 따로다 */
    source_object: raw.source_object ?? null,

    /* 초음파 서빙 값은 화면 표기명과 조금 다르다. 원본 키도 보존하면서
       화면에서 쓰는 별칭을 붙여 두면 AI 소견과 영상 위 윤곽이 함께 나온다. */
    category: result.category ?? grade.display,
    category_confidence: result.category_confidence ?? grade.confidence,
    mask_confidence: result.mask_confidence ?? reliability.level,
    orientation: result.orientation ?? result.orientation_label,
    polygon: result.polygon ?? result.polygons,
    /* MRI는 병변 배열을 tumor 안에 넣어 보낸다. 공통 AI 패널이 같은
       lesions 칸을 보도록 펼쳐 두되, 좌표가 없는 결과를 2D 오버레이로
       꾸며 내지는 않는다. */
    lesions: result.lesions ?? result.tumor?.lesions ?? [],
    density: result.density && {
      ...result.density,
      percent: result.density.percent ?? result.density.dense_density_pct,
    },
    shape: {
      ...shape,
      area: shape.area ?? shape.area_px,
      max_diameter: shape.max_diameter ?? shape.max_diameter_px,
      aspect_ratio: shape.aspect_ratio ?? shape.height_width_ratio,
      convexity: shape.convexity ?? shape.solidity,
      roughness: shape.roughness ?? shape.boundary_irregularity,
    },
  };
}

/* ⚠ dahee 쪽에서 추가한 것 — category · finding_note. main의 radStudyRow는
   이 둘을 안 채운다(Assessment 표 조회가 없어서). List 상세의 "BI-RADS
   undefined"가 main에도 그대로 있다는 뜻이라, 여기 파라미터로 최신 확정
   판독을 받아 얹는다. 호출부(rad.study)가 비동기로 구해서 넘겨준다. */
function radStudyRow(raw = {}, order = {}, assessment = null) {
  const patient = radPatient(raw, order);
  const studyId = raw.study_id ?? raw.id;
  return {
    ...raw,
    id: studyId,
    study_id: studyId,
    patient_id: patient.id,
    patient_name: patient.name,
    patient_no: patient.no,
    age: patient.age,
    sex: patient.sex,
    contrast_allergy: patient.contrast_allergy,
    /* 목적 · 의뢰 문구 — 새 서버는 검사 행에 바로 싣는다(order_note ·
       exam_purpose). 옛 서버는 오더를 따로 불러 order 로 넘겨 준다 */
    exam_name: order.exam_name ?? (examName(order.exam_purpose ?? raw.exam_purpose,
      order.modality ?? raw.modality) || (raw.exam_name ?? "")),
    exam_purpose: raw.exam_purpose ?? order.exam_purpose ?? null,
    purpose: order.purpose ?? order.order_note ?? raw.purpose ?? raw.order_note ?? "",
    ordered_at: raw.ordered_at ?? order.ordered_at ?? null,
    device: raw.device ?? raw.device_name ?? "",
    exam_order_id: raw.exam_order_id ?? raw.exam_order ?? order.exam_order_id,
    finalized: raw.finalized ?? raw.read_status === "finalized",
    viewed_at: raw.viewed_at ?? raw.report?.viewed_at ?? null,
    category: assessment?.category ?? raw.category,
    finding_note: assessment?.finding_note ?? raw.finding_note,
  };
}

function radUpload(raw = {}, order = {}) {
  const study = raw.study ?? {};
  /* 서버가 storage_objects: []와 files: [...]를 함께 보낼 수 있다.
     빈 storage_objects를 우선하면 업로드 완료 파일이 판독 화면으로
     전달되지 않는다. 실제 항목이 있는 목록을 선택한다. */
  const candidates = [
    raw.storage_objects,
    raw.files,
    raw.images,
    study.storage_objects,
    study.files,
    study.images,
  ];
  const listedFiles = candidates.find((value) => Array.isArray(value) && value.length > 0) ?? [];
  const files = listedFiles.map(radFile);
  const row = radStudyRow(study, order);
  return {
    ...raw,
    ...row,
    /* ⚠ 빈 글자가 이미 있는 값을 덮지 않게 — study 가 안 접혀 온 응답(목업)은
       row 의 목적 · 검사명이 ""라 위에서 raw 값을 지웠다 */
    purpose: row.purpose || raw.purpose || raw.order_note || "",
    exam_name: row.exam_name || raw.exam_name || "",
    exam_purpose: row.exam_purpose ?? raw.exam_purpose ?? null,
    study,
    files,
    series: raw.series ?? radSeries(files),
    ai: raw.ai ?? raw.latest_ai_result ?? study.ai ?? null,
    exam_order_id: row.exam_order_id ?? order.exam_order_id,
    order,
  };
}

/* ⚠ 2026-09-18 확인 — MRI 판독 화면 뷰어가 안 뜨는 문제의 원인. 이 함수는
 * raw.study/raw.images 로 접혀 온다고 가정하고 patient·unit·series·ai·
 * doctor 를 전부 다시 만드는데, mock/hospital.json 의 read 항목들은
 * (st-302 등) patient·unit·volume_manifest·series 가 이미 맨 위 칸에
 * 펴져 있다 — study 는 아예 없다. 그래서 study 가 빈 객체가 되고, 거기서
 * 다시 만든 patient 가 「환자 (null/)」로, unit.modality 도 undefined가
 * 돼서 stage()의 `d.unit?.modality === "mri"` 분기를 못 타 MRI 뷰어
 * (MRIReviewGrid)가 아니라 일반 2D Stage로 떨어졌다.
 *
 * raw 에 이미 펴진 값이 있으면 그걸 먼저 쓴다 — study/images 로 다시
 * 만드는 건 그 값이 없을 때(다희님이 확인한 실서버 모양)만 쓰는
 * 대체 경로로 남긴다. */
function radRead(raw = {}, upload = {}, order = {}) {
  const study = raw.study ?? upload.study ?? {};
  const row = radStudyRow(study, order);
  /* read 응답이 images: []를 포함해도 실제 업로드 파일은 upload
     응답(storage_objects/files)에 있을 수 있다. 빈 배열을 우선하면
     업로드가 성공한 검사도 판독 화면에서 원본 없음으로 표시된다. */
  const rawImages = Array.isArray(raw.images) ? raw.images.map(radFile) : [];
  const uploadFiles = Array.isArray(upload.files) ? upload.files.map(radFile) : [];
  /* 업로드 응답에는 저장소 object_key가, read 응답에는 DICOM 메타데이터가
     각각 따로 올 수 있다. 같은 순번의 정보를 합쳐 실제로 내려받을 수
     있는 key/sop를 모두 보존한다. */
  const files = uploadFiles.length
    ? uploadFiles.map((file, i) => ({
        ...(rawImages[i] ?? {}),
        ...file,
        image: file.image ?? rawImages[i]?.image ?? null,
      }))
    : rawImages;
  const current = raw.current_assessment ?? null;
  return {
    ...raw,
    ...row,
    patient: raw.patient ?? radPatient(study, order),
    unit: raw.unit ?? { ...row, id: row.study_id, no: row.study_id, exam_order_id: row.exam_order_id },
    files,
    images: files,
    series: raw.series ?? radSeries(files),
    ai: raw.ai ?? radAi(raw.latest_ai_result, row.modality),
    /* 검사의 AI 결과 전부(서버 09-28~). 옛 서버는 칸이 없어 null — 그때
       화면은 latest_ai_result(위 ai) 하나로 버틴다(radStage) */
    ais: Array.isArray(raw.ai_results) ? raw.ai_results.map((r) => radAi(r, row.modality)) : null,
    doctor: raw.doctor ?? current ?? {},
    finalized: raw.finalized ?? row.finalized,
  };
}

/* 최신 확정(final, 정정으로 안 덮인) 판독을 찾는다 — rad.study()·radRead
   둘 다 쓴다 */
async function radCurrentAssessment(studyId) {
  const hist = await rad.history(studyId).catch(() => []);
  const rows = Array.isArray(hist) ? hist : (hist?.results ?? hist?.items ?? []);
  return currentAssessment(rows);
}

/* 판 목록에서 지금 유효한 한 판. 유방외과 환자 상세가 지난 판과 견줄 때도
   이것을 쓴다 — 규칙이 두 곳이 되면 「현재」가 화면마다 달라진다 */
export function currentAssessment(rows) {
  return rows.find((a) => a.read_stage === "final" && !a.superseded_by)
    ?? rows.find((a) => a.read_stage === "final")
    ?? null;
}

export const rad = {
  /* ⚠ 서버는 큐를 **기본 필터 없이** 준다 (2026-09-16 다희님 확인).
     병리와 같은 사정인데 값이 다르다 — 영상은 status=ordered 다.
     안 담으면 이미 촬영·배정이 끝난 건까지 대기 큐에 섞인다.

     일반 `/exam-orders` 목록은 `assigned=none` 필터를 처리하지 않는다.
     그러면 이미 다른 영상의학과 선생님이 맡은 오더까지 섞이고, 선두를
     받을 때마다 409 ALREADY_ASSIGNED가 난다. 배정되지 않은 촬영 오더만
     거르는 전용 경로 `/radiology/queue`를 써야 한다. */
  /* ⚠ 봉투 언랩 — Queue.jsx 가 {items,total}을 기대한다. 행마다
     radOrderRow 로 patient_name·age·sex 등을 만들어 얹는다. */
  queue:      ()       => get(`${RAD}/queue${qs({ status: "ordered", assigned: "none" })}`)
    .then((raw) => {
      const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
      return { ...raw, items: rows.map(radOrderRow), total: raw?.count ?? raw?.total ?? rows.length };
    }),
  order:      async (id) => radWithPatient(radOrderRow(await get(`/exam-orders/${id}`))),
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
  uploadInfo: (id)     => get(`${RAD}/studies/${id}/upload`).then(async (raw) => {
    const examOrderId = raw?.study?.exam_order;
    const order = examOrderId ? await rad.order(examOrderId).catch(() => ({})) : {};
    return radUpload(raw, order);
  }),
  ticket:     (b)      => post("/tickets", b),
  complete:   (id)     => patch(`/exam-orders/${id}/complete`),
  analyze:    (id)     => post(`/studies/${id}/ai-results`),
  progress:   (id)     => get(`/ai-results${qs({ study: id })}`),
  retake:     (id)     => post(`/exam-orders/${id}/retake`),

  /* ⚠ withFiles(dept/radiology.jsx)가 series에 파일 주소를 얹는 것과
     별개로, 여기서 patient/unit/ai 자체를 못 만들면 화면이 첫 줄에서
     죽는다(d.patient.name). uploadInfo를 한 번 더 불러 order를 얻는다 —
     read 응답에 order 정보가 안 실려 있어서다. */
  read:       async (id) => {
    const raw = await get(`${RAD}/studies/${id}/read`);
    const upload = await rad.uploadInfo(id);
    const result = radRead(raw, upload, upload.order ?? {});
    const patientId = result.patient?.id;
    const patient = patientId == null ? null
      : await get(`/patients/${patientId}/`).then(normalizePatient).catch(() => null);
    return patient == null ? result : {
      ...result,
      patient: {
        ...result.patient,
        id: patientId,
        name: patient.name || result.patient.name,
        age: patient.age ?? result.patient.age,
        sex: patient.sex || result.patient.sex,
        no: patient.patient_number || result.patient.no,
        birth_date: patient.birth_date ?? null,
        phone: patient.phone ?? null,
        contrast_allergy: patient.has_allergy ? (patient.allergy_note || "있음") : null,
      },
    };
  },
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

  /* ⚠ GET /studies/{id}/ 에는 patient_name 등은 이제 오지만(2026-09-18
     백엔드 확정), category · finding_note 는 여전히 없다 — Assessment
     표에 있다(study에 매달려 있지 patient/report에 직접 안 물린다).
     4장 목록 상세가 "BI-RADS undefined" 를 냈던 게 이 자리다. 확정된
     (최신, 정정으로 덮이지 않은) 판독을 찾아 radStudyRow 에 얹는다. */
  study:      async (id) => {
    const raw = await get(`/studies/${id}/`);
    /* 오더는 목적 · 의뢰 문구가 행에 없을 때만, 환자 조회 없이(아래
       radWithPatient 가 한 번 한다) */
    const needOrder = raw?.exam_order && !("order_note" in raw || "exam_purpose" in raw);
    const [order, current] = await Promise.all([
      needOrder ? get(`/exam-orders/${raw.exam_order}`).then(radOrderRow).catch(() => ({})) : Promise.resolve({}),
      radCurrentAssessment(id),
    ]);
    return radWithPatient(radStudyRow(raw, order, current));
  },
  /* ⚠ 서버가 페이지네이션 봉투({count,results,…})로 준다. List.jsx 는
     {items,total}을 기대한다(data.items.filter · data.total) — 병리·영상
     큐가 이미 하던 언랩과 같은 자리다. 행마다 exam_order 를 더 불러
     radStudyRow 로 patient_name 등을 채운다(목록 행엔 category 를 안
     보여줘서 assessment 는 여기선 안 붙인다 — 상세를 열 때 study()가 한다). */
  /* ⚠ 09-28 — **줄마다 오더 · 환자를 부르지 않는다.** 전에는 줄마다
     rad.order(오더 + 환자 = 두 번)를 불러, 홈이 검사 200건을 받으면 30초마다
     400번이 나갔다. 새 서버는 검사 행에 patient_name · order_note ·
     exam_purpose 를 싣는다 — 있으면 그대로 쓴다.
     옛 서버(칸이 없음)만 오더를 **맨 것으로 한 번씩**(환자 조회 없이, 같은
     오더는 한 번) 부른다. want.need(row) 가 false 인 줄은 그마저 안 부른다 —
     홈은 확정된 검사의 목적을 안 쓴다.
     거르기 — assigned=me · read_status= · modality= (새 서버). */
  list:       async (o = {}, want = {}) => {
    const raw = await get(`/studies/${qs(o)}`);
    const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
    const orders = new Map();
    const orderOf = (id) => {
      if (!orders.has(id)) orders.set(id, get(`/exam-orders/${id}`).then(radOrderRow).catch(() => ({})));
      return orders.get(id);
    };
    const has = (r) => r.patient_name && ("order_note" in r || "exam_purpose" in r);
    const items = await Promise.all(rows.map(async (row) => {
      const orderId = row.exam_order_id ?? row.exam_order;
      const skip = has(row) || !orderId || (want.need && !want.need(row));
      return radStudyRow(row, skip ? {} : await orderOf(orderId));
    }));
    return { ...raw, items, total: raw?.count ?? raw?.total ?? rows.length };
  },

  /* 오늘 내가 확정한 판독 — 홈 「오늘 한 일」.
     ⚠ 옛 서버는 두 질의를 몰라 전부 준다. 화면이 오늘 · 확정 · 안 덮인 것만
       다시 거르지만 「내 것」은 못 가린다(assessed_by 가 번호라 /me 와 못 맞춘다) */
  myReads:    ()       => get(`/assessments${qs({ assessed_by: "me", finalized_on: "today" })}`)
    .then((raw) => (Array.isArray(raw) ? raw : raw?.results ?? raw?.items ?? [])),
  /* 09-28 내 판독에 걸린 판정 불일치 — 홈 「내 판독 불일치 결과」.
     ⚠ 이 질의(assessed_by=me)를 모르는 서버는 404 · 403 이거나 남의 것까지
       준다. 앞의 둘은 홈이 칸을 감추고(H.soft 가 아니라 null), 뒤는 막을 수 없다 */
  myDiscordances: ()   => get(`/discordances${qs({ assessed_by: "me" })}`).then(unwrapList),

  /* 품질 판정 — accepted · rejected. 반려여야 재촬영(retake)이 받아진다 */
  quality:    (id, status) => patch(`${RAD}/studies/${id}/upload`, { quality_status: status }),
  history:    (id)     => get(`/assessments${qs({ study: id })}`).then((raw) => {
    if (Array.isArray(raw)) return raw;
    return raw?.results ?? raw?.items ?? [];
  }),
  amend:      (id, b)  => post(`/assessments/${id}/amend`, b),
  /* 「확정 → 다음 건」용 가벼운 목록 — list() 처럼 행마다 오더를 더 부르지 않는다 */
  rows:       (o = {}) => get(`/studies/${qs(o)}`).then(unwrapList),

  /* ⚠ 2026-09-18 — 환자 목록(screens/List.jsx) 상세에 검사 이력을
   * 붙이면서 추가했다. 유방외과 timeline과 같은 서버 경로다
   * (PatientTimelineView, resource="patient") — MATRIX 에 이미
   * RADIOLOGY: R 이 있어 그대로 부를 수 있다(surgery.py 새로 안 고쳐도 됨). */
  timeline:   (pid)     => get(`/patients/${pid}/timeline`),
};

/* ── 검체 바인딩 (공용) ───────────────────────────────────────
 * 간호과·유방외과 둘 다 같은 팝업(SpecimenBindingModal, hospital/lib/)을
 * 쓴다 — 그 컴포넌트가 부르는 자리를 한 곳에 모아 둔다. 영상의학과는
 * 이 화면을 쓰지 않기로 확정됐다(간호과 명세 §3). */
export const specimens = {
  /* 목록 경로에 끝 슬래시를 붙인다. 라우터(ViewSet)로 등록된 목록이라
     슬래시가 없으면 404다 — 2026-09-21 두 웹(example.com·ts.net) 모두에서
     /lesions=404 · /lesions/=200 으로 확인했다. 전에 반대로 적혀 있던
     주석은 그 사이 서버 라우팅이 바뀌기 전 이야기다. */
  lesionsByPatient: (pid) => get(`/lesions/${qs({ patient: pid })}`),
  /* 현재 서버의 specimens 목록은 patient 필터를 아직 받지 않는다. 유방외과
     워크플로 안내에서는 응답을 받은 뒤 해당 환자 것만 골라 쓴다. */
  /* ⚠ 환자 조건을 **서버에** 건다(09-23에 서버도 같이 고쳤다). 전에는
     병원 전체 검체를 받아 화면에서 걸렀다 — 건수가 늘면 그대로 무거워지고,
     거르는 것을 한 곳이라도 빠뜨리면 남의 검체가 섞인다 */
  list: (patient) => get(`/specimens/${qs({ patient })}`).then(unwrapList),
  bind: (b) => post("/specimens/", b),
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
 * 화면은 그대로 두고 이 층만 갈아 끼우면 된다.
 *
 * 2026-09-18 — 목업을 떼고 실제 patients/ 엔드포인트에 맞춘다. 상세
 * (.../patients/{id}/)는 이름·생년월일·전화번호를 pii{} 로 접어서 준다
 * (mock/hospital.json 의 해당 항목이 이미 이 모양이다 — 다른 과가 쓰는
 * 같은 PatientSerializer). 목록(.../patients/?...)은 그대로 펴져 있다.
 * 화면마다 patient.name 을 따로 풀어 쓰게 하지 않고 여기 한 곳에서
 * 펴서 내보낸다 — dept/radiology.jsx 의 withFiles() 와 같은 자리다.
 * age 가 없고 birth_year 만 오면 나이도 여기서 센다(reception/Patients.jsx
 * 의 ageOf() 와 같은 계산). 죽은 코드(openDiscords·finalReport·
 * lesions·bindSpecimen — 어디서도 안 부른다) 는 정리했다. */
function normalizePatient(p) {
  if (!p) return p;
  const { pii, ...rest } = p;
  const birthDate = pii?.birth_date ?? rest.birth_date ?? null;
  return {
    ...rest,
    name:       pii?.name ?? rest.name ?? null,
    birth_date: birthDate,
    phone:      pii?.phone ?? rest.phone ?? null,
    age:        rest.age ?? ageFromBirthDate(birthDate)
      ?? (rest.birth_year ? new Date().getFullYear() - rest.birth_year : null),
  };
}

/* 부가 자료가 실패해도 환자 기본 정보까지 숨기지 않되, 화면에는 실패를
   '자료 없음'으로 오인하지 않도록 상태를 함께 전달한다. */
function optionalResult(promise, fallback) {
  return promise
    .then((value) => ({ value, failed: false }))
    .catch(() => ({ value: fallback, failed: true }));
}

/* 대기·목록은 가볍게 유지하되, 상세를 열었을 때만 환자 원본을 보완한다.
   ExamOrder/Study 응답에는 생년월일·연락처가 없기 때문이다. */
async function radWithPatient(row) {
  const patientId = row?.patient_id ?? row?.patient;
  if (patientId == null) return row;
  const patient = await get(`/patients/${patientId}/`).then(normalizePatient).catch(() => null);
  if (!patient) return row;
  return {
    ...row,
    patient_id: patientId,
    patient_name: patient.name || row.patient_name,
    patient_no: patient.patient_number || row.patient_no,
    age: patient.age ?? row.age,
    sex: patient.sex || row.sex,
    birth_date: patient.birth_date ?? null,
    phone: patient.phone ?? null,
    contrast_allergy: patient.has_allergy ? (patient.allergy_note || "있음") : null,
  };
}

/* 서버는 생년월일을 pii.birth_date 로 준다. 연도만 빼면 생일 전인 환자가
   한 살 크게 보이므로, 오늘 날짜와 월·일까지 비교한다. */
function ageFromBirthDate(value) {
  if (!value) return null;
  const birth = new Date(`${value}T00:00:00`);
  if (Number.isNaN(birth.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const beforeBirthday = today.getMonth() < birth.getMonth()
    || (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate());
  if (beforeBirthday) age -= 1;
  return age >= 0 ? age : null;
}

export const breast = {
  /* 1장 · 대기 환자 */
  /* ⚠ 서버가 페이지네이션 봉투({count,results,…})로 준다. 화면(Waiting.jsx)은
     배열 하나를 기대해서(list.length·list.map) 언랩해서 넘긴다 — 병리·영상
     큐가 이미 하던 것과 같다. pii{} 로 접힌 이름·생년월일·전화도 여기서
     normalizePatient 로 펴서 내보낸다. */
  waiting:      ()   => get(`/patients/${qs({ primary_staff: "me", status: "waiting" })}`)
    .then((raw) => {
      const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
      return rows.map(normalizePatient);
    }),
  /* 내가 주치의인 환자 전부 — 오늘 왔는지와 상관없이. 홈의 「담당 전체」 탭.
     09-27 부터 서버가 primary_staff 와 status 를 같이 보므로 status 를 빼면
     담당 전체다(views/reception.py PatientViewSet.get_queryset) */
  /* 과 전체 대기 — 누구 담당이든 오늘 와서 아직 안 끝난 환자. 홈의 「과 전체」 탭 */
  waitingAll:   ()   => get(`/patients/${qs({ status: "waiting", page_size: PAGE_ALL })}`)
    .then((raw) => {
      const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
      return rows.map(normalizePatient);
    }),
  mine:         ()   => get(`/patients/${qs({ primary_staff: "me", page_size: PAGE_ALL })}`)
    .then((raw) => {
      const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
      return rows.map(normalizePatient);
    }),
  /* 유방외과 전체 환자 목록은 현재 로그인한 의사에게 배정된 환자만이
     아니라 과에서 관리하는 과거·현재 환자 전체를 보여 준다. */
  patients:     ()   => get(`/patients/${qs({ status: "all" })}`)
    .then((raw) => {
      const rows = raw?.results ?? raw?.items ?? (Array.isArray(raw) ? raw : []);
      return rows.map(normalizePatient);
    }),
  /* 환자 상세 응답에는 report가 포함되지 않는다. 유방외과 검토·결정 화면은
     리포트를 함께 쓰므로 목록을 별도로 받아 최신 종합 리포트를 붙인다.
     아직 리포트가 없는 환자는 null로 두고 화면이 안내 상태를 보여 준다. */
  patient:      async (id) => {
    const [rawPatient, reportsR, ordersR, readingsR, lesionsR, oddsR] = await Promise.all([
      get(`/patients/${id}/`),
      optionalResult(get(`/reports/${qs({ patient: id })}`).then(unwrapList), []),
      optionalResult(breast.ordersOf(id), []),
      /* 판독값 · 병변 — 환자 상세 응답에 둘 다 없다. 아래 주석 참고.
         곁가지라 실패해도 화면이 통째로 죽지 않게 빈 값으로 떨어뜨린다 */
      optionalResult(breast.readings(id), { radiology: [], pathology: [] }),
      /* ⚠ 받아서도 **한 번 더 거른다.** 서버가 ?patient= 을 조용히 무시하던
         적이 있었다(09-23에 고쳤다) — 그때 이 화면은 남의 병변을 이 환자
         것으로 그렸다. 같은 실수가 또 나면 화면에서 막는다 */
      optionalResult(
        specimens.lesionsByPatient(id).then(unwrapList)
          .then((rows) => rows.filter(
            (l) => Number(l.patient_id ?? l.patient) === Number(id))),
        [],
      ),
      optionalResult(breast.openDiscordances(id), []),
    ]);
    const reports = reportsR.value;
    const orders = ordersR.value;
    const readings = readingsR.value;
    const lesions = lesionsR.value;
    const odds = oddsR.value;
    const patient = normalizePatient(rawPatient);
    const currentOrder = orders.find((row) => row.visited_at && !["completed", "cancelled"].includes(row.order_status))
      ?? orders.find((row) => row.visited_at)
      ?? orders.at(-1)
      ?? null;
    /* 단계 판독을 최종 리포트로 취급하면 치료 방침 화면이 최종 리포트
       생성 단계를 건너뛴다. final 타입만 환자 대표 리포트로 사용한다. */
    /* 종합 소견서는 의사용 · 환자용 두 벌이 같이 서고, 다시 만들면 또
       두 벌이 는다. 치료 방침은 **가장 최근 의사용**을, 환자 리포트 칸은
       가장 최근 환자용을 본다.
       ⚠ 화면이 읽던 ai_summary · ai_modality_count · is_unlocked 는
         서버에 없는 칸이다 — 그래서 리포트가 있어도 「아직 생성되지
         않았습니다」가 떴다(09-27 환자 127). 서버 칸으로 여기서 채운다:
         본문은 narrative_text, 통합한 판독 수는 content_json.source_ai_ids,
         열람 가능은 lock_status */
    const asFinal = (r) => r && ({
      ...r,
      ai_summary: r.ai_summary ?? r.narrative_text,
      ai_modality_count: r.ai_modality_count ?? r.content_json?.source_ai_ids?.length,
      is_unlocked: r.is_unlocked ?? r.lock_status === "unlocked",
    });
    const finals = reports.filter((row) => row.report_type === "final");
    const report = asFinal(patient?.report?.report_type === "final"
      ? patient.report
      : finals.filter((row) => row.audience !== "patient").at(-1) ?? finals.at(-1) ?? null);
    const patientReport = asFinal(finals.filter((row) => row.audience === "patient").at(-1) ?? null);
    return {
      ...patient,
      report,
      patient_report: patientReport,
      /* 나머지 리포트를 버리지 않는다. 검사 종합·내 환자 화면이 영상/병리
         판독 요약을 여기서 읽는데(Review.jsx·Waiting.jsx 의 other_reports),
         만들어 주는 사람이 없어 늘 「아직 없습니다」로 떴다 — 소견문은
         서버에 멀쩡히 있었다(09-23 김환자에서 확인). */
      other_reports: reports
        .filter((row) => row.report_type === "stage" && row.narrative_text)
        .map((row) => ({
          ...row,
          dept: REPORT_DEPT[row.socket_id] ?? "판독",
          summary: row.narrative_text,
        })),
      /* ⚠ **판정 그 자체가 없었다.** 검사 종합 화면이 「확정」 칩만 띄우고
         정작 BI-RADS 도 B 분류도 못 보여 주고 있었다(09-23 확인). 화면이
         읽던 것은 리포트의 소견문(narrative_text) 하나뿐인데, 판정은
         Assessment · Specimen 표에 있어서 리포트에도 환자 상세에도 안
         실린다. 서버는 진작 내주고 있었다(GET /assessments?study= 는
         유방외과도 부를 수 있다) — 부르는 쪽이 없었을 뿐이다 */
      readings,
      /* ⚠ **화면이 p.lesions 를 읽는데 서버가 그 칸을 안 준다.**
         PatientDetailSerializer 는 Patient + pii 뿐이다. 그래서 병변 줄도,
         뷰어의 3D 패널도 늘 비어 있었다 — /lesions?patient= 로 따로 받는다 */
      lesions,
      /* ⚠ **안 열린 불일치가 늘 「없음」이었다.** 화면은 p.open_discordance
         를 읽는데 서버 응답에 그런 칸이 없다 — undefined 라 검사 종합의
         안전 띠가 어느 환자에게나 초록 「엇갈린 것이 없습니다」로 떴다
         (09-23 확인). 엇갈렸는데 안 엇갈렸다고 말하는 쪽이라 그냥
         비어 있는 것보다 나쁘다. 목록 경로는 진작 있었다 */
      open_discordance: odds[0] ?? null,
      open_discordances: odds,
      data_warnings: [
        reportsR.failed && "판독 리포트",
        ordersR.failed && "검사 오더",
        readingsR.failed && "판독 결과",
        lesionsR.failed && "병변",
        oddsR.failed && "판정 불일치",
      ].filter(Boolean),
      current_order: currentOrder,
      /* 오더 전부 — 진행 중 검사(결과 대기)를 세려고. dept/breast/flow.js */
      orders,
      visit_type: currentOrder?.visit_type ?? null,
      visit_purpose: currentOrder?.exam_purpose ?? null,
      intake_note: currentOrder?.order_note ?? null,
      questionnaire: currentOrder?.questionnaire ?? patient?.questionnaire ?? null,
      allergy: patient?.has_allergy ? (patient.allergy_note || "있음") : "없음",
    };
  },
  reports:      (patientId) => get(`/reports/${qs({ patient: patientId })}`).then(unwrapList),
  finalReport:  (body) => post("/reports/final", body),
  examOrder:    (b)  => post("/exam-orders", b),

  /* "진료 완료" — 촬영 없이 방문을 닫는다. exam_order 를 새로 만들지
   * 않는다(모달리티 없는 오더를 지어낼 수 없다 — ExamOrderRequestSerializer가
   * modality 를 필수로 받는다). 대신 이 환자를 여기로 데려온 exam_order를
   * 찾아 그대로 종결시킨다 — reception.ordersOf 와 같은 조회를 쓴다.
   *
   * ⚠ 2026-09-18 다희님 확인 — PATCH /exam-orders/{id}/complete 는
   * CanCompleteExamOrder 전용 클래스라 유방외과도 이제 부를 수 있다
   * (feature/dahee, dd6268b). 몸통은 안 받는다 — order_status 만
   * completed 로 바뀐다. exam_purpose 는 그대로 NULL로 남고(집계 안
   * 잡힘), "촬영 후 종결"과 "안 찍고 종결"도 completed 하나로 안 갈린다.
   * 둘 다 팀이 합의한 알려진 한계다 — 나중 과제로 미뤘다. */
  /* 실서버는 목록을 { count, results } 봉투로 감싼다. 목업의 배열과
     모양이 달라 종결 팝업에서 .filter 오류가 나던 자리다.
     ⚠ 09-28 — page_size 가 없어 20건에서 잘렸다. 창구 접수 오더는
     scheduled_at 이 비어 있어 이 정렬에서 **맨 뒤**로 가므로(PostgreSQL
     NULLS LAST), 오더가 많은 환자는 오늘 방문이 첫 쪽에서 빠져 「진료
     완료」가 「종결할 오더를 찾지 못했습니다」로 떨어졌다 */
  ordersOf:        (patientId) => get(`/exam-orders${qs({ patient: patientId, ordering: "scheduled_at", page_size: PAGE_ALL })}`).then(unwrapList),
  completeExamOrder: (examOrderId) => patch(`/exam-orders/${examOrderId}/complete`, {}),

  /* 2장 · 검사 종합 확인 */
  timeline:     (pid) => get(`/patients/${pid}/timeline`),
  /* 환자 검사 목록도 다른 목록 API와 같은 {count, results} 봉투로
     내려온다. 화면은 배열을 기준으로 모달리티 탭과 뷰어를 계산하므로
     봉투를 그대로 넘기면 실검사와 타임라인이 있어도
     "촬영한 검사가 없습니다"가 표시된다. */
  studies:      (pid) => get(`/patients/${pid}/studies`).then(unwrapList),

  /* 아직 처분 안 한 판정 불일치 — 영상과 병리가 엇갈린 건.
     ⚠ 목록 경로에는 끝 슬래시가 없다(core/urls.py 의 "discordances") */
  openDiscordances: (pid) =>
    get(`/discordances${qs({ patient: pid, status: "open" })}`).then(unwrapList),
  /* 내 담당 환자의 열린 불일치 전부. primary_staff 를 모르는 옛 서버는
     400/무시 — 그때는 과 전체 열린 것으로 물러난다 */
  myDiscordances: () =>
    get(`/discordances${qs({ status: "open", primary_staff: "me" })}`).then(unwrapList)
      .catch(() => get(`/discordances${qs({ status: "open" })}`).then(unwrapList)),

  /* 09-28 서버 worklist — 환자마다 다음 할 일(next_step)과 건수를 서버가 센다.
     { items:[…], counts:{…} }. ⚠ 없는 서버(404)면 부르는 쪽이 환자별
     상세로 되짚는다(dept/breast/flow.js) — 여기서 삼키지 않는다 */
  worklist: (scope = "me") =>
    get(`/surgery/worklist${qs(scope === "all" ? { scope: "all" } : { primary_staff: "me" })}`),

  /* 판독값 — **소견문이 아니라 판정이다.**
   *
   *   영상   Assessment.category (BI-RADS) · finding_note
   *   병리   Specimen.b_category (B 분류) · diagnosis
   *
   * 둘 다 확정된 것만 센다. 임시저장(draft)은 아직 남에게 보일 값이 아니다.
   * 최신순이다 — 목록이 -performed_at 으로 와서 맨 앞이 이번 검사다. */
  readings: async (pid) => {
    const [studies, specimenRows] = await Promise.all([
      breast.studies(pid).catch(() => []),
      specimens.list(pid).catch(() => []),
    ]);

    const found = await Promise.all(
      /* 번호 없는 검사 줄은 묻지 않는다 — study 없이 부르면 GET /assessments
         (과 전체 목록)가 되어 404 · 헛요청이었다 */
      studies.map((s) => ((s.study_id ?? s.id) != null
        ? radCurrentAssessment(s.study_id ?? s.id) : null)),
    );

    const radiology = studies
      .map((s, i) => {
        const a = found[i];
        if (!a) return null;
        return {
          study_id: s.study_id ?? s.id,
          modality: s.modality ?? null,
          grade: a.category ?? null,
          note: a.finding_note ?? null,
          at: a.finalized_at ?? a.created_at ?? null,
          /* 유방 밀도(A~D) — 서버 09-28~. 옛 서버는 칸이 없어 null */
          density: s.density_category ?? null,
        };
      })
      .filter(Boolean);

    /* 글자로 견준다 — 번호는 같게 나오고, 목업의 「P-1001」 같은 번호도
       맞는다(Number 로 견주면 NaN 끼리라 늘 빠졌다) */
    const pathology = specimenRows
      .filter((row) => String(row.patient_id ?? row.patient) === String(pid))
      .filter((row) => row.finalized_at && (row.diagnosis || row.b_category))
      .map((row) => ({
        specimen_id: row.specimen_id ?? row.id,
        /* 검체번호 — S-DEMO-TISSUE 같은 것. 목록을 가공한 쪽(specimenRow)은
           specimen_no 로 이름을 바꿔 주므로 둘 다 본다 */
        label: row.specimen_label ?? row.specimen_no ?? null,
        grade: row.b_category ?? null,
        note: row.diagnosis ?? null,
        at: row.finalized_at ?? null,
        /* 수용체 · 조직형 · 등급 · sTIL(병리의 입력) — SpecimenSerializer 에
           있다. 옛 서버 · 목업 일부는 없어서 null 로 둔다 */
        histologic_type: row.histologic_type ?? null,
        nottingham_grade: row.nottingham_grade ?? null,
        er: row.er_status ?? null,
        pr: row.pr_status ?? null,
        her2: row.her2_status ?? null,
        ki67: row.ki67_percent ?? null,
        stil: row.stil_calibrated ?? null,
      }));

    /* ⚠ 최신순으로 세운다. 화면(Review.jsx)이 맨 앞을 「이번 판정」으로
       읽는데, 검사 · 검체 조회 순서 그대로라 예전 것이 앞에 올 수 있었다 —
       09-27 환자 127 에서 오늘 확정한 malignant 대신 09-23 의 B2 가 떴다 */
    const newest = (a, b) => String(b.at ?? "").localeCompare(String(a.at ?? ""));
    return { radiology: radiology.sort(newest), pathology: pathology.sort(newest) };
  },

  /* 한 검사의 판독 전부 — 초안 · 정정으로 덮인 것까지(AssessmentSerializer,
     -created_at 순). 진료 이력에서 지난 판독 한 판을 골라 왔을 때만 부른다
     (Review.jsx 의 ?assessment=). readings 는 확정 한 판만 남긴다 */
  assessments: (studyId) => rad.history(studyId),

  /* 유방외과 진료를 열기 전 다음 단계를 판단할 최소 이력. 서버에 별도
     workflow API가 없어서, 이미 있는 검사·오더·검체 조회를 한 번에 묶는다. */
  workflow: async (pid) => {
    const [studiesRaw, orders, specimenRows] = await Promise.all([
      get(`/patients/${pid}/studies`),
      breast.ordersOf(pid),
      specimens.list(pid),
    ]);
    return {
      studies: unwrapList(studiesRaw),
      orders,
      specimens: specimenRows.filter((row) => Number(row.patient_id ?? row.patient) === Number(pid)),
    };
  },

  /* 3장 · 수술 결정
   *
   * ⚠ 2026-09-18 다희님 확인 — POST /assessments 가 아니다. 그런 생성
   * 경로가 서버에 없다. 실제로는 PATCH /assessments/{id}/decision
   * (SurgeryDecisionSerializer: decision_type·decision_value·
   * decision_reason)이고, 건드릴 assessment 는 patient_id 로 못 찾는다
   * — study 에 물려 있다. GET /patients/{id}/timeline 의 "판독" 이벤트가
   * 이제 assessment_id 를 실어 준다(feature/dahee, 6774208) — 화면이
   * 거기서 집어 온다. */
  decide:       (assessmentId, b) => patch(`/assessments/${assessmentId}/decision`, b),
  saveReport:   (rid, b) => put(`/reports/${rid}/`, b),
  explain:      (rid, b) => patch(`/reports/${rid}/explain`, b),
  unlockStatus: (rid) => get(`/reports/${rid}/unlock-status`),
  unlock:       (rid) => patch(`/reports/${rid}/unlock`, {}),
  prescriptions: (patientId) => get(`/patients/${patientId}/prescriptions`).then(unwrapList),
  prescribe:     (patientId, body) => post(`/patients/${patientId}/prescriptions`, body),
  /* 처방 입력칸의 약 이름 자동완성. 환자 앱의 약 찾기와 같은 경로다
   * (core/api/drugs.py — 식약처 e약은요). 키가 비면 서버가 503 을 준다.
   * ⚠ 이름만 받아 쓴다. purpose·how·watch 를 여기서 채우지 않는다 —
   *   drugs.py 머리말: 약전 문장을 처방 설명칸에 넣는 순간 우리가 하는
   *   의학적 조언이 된다. */
  drugs:         (q) => get(`/drugs${qs({ q, page_size: 8 })}`),
  /* DUR(의약품 안전사용) 점검 — 성분끼리 병용금기 · 연령 · 임부 · 노인.
   *   POST /drugs/dur {ingredients, age?, sex?: "F"|"M"}
   *   → {alerts:[{type, level: taboo|caution, ingredient, with?, message, detail}],
   *      checked, partial?, failed?, source, disclaimer}
   * 키가 없는 서버는 503(DUR_UNAVAILABLE). ⚠ 결과는 **알림일 뿐** 처방을
   *   막지 않는다 — 금기여도 확인 표시를 받고 저장한다(Prescription.jsx). */
  dur:           ({ ingredients, age, sex }) => post("/drugs/dur", {
    ingredients,
    ...(age != null && Number.isFinite(Number(age)) ? { age: Number(age) } : null),
    ...(sex ? { sex } : null),
  }),

  /* 4장 · 판정 불일치 처분 */
  discordance:  (id) => get(`/discordances/${id}`),
  /* ⚠ 2026-09-18 다희님 브랜치(dahee)에서 발견 — 접미사 /dispose 가 없다.
   * urls.py 를 다시 보니 실제로 `path("discordances/<int:pk>", ...,
   * {"patch": "partial_update"})` 다 — 상세 경로 그대로 PATCH 하는 것이지
   * /dispose 가 따로 붙지 않는다. 여기가 계속 틀려 있었다. */
  dispose:      (id, b) => patch(`/discordances/${id}`, b),
};

/* ── 간호과 ────────────────────────────────────────────────────
 * 판독 단위가 없다. 유방외과처럼 자기 화면·자기 흐름이라 queue/upload/
 * read/list/amend 틀을 안 쓴다.
 *
 *   1장 내원 대기·배정   원무가 접수한 환자를 유방외과 의사에게 넘긴다
 *   2장 추적 대상 관리   BI-RADS 3 확정 환자의 6·12·24개월 추적
 *   3장 검체 바인딩      유방외과와 같은 팝업(specimens, 위에서 공용화) */
export const nursing = {
  /* 1장 */
  /* ⚠ 2026-09-27 — visited_on=today 를 단다. visited=yes 만으로는 **어제
     접수하고 안 끝난 오더**까지 오늘 대기 줄에 섞였다.
     ⚠ assigned=none 은 **안 단다.** 전에 배정받은 환자가 다시 오면 주치의가
       이미 있어서 그 사람이 줄에서 통째로 빠진다.
     ⚠ 09-27 — 대신 handed=none 을 단다. 보냈는가는 **오더의 handed_at** 이
       갈라 준다(서버, handoff 아래). 예전에는 이 PC 의 localStorage 로 가려서
       다른 PC 에서는 보낸 사람이 다시 떴다.
     예약 환자는 접수(checkin)가 그 예약 오더를 내원 처리하고 requested 로
     되돌려 준다(서버) — 그래서 status=requested 하나로 둘 다 잡힌다 */
  waitingArrived: () => get(`/exam-orders${qs({ status: "requested", visited: "yes", visited_on: "today", handed: "none", ordering: "visited_at", page_size: PAGE_ALL })}`),
  /* ⚠ 서버에 상태 거르개를 안 걸어서 **취소한 예약도** 「금일 내원 예정」·
     「안 오심」에 떴다. 아직 올 수 있는 것(requested · scheduled)만 남긴다 */
  scheduledToday: () => get(`/exam-orders${qs({ scheduled_on: "today", visited: "none", ordering: "scheduled_at", page_size: PAGE_ALL })}`)
    .then((raw) => onlyLive(unwrapList(raw), ["requested", "scheduled"])),
  examOrder:      (id) => get(`/exam-orders/${id}`),
  patient:        (id) => get(`/patients/${id}/`),
  saveNote:       (examOrderId, note) => patch(`/exam-orders/${examOrderId}/note`, { note }),
  /* ⚠ 2026-09-27 — /staff 는 ListAPIView 라 **봉투({count,results})로 온다.**
     예약 판 왼쪽 「보는 사람」은 배열인지만 보고 있어서 명단이 늘 「못
     불렀습니다」로 떴다. 여기서 벗겨 배열로 준다(unwrapList 는 아래 함수
     선언이라 호이스팅된다). 한 쪽 20명에서 잘리지 않게 page_size 도 단다 */
  surgeons:       () => get(`/staff${qs({ role: "surgery", page_size: PAGE_ALL })}`).then(unwrapList),
  /* ⚠ 2026-09-19 확인 — PatientSerializer 가 내는 이름은 primary_staff_id
   * 가 아니라 모델 필드 그대로인 primary_staff 다(core/serializers/
   * reception.py, core/models.py Patient.primary_staff). DRF 는 모르는
   * 키를 그냥 무시하고 200 을 돌려주기 때문에, 예전 이름으로는 응답은
   * 정상인데 실제로는 아무것도 안 바뀌는 채로 넘어가고 있었다. */
  assignSurgeon:  (patientId, staffId) => patch(`/patients/${patientId}/`, { primary_staff: staffId }),
  /* 09-27 간호 → 유방외과 인계. 오더에 handed_at · handed_to 를 남기고 환자
     primary_staff 도 서버가 같이 바꾼다 — 내원 대기의 [보내기]는 이것을 쓴다.
     ⚠ assignSurgeon 으로 보내면 오더에 아무것도 안 남아 대기 줄에 다시
       뜨고, 유방외과 대기에도 안 뜬다 */
  handoff:        (orderId, staffId) => patch(`/exam-orders/${orderId}/handoff`, { staff_id: staffId }),

  /* 2장 */
  /* ⚠ router.register(r"followups", ...) 로 등록된 목록이라 슬래시가
     붙는다 (core/urls.py 확인). createFollowup 은 별도 path()
     "/followups/new" 라 슬래시가 없는 게 맞다 — 헷갈리지 않게 갈라 둔다. */
  followups:      () => get(`/followups/${qs({ include_candidates: 1 })}`),
  createFollowup: (b) => post("/followups/new", b),
  logCall:        (id, b) => patch(`/followups/${id}/call`, b),
  /* 회차 종결. ⚠ /call 은 call_result · call_note 만 적고 status 는
     **안 건드린다**(FollowupCallView). 「연결」로 회차를 끝내려면 ViewSet
     쪽 PATCH /followups/{id}/ 에 closed_reason 을 실어야 서버가
     status · closed_at 을 채운다(FollowupViewSet.partial_update).
     라우터 경로라 끝 슬래시가 붙는다 */
  closeFollowup:  (id, b) => patch(`/followups/${id}/`, b),
  /* 09-28 한 환자의 회차만(?patient=). 후보(BI-RADS 3 · 회차 없음)도 같이 받는다.
     ⚠ 서버가 ?patient= 를 모르면 **전체가 온다** — 화면이 한 번 더 거른다 */
  followupsOf:    (pid) => get(`/followups/${qs({ patient: pid, include_candidates: 1 })}`)
    .then((raw) => unwrapList(raw).filter((r) => String(r.patient ?? r.patient_id) === String(pid))),
  /* 회차 결과 — stable · changed · no_show. 혼자 보내면 결과만 적는다(서버) */
  roundResult:    (id, result) => patch(`/followups/${id}/`, { round_result: result }),

  /* 1장 문진 — 문항 정의(말)와 종이 문진 옮겨 적기.
     ⚠ 정의는 {form_version, questions:[{code, text, options:[{id, text}]}]}.
       못 부르면 화면이 코드 그대로 적는다(Waiting.jsx 의 qaRows) */
  questionnaireForm: () => get("/questionnaire/form"),
  /* 본문은 **답 그대로**({코드: 선택지 id}) — form_version 은 서버가 찍는다.
     서버가 환자 캐시와 오늘 방문 오더 둘 다에 쓴다 */
  saveQuestionnaire: (pid, answers) => patch(`/patients/${pid}/questionnaire/`, answers),
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
/* ⚠ 2026-09-19 확인 — 서버가 주는 페이지네이션 봉투({count,results,…})를
 * 안 벗기고 그대로 넘기던 자리가 이 과에 몇 군데 남아 있었다. 병리·영상
 * 큐에서 이미 겪은 것과 같은 문제인데(2026-09-18, path.queue()/rad.queue()
 * 참고) 원무는 그때 안 고쳤다 — 접수 화면이 정확히 여기서 죽었다
 * ("object is not iterable" — Calendar.jsx가 봉투 객체를 for…of 로
 * 돌리려다 난 에러). 화면들이 배열을 그대로 기대하므로(항목 하나
 * 씌우는 {items,total} 이 아니라) 배열만 뽑아 돌려준다. */
/* ⚠ 2026-09-21 — **봉투의 count 를 버리고 있어서 스무 건이 넘으면 숫자가
 * 틀렸다.** 서버 목록은 한 쪽 20건인데(DefaultPagination) 여기서 results 만
 * 꺼내 주는 바람에, 화면이 그 길이를 세면 21건이든 300건이든 20 으로 읽혔다.
 *
 * **배열 모양은 그대로 두고 total 만 얹는다.** 기존 호출부는 한 줄도 안
 * 바뀌고, 숫자가 필요한 곳만 `.total` 을 읽는다 — 200줄을 받아 셀 필요도
 * 없고 200 을 넘어도 정확하다.
 *
 * ⚠ 안 보이게(enumerable:false) 얹는 이유 — 전개(...arr)나 JSON 으로 옮길 때
 *   따라가지 않아야 한다. 총 개수는 **이 응답의 성질**이지 줄이 아니다. */
/* 취소한 오더를 뺀다(또는 keep 에 든 상태만 남긴다). 서버는 취소를 지우지
   않고 cancelled 로 남겨서, 예약 판만 거르고 **홈 달력 점 · 작은 달력 점 ·
   이번 주/내일 수 · 캘린더**는 취소한 예약까지 셌다.
   ⚠ total 도 거른 수로 다시 단다 — 봉투의 count 는 취소까지 센 수다 */
function onlyLive(arr, keep = null) {
  const out = arr.filter((r) => (keep ? keep.includes(r.order_status)
    : r.order_status !== "cancelled"));
  Object.defineProperty(out, "total", { value: out.length });
  return out;
}

function unwrapList(raw) {
  if (Array.isArray(raw)) return raw;
  const arr = raw?.results ?? raw?.items ?? [];
  Object.defineProperty(arr, "total", { value: raw?.count ?? arr.length });
  return arr;
}

export const reception = {
  search:      (q)  => get(`/patients/${qs({ q })}`).then(unwrapList),
  register:    (b)  => post("/patients/register", b),
  checkIn:     (b)  => post("/exam-orders/checkin", b),
  todayStatus: ()   => get(`/patients/today-status${qs({ page_size: PAGE_ALL })}`).then(unwrapList),
  /* 09-28 한 환자의 동의 기록(읽기 전용) — 간호 · 원무만. 다른 역할은 403,
     경로가 없는 서버는 404 다. 부르는 쪽(screens/Patient.jsx)이 둘 다 칸을 감춘다 */
  consentsOf:  (pid) => get(`/patients/${pid}/consents`).then(unwrapList),

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
      page_size:      PAGE_ALL,
    })}`).then((raw) => onlyLive(unwrapList(raw))),

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
  /* ⚠ 2026-09-27 — page_size 를 안 달아 **스무 명에서 잘렸다**(DefaultPagination).
     환자 목록 화면이 전체를 받는 자리라 PAGE_ALL 을 기본으로 단다. 서버
     max_page_size 가 200 이라 그보다 많으면 거기서 멈춘다 — 수는 .total */
  list:   (p)      => get(`/patients/${qs({ page_size: PAGE_ALL, ...p })}`).then(unwrapList),
  detail: (id)     => get(`/patients/${id}/`),
  /* ⚠ 여기로는 **이름·생년월일·전화를 못 고친다.** 그 셋은 patient_pii 에
     있고 PatientSerializer 는 patient 표만 다룬다 (상세의 pii 는 읽기 전용).
     고칠 수 있는 것은 성별 · 출생연도 · 알레르기 둘 · 주치의다 */
  update: (id, b)  => patch(`/patients/${id}/`, b),

  /* 같은 환자의 예약을 전부 본다 — 같은 날 중복 예약을 잡으려고 */
  /* ⚠ page_size 가 없어 스무 건에서 잘렸다 — 예약이 많은 환자는 뒤쪽(최근)
     예약이 안 보여 같은 날 중복을 못 잡았다 */
  ordersOf: (id)   => get(`/exam-orders${qs({ patient: id, ordering: "scheduled_at", page_size: PAGE_ALL })}`).then(unwrapList),

  /* [예약 완료]. **원무는 날짜만 정한다** — modality · exam_purpose ·
     ordered_by 는 안 보낸다. 서버도 그 셋을 안 받는다
     (ExamOrderScheduleSerializer 는 patient_id · scheduled_at · followup_id).
     09-28 followup_id 는 추적 회차에서 잡는 예약일 때만 — 오더에 회차를 잇는다 */
  reserve: (b)     => post("/exam-orders/schedule", b),

  /* 09-28 창구 인적 사항 정정 — 이름 · 전화 · 생년월일(patient_pii). 보낸 칸만
     고친다. ⚠ 위 update 로는 이 셋이 조용히 안 바뀐다 */
  correctPii: (id, b) => patch(`/patients/${id}/pii`, b),
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
/* ⚠ 2026-09-19 확인 — 위 reception 본체의 다섯 함수와 같은 봉투 문제가
 * 여기도 있었다. 예약 관리 왼쪽 「앱 신청」 줄(Reservations.jsx)이 배열로
 * 바로 쓴다. (옛 Requests.jsx · Calendar.jsx 는 09-28 지웠다) */
reception.requests = () =>
  get(`/exam-orders${qs({
    status: "requested", visited: "none", ordering: "scheduled_at",
    page_size: PAGE_ALL,
  })}`).then(unwrapList);

/* [예약 확인]. **날짜만 보낸다.**
 *
 * ⚠ 2026-09-27 확인 — 서버가 바뀌어 이제 scheduled_at 하나만 받는다
 *   (ExamOrderConfirmSerializer). 실서버에서 돈다. 예약 판(Reservations.jsx)
 *   오른쪽 [신청 확정] 이 이것을 부른다.
 *
 * ⚠ 확정하면 order_status 가 **scheduled** 가 된다. ordered 가 아니다 —
 *   검사 종류가 정해져야 ordered 이고 그건 유방외과 몫이다. 값이 새로
 *   느는 것이라 DB 쪽은 따로 간다.
 */
reception.confirm = (id, scheduledAt) =>
  patch(`/exam-orders/${id}/confirm`, { scheduled_at: scheduledAt });

/* 09-27 예약 변경 · 취소. 새로 만들지 않고 **있는 오더를 고친다.**
   취소는 지우지 않고 cancelled 로 바꾼다(이력이 남는다). 이미 내원했거나
   진행 중인 오더는 서버가 409 RESERVATION_LOCKED 로 막는다 */
reception.reschedule = (id, scheduledAt) =>
  patch(`/exam-orders/${id}/reschedule`, { scheduled_at: scheduledAt });
reception.cancel = (id) => post(`/exam-orders/${id}/cancel`, {});

export const byDept = { pathology: path, radiology: rad, breast, reception, nursing };

/* ── 직원 회원가입 ────────────────────────────────────────────
 * 2026-09-16 백엔드 확정 — core/api/views.py 의 signup_staff.
 *
 *   POST /signup/staff
 *   b:{staff_number, full_name, login_id, password, role}
 *   ⚠ 2026-09-18 docs/backend-api-reference.md §1 대조 — 필드명이 name 이
 *     아니라 full_name 이다. Signup.jsx 도 이 이름으로 보낸다
 *   role 은 다섯 값만 허용 — reception · nursing · radiology · surgery ·
 *   pathology (admin · patient 를 보내면 VALIDATION_ERROR)
 *
 * 환자 가입(src/api.js)과 다른 점 — 마지막 submit 이 로그인으로 안
 * 이어진다. login_id/staff_number 중복이면 서버가 이 호출에서 바로
 * VALIDATION_ERROR 를 준다(별도 중복확인 API 없음). 성공하면
 * account_status=pending · is_active=False 로 만들어지고 토큰은 안
 * 온다 — 관리자 승인 후에야 로그인된다 (Login.jsx 의 account_status
 * 처리와 같은 결).
 *
 * ⚠ 휴대전화 인증 없음. Account 에 phone 컬럼 자체가 없다
 *   (phone_verified 만 미리 파 둔 빈 컬럼) — 요청 본문에도 없다.
 */
export const staffSignup = {
  submit: (b) => post("/signup/staff", b),
  // → {detail}
};

export const apiInfo = { base: BASE, mock: BASE === MOCK };
