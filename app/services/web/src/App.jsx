import { NavLink, Outlet, useLocation } from "react-router-dom";

/* 화면 껍데기 — 아래 탭은 여기 한 곳에만 있다.
 * 로그인·회원가입에서는 감춘다. */
const HIDE_TABS = ["/login", "/signup"];

const TABS = [
  { to: "/",        ic: "⌂", label: "홈"     },
  { to: "/results", ic: "▤", label: "결과"   },
  { to: "/book",    ic: "▦", label: "예약"   },
  { to: "/chat",    ic: "◍", label: "챗봇"   },
  { to: "/me",      ic: "☰", label: "내 정보" },
];

export default function App() {
  const loc = useLocation();
  const hide = HIDE_TABS.includes(loc.pathname);

  return (
    <div className="app">
      <div className="screens"><Outlet /></div>

      {!hide && (
        <nav className="tabs">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.to === "/"}
              className={({ isActive }) => (isActive ? "on" : undefined)}
            >
              <i className="ic">{t.ic}</i>
              {t.label}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
