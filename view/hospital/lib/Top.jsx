import { NavLink } from "react-router-dom";
import { HOSPITAL, PRODUCT, deptPath, menuScreens } from "../nav";
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
export default function Top({ dept, now }) {
  const me = useMe();
  const screens = dept ? menuScreens(dept).filter((s) => can(s.need)) : [];

  return (
    <header className="top">
      <div className="top-l">
        <span className="mark" aria-hidden="true">◈</span>
        <b>{HOSPITAL} {PRODUCT}</b>
        {dept && <><span className="sep">/</span><span className="dept">{dept.name}</span></>}
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

        {me ? (
          <span className="me">
            <span className="ava" aria-hidden="true">{me.name?.[0]}</span>
            <span className="me-tx">
              <b>{me.name} {me.role}</b>
              <small>{me.dept_name ?? dept?.name}</small>
            </span>
          </span>
        ) : (
          <span className="me"><span className="me-tx"><b>—</b><small>로그인 정보 없음</small></span></span>
        )}
      </div>
    </header>
  );
}
