import { Link } from "react-router-dom";
import PatientBar from "./PatientBar";

/* 쪽 머리 — 빵부스러기 · 제목 · 배지.
 *
 * 화면마다 손으로 그리지 않는다. 같은 자리에 같은 크기로 있어야 사람이
 * 「지금 어디인가」를 매번 다시 찾지 않는다.
 *
 * ⚠ **설명 줄(sub)이 없다.** 「환자를 찾아 접수하면 간호 큐로 넘어갑니다」
 *   같은 문장은 처음 한 번 읽고 나면 하루에 수백 번 자리만 먹는다.
 *   화면에 남기는 설명은 둘뿐이다 — 되돌릴 수 없다는 경고, 안 눌리는
 *   이유(권한·조건). 어디 있는지는 빵부스러기가 말한다.
 *
 * back 을 주면 제목 왼쪽에 뒤로 단추가 붙는다. 함수로 받는다 — 위 참고.
 *
 * **배지는 상태를 글자로 말한다.** 색을 따로 만들지 않는 것이 이 판의
 * 규칙이라(tokens.css), 배지도 soot 채움이나 외곽선으로만 가른다.
 *
 * ── 환자 띠 ──────────────────────────────────────────────────
 * patient 를 주면 **쪽 머리보다 위**, 상단바 바로 아래에 띠가 붙는다.
 * 환자 한 명을 다루는 화면은 지금 누구를 보고 있는지 한 번도 헷갈리면
 * 안 된다.
 *
 * ⚠ **main 바깥이다.** 안에 두면 쪽 여백만큼 들어가 띠가 화면 폭을 못
 *   채우고, 붙박이(sticky)가 쪽 안쪽 기준으로 잡힌다.
 *
 * ⚠ **has-pbar 가 높이를 알린다.** 띠가 세로를 먹으므로 뷰포트를 꽉
 *   채우는 자리(판독 뷰어 · 세 단 격자)가 그만큼 덜 가져가야 한다.
 *   그 계산은 --fit-bar 하나로 모아 두었다(hospital.css).
 */
export function Page({ crumb, title, badge, right, back, patient,
                       className = "", children }) {
  return (
    <>
      {patient && <PatientBar patient={patient} />}
      {/* className 은 과별 스타일을 가두는 자리다 — 유방외과가 "breast" 로
          열고, dept/breast/breast.css 의 규칙이 그 안에서만 산다.
          안 가두면 card · btn · split 처럼 이름이 겹치는 규칙이 병리·영상
          화면까지 건드린다 */}
    <main className={`page ${className}${patient ? " has-pbar" : ""}`.trim()}>
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
        {/* 뒤로 — **함수로 받는다.** 브라우저 히스토리(-1)로 돌아가면
            「끝냈으니 다음 환자로」 같은 화면별 사정을 못 싣는다.
            어디로 갈지는 부르는 쪽이 정한다 (유방외과 화면들이 쓴다).
            목록처럼 더 갈 위가 없는 화면은 back 을 안 준다 */}
        {back && (
          <button className="phead-back" onClick={back} aria-label="뒤로">‹</button>
        )}
        <div className="phead-l">
          <h1>
            {title}
            {badge && <span className="badge">{badge}</span>}
          </h1>
        </div>
        {right && <div className="phead-r">{right}</div>}
      </div>

      {children}
    </main>
    </>
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
