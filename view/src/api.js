/* 서버를 부르는 층 — 화면은 여기만 쓴다.
 *
 * 규칙 하나: **주소를 코드에 박지 않는다.**
 *   fetch("/api/v1/…")  ○      자기가 열린 주소에서 부른다
 *   fetch("http://…")   ✗      교차 출처가 되고 CORS 목록에 걸린다
 *
 * 아래 함수들이 전부 상대 경로로 시작하는 이유가 그것이다. 개발 중에는
 * Vite 가 서버로 넘겨 주고(vite.config.js), 배포에서는 nginx 가 같은
 * 주소에서 받는다. 어느 쪽이든 화면 코드는 그대로다.
 *
 * ── 예외 하나: 안드로이드 앱 ───────────────────────────────────────
 * 앱은 화면 파일을 **자기가 들고 돈다**(Capacitor 번들). 그래서 열린 주소가
 * https://localhost 이고, 상대 경로로 부르면 서버가 아니라 자기 자신을
 * 두드린다. 웹의 / 는 의료진 화면이라 서버 주소를 열어 둘 수도 없다
 * (nginx 의 입구 표 · 커밋 ceebfbf).
 *
 * 그래서 **빌드할 때만** 서버 주소를 넣는다. 코드에 박는 것이 아니라
 * 빌드 인자로 받는다 — 웹 빌드에서는 비어 있어 예전 그대로 상대 경로다.
 *   앱  VITE_API_ORIGIN=https://empatho.example.com npm run build
 *   웹  npm run build                      (그대로)
 */
const API_ORIGIN = String(import.meta.env?.VITE_API_ORIGIN || "").replace(/\/+$/, "");

/* 상대 경로 앞에 서버 주소를 붙인다. 비어 있으면 상대 경로 그대로 나간다. */
const at = (path) => API_ORIGIN + path;

/* ── 오류 ─────────────────────────────────────────────────────────
   서버는 { code, detail } 로 실패를 알려 준다. 화면이 code 로 갈라야
   하므로 Error 에 실어 둔다. status 도 남긴다 — 401 과 403 은 화면이
   다르게 굴어야 한다(다시 로그인 / 권한 없음).
   ───────────────────────────────────────────────────────────────── */
export class ApiError extends Error {
  constructor(status, code, detail, traceId = null) {
    super(detail || code || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code || "UNKNOWN";
    this.detail = detail || "";
    this.traceId = traceId;
  }
}

/* 실제 Django는 access 토큰을 요구한다. 토큰은 페이지를 닫으면 사라지는
   메모리에만 두고, 새로 연 탭에서는 refresh 쿠키로 다시 받는다. */
let accessToken = null;
let refreshing = null;

export function setAccessToken(token) {
  accessToken = token || null;
}

/* refresh 를 앱에서 직접 들고 있는다.
 *
 * 웹(https)은 서버가 주는 httponly 쿠키로 충분하다 — 스크립트가 못 읽는 쪽이
 * 안전하다. 그런데 **앱(Capacitor·에뮬레이터)은 http·다른 출처라 브라우저가
 * Secure 쿠키를 통째로 버린다.** 그러면 액세스(30분)가 끝나는 순간 쓰던 중에
 * 로그아웃된다. 그래서 로그인 응답의 refresh 를 여기 저장했다가 재발급 때
 * 본문으로 보낸다. 쿠키가 살아 있는 웹에서는 이 값이 비어 있어도 그대로 돈다.
 *
 * localStorage 를 쓰는 이유 — 앱을 껐다 켜도 14일은 다시 로그인하지 않게. */
const REFRESH_KEY = "empatho.refresh";
let refreshToken = null;

export function setRefreshToken(token) {
  refreshToken = token || null;
  try {
    if (token) localStorage.setItem(REFRESH_KEY, token);
    else localStorage.removeItem(REFRESH_KEY);
  } catch { /* 저장이 막힌 브라우저(프라이빗 모드 등)면 메모리로만 쓴다 */ }
}

function getRefreshToken() {
  if (refreshToken) return refreshToken;
  try { refreshToken = localStorage.getItem(REFRESH_KEY); } catch { /* 위와 같다 */ }
  return refreshToken;
}

function unwrap(data) {
  return data && typeof data === "object" && "success" in data ? data.data : data;
}

function apiError(status, data, fallback, traceId) {
  const error = data?.error;
  return new ApiError(
    status,
    error?.code || data?.code,
    error?.message || data?.detail || fallback,
    data?.trace_id || traceId,
  );
}

async function refreshAccess() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      // 쿠키가 있으면 서버가 그걸 먼저 본다(웹). 앱은 저장해 둔 refresh 를 싣는다.
      const saved = getRefreshToken();
      const res = await fetch(at("/api/v1/token/refresh"), {
        method: "POST",
        headers: {
          Accept: "application/json",
          ...(saved ? { "Content-Type": "application/json" } : {}),
        },
        credentials: "include",
        body: saved ? JSON.stringify({ refresh: saved }) : undefined,
      });
      const payload = await res.json().catch(() => null);
      const next = res.ok ? unwrap(payload)?.access : null;
      if (next) setAccessToken(next);
      // 재발급까지 막혔으면 들고 있던 refresh 도 버린다 — 만료·폐기된 것이라
      // 계속 들고 있어 봐야 매 요청마다 헛되이 한 번씩 더 두드리게 된다.
      if (!next) setRefreshToken(null);
      return next || null;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function call(path, { method = "GET", body, signal, headers, retried = false } = {}) {
  if (!path.startsWith("/")) {
    throw new Error(`상대 경로여야 한다: ${path}`);
  }
  const res = await fetch(at(path), {
    method,
    signal,
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });

  if (res.status === 204) return null;

  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { /* 본문이 JSON 이 아닐 때 */ }
  }

  /* 새로고침 뒤 access는 비어 있지만 refresh 쿠키가 남아 있을 수 있다.
     로그인·갱신 요청 자체에는 이 과정을 걸지 않는다. */
  if (res.status === 401 && !retried
      && path !== "/api/v1/login" && path !== "/api/v1/token/refresh") {
    const next = await refreshAccess();
    if (next) return call(path, { method, body, signal, headers, retried: true });
  }

  if (!res.ok || data?.success === false) {
    throw apiError(res.status, data, text.slice(0, 300), res.headers.get("X-Trace-Id"));
  }
  return unwrap(data);
}

export const get  = (p, o)       => call(p, { ...o, method: "GET" });
export const post = (p, body, o) => call(p, { ...o, method: "POST", body });
export const put  = (p, body, o) => call(p, { ...o, method: "PUT", body });
export const patch = (p, body, o) => call(p, { ...o, method: "PATCH", body });
export const del  = (p, o)       => call(p, { ...o, method: "DELETE" });

/* 질의 문자열. 빈 값은 빼고 붙인다 — `?q=` 만 달랑 가면 서버가 «빈
   글자로 찾아 달라»로 읽을 수 있다 */
function qs(o = {}) {
  const e = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? `?${new URLSearchParams(e)}` : "";
}

/* ── 판독 진행 상태는 이 앱이 안 본다 ─────────────────────────────
   전에 waitForRead() 가 여기 있었다. `/api/v1/reads/{id}` 를 2초마다
   찔러 run_status 가 done 이 되기를 기다리는 함수였는데, 지웠다
   (2026-09-17, empatho-app 을 보고 확인).

     · 그 경로가 서버에 없다. 진행 상태는 AiResult.run_status 에 있고
       꺼내는 길은 병원 웹이 쓰는 `GET /ai-results?study={id}` 다
       — { status, pct } 로 나온다 (run_status 는 DB 컬럼명이라
       응답에 안 나온다).
     · 애초에 **환자는 추론을 걸지 않는다.** 앱에는 분석을 시작하는
       화면이 없고, 다 끝난 뒤 리포트를 받는다. 기다릴 일이 없다.

   환자에게 「끝났다」를 알리는 길은 폴링이 아니라 **알림**이다 —
   바로 아래 openNotifications 가 그 자리다.
   ───────────────────────────────────────────────────────────────── */

/* ── 실시간 알림 ───────────────────────────────────────────────────
   notify 가 SSE 로 흘려 준다. nginx 쪽은 버퍼링을 꺼 두었고 24시간까지
   열어 둔다(conf/nginx/default.conf).

   끊기면 브라우저가 알아서 다시 붙는다. 다만 **버퍼가 넘치면 서버가
   resync 를 보낸다** — 그때는 목록을 통째로 다시 받아야 한다. 놓친
   알림을 이어붙이려 하면 안 된다.

   ── 티켓을 주소에 싣는다 ─────────────────────────────────────────
   ⚠ **EventSource 는 헤더를 못 붙인다.** 규격에 그런 자리가 없어서
     Authorization 을 쓸 수가 없다. 그래서 구독만 ?ticket= 으로 받는다
     (gosvc 의 streamTicket). 서버도 이 경로의 접근 로그를 꺼 두었다.

   ── 티켓이 만료되면 ─────────────────────────────────────────────
   ⚠ EventSource 의 자동 재연결은 **같은 주소로** 다시 붙는다. 티켓이
     만료되면 옛 티켓으로 영원히 401 을 맞는다 — 화면은 「다시 붙는 중」
     으로 보이고 알림만 조용히 안 온다.

     그래서 자동 재연결에 맡기지 않고, 끊기면 **티켓을 새로 받아** 다시
     연다. 판독 화면을 하루 종일 켜 두는 자리라 이게 없으면 오후에는
     알림이 안 온다.
   ───────────────────────────────────────────────────────────────── */
export function openNotifications({ issue, onEvent, onResync, onError } = {}) {
  let es = null;
  let closed = false;
  let tries = 0;
  let timer = null;

  async function open() {
    if (closed) return;
    let url = "/svc/v1/notify/stream";
    try {
      /* issue 가 없으면 티켓 없이 연다 — 목업은 인증을 안 본다 */
      if (issue) {
        /* ⚠ scope_id 를 **반드시 실어야 한다** (2026-09-17, empatho-app 의
           core/api/tickets.py 로 확인). notify 티켓은 대상이 검사나
           검체가 아니라 **사람**이라 보낼 것이 없어 보이는데, 서버가
           `if not scope_id` 로 먼저 막아서 빼면 VALIDATION_ERROR 다.
           전에는 purpose 만 보내고 있어서 **열리지 않았을 것**이다.

           보낸 값 자체는 서버가 버린다 — 「요청이 보낸 scope_id 를
           버린다」고 코드에 적혀 있고, 로그인한 계정으로 바꿔 끼운다.
           남의 알림을 구독하지 못하게 하려는 것이다. 그래서 여기 무엇을
           넣든 결과가 같지만, 빈 값·0 은 안 된다 */
        const t = await issue({ purpose: "notify", scope_id: "me" });
        url += `?ticket=${encodeURIComponent(t.token)}`;
      }
    } catch (e) {
      onError?.(e);
      return retry();
    }
    if (closed) return;

    es = new EventSource(url);

    es.onopen = () => { tries = 0; };   /* 붙었으면 기다린 시간을 되돌린다 */

    es.onmessage = (e) => {
      let d = null;
      try { d = JSON.parse(e.data); } catch { return; }
      if (d?.type === "resync") onResync?.(d);
      else onEvent?.(d);
    };

    es.onerror = (e) => {
      onError?.(e);
      /* ⚠ 여기서 브라우저에 맡기지 않고 우리가 닫는다. 안 닫으면 옛 티켓으로
         계속 다시 붙으려 한다 */
      es.close();
      es = null;
      retry();
    };
  }

  /* 1·2·4·8…초, 최대 30초. 서버가 죽었을 때 초당 한 번씩 두드리지 않는다 */
  function retry() {
    if (closed) return;
    const wait = Math.min(30000, 1000 * 2 ** tries++);
    timer = setTimeout(open, wait);
  }

  open();

  return () => {
    closed = true;
    clearTimeout(timer);
    es?.close();
  };
}

/* ── 화면이 부르는 것들 ────────────────────────────────────────────
   경로는 아직 Django 에 없다. 가짜 API(mock/db.json)가 같은 모양으로
   돌려주므로 화면은 지금부터 만들 수 있다.

   **여기 적힌 것이 Django 에 요청할 목록이다.** 늘어나면 여기부터 고치고
   mock/db.json 을 맞춘다 — 두 곳이 어긋나면 화면이 조용히 빈다.
   ───────────────────────────────────────────────────────────────── */
/* 안 고른 문항을 걷어낸다. 위 04 의 세 번째 약속을 지키는 자리다. */
export function onlyAnswered(ans) {
  return Object.fromEntries(
    Object.entries(ans ?? {}).filter(([, v]) => v != null && v !== ""));
}

export const api = {
  // 01  로그인
  //
  //     ⚠ 경로와 칸 이름을 고쳤다 (2026-09-17, empatho-app 의 Django 를
  //       직접 보고 맞춤). 전에는 `/auth/login` 에 `{ username }` 을
  //       보내고 있었는데 **둘 다 서버에 없는 것**이었다.
  //
  //         POST /api/v1/login  { login_id, password }  →  { access, refresh }
  //
  //     **환자와 직원이 같은 문으로 들어간다.** 계정이 한 표(account)에
  //     있고 role 로만 갈린다 — 그래서 병원 웹과 경로가 같다. 앱이
  //     따로 쓸 로그인이 있는 줄 알았던 것이 착각이었다.
  //
  //     refresh_token 은 httpOnly 쿠키로 서버가 보관한다. access 토큰은
  //     이 파일의 메모리에만 두며, 새로고침 뒤에는 `/token/refresh`로
  //     다시 받는다.
  login:        async (id, pw) => {
    const session = await post("/api/v1/login", { login_id: id, password: pw });
    setAccessToken(session?.access);
    // 앱은 이걸 들고 있어야 30분 뒤에 안 끊긴다(웹은 쿠키가 있어 없어도 된다).
    setRefreshToken(session?.refresh);
    return session;
  },
  logout:       async () => {
    try { return await post("/api/v1/logout"); }
    finally { setAccessToken(null); setRefreshToken(null); }
  },
  me:           ()         => get("/api/v1/me"),

  // 02  가입 — 두 걸음이다. 서버 쪽은 empatho-app core/api/signup.py.
  //
  //   ① identity   포트원 본인인증을 마친 id 와 입력값(이름 · 생년월일 ·
  //                성별 · 휴대폰)을 보낸다. 서버가 포트원에 다시 묻고 입력값과
  //                대조해 맞으면 verify_token(10분)을 준다. 다르면 거절이다
  //   ② signup     아이디 · 비밀번호를 정해 ①의 표를 들고 가입을 마친다
  //
  // **아이디는 사용자가 정한다.** 병원 기록과는 이름+생년월일+휴대폰이 모두
  // 같을 때만 잇는다. 주민등록번호는 받지 않는다.
  identity:     (payload)  => post("/api/v1/signup/identity", payload),
  checkId:      (v)        => get(`/api/v1/signup/check-id?value=${encodeURIComponent(v)}`),
  signup:       async (payload) => {
    const session = await post("/api/v1/signup/link", payload);
    // 가입이 끝나면 곧 로그인 상태다 — login 과 같이 토큰을 쥔다
    setAccessToken(session?.access);
    setRefreshToken(session?.refresh);
    return session;
  },

  // 03  홈
  home:         ()         => get("/api/v1/home"),

  // 04  문진
  //
  //     DB 는 questionnaire 를 **jsonb 한 칸**에 담는다. jsonb 는 모양을
  //     강제하지 않으므로(CHECK 을 못 건다) 양쪽이 같은 모양을 쓰기로
  //     약속하는 수밖에 없다. 그 약속이 아래 세 줄이다.
  //
  //       · 보내는 것은 { answers: { 문항id: 선택지id } } 한 겹이다.
  //         평평하게 보내면 나중에 answered_at 같은 것을 더할 때 그게
  //         문항인지 메타인지 구분이 안 된다.
  //       · 값은 **선택지 id** 다. 「없다」 같은 문구를 넣으면 문구를
  //         다듬는 순간 옛 자료가 무슨 뜻이었는지 모르게 된다.
  //       · **안 고른 문항은 아예 안 보낸다.** null 을 채워 보내면
  //         「모르겠다」와 「아직 안 답함」이 같은 모양이 된다.
  //
  //     answered_at 과 form_version 은 서버가 찍는다. 앱은 모른다.
  questionnaire:      ()      => get("/api/v1/questionnaire"),
  saveQuestionnaire:  (ans)   => put("/api/v1/questionnaire",
                                     { answers: onlyAnswered(ans) }),

  // 05  예약 — 환자는 **날짜와 시간만** 신청한다.
  //     검사 종류(modality)는 병원이 확정할 때 정한다. 그래서 신청 본문에
  //     modality 가 없다 — 앱이 보내면 안 되는 값이다.
  //     신청 본문에 **촬영 방법을 바꾸는 문항 셋**을 같이 싣는다. 병원이
  //     검사 종류를 정하는 시점에 임신·보형물·조영제를 알아야 한 번에
  //     제대로 잡는다. 나머지 문진은 검사 전에 문진 화면에서 채운다.
  //
  //     ⚠ 문진은 **04 와 같은 한 겹짜리 모양**이다. answers 를 벗기고
  //       평평하게 보내면 Django 가 한쪽만 읽는다.
  //
  //       { date, time,
  //         questionnaire: { answers: { pregnancy: "no", … } } }
  reservations:  ()        => get("/api/v1/me/reservations"),
  requestVisit:  (body)    => post("/api/v1/me/reservation-requests/", body),
  cancelVisit:   (id)      => post(`/api/v1/me/reservations/${id}/cancel`),

  // 06 · 07  결과 · 안내문
  //     내원 한 번에 리포트 하나다. 서버가 report_type='final' ·
  //     audience='patient' 만 준다 — **앱은 묶는 일을 하지 않는다.**
  //     lock_status 가 'locked' 면 본문이 오지 않는다(대면 설명 전).
  //
  //     ⚠ 서버는 목록을 { count, results } 로 준다(알림과 같다). 화면은
  //     items 를 읽어서 여기서 맞춘다 — 안 맞추면 결과가 있어도 늘 빈 목록이다.
  //     Report 에는 title · visit_date · read_at 칸이 없어 가까운 칸으로
  //     채운다: 날짜는 잠금이 풀린 날(설명한 날), 읽음은 last_viewed_at.
  results:      ()         => get("/api/v1/reports/").then((raw) => ({
    ...(raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {}),
    items: (Array.isArray(raw) ? raw : (raw?.results ?? raw?.items ?? [])).map((r) => ({
      ...r,
      title: r.title ?? "검사 결과 안내",
      visit_date: r.visit_date ?? (r.unlocked_at || r.explained_at || "").slice(0, 10),
      read_at: r.read_at ?? r.last_viewed_at,
    })),
  })),
  report:       (id)       => get(`/api/v1/reports/${id}/`),

  // 08  챗봇 — 개인 결과를 인용하지 않는 안내용이다
  chat:         (q)        => post("/api/v1/chat", { question: q }),

  // 09  알림
  // Django router는 목록을 { count, results }로 감싼다. 화면은 목업과
  // 같은 { items }만 보도록 여기서 맞춘다. 읽음은 별도 /read 경로가
  // 아니라 PATCH 본문 acknowledged:true가 서버 규격이다.
  notifications: ()        => get("/api/v1/notifications/").then((raw) => ({
    ...(raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {}),
    items: Array.isArray(raw) ? raw : (raw?.results ?? raw?.items ?? []),
  })),
  markRead:      (id)      => patch(`/api/v1/notifications/${id}/`, { acknowledged: true }),
  // FCM에서 얻은 기기 토큰을 계정에 연결하는 API다. 알림 종류별 수신
  // 설정 API는 아직 서버에 없으므로 Settings의 토글과 혼용하지 않는다.
  registerPushToken: (token) => patch("/api/v1/me/push-token", { push_token: token || "" }),

  // 11  복약 관리 — **처방전이 원천이다**
  //
  //     약 목록을 따로 들고 있지 않는다. 처방전을 불러오고 그 안의 약을
  //     꺼내 쓴다. 약이 왜 거기 있는지(누가 · 언제 · 며칠분 처방했는지)를
  //     화면이 같이 말할 수 있어야 하기 때문이다 — 「타목시펜 20mg」만
  //     띄우면 환자는 그게 언제 끝나는 약인지도 모른다.
  //
  //       GET  /me/prescriptions               { items, note }
  //       POST /me/medications/{drugId}/log    { time } → { log_id, taken_at }
  //       DELETE …/log/{logId}                 잘못 누른 것을 되돌린다
  //
  //     처방전 = { prescription_id, issued_on, prescriber, dept, hospital,
  //                days, status: "active"|"ended", drugs: [...] }
  //     약     = { drug_id, name, ingredient, dose, times[], per_day,
  //                purpose, how, watch, today: [{ time, log_id|null }] }
  //
  //     ⚠ **설명(purpose · how · watch)은 처방에 실려 온다.** 앱이 약 이름
  //       으로 어딘가를 뒤져 지어내지 않는다. 같은 성분도 환자마다 쓰는
  //       이유가 다르고, 무엇을 주의해야 하는지는 처방한 사람이 안다.
  //       앱이 약전을 긁어다 붙이면 그 순간 **의학적 조언**이 된다.
  //
  //     ⚠ **환자는 약을 더하거나 고치지 못한다.** 손잡이는 「먹었다」를
  //       적는 것 하나뿐이다. 앱에서 약을 만들 수 있게 하면 화면의 목록과
  //       처방이 갈라지고, 그 뒤로는 어느 쪽이 맞는지 아무도 모른다.
  //
  //     ⚠ **복용 시각은 서버가 찍는다.** 앱은 「어느 회차」인지만 보낸다 —
  //       기기 시계가 틀어진 만큼 기록이 어긋나면 안 되는 자료다.
  prescriptions: ()          => get("/api/v1/me/prescriptions"),
  takeMed:       (id, time)  => post(`/api/v1/me/medications/${id}/log`, { time }),
  undoMed:       (id, logId) => del(`/api/v1/me/medications/${id}/log/${logId}`),

  // 11-2  약 정보 찾기 — **식약처 자료를 옮겨 주는 사전이다**
  //
  //     Django 가 식약처 「의약품개요정보(e약은요)」 공공데이터를 받아
  //     칸 이름만 우리 것으로 바꿔 준다.
  //
  //       GET /api/v1/drugs?q=타이레놀&page=1&page_size=10
  //         → { items, count, page, page_size, source, disclaimer }
  //       GET /api/v1/drugs/{item_seq}
  //         → { item, source, disclaimer }
  //
  //       약 = { item_seq, name, maker, image, efficacy, how_to_use,
  //              warning, caution, interaction, side_effect, storage,
  //              updated_at }
  //
  //     ⚠ **바로 위 11 의 처방 설명과 섞지 않는다.** purpose · how · watch
  //       는 처방한 사람이 이 환자를 보고 쓴 문장이고, 여기 오는 것은 그
  //       약의 일반 허가사항이다. 여기 것을 그 칸에 끼워 넣으면 그 순간
  //       앱이 **의학적 조언**을 하게 된다 — 11 의 경고가 막으려던 그것이다.
  //
  //     ⚠ source · disclaimer 를 **화면에 반드시 적는다.** 서버가 매번
  //       실어 보내는 이유가 그것이다(문구가 바뀌어도 앱 배포를 안 기다린다).
  //       빼면 환자에게는 병원이 해 준 설명으로 읽힌다.
  drugs:         (o = {})    => get(`/api/v1/drugs${qs(o)}`),
  drug:          (seq)       => get(`/api/v1/drugs/${encodeURIComponent(seq)}`),

  // 12  병원 찾기
  //
  //     원천은 국립중앙의료원 「전국 병·의원 찾기 서비스」다(서버가 부른다).
  //
  //     ⚠ **기기 위치를 받지 않는다.** 그쪽에 좌표 주변을 찾는 기능이
  //       따로 있지만 서버가 쓰지 않는다 — 쓰면 환자의 좌표가 우리 로그에
  //       남고, 그건 따로 동의를 받아야 하는 정보다. 병원 좌표(lat·lng)만
  //       받아 거리는 브라우저에서 잰다.
  //
  //     ⚠ **협력 병원 목록이 아니다.** 전국 병·의원 79,013 건이 그대로
  //       온다. 응답의 note 가 그 말을 싣고 있으니 화면에서 빼지 말 것 —
  //       빼면 병원이 보증한 목록으로 읽힌다.
  //
  //     ⚠ 거르는 것은 **서버가 한다.** 전국 자료라 한 장에 오는 것만
  //       화면에서 걸러 봐야 그 장 안에서만 걸러진다.
  //
  //     ⚠ 주소를 `/hospitals` 로 둔다. 목업에서 직원용 접두사
  //       `/api/v1/hospital` 과 **글자가 겹쳐** 한동안 요청이 그쪽으로
  //       빨려 들어갔다 — mock/hospital.js 가 경계를 마디로 보게 고쳤다.
  //       실제 서버에는 그 접두사가 없어서 겹칠 일이 없다.
  //
  //       GET /hospitals?q=&region=&page=&page_size=
  //         → { items, regions, count, page, page_size, source, note }
  //
  //       병원 = { hospital_id, name, dept, address, phone,
  //                region, hours, etc, lat, lng }
  //
  //       ⚠ hours 는 **서버가 묶어서 준다** — 월~금이 다 같을 때만
  //         「평일 09:00~18:00」이고 하루라도 다르면 요일을 따로 적어
  //         보낸다. 화면에서 다시 묶지 말 것.
  //       ⚠ phone · lat · lng · hours · etc 는 **비어 있을 수 있다.**
  //         화면이 전화 · 길찾기 단추와 그 줄을 그때만 낸다.
  //
  //       지역 칩(regions)도 서버가 준다. 화면이 시도 이름을 들고 있으면
  //       원천 자료의 이름과 어긋날 수 있다 — 실제로 「광주·전남」이
  //       자료에서는 한 덩어리(전남광주통합특별시)라 그 번역을 서버가 한다.
  hospitals:     (o = {})    => get(`/api/v1/hospitals${qs(o)}`),

  // 10  내 정보
  consents:      ()        => get("/api/v1/consents"),
  //     필수 동의는 철회할 수 없다. 서버가 can_withdraw 로 알려 주고,
  //     화면은 그때만 철회 자리를 낸다 — 눌러도 안 되는 것을 흐리게
  //     두면 「왜 안 되지」를 만든다.
  withdrawConsent: (kind)  => post(`/api/v1/consents/${kind}/withdraw`),
};
