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
const OPEN = new Set([`${PREFIX}/auth/login`, `${PREFIX}/auth/logout`]);

const send = (res, obj, code = 200) => {
  res.statusCode = code;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
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
        if (!req.url.startsWith(PREFIX)) return next();

        const path = req.url.split("?")[0];

        /* 로그인 상태 — 직원용 쿠키 하나. 환자 앱과 겹치지 않는다 */
        const signedIn =
          new RegExp(`(?:^|;\\s*)${COOKIE}=1`).test(req.headers.cookie || "");
        if (path === `${PREFIX}/auth/login`) {
          res.setHeader("Set-Cookie",
            `${COOKIE}=1; Path=/; SameSite=Lax; Max-Age=43200`);
        } else if (path === `${PREFIX}/auth/logout`) {
          res.setHeader("Set-Cookie", `${COOKIE}=; Path=/; SameSite=Lax; Max-Age=0`);
        } else if (!OPEN_ALL && !signedIn && !OPEN.has(path)) {
          return send(res, { code: "NOT_AUTHENTICATED", detail: "로그인이 필요합니다" }, 401);
        }

        /* 요청마다 새로 읽는다 — 고치고 새로고침만 하면 반영된다 */
        let db;
        try {
          db = JSON.parse(readFileSync(resolve(here, "hospital.json"), "utf-8"));
        } catch (e) {
          return send(res, { code: "MOCK_BROKEN", detail: String(e) }, 500);
        }

        const hit = pick(db, req.method, req.url);
        if (hit === undefined) {
          return send(res, {
            code: "NOT_IN_MOCK",
            detail: `mock/hospital.json 에 "${req.method} ${path}" 가 없다`,
          }, 404);
        }

        // 사람이 기다리는 느낌. 즉답이면 「불러오는 중」을 못 본다
        setTimeout(() => send(res, hit), 160);
      });
    },
  };
}
