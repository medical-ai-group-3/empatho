import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { HOSPITAL, PRODUCT, deptPath, go, homeDept, menuScreens, myDepts } from "../nav";
import { can } from "../perm";
import { acknowledgeNotification, notifications } from "../api";
import { useMe } from "./useMe";

/* 상단바 — 지금 어느 과의 어느 화면인지, 그리고 내가 누구인지
 * ────────────────────────────────────────────────────────────────
 *
 * 메뉴는 nav.js 의 표에서 만들어진다. 화면을 더해도 여기는 안 고친다.
 *
 * **권한이 없는 화면은 메뉴에 안 뜬다.** 눌러 봐야 「권한이 없습니다」만
 * 나올 자리를 띄워 두면 매번 헛걸음하게 된다. (버튼은 반대다 — 버튼은
 * 감추지 않고 끈다. 사라지면 고장으로 오해한다.)
 *
 * 왼쪽은 **지금 보는 화면의 과**, 오른쪽은 **로그인한 사람**이다.
 * 둘이 다를 수 있어서 과 이름이 두 번 나오지 않게 오른쪽은 작게만 적는다.
 */
export default function Top({ dept, now }) {
  const me = useMe();
  const screens = dept ? menuScreens(dept).filter((s) => can(s.need)) : [];

  /* ── 과 전환 ────────────────────────────────────────────────
     이게 없으면 한 과에 들어간 뒤로는 주소를 직접 치지 않는 한 다른 과로
     못 간다. 상단 메뉴는 «지금 과의 화면 다섯 장»만 만들기 때문이다. */
  const depts = myDepts();
  const [open, setOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [bellLoading, setBellLoading] = useState(false);
  const [bellError, setBellError] = useState(null);
  const [bellItems, setBellItems] = useState([]);
  const box = useRef(null);
  const bellBox = useRef(null);

  /* 바깥을 누르거나 Esc 로 닫는다. 열어 둔 채 다른 곳을 누르면
     닫히는 게 당연해서, 안 닫히면 고장으로 본다 */
  useEffect(() => {
    if (!open && !bellOpen) return;
    const away = (e) => {
      if (!box.current?.contains(e.target)) setOpen(false);
      if (!bellBox.current?.contains(e.target)) setBellOpen(false);
    };
    const esc = (e) => {
      if (e.key === "Escape") { setOpen(false); setBellOpen(false); }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open, bellOpen]);

  async function toggleBell() {
    if (bellOpen) {
      setBellOpen(false);
      return;
    }
    setOpen(false);
    setBellOpen(true);
    setBellLoading(true);
    setBellError(null);
    try {
      setBellItems(await notifications());
    } catch (e) {
      setBellError(e.detail || e.message || "알림을 불러오지 못했습니다.");
    } finally {
      setBellLoading(false);
    }
  }

  async function acknowledge(item) {
    const id = item.notification_id ?? item.id;
    if (!id || item.acknowledged_at) return;
    /* 먼저 표시를 바꿔 두고 실패하면 원래 목록을 다시 받는다. */
    setBellItems((items) => items.map((n) =>
      (n.notification_id ?? n.id) === id
        ? { ...n, acknowledged_at: new Date().toISOString() }
        : n));
    try {
      await acknowledgeNotification(id);
    } catch {
      try { setBellItems(await notifications()); } catch { /* 다음 열기에서 다시 시도 */ }
    }
  }

  const todayItems = bellItems.filter(isTodayNotification);
  const unreadCount = todayItems.filter((n) => !n.acknowledged_at).length;

  return (
    <header className="top">
      <div className="top-l">
        {/* 로고는 첫 화면으로 돌아가는 자리다. 어디서든 빠져나올 구멍이
            하나는 있어야 한다.
            ⚠ **내가 갈 수 있는 과**로 보낸다. 첫 과로 고정하면 원무 계정이
              누를 때마다 권한 없는 병리과로 끌려간다 — 빠져나오는 구멍이
              오히려 가두는 구멍이 된다 */}
        <Link className="brand" to={deptPath(homeDept())}>
          <span className="mark" aria-hidden="true">◈</span>
          <b>{HOSPITAL} {PRODUCT}</b>
        </Link>

        {dept && (
          <>
            <span className="sep">/</span>
            {/* 갈 수 있는 과가 하나뿐이면 고를 것이 없다. 누를 수 있는
                것처럼 보이게 두지 않는다 */}
            {depts.length > 1 ? (
              <span className="deptpick" ref={box}>
                <button className="dept" aria-expanded={open} aria-haspopup="menu"
                        onClick={() => setOpen(!open)}>
                  {dept.name}<i aria-hidden="true">▾</i>
                </button>
                {open && (
                  <ul className="deptmenu" role="menu">
                    {depts.map((d) => (
                      <li key={d.key} role="none">
                        <Link role="menuitem" to={deptPath(d)}
                              className={d.key === dept.key ? "on" : undefined}
                              onClick={() => setOpen(false)}>
                          {d.name}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </span>
            ) : (
              <span className="dept flat">{dept.name}</span>
            )}
          </>
        )}
      </div>

      {screens.length > 0 && (
        <nav className="menu">
          {screens.map((s) => (
            <NavLink key={s.key || "_"} to={`${deptPath(dept)}${s.key ? `/${s.key}` : ""}`}
                     end={!s.key}
                     title={s.sub}
                     className={({ isActive }) => (isActive ? "on" : undefined)}>
              {s.menu}
            </NavLink>
          ))}
        </nav>
      )}

      <div className="top-r">
        <span className="bell-wrap" ref={bellBox}>
          <button className="bell" aria-label="내게 온 오늘 알림" title="내게 온 오늘 알림"
                  aria-expanded={bellOpen} aria-haspopup="dialog" onClick={toggleBell}>
            <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none"
                 stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 9a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8" />
              <path d="M10 21h4" />
            </svg>
            {unreadCount > 0 && <i>{unreadCount > 9 ? "9+" : unreadCount}</i>}
          </button>
          {bellOpen && (
            <section className="notice-pop" role="dialog" aria-label="내게 온 오늘 알림">
              <header><b>내게 온 오늘 알림</b><button onClick={() => setBellOpen(false)} aria-label="닫기">×</button></header>
              {bellLoading && <p className="notice-state">알림을 불러오는 중…</p>}
              {!bellLoading && bellError && <p className="notice-state bad">{bellError}</p>}
              {!bellLoading && !bellError && todayItems.length === 0 && (
                <p className="notice-state">오늘 온 알림이 없습니다.</p>
              )}
              {!bellLoading && !bellError && todayItems.length > 0 && (
                <ul>
                  {todayItems.map((item) => {
                    const id = item.notification_id ?? item.id;
                    const unread = !item.acknowledged_at;
                    return (
                      <li key={id}>
                        <button className={unread ? "new" : undefined} onClick={() => acknowledge(item)}>
                          <b>{item.message}</b>
                          <span>{notificationTime(item.sent_at ?? item.created_at)}</span>
                          {unread && <em>새 알림</em>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          )}
        </span>
        <span className="when">{now}</span>

        {/* 이름을 누르면 내 정보로 간다.
            ⚠ 로그인 정보가 없을 때는 **링크가 아니라 글자로 둔다** — 누를
              곳이 없는데 눌리면 빈 화면으로 보내게 된다 */}
        {me ? (
          <NavLink to={go.me()} className={({ isActive }) => `me${isActive ? " on" : ""}`}
                   title="내 정보">
            <span className="ava" aria-hidden="true">{me.name?.[0]}</span>
            <span className="me-tx">
              {/* ⚠ role 은 직책이 아니라 **역할 값**이다 — 진짜 서버는
                  "pathology" 같은 값을 준다(MeSerializer 의 role). 그대로
                  찍으면 「한지우 reception」이 된다. 한글 이름은 dept_name 이다 */}
              <b>{me.name} {me.dept_name}</b>
              {/* 보고 있는 과와 내 과가 다를 때만 적는다. 같으면 같은 말이
                  두 줄로 겹친다 */}
              {dept && dept.name !== me.dept_name && (
                <small>{dept.name} 보는 중</small>
              )}
            </span>
          </NavLink>
        ) : (
          <span className="me"><span className="me-tx"><b>—</b><small>로그인 정보 없음</small></span></span>
        )}
      </div>
    </header>
  );
}

function isTodayNotification(item) {
  const value = item.sent_at ?? item.created_at;
  if (!value) return false;
  const date = new Date(value);
  const today = new Date();
  return !Number.isNaN(date.getTime())
    && date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate();
}

function notificationTime(value) {
  if (!value) return "방금";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "오늘";
  return new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit" }).format(date);
}
