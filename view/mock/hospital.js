import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/* ── 병원 웹 가짜 API ──────────────────────────────────────────────
   /api/v1/hospital/** 만 맡는다. 환자 앱 쪽(mock/db.json)은 안 건드린다.

   ── 왜 파일과 플러그인을 나눴나 ────────────────────────────────
   ① **로그인이 갈린다.** 환자와 직원은 다른 계정이고 권한 판정이 다른
      계층이다. 목업도 쿠키를 따로 쓴다 — 안 그러면 병원 웹에서
      로그인했다고 환자 앱까지 로그인된 것으로 보인다.
   ② **규격이 갈린다.** 이 파일의 응답이 곧 Django 와의 계약인데,
      두 앱이 한 파일을 나눠 쓰면 어느 줄이 누구 것인지 흐려진다.

   ⚠ vite.config.js 의 plugins 에서 **환자 앱 목업보다 앞에** 두어야
     한다. 그쪽이 /api/ 전체를 가져가므로, 뒤에 두면 여기까지 안 온다.

   ── {id} 자리 맞추기 ──────────────────────────────────────────
   mock/hospital.json 의 열쇠에 {id} 를 쓰면 그 자리에 아무 값이나 와도
   맞는다. 덕분에 환자를 아무나 눌러도 화면이 돈다.

   ⚠ 다만 **돌아오는 자료는 늘 같다.** 목업이라 그렇다 — 윤서현을 눌러도
     이정민의 검체가 온다. 화면 구조를 보기 위한 것이고, 진짜 서버가
     붙으면 그 자리에 제 자료가 온다.
   ────────────────────────────────────────────────────────────── */
const PREFIX = "/api/v1/hospital";
const COOKIE = "empatho_mock_staff";     // 환자 앱은 empatho_mock_session

/* 로그인 없이 부를 수 있는 곳. 나머지는 401 이다 —
   Django 가 실제로 하는 일을 흉내 내야 붙이는 날 처음 깨지지 않는다.
   ⚠ 지금은 로그인 화면이 없어서 전부 열어 둔다. 화면이 생기면
     OPEN 을 좁히고 아래 401 분기를 켠다. */
const OPEN_ALL = true;
/* ⚠ /auth 접두를 뗐다. 다희님 경로표(9/16)의 로그인이 POST /api/v1/login
   이라 /auth 를 쓰면 로그아웃만 혼자 튄다 */
const OPEN = new Set([`${PREFIX}/login`, `${PREFIX}/logout`]);

/* ── 응답 봉투 ──────────────────────────────────────────────────
   실제 서버와 같은 모양으로 싸서 보낸다. 안 싸면 붙이는 날 화면이
   전부 한 겹씩 어긋난다.

     성공  { success:true,  data:…,   error:null, trace_id:"…" }
     실패  { success:false, data:null, error:{code,message,details}, trace_id:"…" }

   trace_id 는 헤더 X-Trace-Id 에도 실어 보낸다 — 화면이 헤더에서
   줍는 길도 같이 시험해 보려고. */
const traceId = () =>
  "mock-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

const send = (res, data, code = 200) => {
  const tid = traceId();
  res.statusCode = code;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.setHeader("X-Trace-Id", tid);
  res.end(JSON.stringify({ success: true, data, error: null, trace_id: tid }));
};

const fail = (res, code, message, status = 400, details = null) => {
  const tid = traceId();
  res.statusCode = status;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.setHeader("X-Trace-Id", tid);
  res.end(JSON.stringify({
    success: false, data: null,
    error: { code, message, details },
    trace_id: tid,
  }));
};

/* 열쇠와 실제 주소를 맞춰 본다.

   ⚠ **물음표 뒤도 본다.** 접수 대기 큐와 전체 목록이 경로는 같고 질의만
     다르다(?status=bound&assigned=none). 경로만 보면 둘이 한 곳이 된다.

   규칙
     · 경로 조각의 {id} 는 아무 값이나 맞는다
     · 열쇠에 질의가 있으면 **그 값들이 전부 들어 있어야** 맞는다
     · 열쇠에 질의가 없으면 질의는 안 본다 — 정렬·검색 같은 것이
       붙어도 같은 곳으로 간다
   ────────────────────────────────────────────────────────────── */
const isVar = (seg) => seg.startsWith("{") && seg.endsWith("}");

function matchPath(pattern, path) {
  const a = pattern.split("/");
  const b = path.split("/");
  return a.length === b.length && a.every((seg, i) => isVar(seg) || seg === b[i]);
}

function matchQuery(pattern, query) {
  if (!pattern) return true;                       // 열쇠에 질의가 없다
  const want = new URLSearchParams(pattern);
  const got  = new URLSearchParams(query || "");
  for (const [k, v] of want) {
    const g = got.get(k);
    if (g === null) return false;
    if (!isVar(v) && g !== v) return false;
  }
  return true;
}

function pick(db, method, url) {
  const exact = db[`${method} ${url}`];
  if (exact !== undefined) return exact;

  const [path, query] = url.split("?");
  let loose;                                       // 질의 없는 열쇠는 뒤로 미룬다
  for (const key of Object.keys(db)) {
    const sp = key.indexOf(" ");
    if (sp < 0 || key.slice(0, sp) !== method) continue;
    const [kp, kq] = key.slice(sp + 1).split("?");
    if (!matchPath(kp, path)) continue;
    if (!matchQuery(kq, query)) continue;
    /* 질의까지 맞는 열쇠가 이긴다. 큐(?status=bound)와 전체 목록이
       같은 경로라, 질의 있는 쪽을 먼저 집어야 한다 */
    if (kq) return db[key];
    if (loose === undefined) loose = db[key];
  }
  return loose;
}

/* 요청 본문을 JSON 으로 읽는다. 깨진 본문은 빈 객체로 둔다 —
   목업이 본문 파싱에서 500 을 내면 화면 쪽 문제와 구분이 안 된다. */
function readBody(req, done) {
  let raw = "";
  /* ⚠ **인코딩을 먼저 정한다.** 안 정하면 조각이 Buffer 로 와서 조각마다
     따로 문자열이 된다. 한글은 세 바이트라 조각 경계에 걸리면 그 글자가
     깨진다 — 「김서연」이 「김<0xEC>…」가 된다. setEncoding 을 주면 Node 가
     경계에 걸친 바이트를 다음 조각까지 들고 간다. */
  req.setEncoding("utf8");
  req.on("data", (c) => { raw += c; });
  req.on("end", () => {
    let body = {};
    try { body = JSON.parse(raw || "{}"); } catch { /* 빈 객체로 둔다 */ }
    done(body);
  });
}

/* 내 기계에서만 쓰는 계정. **git 에 없다** (.gitignore 의 *.local.json).
 *
 * hospital.json 의 __accounts 위에 덮어쓴다 — 같은 열쇠면 이쪽이 이긴다.
 * 여섯 과를 전부 여는 계정처럼 팀 저장소에 들어가면 안 되는 것을 여기 둔다.
 *
 * ⚠ **없는 것이 정상이다.** 다른 사람 기계에는 이 파일이 없으므로, 못 읽으면
 *   조용히 빈 객체로 넘어간다. 여기서 500 을 내면 그 사람은 목업이 고장 난
 *   줄 안다.
 */
function localAccounts() {
  try {
    return JSON.parse(readFileSync(resolve(here, "accounts.local.json"), "utf-8"));
  } catch {
    return {};
  }
}

/* 목업 토큰에서 아이디를 되꺼낸다. 진짜 서버는 JWT 를 푼다 */
function bearerId(req) {
  const h = req.headers.authorization || "";
  if (!h.startsWith("Bearer ")) return "";
  const t = h.slice(7).trim();
  return t.startsWith("mock.") ? t.slice(5) : "";
}

/* 아이디 앞머리로 과를 고른다. 긴 이름이 먼저다 —
   "reception" 을 "rec" 로 먼저 걸러 버리면 안 된다 */
const ROLE_HINT = [
  ["reception", "reception"], ["radiology", "radiology"],
  ["pathology", "pathology"], ["nursing", "nursing"],
  ["surgery", "surgery"], ["admin", "admin"],
  ["rec", "reception"], ["rad", "radiology"], ["path", "pathology"],
  ["nur", "nursing"], ["sur", "surgery"],
  // all1 → accounts.local.json 의 「전체보기」. 그 파일이 없으면 못 찾고
  // 고정 응답으로 떨어진다 — 다른 사람 기계에서는 그게 맞다
  ["all", "all"],
];
function roleOf(id) {
  const low = String(id).toLowerCase();
  for (const [prefix, role] of ROLE_HINT) {
    if (low.startsWith(prefix)) return role;
  }
  return "";
}

/* 이미 확정한 신청. **두 번 확정하면 409** 를 내려고 들고 있는다 —
   실제 서버도 order_status 가 requested 가 아니면 ALREADY_CONFIRMED 다.
   ⚠ 메모리라 vite 를 다시 띄우면 비워진다. 목업이라 그래도 된다 */
const confirmed = new Set();

export function hospitalRoutes() {
  return {
    name: "empatho-hospital-routes",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const path = (req.url || "").split("?")[0];
        if (path === "/hospital" || path.startsWith("/hospital/")) {
          const last = path.slice(path.lastIndexOf("/") + 1);
          if (!last.includes(".")) req.url = "/hospital.html";
        }
        next();
      });
    },
  };
}

export default function hospitalMock() {
  return {
    name: "empatho-hospital-mock",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        /* ⚠ 접두사 뒤에 **슬래시가 와야** 우리 것이다.
           startsWith(PREFIX) 만 보면 `/api/v1/hospitals`(환자 앱의 병원
           찾기)까지 가로챈다 — 글자만 보면 접두사로 시작하는 것이 맞아서
           환자 앱 요청이 여기로 빨려 들어와 NOT_IN_MOCK 이 났다.
           경계를 글자가 아니라 **경로 마디**로 본다 */
        if (req.url !== PREFIX && !req.url.startsWith(`${PREFIX}/`)) return next();

        const path = req.url.split("?")[0];

        /* 로그인 상태 — 직원용 쿠키 하나. 환자 앱과 겹치지 않는다 */
        const signedIn =
          new RegExp(`(?:^|;\\s*)${COOKIE}=1`).test(req.headers.cookie || "");
        if (path === `${PREFIX}/login`) {
          res.setHeader("Set-Cookie",
            `${COOKIE}=1; Path=/; SameSite=Lax; Max-Age=43200`);
        } else if (path === `${PREFIX}/logout`) {
          res.setHeader("Set-Cookie", `${COOKIE}=; Path=/; SameSite=Lax; Max-Age=0`);
        } else if (!OPEN_ALL && !signedIn && !OPEN.has(path)) {
          return fail(res, "UNAUTHENTICATED", "로그인이 필요합니다", 401);
        }

        /* 요청마다 새로 읽는다 — 고치고 새로고침만 하면 반영된다 */
        let db;
        try {
          db = JSON.parse(readFileSync(resolve(here, "hospital.json"), "utf-8"));
        } catch (e) {
          return fail(res, "MOCK_BROKEN", String(e), 500);
        }
        db.__accounts = { ...db.__accounts, ...localAccounts() };

        /* ── 로그인 · 나 ──────────────────────────────────────────
           **아이디에 따라 과가 갈린다.** 고정 응답 하나만 두면 어느 아이디로
           들어와도 같은 사람이라, 원무·간호 화면을 열어 볼 수가 없다.

           진짜 서버는 JWT 를 준다. 목업은 그 흉내만 낸다 — 아이디를 토큰에
           담아 두고 /me 에서 되꺼내 그 과의 사람을 돌려준다.

             rec1 · reception…   → 원무과      nur1 · nursing…   → 간호과
             path1 · pathology…  → 병리과      rad1 · radiology… → 영상의학과
             sur1 · surgery…     → 유방외과    admin1            → 관리자

           못 알아보는 아이디는 hospital.json 의 GET …/me 를 그대로 준다. */
        if (path === `${PREFIX}/login` && req.method === "POST") {
          return readBody(req, (body) => {
            const id = String(body.login_id || "").trim();
            if (!id || !body.password) {
              return fail(res, "UNAUTHENTICATED",
                "아이디 또는 비밀번호가 올바르지 않습니다.", 401);
            }
            /* 승인 대기 계정을 볼 수 있게 남긴 자리 — 0012 의 account_status
               가 pending 이면 is_active 가 False 라 로그인이 막힌다 */
            if (id.startsWith("pending")) {
              return fail(res, "UNAUTHENTICATED",
                "승인 대기 중인 계정입니다. 관리자 승인 후 이용할 수 있습니다.", 401);
            }
            /* HTTP Authorization 헤더는 ISO-8859-1 범위만 받는다. 목업
               아이디에 한글 이름을 넣어도 그대로 토큰으로 쓰면 다음 /me
               요청 자체가 브라우저에서 막힌다. 실제 JWT도 ASCII이므로,
               목업은 로그인 아이디 대신 영문 역할값으로 고정한다. */
            send(res, { access: `mock.${roleOf(id) || "staff"}` });
          });
        }

        if (path === `${PREFIX}/me` && req.method === "GET") {
          const who = db.__accounts?.[roleOf(bearerId(req))];
          if (who) return send(res, who);
          /* 목록에 없으면 기존 고정 응답으로 떨어진다 */
        }

        /* ── 환자 등록 ────────────────────────────────────────────
           **보낸 것을 돌려준다.** 고정 응답을 주면 홍길동을 등록해도 화면에
           「새환자」가 채워져서 등록 → 칸 채움 → 접수 흐름을 볼 수가 없다.

           환자번호는 서버가 발급한다 — 진짜 서버는 "P" + uuid4 앞 열 자리다
           (PatientRegisterSerializer). 모양만 맞춰 흉내 낸다.

           ⚠ 중복 판정은 여기서 안 한다. 진짜 서버도 새로 만든 것과 있던 것을
             **똑같이 201 로** 주고 구분할 칸이 없어서, 화면이 등록 전에
             GET /patients?q= 로 먼저 본다 (screens/reception/Register.jsx). */
        if (path === `${PREFIX}/patients/register` && req.method === "POST") {
          return readBody(req, (body) => {
            const base = db[`POST ${PREFIX}/patients/register`] ?? {};
            const id = 900 + Math.floor(Math.random() * 90);
            const no = (Date.now().toString(36) + Math.random().toString(36).slice(2))
              .slice(0, 10).toUpperCase();
            send(res, {
              ...base,
              patient_id: id,
              patient_number: `P${no}`,
              pii: {
                patient_id: id,
                name: body.name ?? null,
                birth_date: body.birth_date ?? null,
                phone: body.phone ?? null,
              },
            });
          });
        }

        /* ── 예약 확정 (4장) ────────────────────────────────────
           **날짜만 받는다.** 원무가 날짜만 확정하는 자리라 modality ·
           exam_purpose · ordered_by 는 안 온다 — 그건 유방외과가 정한다.

           확정하면 order_status 는 **scheduled** 다. ordered 가 아니다 —
           검사 종류가 정해져야 ordered 이고 그건 유방외과 몫이다.

           ⚠ 진짜 서버(ExamOrderConfirmView)는 아직 그 셋을 필수로 받는다.
             scheduled_at 만 받도록 바뀔 예정이고, 여기는 바뀐 뒤의 모양이다. */
        const wantConfirm = path.match(
          new RegExp(`^${PREFIX}/exam-orders/([^/]+)/confirm$`));
        if (wantConfirm && req.method === "PATCH") {
          const id = wantConfirm[1];
          if (confirmed.has(id)) {
            return fail(res, "ALREADY_CONFIRMED", "이미 확정된 예약입니다.", 409);
          }
          return readBody(req, (body) => {
            confirmed.add(id);
            send(res, {
              exam_order_id: Number(id),
              order_status: "scheduled",
              scheduled_at: body.scheduled_at ?? null,
              modality: null,
              exam_purpose: null,
              ordered_by: null,
            });
          });
        }

        const hit = pick(db, req.method, req.url);
        if (hit === undefined) {
          return fail(res, "NOT_IN_MOCK",
            `mock/hospital.json 에 "${req.method} ${path}" 가 없다`, 404);
        }

        // 사람이 기다리는 느낌. 즉답이면 「불러오는 중」을 못 본다
        setTimeout(() => send(res, hit), 160);
      });
    },
  };
}
