import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import App, { Bare } from "./App.jsx";
import Boom from "./lib/Boom.jsx";
import RequireAuth from "./lib/RequireAuth.jsx";
import { Head } from "./lib/Screen.jsx";
import Icon from "./lib/Icon.jsx";
import { applyScale, applyTheme, readScale, readTheme } from "./lib/theme.js";
import Book from "./screens/Book.jsx";
import Chat from "./screens/Chat.jsx";
import Drugs from "./screens/Drugs.jsx";
import Home from "./screens/Home.jsx";
import Hospitals from "./screens/Hospitals.jsx";
import Meds from "./screens/Meds.jsx";
import Login from "./screens/Login.jsx";
import Me from "./screens/Me.jsx";
import Notis from "./screens/Notis.jsx";
import Quest from "./screens/Quest.jsx";
import Report from "./screens/Report.jsx";
import Results from "./screens/Results.jsx";
import Settings from "./screens/Settings.jsx";
import Signup from "./screens/Signup.jsx";
import Welcome from "./screens/Welcome.jsx";
import "./index.css";

/* 주소를 진짜 경로로 쓴다(# 를 안 쓴다).
 * nginx 가 어떤 경로로 들어와도 index.html 을 주므로(try_files) 새로고침해도
 * 살아난다 — conf/nginx.conf 의 프런트 구역이 그 일을 한다.
 *
 * 그래서 **브라우저 뒤로가기가 곧 앱 뒤로가기**다. 화면마다 돌아갈 곳을
 * 박아 둘 필요가 없다. */

/* 없는 주소로 왔을 때. 여기도 Head 를 쓴다 — 뒤로가기가 화면마다 다르게
 * 생기지 않게 하려면 머리말을 손으로 그리는 자리가 없어야 한다.
 *
 * 한 줄을 위쪽에 붙여 두면 «잘못 눌렀나» 싶다. 가운데에 세우고 나갈
 * 길을 하나 둔다 — 오래된 알림 링크로 들어오면 여기가 첫 화면이라
 * 되짚을 이력이 없다. */
function Missing() {
  return (
    <>
      <Head title="없는 화면" />
      <div className="pane">
        <div className="empty">
          <Icon name="help" className="ic" />
          <p>주소가 잘못되었거나 사라진 화면입니다.</p>
        </div>
        <Link className="btn ghost" to="/">홈으로</Link>
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
applyScale(readScale());

/* Boom 이 제일 바깥이다 — 라우터가 터져도 받아 내야 한다.
   하는 일은 하나, **하얀 화면 대신 나갈 길을 남기는 것**이다(lib/Boom). */
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Boom>
    <BrowserRouter>
      <Routes>
        {/* 웰컴은 껍데기도 안 쓴다 — 여백을 화면 끝까지 쓴다 */}
        <Route path="/welcome" element={<Welcome />} />

        {/* 로그인 전 — 탭도 뒤로가기도 없다 */}
        <Route element={<Bare />}>
          <Route path="/login"  element={<Login />} />
          <Route path="/signup" element={<Signup />} />
        </Route>

        {/* 로그인 뒤 — RequireAuth 가 /api/v1/me 로 먼저 묻는다.
            401 이면 /login 으로 보내고, 가려던 주소를 기억해 둔다. */}
        <Route element={<RequireAuth><App /></RequireAuth>}>
          <Route path="/"             element={<Home />} />
          <Route path="/results"      element={<Results />} />
          <Route path="/reports/:id"  element={<Report />} />
          <Route path="/book"         element={<Book />} />
          <Route path="/quest"        element={<Quest />} />
          <Route path="/meds"         element={<Meds />} />
          {/* 약 정보 찾기. 탭에는 안 둔다 — 복약 관리에서 들어간다 */}
          <Route path="/drugs"        element={<Drugs />} />
          <Route path="/hospitals"    element={<Hospitals />} />
          <Route path="/chat"         element={<Chat />} />
          <Route path="/notis"        element={<Notis />} />
          <Route path="/me"           element={<Me />} />
          <Route path="/settings"     element={<Settings />} />
          <Route path="*"             element={<Missing />} />
        </Route>
      </Routes>
    </BrowserRouter>
    </Boom>
  </StrictMode>
);
