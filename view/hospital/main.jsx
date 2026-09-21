import { StrictMode, Suspense, lazy, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter, Navigate, Outlet, Route, Routes, useLocation,
} from "react-router-dom";

/* 팀 공용 디자인 시스템 토큰 — tokens.css/themes.css 는 :root 에 새 이름의
   커스텀 프로퍼티만 얹으므로 전역으로 불러도 안전하다. base.css(전역
   body/.btn/.card 규칙)는 여기서 안 부른다 — 회원가입 화면 전용으로
   스코프한 styles/signup-ds.css 가 그 역할을 대신한다. */
import "./styles/tokens.css";
import "./styles/themes.css";

import "./tokens.css";
import "./hospital.css";

import { adminSession, apiInfo } from "./api";
import { DEPTS, ROOT, deptPath, findDept, homeDept } from "./nav";
import Top from "./lib/Top";
import StickyMemo from "./lib/StickyMemo";
import { useLoadMe, useMe } from "./lib/useMe";
import { useSignedIn } from "./lib/session";
import Login from "./screens/auth/Login";
import Signup from "./screens/auth/Signup";
import Boom from "./lib/Boom";

import HomeScreen from "./lib/Home";
import PatientScreen from "./screens/Patient";
import QueueScreen from "./screens/Queue";
import UploadScreen from "./screens/Upload";
import ReadScreen from "./screens/Read";
import ListScreen from "./screens/List";
import AmendScreen from "./screens/Amend";
import MeScreen from "./screens/Me";
import ReceptionIntake from "./screens/reception/Intake";
import ReceptionPatients from "./screens/reception/Patients";
import ReceptionReservations from "./screens/reception/Reservations";
import AdminConsole from "./screens/admin/Console";

/* 유방외과 — 병리·영상과 화면 구성이 달라 자기 화면을 직접 들고 온다.
 *
 * ⚠ **늦게 불러온다(lazy).** 이 화면들이 three · cornerstone · nifti 를
 *   끌고 오는데 합쳐서 500kB 가 넘는다. 위에서 그냥 import 하면 병리·영상만
 *   쓰는 선생님도 3D 라이브러리를 통째로 내려받는다 — 실제로 묶음이
 *   194kB 에서 739kB 로 뛰었다. 유방외과 화면에 들어갈 때만 받게 한다. */
const BreastWaiting = lazy(() => import("./dept/breast/screens/Waiting"));
const BreastPatients = lazy(() => import("./dept/breast/screens/Patients"));
const BreastReview = lazy(() => import("./dept/breast/screens/Review"));
const BreastDecision = lazy(() => import("./dept/breast/screens/Decision"));
const BreastDiscordance = lazy(() => import("./dept/breast/screens/Discordance"));

/* 간호과도 breast처럼 자기 화면을 직접 들고 온다 — 다만 무거운 라이브러리를
   끌지는 않는다. lazy는 다른 과 화면들과 코드 스플리팅 일관성 때문에 유지 */
const NursingWaiting = lazy(() => import("./dept/nursing/screens/Waiting"));
const NursingFollowups = lazy(() => import("./dept/nursing/screens/Followups"));

import { pathology } from "./dept/pathology";
import { breast } from "./dept/breast";
import { radiology } from "./dept/radiology";
import { nursing } from "./dept/nursing";

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
 *   /hospital/breast/patients         전체 환자 목록
 *   /hospital/breast/patients/:id/review    2장 검사 종합 확인
 *   /hospital/breast/patients/:id/decision  3장 수술 결정
 *   /hospital/breast/discordances/:id       4장 판정 불일치 처분
 *
 *   /hospital/me                      내 정보 (과 바깥 — 사람은 과에 안 딸린다)
 *
 * ⚠ **뿌리 주소를 가로채지 않는다.** 그 자리는 환자 앱이다.
 */

/* 원무과는 없다 — 접수·간호로 합쳤다(6.1). 원무 화면들은 nursing 설정이
   합쳐 준 api 를 받는다 (dept/nursing.jsx) */
const CFG = { pathology, radiology, breast, nursing };

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
    /* 목업 띠가 깔리면 화면 바닥을 그만큼 덜 쓴다. 뷰포트에 딱 맞춰
       높이를 재는 화면(홈 · 예약 판)이 그 띠 밑으로 깔리면 마지막 줄을
       못 누른다 — 띠는 sticky 라 그 위에 뜬다 */
    <div className={`shell${apiInfo.mock ? " has-mockbar" : ""}`}>
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
      {/* Boom 바깥이다 — 라우트 쪽 화면이 죽어도 메모는 그대로 떠 있어야
          한다. Shell은 <Outlet/>을 감싸는 자리라 과를 옮겨도(라우트가
          바뀌어도) 다시 마운트되지 않는다 — 그래서 메모가 안 사라진다. */}
      <StickyMemo />
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
  const [mode, setMode] = useState("login");
  if (useSignedIn()) return children;
  return mode === "signup"
    ? <Signup onBack={() => setMode("login")} />
    : <Login onSignup={() => setMode("signup")} />;
}

/* ── 관리자는 병원 화면을 거치지 않는다 ────────────────────────
 *
 * role 이 admin 이면 로그인 직후 바로 Django admin 으로 보낸다. 관리자가
 * 병원 웹에서 할 일이 없어서다 — 계정 승인도 자료 조회도 저쪽 화면이다.
 *
 * **여기서 판단하는 이유** — 로그인 응답에는 access 만 오고 role 이 없다.
 * role 은 Boot 의 useLoadMe() 가 GET /me 로 이미 가져오므로, 판단에 필요한
 * 값이 여기 있다. Login.jsx 는 「토큰을 받아 넣는 것까지」만 하도록 일부러
 * 좁혀 둔 파일이라 거기에 /me 를 또 붙이지 않는다.
 *
 * ⚠ **admin-session 을 먼저 await 한다.** 순서가 바뀌면 쿠키 없이 /admin/ 에
 *   닿아서 Django 로그인 화면이 뜬다 — 비밀번호를 두 번 치는 그림이 된다.
 *
 * ⚠ **replace 다. assign 이 아니다.** assign 이면 뒤로가기가 병원 화면으로
 *   돌아오고, 그 화면이 다시 admin 으로 넘겨서 뒤로가기가 먹통이 된다.
 *
 * ⚠ **useRef 가드.** StrictMode 가 effect 를 두 번 돌려서 admin-session 이
 *   두 번 나간다. 실패하면 가드를 풀어 다시 눌러 볼 수 있게 둔다.
 *
 * ⚠ **목업에서는 안 한다.** vite 목업이 POST /admin-session 을 가로채
 *   「성공」만 답하고 쿠키는 안 심는다. 넘어가 봐야 Django 로그인 화면이라,
 *   목업에서는 관리자 화면(버튼)에 남는다.
 */
function useAdminJump(ready) {
  const me = useMe();
  const sent = useRef(false);

  useEffect(() => {
    if (!ready || apiInfo.mock) return;
    if (me?.role !== "admin" || sent.current) return;
    sent.current = true;

    adminSession().then(
      ({ admin_url: url }) => window.location.replace(url),
      // 실패하면 아무 데도 안 보낸다. 병원 화면이 그대로 서고, 관리자
      // 화면의 단추로 다시 해 볼 수 있다
      () => { sent.current = false; },
    );
  }, [ready, me]);
}

/* 로그인 응답(perms)이 올 때까지 기다린다. 안 기다리면 첫 그림에서
   권한이 전부 false 라 메뉴가 비었다가 나타난다 */
function Boot({ children }) {
  const { loading, error } = useLoadMe();
  useAdminJump(!loading && !error);

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
  /* 과 홈 — 다섯 과가 같은 화면을 쓴다. 칸이 무엇인지는 dept/*.jsx 의
     home 이 정한다(5.3 칸은 과마다 다르다) */
  home:   HomeScreen,

  queue:  QueueScreen,
  list:   ListScreen,
  upload: UploadScreen,
  read:   ReadScreen,
  amend:  AmendScreen,

  /* 유방외과. 이름에 과를 붙여 둔다 — 「대기」가 과마다 다른 화면이라
     queue 처럼 짧게 두면 어느 과 것인지 안 보인다 */
  "breast.waiting":     BreastWaiting,
  "breast.patients":    BreastPatients,
  "breast.review":      BreastReview,
  "breast.decision":    BreastDecision,
  "breast.discordance": BreastDiscordance,

  /* 접수·간호. 다섯 장 틀을 안 쓴다 — 집는 절차도 판독도 없고
     환자를 시스템에 들여보내는 입구다. 이름의 reception 은 **화면이
     어디서 왔는지**를 말하는 것뿐이고, 과는 nursing 하나다 */
  "reception.intake":   ReceptionIntake,
  "reception.patients": ReceptionPatients,
  "reception.reservations": ReceptionReservations,

  /* 관리자. 화면은 하나고 Django admin 으로 넘기는 자리다 */
  "admin.console":      AdminConsole,

  "nursing.waiting":   NursingWaiting,
  "nursing.followups": NursingFollowups,
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
          <Route path={ROOT} element={<HomeRedirect />} />
          <Route path={ROOT} element={<Shell />}>
            {/* ⚠ 과 바깥에 있는 유일한 화면이다. Shell 은 그대로 쓰되
                주소가 /hospital/me 라 deptFromPath 가 "me" 를 찾다 null 을
                주고, 상단 메뉴가 자동으로 빈다 — Top 이 dept 없을 때를
                이미 다룬다 */}
            <Route path="me" element={<MeScreen />} />
            {/* 환자 상세도 과 바깥이다 — 어디서 와도 같은 화면이라
                과 하나에 매달면 다른 과에서 그 주소로 못 온다 (6.5) */}
            <Route path="patients/:id" element={<PatientScreen />} />
            {DEPTS.map((d) => deptRoutes(d.key))}
          </Route>
          <Route path={`${ROOT}/*`} element={<HomeRedirect />} />
        </Routes>
      </Boot>
      </Gate>
    </BrowserRouter>
  );
}

/* App을 처음 그릴 때는 아직 /me 응답이 없다. JSX 안에서
   homeDept()를 바로 실행하면 그 순간의 빈 권한으로 병리과 주소가
   고정된다. Boot가 권한을 읽고 난 뒤 이 컴포넌트가 렌더될 때 계산해야
   각 계정이 자기 부서 대시보드로 간다. */
function HomeRedirect() {
  return <Navigate to={deptPath(homeDept())} replace />;
}

function stamp() {
  return new Date().toLocaleString("ko-KR", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

createRoot(document.getElementById("root")).render(
  <StrictMode><App /></StrictMode>,
);
