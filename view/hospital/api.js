/* 서버를 부르는 자리. **fetch 는 여기 말고 쓰지 않는다.**
 *
 * 병리과 화면 명세(2026-09-14 · 백엔드 최일운)의 엔드포인트를 옮겼다.
 *
 * ═══ 진짜 서버로 갈아탈 때 고칠 곳 ══════════════════════════════
 * 세 자리뿐이고, 전부 이 파일 안에 있다. 화면은 하나도 안 건드린다.
 *
 *   ① BASE        주소 앞머리          아래 «주소» 구역
 *   ② unwrap      응답 봉투 벗기기      아래 «봉투» 구역
 *   ③ setToken    JWT 붙이기           아래 «인증» 구역
 *
 * 세 자리에 ⚠ 를 달아 두었다.
 * ══════════════════════════════════════════════════════════════
 */

/* ── ① 주소 ───────────────────────────────────────────────────
   mock 으로 돌 때와 진짜 서버에 붙을 때가 다르다.

     npm run dev:mock   /api/v1/hospital  ← mock/hospital.js 가 받는다
     npm run dev        /api/v1           ← nginx 가 Django 로 넘긴다

   ⚠ 명세는 `/specimens` 처럼 짧게 적혀 있는데, 환자 앱이 이미
     `/api/v1/reports` 를 쓰고 있어 `/reports/{id}` 가 겹친다. 직원과
     환자는 권한 계층이 달라 어딘가에서 갈라야 한다. 정해지면 아래
     REAL 한 줄만 고치면 된다.

   .env 로도 덮어쓸 수 있다 — 서버 주소가 사람마다 다를 때 쓴다.
     VITE_API_BASE=/api/v1/staff */
const MOCK = "/api/v1/hospital";
const REAL = "/api/v1";
const BASE = import.meta.env.VITE_API_BASE
          ?? (import.meta.env.MODE === "mock" ? MOCK : REAL);

/* ── ③ 인증 ───────────────────────────────────────────────────
   명세에 JWT 가 「이미 있는 것」으로 적혀 있다. 로그인 화면은 아직
   우리 범위 밖이라 토큰을 받을 길이 없지만, **받는 자리는 만들어 둔다.**

   로그인이 생기면 거기서 setToken(t) 한 번 부르면 끝이다.

   ⚠ 토큰을 localStorage 에 두지 않는다. 다른 스크립트가 읽어 갈 수
     있어서다. 새로고침하면 다시 로그인해야 하는데, 업무 화면에서는
     그 편이 맞다 — 자리를 비운 사이 열려 있으면 안 된다. */
let token = null;
export const setToken = (t) => { token = t; };
export const hasToken = () => Boolean(token);

/* ── ② 봉투 ───────────────────────────────────────────────────
   명세에 「응답 봉투」가 공통 기반으로 적혀 있는데 모양은 안 나와 있다.
   흔한 두 가지를 다 받게 해 두었다 — 어느 쪽이든 화면은 안 바뀐다.

       { "data": {...} }   →  {...}
       {...}               →  {...}   (봉투 없음)

   ⚠ 실제 모양이 정해지면 **이 함수 하나만** 고친다. 예를 들어
     { result: {...}, meta: {...} } 라면 o.result 를 돌려주면 된다. */
function unwrap(o) {
  if (o && typeof o === "object" && "data" in o && !Array.isArray(o)) return o.data;
  return o;
}

/* 오류도 봉투에 들어올 수 있다.
       { "error": { "code": "...", "detail": "..." } }
   화면은 e.code · e.detail · e.status 를 본다(lib/Body). 그 셋이
   채워지기만 하면 어느 모양이든 된다. */
function unwrapError(o, status, statusText) {
  const e = (o && typeof o === "object" && o.error) ? o.error : o;
  return Object.assign(new Error(e?.detail || statusText || "요청에 실패했습니다"), {
    status,
    code: e?.code ?? null,
    detail: e?.detail ?? null,
    fields: e?.fields ?? null,      // 칸별 오류가 오면 서식이 받아 쓴다
  });
}

/* ── 부르기 ──────────────────────────────────────────────────── */
async function req(method, path, body) {
  const headers = {};
  if (body) headers["content-type"] = "application/json";
  if (token) headers.authorization = `Bearer ${token}`;

  let r;
  try {
    r = await fetch(BASE + path, {
      method, headers,
      body: body ? JSON.stringify(body) : undefined,
      /* 쿠키 세션을 쓰는 경우를 위해 남겨 둔다. JWT 로 확정되면
         빼도 되지만 있어서 손해는 없다 */
      credentials: "same-origin",
    });
  } catch (e) {
    /* 서버가 안 떠 있거나 망이 끊긴 경우. 여기서 안 잡으면 화면에
       「Failed to fetch」라는 알 수 없는 말이 뜬다 */
    throw Object.assign(new Error("서버에 연결하지 못했습니다"), {
      status: 0, code: "NETWORK", detail: String(e.message ?? e),
    });
  }

  let json = null;
  try { json = await r.json(); } catch { /* 본문이 없을 수 있다 */ }

  if (!r.ok) throw unwrapError(json, r.status, r.statusText);
  return unwrap(json);
}

const get   = (p)    => req("GET", p);
const post  = (p, b) => req("POST", p, b);
const put   = (p, b) => req("PUT", p, b);
const patch = (p, b) => req("PATCH", p, b);

/* 질의 문자열. 빈 값은 빼고 보낸다 — ?q= 처럼 빈 채로 가면 서버가
   「빈 문자열로 검색」으로 읽을 수 있다 */
const qs = (o) => {
  const s = new URLSearchParams(
    Object.entries(o).filter(([, v]) => v != null && v !== "")).toString();
  return s ? `?${s}` : "";
};

/* ── 명세의 에러 코드 ─────────────────────────────────────────
   화면이 분기하는 것만 이름을 붙인다. 나머지는 e.code 를 그대로
   보여주면 된다 — 사람이 그 코드를 들고 문의할 수 있어야 한다. */
export const ERR = {
  ALREADY_ASSIGNED: "ALREADY_ASSIGNED",   // 다른 사람이 먼저 집었다
  NETWORK:          "NETWORK",            // 우리가 붙인 것. 서버가 아니다
};

export const api = {
  /* ── 1 · 검체 접수 대기 (명세 p.21) ─────────────────────────
     선착순 큐. 바인딩이 끝나고 **아무도 안 집은** 것만 온다. */
  queue:      ()   => get(`/specimens${qs({ status: "bound", assigned: "none" })}`),
  specimen:   (id) => get(`/specimens/${id}`),
  /* 집기. 조건부 UPDATE 라 **먼저 도착한 하나만 성공**한다.
     나머지는 409 ALREADY_ASSIGNED */
  assign:     (id) => patch(`/specimens/${id}/assign`),

  /* ── 2 · 조직 이미지 업로드 (p.22) ──────────────────────────
     올리는 것은 WSI 전체가 아니라 **크롭 조직 이미지 여러 장**이다. */
  uploadInfo: (id) => get(`/specimens/${id}/upload`),
  ticket:     (b)  => post(`/tickets`, b),
  analyze:    (id) => post(`/specimens/${id}/ai-results`),
  aiResults:  (id) => get(`/ai-results${qs({ specimen: id })}`),

  /* ── 3 · 판독 (p.23) ────────────────────────────────────────
     AI 는 업로드 화면에서 이미 끝났다. 여기에 「분석 중」은 없다. */
  read:       (id)    => get(`/specimens/${id}/read`),
  draft:      (id, b) => put(`/specimens/${id}/draft`, b),
  finalize:   (id, b) => patch(`/specimens/${id}/finalize`, b),

  /* ── 4 · 전체 환자 목록 (p.24) ──────────────────────────────
     unbound 는 안 온다 — 바인딩 전이라 병리 일이 아니다. */
  list:       (o = {}) => get(`/specimens${qs(o)}`),

  /* ── 5 · 판독 정정 (p.25) ───────────────────────────────────
     옛 값을 specimen.amend_history(JSONB) 에 밀어넣고 본 컬럼을 덮는다.
     **새 행을 만들지 않는다.** */
  amend:      (id, b) => post(`/specimens/${id}/amend`, b),
};

/* 지금 어디를 보고 있는지. 화면 아래에 찍어 두면 「목업을 보고 있는 줄
   몰랐다」가 안 생긴다 */
export const apiInfo = { base: BASE, mock: BASE === MOCK };
