import { NavLink, Outlet } from "react-router-dom";

/* 로그인한 뒤의 껍데기 — 아래 탭은 여기 한 곳에만 있다.
 *
 * 전에는 「로그인 · 회원가입에서는 감춘다」는 목록을 들고 있었는데,
 * 이제 그 두 화면은 이 껍데기를 아예 안 쓴다(Bare 를 쓴다). 화면 이름을
 * 목록으로 관리하면 새 화면을 더할 때마다 그 목록을 손봐야 하고,
 * 잊으면 로그인 화면에 탭이 뜬다. */
const TABS = [
  { to: "/",        ic: "⌂", label: "홈"     },
  { to: "/results", ic: "▤", label: "결과"   },
  { to: "/book",    ic: "▦", label: "예약"   },
  { to: "/chat",    ic: "◍", label: "챗봇"   },
  { to: "/me",      ic: "☰", label: "내 정보" },
];

export default function App() {
  return (
    <div className="app">
      <div className="screens"><Outlet /></div>
      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/"}
            className={({ isActive }) => (isActive ? "on" : undefined)}
            /* 코치마크가 짚을 자리. 클래스로 찾으면 디자인을 고칠 때
               조용히 끊긴다 */
            data-coach={`tab-${t.to.replace("/", "") || "home"}`}
          >
            <i className="ic">{t.ic}</i>
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

/* 탭 없는 껍데기 — 로그인 · 본인 확인이 쓴다. */
export function Bare() {
  return (
    <div className="app">
      <div className="screens"><Outlet /></div>
    </div>
  );
}
