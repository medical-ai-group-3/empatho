import { Link } from "react-router-dom";

/* 쪽 머리 — 빵부스러기 · 제목 · 배지 · 한 줄 설명.
 *
 * 화면마다 손으로 그리지 않는다. 같은 자리에 같은 크기로 있어야 사람이
 * 「지금 어디인가」를 매번 다시 찾지 않는다.
 *
 * **배지는 상태를 글자로 말한다.** 색을 따로 만들지 않는 것이 이 판의
 * 규칙이라(tokens.css), 배지도 soot 채움이나 외곽선으로만 가른다.
 */
export function Page({ crumb, title, badge, sub, right, children }) {
  return (
    <main className="page">
      {crumb?.length > 0 && (
        <nav className="crumb" aria-label="현재 위치">
          {crumb.map((c, i) => (
            <span key={i}>
              {i > 0 && <i aria-hidden="true">›</i>}
              {c}
            </span>
          ))}
        </nav>
      )}

      <div className="phead">
        <div className="phead-l">
          <h1>
            {title}
            {badge && <span className="badge">{badge}</span>}
          </h1>
          {sub && <p className="sub">{sub}</p>}
        </div>
        {right && <div className="phead-r">{right}</div>}
      </div>

      {children}
    </main>
  );
}

/* 카드 하나. 제목이 있으면 머리에 얹는다 */
export function Card({ title, right, pad = true, className = "", children }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="card-h">
          {title && <h2>{title}</h2>}
          {right && <div className="card-h-r">{right}</div>}
        </div>
      )}
      <div className={pad ? "card-b" : "card-b flush"}>{children}</div>
    </section>
  );
}

export function Btn({ kind = "line", to, children, ...rest }) {
  const cls = `btn ${kind}`;
  return to
    ? <Link className={cls} to={to} {...rest}>{children}</Link>
    : <button className={cls} {...rest}>{children}</button>;
}
