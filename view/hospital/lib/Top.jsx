import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { DEPTS, HOSPITAL, HOME, PRODUCT, deptPath, go, menuScreens } from "../nav";
import { can } from "../perm";
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
/* 내가 들어갈 수 있는 과 — 화면이 하나라도 열리면 그 과는 보인다.
   권한이 하나도 없는 과는 아예 안 띄운다. 눌러 봐야 빈 화면이다 */
function myDepts() {
  return DEPTS.filter((d) => d.screens.some((s) => can(s.need)));
}

export default function Top({ dept, now }) {
  const me = useMe();
  const screens = dept ? menuScreens(dept).filter((s) => can(s.need)) : [];

  /* ── 과 전환 ────────────────────────────────────────────────
     이게 없으면 한 과에 들어간 뒤로는 주소를 직접 치지 않는 한 다른 과로
     못 간다. 상단 메뉴는 «지금 과의 화면 다섯 장»만 만들기 때문이다. */
  const depts = myDepts();
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  /* 바깥을 누르거나 Esc 로 닫는다. 열어 둔 채 다른 곳을 누르면
     닫히는 게 당연해서, 안 닫히면 고장으로 본다 */
  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <header className="top">
      <div className="top-l">
        {/* 로고는 첫 화면으로 돌아가는 자리다. 어디서든 빠져나올 구멍이
            하나는 있어야 한다 */}
        <Link className="brand" to={deptPath(HOME)}>
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
        <button className="bell" aria-label="알림 3건">
          <span aria-hidden="true">◍</span><i>3</i>
        </button>
        <span className="when">{now}</span>

        {/* 이름을 누르면 내 정보로 간다.
            ⚠ 로그인 정보가 없을 때는 **링크가 아니라 글자로 둔다** — 누를
              곳이 없는데 눌리면 빈 화면으로 보내게 된다 */}
        {me ? (
          <NavLink to={go.me()} className={({ isActive }) => `me${isActive ? " on" : ""}`}
                   title="내 정보">
            <span className="ava" aria-hidden="true">{me.name?.[0]}</span>
            <span className="me-tx">
              <b>{me.name} {me.role}</b>
              <small>{me.dept_name ?? dept?.name}</small>
            </span>
          </NavLink>
        ) : (
          <span className="me"><span className="me-tx"><b>—</b><small>로그인 정보 없음</small></span></span>
        )}
      </div>
    </header>
  );
}
