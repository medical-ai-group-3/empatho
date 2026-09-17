import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import hospitalMock, { hospitalRoutes } from "./mock/hospital.js";

const here = dirname(fileURLToPath(import.meta.url));

// 붙을 서버. 자리를 옮기면 이것만 바꾼다 — 코드에는 주소가 없다.
const SERVER = process.env.EMPATHO_SERVER || "http://app-host";

// 목업 모드에서 /admin 을 넘길 곳. Django admin 은 목업으로 흉내 낼 수 없어서
// (진짜 화면이고 세션 쿠키로 돈다) 로컬 Django 를 본다.
//   cd services/django && python manage.py runserver 8000
const DJANGO = process.env.EMPATHO_DJANGO || "http://127.0.0.1:8000";

// 가짜 API 로 돌릴지는 아래 defineConfig 의 mode 로 가른다.
//   npm run dev        서버에 붙는다
//   npm run dev:mock   가짜 API 로 혼자 돈다  (vite --mode mock)
//
// 환경변수(EMPATHO_MOCK=1 vite)로 하지 않는 이유 — 그건 리눅스·맥 셸 문법이라
// **윈도우에서 안 돈다.** npm 이 cmd 로 스크립트를 돌리는데 cmd 는 앞부분을
// 명령어로 읽는다. --mode 는 vite 가 직접 받으므로 어느 OS 에서나 같다.

/* ── 가짜 API ──────────────────────────────────────────────────────
   Django 가 아직 없다. mock/db.json 을 그대로 돌려준다.

   **이 응답이 곧 계약이다.** 화면이 이 모양으로 만들어지므로, Django 가
   생길 때 여기 적힌 모양과 같아야 한다. 그래서 파일을 매 요청 새로 읽는다 —
   고치면 새로고침만으로 반영되고, 규격을 다듬는 자리가 한 곳이 된다.

   개발에서만 붙는다. 빌드 결과에는 한 줄도 안 들어간다.
   ────────────────────────────────────────────────────────────────── */
/* 요청 본문을 모아 JSON 으로 읽는다. 챗봇처럼 **보낸 내용에 따라 답이
   달라지는** 곳에서만 쓴다. 깨진 본문은 빈 객체로 넘긴다 — 가짜 API 가
   본문 때문에 500 을 내면 화면 쪽 문제와 구분이 안 된다. */
function readBody(req, done) {
  let raw = "";
  req.on("data", (c) => { raw += c; });
  req.on("end", () => {
    let body = {};
    try { body = JSON.parse(raw || "{}"); } catch { /* 빈 객체로 둔다 */ }
    done(body);
  });
}

/* 응답 한 벌. 헤더를 빠뜨리면 한글이 깨져서 «서버가 이상하다»로 읽힌다 */
function send(res, obj) {
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}

function mockApi() {
  /* 로그인 상태를 기억한다.
     Django 는 세션 쿠키로 판정하고, 로그인 전에는 **401 을 준다.** 가짜 API 가
     늘 200 을 주면 로그인 화면이 화면에서만 존재하고 실제로는 아무도 안 거친다 —
     그러면 붙이는 날 처음으로 깨진다.

     ⚠ 전에는 이걸 `let signedIn = false` 한 개로 뒀다. 그러면 **서버에 상태가
       하나뿐이라 모든 기기가 그걸 나눠 쓴다.** PC 에서 로그인하면 폰도 로그인된
       것으로 보여서 로그인 화면이 아예 안 떴다.

       그래서 쿠키로 옮겼다. 브라우저마다 따로 기억하고, 그 편이 Django 가
       실제로 하는 일과도 같다. */
  /* 열쇠에 {id} 를 쓰면 그 자리에 아무 값이나 와도 맞는다.
     병원 웹 목업(mock/hospital.js)이 진작 하던 것을 이쪽에도 들였다 —
     복약 기록처럼 **번호가 붙는 주소**가 생기면서 필요해졌다.
     그 셋을 db.json 에 하나하나 적어 두는 것은 자료가 아니라 잡일이다.

     ⚠ 정확히 맞는 열쇠를 **먼저** 본다. 여기는 못 찾았을 때만 온다 —
       안 그러면 구체적인 열쇠를 {id} 짜리가 가로챈다 */
  function wildcard(db, method, path) {
    const parts = path.split("/");
    for (const key of Object.keys(db)) {
      const sp = key.indexOf(" ");
      if (sp < 0) continue;
      if (key.slice(0, sp) !== method) continue;
      const kp = key.slice(sp + 1).split("/");
      if (kp.length !== parts.length) continue;
      if (kp.every((k, i) => k === parts[i] || /^\{.+\}$/.test(k))) return db[key];
    }
    return undefined;
  }

  const SEEN = "empatho_mock_session";
  const isIn = (req) =>
    new RegExp(`(?:^|;\\s*)${SEEN}=1`).test(req.headers.cookie || "");
  const setIn = (res, on) =>
    res.setHeader("Set-Cookie", on
      ? `${SEEN}=1; Path=/; SameSite=Lax; Max-Age=86400`
      : `${SEEN}=; Path=/; SameSite=Lax; Max-Age=0`);

  // 로그인 전에도 부를 수 있는 곳. 나머지는 전부 401 이다.
  const OPEN = new Set([
    "/api/v1/login",
    "/api/v1/logout",
    "/api/v1/signup/verify-phone",
    "/api/v1/signup/link",
  ]);

  return {
    name: "empatho-mock-api",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url.startsWith("/api/")) return next();

        const p0 = req.url.split("?")[0];
        if (p0 === "/api/v1/login" || p0 === "/api/v1/signup/link") {
          setIn(res, true);
        } else if (p0 === "/api/v1/logout") {
          setIn(res, false);
        } else if (!isIn(req) && !OPEN.has(p0)) {
          res.statusCode = 401;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify({
            code: "NOT_AUTHENTICATED",
            detail: "로그인이 필요합니다",
          }));
          return;
        }

        let db;
        try {
          db = JSON.parse(
            readFileSync(resolve(here, "mock/db.json"), "utf-8"));
        } catch (e) {
          res.statusCode = 500;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ code: "MOCK_BROKEN", detail: String(e) }));
          return;
        }

        const path = req.url.split("?")[0];
        const hit = db[`${req.method} ${path}`] ?? db[path]
                 ?? wildcard(db, req.method, path);

        // 판독 폴링을 흉내 낸다 — 부를 때마다 한 칸씩 나아간다.
        // 「분석 중」 화면을 진짜로 시험해 볼 수 있어야 한다.
        if (path.startsWith("/api/v1/reads/") && hit && hit.__progress) {
          const seq = hit.__progress;
          mockApi.tick = (mockApi.tick || 0) + 1;
          const step = seq[Math.min(mockApi.tick - 1, seq.length - 1)];
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify(step));
          return;
        }

        if (hit === undefined) {
          res.statusCode = 404;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify({
            code: "NOT_IN_MOCK",
            detail: `mock/db.json 에 "${req.method} ${path}" 가 없다`,
          }));
          return;
        }

        /* 챗봇 — **물음에 따라 답이 갈린다.**
           하나뿐인 답을 늘 돌려주면 무엇을 물어도 같은 말이 나와서,
           화면이 제대로 도는지 시험할 수가 없다.

           db.json 의 __match 를 위에서부터 훑어 when 의 낱말이 물음에
           하나라도 들어 있으면 그 답을 준다. 아무것도 안 걸리면 기본
           answer 다.

           ⚠ 이 규칙은 **가짜 API 안에만 있다.** Django 는 몰라도 되고,
             응답 모양(answer · disclaimer · stored)만 같으면 된다. */
        if (path === "/api/v1/chat" && hit && hit.__match) {
          readBody(req, (body) => {
            const q = String(body.question || "");
            const m = hit.__match.find((x) => x.when.some((w) => q.includes(w)));
            send(res, {
              answer: (m || hit).answer,
              disclaimer: hit.disclaimer,
              stored: hit.stored,
            });
          });
          return;
        }

        // 사람이 기다리는 느낌. 즉답이면 «분석 중»을 못 본다.
        setTimeout(() => send(res, hit), 180);
      });
    },
  };
}

/* ── 없어진 것: keepDir() ──────────────────────────────────────────
   전에는 빌드 뒤 ../../web-dist/.gitkeep 을 되돌려 놓는 조각이 있었다.
   emptyOutDir 가 그 폴더를 비우면서 .gitkeep 까지 지웠고, 그게 git 에서
   사라지면 새 체크아웃에 폴더가 없어서 docker compose 가 root 소유 빈
   폴더를 만들어 버렸다.

   이 저장소에서는 **그 일이 일어나지 않는다.** emptyOutDir 가 비우는
   것은 이제 이 저장소 안의 dist/ 뿐이고, 그건 어차피 git 이 안 본다
   (.gitignore). web-dist/ 는 empatho-app 쪽 저장소가 계속 들고 있으면
   되고, 배포는 거기에 **덮어쓰기만** 한다.
   ────────────────────────────────────────────────────────────────── */

export default defineConfig(({ mode }) => {
  const MOCK = mode === "mock";
  return {
    plugins: [react(), hospitalRoutes(), ...(MOCK ? [hospitalMock(), mockApi()] : [])],

  /* 빌드 결과는 **이 저장소 안**에 낸다.
     전에는 resolve(here, "../../web-dist") 였다. empatho-app 안에 있을
     때는 nginx 가 서빙하는 자리를 바로 가리켜서 편했는데, 이 저장소가
     홀로 서면서 그 경로가 **저장소 바깥**을 가리키게 됐다. 어디에
     클론하느냐에 따라 엉뚱한 폴더에 쏟아진다.

     ⚠ 그래서 배포 절차에 한 줄이 붙는다 — 빌드한 dist/ 를 nginx 가
       보는 web-dist/ 로 옮겨야 한다(README 참고). */
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main:    resolve(here, "index.html"),
        hospital: resolve(here, "hospital.html"),
      },
    },
  },

  server: {
    host: true,        // 휴대폰에서 열어 보려면 필요하다
    port: 5173,
    // 개발 중에도 **상대 경로**로 부르게 한다. 코드에 주소를 박으면
    // 배포에서 교차 출처가 되고, 그때 CORS 목록에 없는 기기는 막힌다.
    //
    // /admin 과 /static 은 **두 모드 모두** 넘긴다.
    //
    //   Django admin 은 우리가 짓는 화면이 아니라 Django 가 주는 화면이다.
    //   여기에 안 적으면 vite 의 SPA 폴백이 걸려서 **환자 앱 index.html 이
    //   돌아온다** — 새 탭에 환자 앱이 뜨고, 404 도 아니라 200 이라 뭐가
    //   잘못됐는지도 안 보인다.
    //
    //   /static 도 같이 넘긴다. admin 화면의 CSS 가 거기 있어서, 빠뜨리면
    //   글자만 있는 admin 이 나온다 (conf/nginx/default.conf 도 같은 이유로
    //   두 자리를 함께 넘긴다).
    //
    //   목업 모드에서는 붙을 서버가 없으므로 **로컬 Django** 를 본다.
    //   띄워 두지 않았으면 연결 오류가 나는데, 그게 맞다 — 환자 앱이
    //   대신 뜨는 것보다 무엇이 없는지가 분명하다.
    //     python manage.py runserver 8000
    proxy: {
      ...(MOCK ? {} : {
        "/api": { target: SERVER, changeOrigin: true },
        "/svc": { target: SERVER, changeOrigin: true },
      }),
      "/admin":  { target: MOCK ? DJANGO : SERVER, changeOrigin: true },
      "/static": { target: MOCK ? DJANGO : SERVER, changeOrigin: true },
    },
  },

  // cornerstone3D의 dicom-image-loader가 웹워커(decodeImageFrameWorker.js,
  // ESM 모듈 워커)로 픽셀 디코딩을 한다 — 워커 산출물도 ESM이어야 한다.
  // (유방외과 MRI DICOM 뷰어가 쓴다 — staff-view/vite.config.js 에서 옮겨 옴)
  worker: { format: "es" },
  // 코덱 wasm 로더(emscripten UMD 산출물)는 메인 엔트리에서는 안 보이고
  // 워커 안에서만 import된다 — 자동 탐지가 안 되니 직접 올려서 미리
  // 번들링(CJS→ESM interop 포함)하게 만든다. 안 하면 워커 안에서
  // "does not provide an export named 'default'"로 조용히 죽는다.
  optimizeDeps: {
    include: [
      "@cornerstonejs/codec-libjpeg-turbo-8bit/decodewasmjs",
      "@cornerstonejs/codec-charls/decodewasmjs",
      "@cornerstonejs/codec-openjpeg/decodewasmjs",
      "@cornerstonejs/codec-openjph/wasmjs",
    ],
  },
  };
});
