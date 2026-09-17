import { useState } from "react";
import { staffSignup } from "../../api";
import { HOSPITAL, PRODUCT, STAFF_DEPTS } from "../../nav";
import "../../styles/signup-ds.css";

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
 * 이 화면만 팀 공용 디자인 시스템(styles/tokens.css · themes.css ·
 * signup-ds.css)을 쓴다. 루트에 붙인 `ds-scope` 클래스 밖으로는 안
 * 새어나간다 — 로그인 등 다른 화면은 그대로 hospital.css 를 쓴다.
 */
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

  if (done) {
    return (
      <main className="login ds-scope">
        <div className="box">
          <div className="mark">
            <span className="dot" aria-hidden="true">◈</span>
            <h3>{HOSPITAL} {PRODUCT}</h3>
            <span className="text-caption">의료진용</span>
          </div>
          <div className="card">
            <p>{done}</p>
          </div>
          <button className="btn btn-ghost" type="button" onClick={onBack}>
            로그인으로
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="login ds-scope">
      <div className="box">
        <div className="mark">
          <span className="dot" aria-hidden="true">◈</span>
          <h3>{HOSPITAL} {PRODUCT}</h3>
          <span className="text-caption">의료진용</span>
        </div>

        <div className="card">
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "var(--spacing-16)" }}>
            <label className="field">
              <span>직원번호</span>
              <input className="input" value={f.staffNumber} onChange={set("staffNumber")}
                     placeholder="사내 직원 등록번호를 입력하세요." disabled={busy} />
            </label>

            <label className="field">
              <span>이름</span>
              <input className="input" value={f.name} onChange={set("name")}
                     autoComplete="name" disabled={busy} />
            </label>

            <label className="field">
              <span>아이디</span>
              <input className="input" value={f.loginId} onChange={set("loginId")}
                     autoComplete="username" autoCapitalize="off"
                     placeholder="로그인에 사용할 아이디" disabled={busy} />
            </label>

            <label className="field">
              <span>비밀번호</span>
              <input className="input" type="password" value={f.password} onChange={set("password")}
                     autoComplete="new-password" disabled={busy} />
              <em>여덟 자 이상</em>
            </label>

            <label className="field">
              <span>비밀번호 확인</span>
              <input className="input" type="password" value={f.password2} onChange={set("password2")}
                     autoComplete="new-password" disabled={busy} />
              {f.password2 && f.password !== f.password2 && <em>두 번 넣으신 값이 다릅니다</em>}
            </label>

            <label className="field">
              <span>부서</span>
              <select className="input" value={f.role} onChange={set("role")} disabled={busy}>
                <option value="">부서를 선택하세요.</option>
                {STAFF_DEPTS.map((d) => (
                  <option key={d.key} value={d.key}>{d.name}</option>
                ))}
              </select>
            </label>

            <label className="agree">
              <input type="checkbox" checked={agree}
                     onChange={(e) => setAgree(e.target.checked)}
                     disabled={busy} />
              <span>개인정보 수집 및 이용에 동의합니다. (필수)</span>
            </label>

            {error && <Failed error={error} />}

            <button className="btn btn-primary" type="submit" disabled={!ready || busy}>
              {busy ? "신청하는 중…" : "가입 신청"}
            </button>
          </form>
        </div>

        <p className="text-caption" style={{ textAlign: "center" }}>
          제출 후 관리자 승인이 있어야 로그인할 수 있습니다.
        </p>

        <button className="btn btn-ghost" type="button" onClick={onBack} disabled={busy}>
          로그인으로
        </button>
      </div>
    </main>
  );
}

/* 아이디·직원번호 중복 · 필드 검증 실패가 여기로 온다. VALIDATION_ERROR 면
   fields 에 칸별 사유가 실려 오지만, 지금은 한 줄로 뭉쳐 보여준다 —
   화면에 칸이 몇 안 돼 사람이 바로 알아본다. */
function Failed({ error }) {
  return (
    <div className="err" role="alert">
      <b>{error.detail || error.message}</b>
      <span>
        {error.code}
        {error.traceId && <> · {error.traceId}</>}
      </span>
    </div>
  );
}
