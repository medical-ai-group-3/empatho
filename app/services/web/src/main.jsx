import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import App from "./App.jsx";
import { Head } from "./lib/Screen.jsx";
import { applyTheme, readTheme } from "./lib/theme.js";
import Book from "./screens/Book.jsx";
import Home from "./screens/Home.jsx";
import Report from "./screens/Report.jsx";
import Results from "./screens/Results.jsx";
import "./index.css";

/* 주소를 진짜 경로로 쓴다(# 를 안 쓴다).
 * nginx 가 어떤 경로로 들어와도 index.html 을 주므로(try_files) 새로고침해도
 * 살아난다 — conf/nginx.conf 의 프런트 구역이 그 일을 한다.
 *
 * 그래서 **브라우저 뒤로가기가 곧 앱 뒤로가기**다. 화면마다 돌아갈 곳을
 * 박아 둘 필요가 없다. */
/* 아직 안 만든 화면. 여기도 Head 를 쓴다 — 뒤로가기가 화면마다 다르게
 * 생기지 않게 하려면 머리말을 손으로 그리는 자리가 없어야 한다. */
function Soon({ name }) {
  return (
    <>
      <Head title={name} />
      <div className="pane">
        <p className="note c" style={{ paddingTop: 40 }}>준비 중입니다.</p>
      </div>
    </>
  );
}

/* ── 밝은 판 · 어두운 판 ────────────────────────────────────────
   기본은 **기기 설정을 따른다**. 사람이 골라 둔 것이 있으면 그것이 이긴다.

   React 가 그리기 전에 세워 둔다. 안 그러면 첫 한 프레임이 밝게 떴다가
   어두워져서 눈이 부시다.
   ───────────────────────────────────────────────────────────── */
applyTheme(readTheme());

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/"             element={<Home />} />
          <Route path="/results"      element={<Results />} />
          <Route path="/reports/:id"  element={<Report />} />
          <Route path="/book"         element={<Book />} />
          <Route path="/quest"        element={<Soon name="자가검진 문진" />} />
          <Route path="/chat"         element={<Soon name="안내 챗봇" />} />
          <Route path="/notis"        element={<Soon name="알림" />} />
          <Route path="/me"           element={<Soon name="내 정보" />} />
          <Route path="*"             element={<Soon name="없는 화면" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
