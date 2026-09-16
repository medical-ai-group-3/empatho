import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter, Navigate, Outlet, Route, Routes, useParams,
} from "react-router-dom";

import "./tokens.css";
import "./hospital.css";

import { apiInfo } from "./api";
import { DEPTS, HOME, ROOT, deptPath, findDept } from "./nav";
import Top from "./lib/Top";
import { useLoadMe } from "./lib/useMe";
import Boom from "./lib/Boom";

import QueueScreen from "./screens/Queue";
import UploadScreen from "./screens/Upload";
import ReadScreen from "./screens/Read";
import ListScreen from "./screens/List";
import AmendScreen from "./screens/Amend";
import MeScreen from "./screens/Me";

import { pathology } from "./dept/pathology";
import { radiology } from "./dept/radiology";

/* 병원 웹 — 라우트
 * ════════════════════════════════════════════════════════════════
 *
 * 과가 둘이고, 과마다 화면이 다섯 장이다. 화면의 뼈대는 screens/ 에
 * 하나씩만 있고, 과별로 다른 것은 dept/ 의 설정이 들고 온다.
 *
 *   /hospital/pathology               1장 검체 접수 대기
 *   /hospital/pathology/specimens     4장 전체 환자 목록
 *   /hospital/pathology/specimens/:id/upload   2장 업로드
 *   /hospital/pathology/read/:id      3장 판독
 *   /hospital/pathology/read/:id/amend 5장 판독 정정
 *
 *   /hospital/radiology               1장 촬영 대기 큐
 *   /hospital/radiology/patients      4장 전체 환자 목록
 *   /hospital/radiology/studies/:id/upload     2장 업로드
 *   /hospital/radiology/read/:id      3장 판독
 *   /hospital/radiology/read/:id/amend 5장 판독 정정
 *
 *   /hospital/me                      내 정보 (과 바깥 — 사람은 과에 안 딸린다)
 *
 * ⚠ **뿌리 주소를 가로채지 않는다.** 그 자리는 환자 앱이다.
 */

const CFG = { pathology, radiology };

function Shell() {
  const { dept } = useParams();
  const d = findDept(dept);
  const [now, setNow] = useState(stamp);

  useEffect(() => {
    const t = setInterval(() => setNow(stamp()), 30000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="shell">
      <Top dept={d} now={now} />
      <Boom>
        <Outlet />
      </Boom>
      {apiInfo.mock && (
        <footer className="mockbar">
          목업 자료 — 지어낸 값입니다 · {apiInfo.base}
        </footer>
      )}
    </div>
  );
}

/* 로그인 응답(perms)이 올 때까지 기다린다. 안 기다리면 첫 그림에서
   권한이 전부 false 라 메뉴가 비었다가 나타난다 */
function Boot({ children }) {
  const { loading, error } = useLoadMe();

  if (loading) {
    return <div className="boot"><b>불러오는 중…</b></div>;
  }
  if (error) {
    return (
      <div className="boot">
        <b>로그인 정보를 가져오지 못했습니다</b>
        <span>{error.detail || error.message}</span>
        <span className="muted small">
          권한을 확인할 수 없어 화면을 열 수 없습니다. 다시 로그인해 주세요.
        </span>
      </div>
    );
  }
  return children;
}

/* ── 화면 뼈대 표 ──────────────────────────────────────────────
 *
 * nav.js 의 각 화면이 use 로 여기 이름 하나를 고른다.
 *
 * ⚠ 전에는 «과마다 정확히 다섯 장, 이 순서»를 박아 두었다 —
 *     const [queue, list, upload, read, amend] = d.screens;
 *   병리와 영상이 우연히 같은 모양이라 굴러갔지만, 화면 수나 구성이
 *   다른 과는 **아예 못 넣는다.** 순서 대신 이름으로 고르게 바꾼다.
 *   과를 더할 때 이 파일에서 고칠 것은 아래 표에 한 줄 더하는 것뿐이다.
 */
const SCREENS = {
  queue:  QueueScreen,
  list:   ListScreen,
  upload: UploadScreen,
  read:   ReadScreen,
  amend:  AmendScreen,
};

/* 과 하나의 화면들 — 몇 장이든 nav.js 의 표대로 만들어진다 */
function deptRoutes(key) {
  const cfg = CFG[key];
  const d = findDept(key);

  return (
    <Route key={key} path={key}>
      {d.screens.map((s) => {
        const El = SCREENS[s.use];
        /* 표에 없는 이름을 적으면 조용히 빈 화면이 되는 대신 여기서 걸린다 */
        if (!El) {
          throw new Error(
            `nav.js: ${key} 의 "${s.key}" 가 use:"${s.use}" 라고 적었는데 ` +
            `main.jsx 의 SCREENS 표에 그런 이름이 없다`);
        }
        return s.key
          ? <Route key={s.key} path={s.key} element={<El cfg={cfg} />} />
          : <Route key="_index" index element={<El cfg={cfg} />} />;
      })}
    </Route>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Boot>
        <Routes>
          <Route path={ROOT} element={<Navigate to={deptPath(HOME)} replace />} />
          <Route path={ROOT} element={<Shell />}>
            {/* ⚠ 과 바깥에 있는 유일한 화면이다. Shell 은 그대로 쓰되
                :dept 가 없어서 findDept 가 null 을 주고, 상단 메뉴가
                자동으로 빈다 — Top 이 dept 없을 때를 이미 다룬다 */}
            <Route path="me" element={<MeScreen />} />
            {DEPTS.map((d) => deptRoutes(d.key))}
          </Route>
          <Route path={`${ROOT}/*`} element={<Navigate to={deptPath(HOME)} replace />} />
        </Routes>
      </Boot>
    </BrowserRouter>
  );
}

function stamp() {
  return new Date().toLocaleString("ko-KR", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

createRoot(document.getElementById("root")).render(
  <StrictMode><App /></StrictMode>,
);
