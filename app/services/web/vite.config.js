import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

// 붙을 서버. 자리를 옮기면 이것만 바꾼다 — 코드에는 주소가 없다.
const SERVER = process.env.EMPATHO_SERVER || "http://app-host";

// 가짜 API 로 돌릴지. Django 에 /api/ 가 생기기 전까지 이걸 쓴다.
//   npm run dev        서버에 붙는다
//   npm run dev:mock   가짜 API 로 혼자 돈다
const MOCK = process.env.EMPATHO_MOCK === "1";

/* ── 가짜 API ──────────────────────────────────────────────────────
   Django 가 아직 없다. mock/db.json 을 그대로 돌려준다.

   **이 응답이 곧 계약이다.** 화면이 이 모양으로 만들어지므로, Django 가
   생길 때 여기 적힌 모양과 같아야 한다. 그래서 파일을 매 요청 새로 읽는다 —
   고치면 새로고침만으로 반영되고, 규격을 다듬는 자리가 한 곳이 된다.

   개발에서만 붙는다. 빌드 결과에는 한 줄도 안 들어간다.
   ────────────────────────────────────────────────────────────────── */
function mockApi() {
  return {
    name: "empatho-mock-api",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url.startsWith("/api/")) return next();

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
        const hit = db[`${req.method} ${path}`] ?? db[path];

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

        // 사람이 기다리는 느낌. 즉답이면 «분석 중»을 못 본다.
        setTimeout(() => {
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify(hit));
        }, 180);
      });
    },
  };
}

/* ── 빌드 뒤 .gitkeep 을 되돌려 놓는다 ──────────────────────────────
   emptyOutDir 가 web-dist/ 를 비우면서 .gitkeep 까지 지운다. 그게 git 에서
   사라지면 새로 받은 체크아웃에 그 폴더가 없고, 그 상태로 docker compose 가
   먼저 뜨면 **Docker 가 root 소유 빈 폴더를 만든다.** 다음 배포의
   npm run build 가 거기에 못 쓴다.

   폴더 하나 때문에 배포가 멎는 것이라 여기서 한 줄로 막는다.
   ────────────────────────────────────────────────────────────────── */
function keepDir() {
  return {
    name: "empatho-keep-outdir",
    apply: "build",
    closeBundle() {
      writeFileSync(resolve(here, "../../web-dist/.gitkeep"), "");
    },
  };
}

export default defineConfig({
  plugins: [react(), keepDir(), ...(MOCK ? [mockApi()] : [])],

  // nginx 가 web-dist/ 를 서빙한다(compose.proxy.yml). 거기로 바로 내보낸다.
  build: {
    outDir: resolve(here, "../../web-dist"),
    emptyOutDir: true,
  },

  server: {
    host: true,        // 휴대폰에서 열어 보려면 필요하다
    port: 5173,
    // 개발 중에도 **상대 경로**로 부르게 한다. 코드에 주소를 박으면
    // 배포에서 교차 출처가 되고, 그때 CORS 목록에 없는 기기는 막힌다.
    proxy: MOCK ? {} : {
      "/api": { target: SERVER, changeOrigin: true },
      "/svc": { target: SERVER, changeOrigin: true },
    },
  },
});
