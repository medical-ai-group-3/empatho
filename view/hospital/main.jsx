import { StrictMode, Suspense, lazy, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter, Navigate, Outlet, Route, Routes, useLocation,
} from "react-router-dom";

import "./tokens.css";
import "./hospital.css";

import { apiInfo } from "./api";
import { DEPTS, ROOT, deptPath, findDept, homeDept } from "./nav";
import Top from "./lib/Top";
import { useLoadMe } from "./lib/useMe";
import { useSignedIn } from "./lib/session";
import Login from "./screens/auth/Login";
import Boom from "./lib/Boom";

import QueueScreen from "./screens/Queue";
import UploadScreen from "./screens/Upload";
import ReadScreen from "./screens/Read";
import ListScreen from "./screens/List";
import AmendScreen from "./screens/Amend";
import MeScreen from "./screens/Me";
import ReceptionIntake from "./screens/reception/Intake";
import ReceptionPatients from "./screens/reception/Patients";
import ReceptionRequests from "./screens/reception/Requests";

/* 유방외과 — 병리·영상과 화면 구성이 달라 자기 화면을 직접 들고 온다.
 *
 * ⚠ **늦게 불러온다(lazy).** 이 화면들이 three · cornerstone · nifti 를
 *   끌고 오는데 합쳐서 500kB 가 넘는다. 위에서 그냥 import 하면 병리·영상만
 *   쓰는 선생님도 3D 라이브러리를 통째로 내려받는다 — 실제로 묶음이
 *   194kB 에서 739kB 로 뛰었다. 유방외과 화면에 들어갈 때만 받게 한다. */
const BreastWaiting = lazy(() => import("./dept/breast/screens/Waiting"));
const BreastReview = lazy(() => import("./dept/breast/screens/Review"));
const BreastDecision = lazy(() => import("./dept/breast/screens/Decision"));
const BreastDiscordance = lazy(() => import("./dept/breast/screens/Discordance"));

import { pathology } from "./dept/pathology";
import { breast } from "./dept/breast";
import { radiology } from "./dept/radiology";
import { reception } from "./dept/reception";

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
 *   /hospital/breast                  1장 대기 환자
 *   /hospital/breast/patients/:id/review    2장 검사 종합 확인
 *   /hospital/breast/patients/:id/decision  3장 수술 결정
 *   /hospital/breast/discordances/:id       4장 판정 불일치 처분
 *
 *   /hospital/me                      내 정보 (과 바깥 — 사람은 과에 안 딸린다)
 *
 * ⚠ **뿌리 주소를 가로채지 않는다.** 그 자리는 환자 앱이다.
 */

const CFG = { pathology, radiology, breast, reception };

/* 주소에서 과를 읽는다 — /hospital/reception/patients → "reception"
 *
 * ⚠ **useParams() 를 쓰면 안 된다.** Shell 이 걸린 라우트는 path="/hospital"
 *   이고 그 아래가 path="reception" 처럼 리터럴이라, 어디에도 :dept 파라미터가
 *   없다. useParams() 는 늘 빈 객체를 주고 findDept 가 null 을 돌려줘서
 *   **상단 메뉴와 과 이름이 다섯 과 모두 통째로 사라진다.**
 *   라우트를 «다섯 장 고정»에서 선언 기반으로 바꿀 때(6176ec0) 생긴 구멍이다.
 *
 *   라우트에 :dept 를 넣는 길도 있지만 그러면 과마다 화면 표를 따로 쓰는
 *   지금 구조(deptRoutes)를 다시 손봐야 한다. 주소는 이미 과를 담고 있으니
 *   읽기만 한다.
 */
function deptFromPath(pathname) {
  /* "/hospital/reception/patients" → ["", "hospital", "reception", …] */
  return findDept(pathname.split("/")[2] ?? "");
}

function Shell() {
  const { pathname } = useLocation();
  const d = deptFromPath(pathname);
  const [now, setNow] = useState(stamp);

  useEffect(() => {
    const t = setInterval(() => setNow(stamp()), 30000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="shell">
      <Top dept={d} now={now} />
      <Boom>
        {/* lazy 로 미룬 화면(유방외과)이 오는 동안 자리를 지킨다.
            Boom 안쪽이다 — 늦게 불러오다 실패하면 그것도 오류로 잡혀야 한다 */}
        <Suspense fallback={<div className="slot big"><b>화면을 불러오는 중…</b></div>}>
          <Outlet />
        </Suspense>
      </Boom>
      {apiInfo.mock && (
        <footer className="mockbar">
          목업 자료 — 지어낸 값입니다 · {apiInfo.base}
        </footer>
      )}
    </div>
  );
}

/* ── 로그인 관문 ──────────────────────────────────────────────
 *
 * 토큰이 없으면 로그인 화면만 띄운다. **Boot 보다 앞이다** — 토큰 없이
 * Boot 을 태우면 GET /me 가 401 로 떨어지고, 사람에게는 「로그인 정보를
 * 가져오지 못했습니다」라는 엉뚱한 오류로 보인다. 로그인을 안 한 것은
 * 오류가 아니다.
 *
 * 토큰이 있느냐만 본다 (session.js 의 useSignedIn). 만료된 토큰이면
 * 여기는 통과하고 Boot 의 /me 가 401 을 받는데, 그건 갱신 경로가
 * 생긴 뒤에 다룰 자리다.
 */
function Gate({ children }) {
  return useSignedIn() ? children : <Login />;
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

  /* 유방외과. 이름에 과를 붙여 둔다 — 「대기」가 과마다 다른 화면이라
     queue 처럼 짧게 두면 어느 과 것인지 안 보인다 */
  "breast.waiting":     BreastWaiting,
  "breast.review":      BreastReview,
  "breast.decision":    BreastDecision,
  "breast.discordance": BreastDiscordance,

  /* 원무과. 다섯 장 틀을 안 쓴다 — 집는 절차도 판독도 없고
     환자를 시스템에 들여보내는 입구다 */
  "reception.intake":   ReceptionIntake,
  "reception.patients": ReceptionPatients,
  "reception.requests": ReceptionRequests,
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
      <Gate>
      <Boot>
        <Routes>
          {/* ⚠ **Boot 안쪽이라서** homeDept() 가 제 답을 준다. 밖이면 아직
              perms 가 없어 전부 false 로 보이고 늘 첫 과로 떨어진다 */}
          <Route path={ROOT} element={<Navigate to={deptPath(homeDept())} replace />} />
          <Route path={ROOT} element={<Shell />}>
            {/* ⚠ 과 바깥에 있는 유일한 화면이다. Shell 은 그대로 쓰되
                주소가 /hospital/me 라 deptFromPath 가 "me" 를 찾다 null 을
                주고, 상단 메뉴가 자동으로 빈다 — Top 이 dept 없을 때를
                이미 다룬다 */}
            <Route path="me" element={<MeScreen />} />
            {DEPTS.map((d) => deptRoutes(d.key))}
          </Route>
          <Route path={`${ROOT}/*`} element={<Navigate to={deptPath(homeDept())} replace />} />
        </Routes>
      </Boot>
      </Gate>
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
