import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { applyTheme, readTheme, saveTheme } from "./lib/theme.js";

/* 의료진 워크스테이션 껍데기 — 상단바(로고·병원명·다크모드·알림·시계·담당의)는
 * 화면이 바뀌어도 늘 고정으로 떠 있다. 네비게이션바는 없다 — 화면 이동은
 * 화면마다 있는 뒤로가기 버튼(lib/Screen.jsx의 Head)으로 한다.
 * 로고를 누르면 첫 대시보드(대기 환자)로 바로 간다.
 *
 * 우측 순서(요청받은 대로): 다크/라이트 토글 · 알림 · 날짜시간 · 이름/과 · 프로필 */
export default function App({ deptLabel = "" }) {
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-row">
          <Link className="brand-btn" to="/" aria-label="대기 환자(첫 화면)로 이동">
            <span className="logo">EMPATHO</span>
            <span className="hospital">
              <span className="h1">미래 대학병원</span>
              <span className="h2">{deptLabel}</span>
            </span>
          </Link>

          <div className="right">
            <ThemeToggle />
            <button className="bell" aria-label="알림">
              <BellIcon />
              <i className="dot" aria-hidden="true" />
            </button>
            <Clock />
            <Link className="who-btn" to="/me" aria-label="내 정보 · 설정">
              <span className="who"><b>서냐냥</b><span>{deptLabel} · 선생님</span></span>
              <span className="avatar sm" aria-hidden="true">서</span>
            </Link>
          </div>
        </div>
      </header>
      <div className="workspace"><Outlet /></div>
    </div>
  );
}

function ThemeToggle() {
  const [mode, setMode] = useState(readTheme);

  function toggle() {
    const next = mode === "dark" ? "light" : "dark";
    setMode(next);
    applyTheme(next);
    saveTheme(next);
  }

  return (
    <button className="theme-btn" onClick={toggle}
      aria-label={mode === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}>
      {mode === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000 * 30);
    return () => clearInterval(t);
  }, []);
  const date = now.toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit", weekday: "short" });
  const time = now.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  return <span className="clock">{date} · {time}</span>;
}

function BellIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.5v2.4M12 19.1v2.4M4.6 4.6l1.7 1.7M17.7 17.7l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.6 19.4l1.7-1.7M17.7 6.3l1.7-1.7" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.7 14.9A8.6 8.6 0 0 1 9.1 3.3a.7.7 0 0 0-.9-.9 10 10 0 1 0 13.4 13.4.7.7 0 0 0-.9-.9Z" />
    </svg>
  );
}
