import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Outlet, Route, Routes } from "react-router-dom";

import { DEPTS, HOSPITAL, PRODUCT, ROOT, deptPath, findDept, screenCount,
         screenPath } from "./nav";
import Skeleton from "./Skeleton";
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
    </div>
  );
}

/* 부서 고르기 — 설계서 첫 장이 하는 일이다. 어느 부서로 들어갈지
   고르고, 그 부서가 가진 화면을 미리 보여 준다. */
function Index() {
  return (
    <div className="app">
      <header className="top bare">
        <div className="top-l">
          <span className="mark" aria-hidden="true">◈</span>
          <b>{HOSPITAL} {PRODUCT}</b>
        </div>
      </header>

      <main className="page">
        <div className="phead">
          <div className="phead-l">
            <h1>화면 설계<span className="badge">{screenCount}개 화면</span></h1>
            <p className="sub">
              부서를 골라 들어가면 화면 사이를 오가며 흐름을 확인할 수 있습니다.
            </p>
          </div>
        </div>

        <p className="flow">
          로그인 → 원무과 접수·예약 → 간호과 문진·추적 → 유방외과 진료 →
          영상의학과 촬영·판독 → 병리과 검체·판독 → 수술 결정·환자 설명
        </p>

        <div className="depts">
          {DEPTS.map((d) => (
            <section className="dcard" key={d.key}>
              <span className="en">{d.en}</span>
              <h2>{d.name}</h2>
              <p className="who">
                {d.who ? `${d.who.name} ${d.who.role} · ${d.note}` : d.note}
              </p>
              <ul>
                {d.screens.map((s) => (
                  <li key={s.key || "_"}>
                    <Link to={screenPath(d, s)}>{s.title}</Link>
                    <span className="src">p.{s.page}</span>
                  </li>
                ))}
              </ul>
              <Link className="btn line" to={deptPath(d)}>열기</Link>
            </section>
          ))}
        </div>
      </main>
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
const REAL = {
  "pathology/":         PathSpecimens,
  "pathology/patients": PathPatients,
  "pathology/upload":   PathUpload,
  "pathology/read":     PathRead,
  "pathology/amend":    PathAmend,
};

/* 표 한 줄 → Route 하나 */
function routesOf(d) {
  return d.screens.map((s) => {
    const Real = REAL[`${d.key}/${s.key}`];
    return (
      <Route key={s.key || "_"}
             path={s.key || undefined}
             index={!s.key}
             element={Real ? <Real /> : <Skeleton dept={d} screen={s} />} />
    );
  });
}

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
        <Route path={ROOT} element={<Index />} />
        <Route path={ROOT} element={<Shell />}>
          {DEPTS.map((d) => (
            <Route key={d.key} path={d.key}>{routesOf(d)}</Route>
          ))}
        </Route>
        {/* ⚠ 뿌리 주소를 여기서 다루지 않는다. 그 자리는 환자 앱 것이다.
            병원 웹은 /hospital 아래만 맡는다 — 한 저장소에 있을 뿐
            서로 다른 물건이고, 뿌리를 가로채면 둘이 엉킨다. */}
        <Route path="*" element={<div className="app"><Missing /></div>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
