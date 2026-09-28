import { useState } from "react";
import { staffSignup } from "../../api";
import { HOSPITAL, PRODUCT, STAFF_DEPTS } from "../../nav";
import "./EmpathoLogin.css";
import "./Signup.css";

/* 직원 회원가입 — 신청 → 관리자 승인 구조
 * ────────────────────────────────────────────────────────────────
 *
 * 로그인 화면(Login.jsx)에 이미 적혀 있는 규칙 그대로다 — 「계정은
 * 관리자가 만들고 승인합니다. 제출 후 관리자 승인이 있어야 로그인할
 * 수 있습니다.」 그래서 여기서 하는 일은 **신청을 접수하는 것까지**다.
 * 제출이 성공해도 토큰이 오지 않는다 — 승인 전이라 로그인 자체가
 * 안 되기 때문이다. 환자 가입(src/screens/Signup.jsx)처럼 끝나자마자
 * 로그인 상태로 들어가는 것과 다른 지점이다.
 *
 * ⚠ 휴대전화 인증 없음. Account 모델에 phone 컬럼 자체가 없고
 *   (phone_verified 만 미리 파 둔 빈 컬럼), signup_staff 요청 본문에도
 *   전화번호 필드가 없다 — 2026-09-16 백엔드 확인. 나중에 흐름이
 *   생기면 그때 이 화면에 다시 붙인다.
 *
 * 아이디·직원번호 중복은 서버가 제출 시점에 같이 본다. 별도 중복확인
 * API 가 없어서, 여기서는 형식만 확인하고 겹치면 서버가 주는
 * VALIDATION_ERROR 를 그대로 보여준다.
 *
 * ── 디자인 ──────────────────────────────────────────────────────
 * 로그인(EmpathoLogin)과 한 흐름으로 읽히도록 **같은 무대를 빌려 쓴다**
 * — 로비 사진 배경 · 오른쪽 어두운 유리 패널 · 브랜드 머리 · 입력칸 ·
 * 흰 제출 버튼이 모두 EmpathoLogin.css 의 `.empatho-scene` 규칙이다.
 * 가입에만 있는 것(두 단 칸 배치 · 부서 선택 · 동의 · 긴 패널 스크롤)은
 * Signup.css 가 `.empatho-scene.signup-scene` 아래에서만 더한다.
 * 영상은 틀지 않는다 — 문이 열리는 전환은 로그인 성공에만 있다.
 */
const POSTER = "/empatho/door-poster.jpg";

export default function Signup({ onBack }) {
  const [f, setF] = useState({
    staffNumber: "", name: "", loginId: "", password: "", password2: "",
    role: "",
  });
  const [agree, setAgree] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);   // 접수 완료 후 서버 안내문

  const set = (k) => (e) => setF((v) => ({ ...v, [k]: e.target.value }));

  const ready =
    f.staffNumber.trim() && f.name.trim() && f.loginId.trim() &&
    f.password.length >= 8 && f.password === f.password2 &&
    f.role && agree;

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true); setError(null);
    try {
      const r = await staffSignup.submit({
        staff_number: f.staffNumber.trim(),
        full_name: f.name.trim(),
        login_id: f.loginId.trim(),
        password: f.password,
        role: f.role,
      });
      setDone(r?.detail || "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.");
    } catch (e2) { setError(e2); } finally { setBusy(false); }
  }

  const mismatch = f.password2 && f.password !== f.password2;

  return (
    <main className="empatho-scene signup-scene">
      <div className="stage" aria-hidden="true">
        <img className="plate" src={POSTER} alt="" />
      </div>

      <section className="panel" aria-labelledby="signup-brand">
        <div className="panel__inner">
          <header className="brand">
            <h1 className="brand__mark" id="signup-brand">
              <span className="brand__hospital">{HOSPITAL}</span>{PRODUCT}
            </h1>
            <p className="brand__tag">의료진용</p>
          </header>

          {done ? (
            <div className="su-done" role="status">
              <h2 className="su-title">신청을 받았습니다</h2>
              <p className="su-lead">{done}</p>
              <button className="submit" type="button" onClick={onBack}>
                <span className="submit__label">로그인으로 돌아가기</span>
                <Arrow />
              </button>
            </div>
          ) : (
            <>
              <div className="su-head">
                <h2 className="su-title">회원가입 신청</h2>
                <p className="su-lead">
                  제출 후 관리자 승인이 있어야 로그인할 수 있습니다.
                </p>
              </div>

              <form className="form su-form" onSubmit={submit}>
                <div className="su-grid">
                  <div className="field">
                    <label htmlFor="su-staff">직원번호</label>
                    <div className="control">
                      <input id="su-staff" value={f.staffNumber} onChange={set("staffNumber")}
                             placeholder="사내 직원 등록번호" disabled={busy} />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="su-name">이름</label>
                    <div className="control">
                      <input id="su-name" value={f.name} onChange={set("name")}
                             autoComplete="name" placeholder="실명" disabled={busy} />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="su-role">부서</label>
                    <div className="control">
                      <select id="su-role" value={f.role} onChange={set("role")} disabled={busy}
                              data-empty={f.role ? undefined : "true"}>
                        <option value="">부서를 선택하세요.</option>
                        {STAFF_DEPTS.map((d) => (
                          <option key={d.key} value={d.key}>{d.name}</option>
                        ))}
                      </select>
                      <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="m7 10 5 5 5-5" />
                      </svg>
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="su-login">아이디</label>
                    <div className="control">
                      <input id="su-login" value={f.loginId} onChange={set("loginId")}
                             autoComplete="username" autoCapitalize="off"
                             placeholder="로그인에 사용할 아이디" disabled={busy} />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="su-pw">비밀번호</label>
                    <div className="control">
                      <input id="su-pw" type="password" value={f.password} onChange={set("password")}
                             autoComplete="new-password" placeholder="비밀번호"
                             aria-describedby="su-pw-hint" disabled={busy} />
                    </div>
                    <p className="su-hint" id="su-pw-hint">8자 이상</p>
                  </div>

                  <div className="field">
                    <label htmlFor="su-pw2">비밀번호 확인</label>
                    <div className="control">
                      <input id="su-pw2" type="password" value={f.password2} onChange={set("password2")}
                             autoComplete="new-password" placeholder="비밀번호 다시 입력"
                             aria-invalid={mismatch ? "true" : undefined}
                             aria-describedby={mismatch ? "su-pw2-hint" : undefined}
                             disabled={busy} />
                    </div>
                    {mismatch && (
                      <p className="su-hint su-hint--bad" id="su-pw2-hint">
                        비밀번호가 일치하지 않습니다.
                      </p>
                    )}
                  </div>
                </div>

                <label className="check su-agree">
                  <input type="checkbox" checked={agree}
                         onChange={(e) => setAgree(e.target.checked)}
                         disabled={busy} />
                  <span className="box" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
                  </span>
                  <span>개인정보 수집 및 이용에 동의합니다. (필수)</span>
                </label>

                {error && <Failed error={error} />}

                <button className="submit" type="submit" disabled={!ready || busy}>
                  <span className="submit__label">{busy ? "신청하는 중…" : "가입 신청"}</span>
                  <Arrow />
                </button>
              </form>

              <div className="row su-back">
                <a
                  className="link" href="#login"
                  onClick={(event) => { event.preventDefault(); if (!busy) onBack(); }}
                  aria-disabled={busy || undefined}
                >
                  <svg className="su-back__arrow" viewBox="0 0 24 24" aria-hidden="true">
                    <line x1="20" y1="12" x2="5" y2="12" /><path d="m11 6-6 6 6 6" />
                  </svg>
                  로그인으로 돌아가기
                </a>
              </div>
            </>
          )}
        </div>
      </section>
    </main>
  );
}

function Arrow() {
  return (
    <svg className="submit__arrow" viewBox="0 0 24 24" aria-hidden="true">
      <line x1="4" y1="12" x2="19" y2="12" /><path d="m13 6 6 6-6 6" />
    </svg>
  );
}

/* 아이디·직원번호 중복 · 필드 검증 실패가 여기로 온다. VALIDATION_ERROR 면
   fields 에 칸별 사유가 실려 오지만, 지금은 한 줄로 뭉쳐 보여준다 —
   화면에 칸이 몇 안 돼 사람이 바로 알아본다. */
function Failed({ error }) {
  return (
    <div className="su-err" role="alert">
      <b>{error.detail || error.message}</b>
      <span>
        {error.code}
        {error.traceId && <> · {error.traceId}</>}
      </span>
    </div>
  );
}
