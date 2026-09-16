import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

// 붙을 서버. 자리를 옮기면 이것만 바꾼다 — 코드에는 주소가 없다.
const SERVER = process.env.EMPATHO_SERVER || "http://app-host";

/* 가짜 API — mock/db.json 을 매 요청 새로 읽어 그대로 돌려준다.
 * empatho-view/vite.config.js 의 mockApi() 와 같은 규칙:
 *   · 쿼리스트링은 무시한다(path만 본다)
 *   · id가 붙는 자원은 리터럴 풀패스 키로 등록한다("GET /api/v1/patients/P-1001")
 * 의료진 워크스테이션이라 로그인 게이팅은 두지 않는다. */
function mockApi() {
  return {
    name: "staff-mock-api",
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

        if (hit === undefined) {
          res.statusCode = 404;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify({
            code: "NOT_IN_MOCK",
            detail: `mock/db.json 에 "${req.method} ${path}" 가 없다`,
          }));
          return;
        }

        setTimeout(() => {
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(JSON.stringify(hit));
        }, 120);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const MOCK = mode === "mock";
  return {
    plugins: [react(), ...(MOCK ? [mockApi()] : [])],

    build: {
      outDir: "dist",
      emptyOutDir: true,
    },

    server: {
      host: true,
      port: 5174,
      proxy: MOCK ? {} : {
        "/api": { target: SERVER, changeOrigin: true },
      },
    },

    // cornerstone3D의 dicom-image-loader가 웹워커(decodeImageFrameWorker.js,
    // ESM 모듈 워커)로 픽셀 디코딩을 한다 — 워커 산출물도 ESM이어야 한다.
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
