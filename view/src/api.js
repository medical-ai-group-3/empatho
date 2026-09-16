/* 서버를 부르는 층 — 화면은 여기만 쓴다.
 *
 * 규칙 하나: **주소를 코드에 박지 않는다.**
 *   fetch("/api/v1/…")  ○      자기가 열린 주소에서 부른다
 *   fetch("http://…")   ✗      교차 출처가 되고 CORS 목록에 걸린다
 *
 * 아래 함수들이 전부 상대 경로로 시작하는 이유가 그것이다. 개발 중에는
 * Vite 가 서버로 넘겨 주고(vite.config.js), 배포에서는 nginx 가 같은
 * 주소에서 받는다. 어느 쪽이든 화면 코드는 그대로다.
 */

/* ── 오류 ─────────────────────────────────────────────────────────
   서버는 { code, detail } 로 실패를 알려 준다. 화면이 code 로 갈라야
   하므로 Error 에 실어 둔다. status 도 남긴다 — 401 과 403 은 화면이
   다르게 굴어야 한다(다시 로그인 / 권한 없음).
   ───────────────────────────────────────────────────────────────── */
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

export const get  = (p, o)       => call(p, { ...o, method: "GET" });
export const post = (p, body, o) => call(p, { ...o, method: "POST", body });
export const put  = (p, body, o) => call(p, { ...o, method: "PUT", body });

/* ── 판독은 비동기다 ───────────────────────────────────────────────
   사진 한 장에 12~27초, 검사 한 건에 49~108초 걸린다. 워커가 하나라
   요청이 겹치면 줄을 선다. 그래서 즉시 작업번호를 받고 나중에 조회한다.

   run_status 는 queued · running · done · failed 넷이다.
   화면은 이 함수에 onStep 을 주고 «분석 중» 표시를 갱신하면 된다.

   ⚠ 타임아웃을 짧게 두지 말 것. 기본 6분은 검사 한 건 최악(108초)의
     세 배가 넘는데, 앞에 두 건이 밀려 있으면 그것도 모자란다. 화면에는
     «오래 걸립니다» 를 보여주고 기다리는 편이 낫다.
   ───────────────────────────────────────────────────────────────── */
export async function waitForRead(readId, {
  onStep,
  intervalMs = 2000,
  timeoutMs = 6 * 60 * 1000,
  signal,
} = {}) {
  const until = Date.now() + timeoutMs;
  for (;;) {
    const r = await get(`/api/v1/reads/${readId}`, { signal });
    onStep?.(r);

    if (r.run_status === "done") return r;
    if (r.run_status === "failed") {
      throw new ApiError(200, "READ_FAILED", r.fail_reason || "판독이 실패했다");
    }
    if (Date.now() > until) {
      throw new ApiError(200, "READ_TIMEOUT",
        "판독이 예상보다 오래 걸린다. 잠시 뒤 다시 확인해 주세요");
    }
    await sleep(intervalMs, signal);
  }
}

function sleep(ms, signal) {
  return new Promise((ok, fail) => {
    const t = setTimeout(ok, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      fail(new DOMException("취소됨", "AbortError"));
    }, { once: true });
  });
}

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
        const t = await issue({ purpose: "notify" });
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
  login:        (id, pw)   => post("/api/v1/auth/login", { username: id, password: pw }),
  logout:       ()         => post("/api/v1/auth/logout"),
  me:           ()         => get("/api/v1/me"),

  // 02  가입 — 세 걸음이다.
  //
  //   ① sendCode    이름 · 주민등록번호 · 휴대폰을 보내고 인증번호를 받는다
  //   ② verifyCode  받은 번호를 확인하면 verify_token 이 온다
  //   ③ signup      아이디 · 비밀번호를 정해 ②의 표를 들고 가입을 마친다
  //
  // **아이디는 사용자가 정한다.** 병원 기록과 잇는 것은 주민등록번호다 —
  // 병원이 그 고유번호로 이미 있는 환자를 찾아 준다.
  //
  // ⚠ 주민등록번호는 **어디에도 저장하지 않는다.** ①의 본문에 한 번 실려
  //   갈 뿐이고, 화면은 보내자마자 상태에서 지운다. localStorage 나
  //   sessionStorage 에 넣지 말 것. 로그에도 남기지 말 것.
  sendCode:     (payload)  => post("/api/v1/signup/verify-phone", payload),
  verifyCode:   (payload)  => post("/api/v1/signup/verify-code", payload),
  checkId:      (v)        => get(`/api/v1/signup/check-id?value=${encodeURIComponent(v)}`),
  signup:       (payload)  => post("/api/v1/signup/link", payload),

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
  //       { date, time, questionnaire: { pregnancy: "no", … } }
  reservations:  ()        => get("/api/v1/me/reservations"),
  requestVisit:  (body)    => post("/api/v1/me/reservation-requests", body),
  cancelVisit:   (id)      => post(`/api/v1/me/reservations/${id}/cancel`),

  // 06 · 07  결과 · 안내문
  //     내원 한 번에 리포트 하나다. 서버가 report_type='final' ·
  //     audience='patient' 만 준다 — **앱은 묶는 일을 하지 않는다.**
  //     lock_status 가 'locked' 면 본문이 오지 않는다(대면 설명 전).
  results:      ()         => get("/api/v1/reports"),
  report:       (id)       => get(`/api/v1/reports/${id}`),

  // 08  챗봇 — 개인 결과를 인용하지 않는 안내용이다
  chat:         (q)        => post("/api/v1/chat", { question: q }),

  // 09  알림
  notifications: ()        => get("/api/v1/notifications"),
  markRead:      (id)      => post(`/api/v1/notifications/${id}/read`),

  // 10  내 정보
  consents:      ()        => get("/api/v1/consents"),
  //     필수 동의는 철회할 수 없다. 서버가 can_withdraw 로 알려 주고,
  //     화면은 그때만 철회 자리를 낸다 — 눌러도 안 되는 것을 흐리게
  //     두면 「왜 안 되지」를 만든다.
  withdrawConsent: (kind)  => post(`/api/v1/consents/${kind}/withdraw`),
  setPush:       (kind, on) => put(`/api/v1/notifications/settings/${kind}`, { enabled: on }),
};
