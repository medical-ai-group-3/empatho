import Waiting from "./screens/Waiting";
import Decision from "./screens/Decision";
import Discordance from "./screens/Discordance";
import Review from "./screens/Review";
import MRIReviewGrid from "../../components/MRIReviewGrid";

/* 유방외과 라우트 배열 — useRoutes()용 route config 객체다.
 * <Route> JSX를 감싸는 컴포넌트로 만들면 <Routes>의 정적 트리 분석을
 * 통과하지 못해 조용히 무시된다(React Router의 createRoutesFromChildren은
 * 오직 <Route>/<Fragment> 자식만 읽는다). 배열로 두면 그런 문제 없이
 * 그대로 합칠 수 있다 — 과가 늘면 depts/radiology/routes.jsx 를 만들어
 * main.jsx에서 나란히 스프레드하면 된다. */
const breastRoutes = [
  { path: "/", element: <Waiting /> },
  { path: "/patients/:id/decision", element: <Decision /> },
  { path: "/patients/:id/review", element: <Review /> },
  { path: "/discordances/:id", element: <Discordance /> },
  {
    path: "/anatomy-test",
    element: (
      <div style={{ width: 900, height: 700 }}>
        <MRIReviewGrid selectedLesion={0} />
      </div>
    ),
  },
];

export default breastRoutes;
