import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { apiInfo } from "./api";
import { HOME, ROOT, deptPath } from "./nav";
import PathAmend from "./screens/path/Amend";
import PathPatients from "./screens/path/Patients";
import PathRead from "./screens/path/Read";
import PathSpecimens from "./screens/path/Specimens";
import PathUpload from "./screens/path/Upload";
import Top from "./lib/Top";
import "./hospital.css";

/* 의료진용 콘솔 — 진입점.
 *
 * **라우팅을 손으로 적지 않는다.** nav.js 의 표를 돌며 만든다. 화면을
 * 더하려면 그 표에 줄 하나를 더하면 되고, 메뉴 · 주소 · 쪽 머리가 함께
 * 따라온다.
 *
 * 주소는 /console 아래에 둔다. 같은 저장소에 환자 앱이 있고 그쪽이
 * / 를 쓴다 — 입구가 둘이라 CSS 와 토큰은 안 섞이지만 **주소는 한
 * 서버에서 나가므로** 앞머리로 갈라 준다.
 *
 * ⚠ nginx 에 한 줄이 필요하다. /hospital 로 들어온 요청은 hospital.html 을
 *   돌려줘야 새로고침해도 살아난다. 지금 규칙은 전부 index.html 로
 *   보내므로, 그대로 두면 콘솔 주소에서 환자 앱이 뜬다.
 */

function Shell() {
  const [now, setNow] = useState(fmtNow);
  useEffect(() => {
    const t = setInterval(() => setNow(fmtNow()), 30_000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="app">
      <Top now={now} />
      <Outlet />
      {/* **목업을 보면서 진짜인 줄 아는 일**을 막는다. 시연 자리에서
          「이거 실제 자료인가요」를 들었을 때 화면이 대신 답한다.
          진짜 서버에 붙으면 이 줄이 사라진다 */}
      {apiInfo.mock && (
        <footer className="mockbar">
          목업 자료 — 지어낸 값입니다 · {apiInfo.base}
        </footer>
      )}
    </div>
  );
}

function Missing() {
  return (
    <main className="page">
      <div className="slot big">
        <b>없는 화면입니다</b>
        <span>주소가 잘못되었거나 아직 만들지 않은 화면입니다.</span>
        <Link className="btn line" to={ROOT}>부서 고르기</Link>
      </div>
    </main>
  );
}

/* 진짜로 만든 화면. 표(nav.js)의 «부서/화면» 열쇠로 찾는다.
   여기 없는 것은 뼈대(Skeleton)가 대신 그린다 — 자리는 잡혀 있고
   내용만 안 들어간 상태다. 화면 하나가 완성될 때마다 여기 한 줄씩
   더하면 되고, 라우팅은 안 건드린다. */




const p2 = (n) => String(n).padStart(2, "0");
const WD = ["일", "월", "화", "수", "목", "금", "토"];
function fmtNow() {
  const d = new Date();
  return `${d.getFullYear()}.${p2(d.getMonth() + 1)}.${p2(d.getDate())} `
       + `(${WD[d.getDay()]}) ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* /hospital 로 들어오면 첫 부서로 보낸다. 부서 고르기 화면을
            따로 두지 않는다 — 부서가 하나뿐이라 한 번 더 누르게 할
            이유가 없다. 부서가 늘면 그때 만든다. */}
        <Route path={ROOT} element={<Navigate to={deptPath(HOME)} replace />} />
        <Route path={ROOT} element={<Shell />}>
          {/* 병리과 — 명세의 라우트 그대로.
              검체 번호가 주소에 들어간다(:id). 물음표 뒤가 아니라 경로다. */}
          <Route path="pathology">
            <Route index                         element={<PathSpecimens />} />
            <Route path="specimens"              element={<PathPatients />} />
            <Route path="specimens/:id/upload"   element={<PathUpload />} />
            <Route path="read/:id"               element={<PathRead />} />
            <Route path="read/:id/amend"         element={<PathAmend />} />
          </Route>
        </Route>
        {/* ⚠ 뿌리 주소를 여기서 다루지 않는다. 그 자리는 환자 앱 것이다.
            병원 웹은 /hospital 아래만 맡는다 — 한 저장소에 있을 뿐
            서로 다른 물건이고, 뿌리를 가로채면 둘이 엉킨다. */}
        <Route path="*" element={<div className="app"><Missing /></div>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
