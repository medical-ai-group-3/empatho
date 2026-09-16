import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, useRoutes } from "react-router-dom";

import App from "./App.jsx";
import breastRoutes from "./depts/breast/routes.jsx";
import Profile from "./screens/Profile.jsx";
import { applyTheme, readTheme } from "./lib/theme.js";
import "./index.css";

/* React가 그리기 전에 다크/라이트를 세워 둔다 — 안 그러면 첫 프레임이
   라이트로 떴다가 다크로 바뀌면서 눈이 부시다. */
applyTheme(readTheme());

/* 과가 늘면 여기에 나란히 스프레드한다:
 *   [{ element: <App/>, children: [...breastRoutes, ...radiologyRoutes, missing] }]
 * useRoutes()는 배열(route config)을 합치는 방식이라 JSX <Route> 트리를
 * 컴포넌트로 감쌀 때 생기는 문제(depts/breast/routes.jsx 주석 참고)가 없다. */
function Missing() {
  return (
    <div className="pane">
      <div className="empty">
        <i className="ic" aria-hidden="true">◍</i>
        <p>주소가 잘못되었거나 아직 만들지 않은 화면입니다.</p>
      </div>
    </div>
  );
}

function AppRoutes() {
  return useRoutes([
    {
      element: <App deptLabel="유방외과" />,
      children: [
        ...breastRoutes,
        { path: "/me", element: <Profile /> },
        { path: "*", element: <Missing /> },
      ],
    },
  ]);
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  </StrictMode>
);
