import { NavLink, useParams } from "react-router-dom";
import { HOSPITAL, PRODUCT, ROOT, findDept, screenPath } from "../nav";

/* 상단바 — 부서 안의 화면을 오가는 곳.
 *
 * 메뉴는 nav.js 의 표에서 만들어진다. 화면을 더해도 여기는 안 고친다.
 *
 * 왼쪽에 병원과 부서, 가운데에 그 부서의 화면들, 오른쪽에 알림 · 시각 ·
 * 로그인한 사람. **부서 이름이 왼쪽과 오른쪽에 두 번 나오지 않게** 했다 —
 * 와이어프레임에서 「원무과」와 「OO과」가 나란히 있어 어느 쪽이 무엇인지
 * 헷갈렸다. 왼쪽은 **지금 보는 화면의 부서**, 오른쪽은 **로그인한 사람**이고
 * 둘이 다를 수 있으므로, 오른쪽은 이름 아래 작게만 적는다.
 */
export default function Top({ now }) {
  const { dept } = useParams();
  const d = findDept(dept);

  return (
    <header className="top">
      <div className="top-l">
        <span className="mark" aria-hidden="true">◈</span>
        <b>{HOSPITAL} {PRODUCT}</b>
        {d && !d.bare && <><span className="sep">/</span><span className="dept">{d.name}</span></>}
      </div>

      {d && !d.bare && (
        <nav className="menu">
          {d.screens.map((s) => (
            <NavLink key={s.key || "_"} to={screenPath(d, s)}
                     end={!s.key}
                     className={({ isActive }) => (isActive ? "on" : undefined)}>
              {s.menu}
            </NavLink>
          ))}
        </nav>
      )}

      <div className="top-r">
        {/* 안 읽은 알림 — 숫자를 낸다. 업무 화면이라 «있다»보다
            «몇 건»이 쓸모 있다 */}
        <button className="bell" aria-label="알림 3건">
          <span aria-hidden="true">◍</span><i>3</i>
        </button>
        <span className="when">{now}</span>
        {d?.who && (
          <span className="me">
            <span className="ava" aria-hidden="true">{d.who.name[0]}</span>
            <span className="me-tx">
              <b>{d.who.name} {d.who.role}</b>
              <small>{d.name}</small>
            </span>
          </span>
        )}
        <NavLink className="out" to={ROOT} title="부서 고르기">⌂</NavLink>
      </div>
    </header>
  );
}
