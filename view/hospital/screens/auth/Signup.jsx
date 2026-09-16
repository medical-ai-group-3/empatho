import { useState } from "react";
import { staffSignup } from "../../api";
import { Card } from "../../lib/Page";
import { HOSPITAL, PRODUCT, STAFF_DEPTS } from "../../nav";

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
 * 휴대전화 인증은 화면을 옮기지 않는다. 「인증번호 받기」를 누르면
 * 그 아래에 인증번호 칸이 열린다 — 아이디 중복확인과 같은 자리에서
 * 끝나는 일이라 별도 단계로 화면을 넘길 이유가 없다.
 */
export default function Signup({ onBack }) {
  const [f, setF] = useState({
    employeeNo: "", name: "", loginId: "", password: "", password2: "",
    dept: "", phone: "", code: "",
  });
  const [agree, setAgree] = useState(false);

  const [idOk, setIdOk] = useState(null);
  const [verifyToken, setVerifyToken] = useState(null);
  const [codeSent, setCodeSent] = useState(false);

  const [busy, setBusy] = useState(null);   // 지금 도는 일의 이름
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);   // 접수 완료 후 서버 안내문

  const set = (k) => (e) => {
    setF((v) => ({ ...v, [k]: e.target.value }));
    if (k === "loginId") setIdOk(null);              // 고치면 확인이 무효다
    if (k === "phone") { setCodeSent(false); setVerifyToken(null); }
  };

  const ready =
    f.employeeNo.trim() && f.name.trim() && f.loginId.trim() &&
    f.password.length >= 8 && f.password === f.password2 &&
    f.dept && idOk?.available === true && verifyToken && agree;

  async function checkId() {
    if (f.loginId.length < 4) return;
    setBusy("checkId"); setError(null);
    try {
      setIdOk(await staffSignup.checkId(f.loginId));
    } catch (e) { setError(e); } finally { setBusy(null); }
  }

  async function sendCode(e) {
    e.preventDefault();
    setBusy("sendCode"); setError(null);
    try {
      await staffSignup.sendCode({ phone: f.phone });
      setCodeSent(true);
    } catch (e2) { setError(e2); } finally { setBusy(null); }
  }

  async function verifyCode(e) {
    e.preventDefault();
    setBusy("verifyCode"); setError(null);
    try {
      const r = await staffSignup.verifyCode({ phone: f.phone, code: f.code });
      setVerifyToken(r.verify_token);
    } catch (e2) { setError(e2); } finally { setBusy(null); }
  }

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy("submit"); setError(null);
    try {
      const r = await staffSignup.submit({
        employee_no: f.employeeNo.trim(),
        name: f.name.trim(),
        login_id: f.loginId.trim(),
        password: f.password,
        dept: f.dept,
        phone: f.phone,
        verify_token: verifyToken,
        agree_privacy: agree,
      });
      setDone(r?.detail || "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.");
    } catch (e2) { setError(e2); } finally { setBusy(null); }
  }

  if (done) {
    return (
      <main className="login">
        <div className="login-box">
          <div className="login-mark">
            <span aria-hidden="true">◈</span>
            <b>{HOSPITAL} {PRODUCT}</b>
            <small>의료진용</small>
          </div>
          <Card>
            <p className="note">{done}</p>
          </Card>
          <button className="btn line" type="button" onClick={onBack}>
            로그인으로
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="login">
      <div className="login-box wide">
        <div className="login-mark">
          <span aria-hidden="true">◈</span>
          <b>{HOSPITAL} {PRODUCT}</b>
          <small>의료진용</small>
        </div>

        <Card>
          <form onSubmit={submit}>
            <label className="field">
              <span>직원번호</span>
              <input value={f.employeeNo} onChange={set("employeeNo")}
                     placeholder="사내 직원 등록번호를 입력하세요." disabled={busy === "submit"} />
            </label>

            <label className="field">
              <span>이름</span>
              <input value={f.name} onChange={set("name")}
                     autoComplete="name" disabled={busy === "submit"} />
            </label>

            <div className="field">
              <span>아이디</span>
              <div className="pair">
                <input value={f.loginId} onChange={set("loginId")}
                       autoComplete="username" autoCapitalize="off"
                       placeholder="로그인에 사용할 아이디" disabled={busy === "submit"} />
                <button className="btn line" type="button"
                        disabled={f.loginId.length < 4 || busy === "checkId"}
                        onClick={checkId}>
                  중복 확인
                </button>
              </div>
              {idOk && (
                <em>{idOk.available ? idOk.detail : "이미 쓰이고 있는 아이디입니다"}</em>
              )}
            </div>

            <label className="field">
              <span>비밀번호</span>
              <input type="password" value={f.password} onChange={set("password")}
                     autoComplete="new-password" disabled={busy === "submit"} />
              <em>여덟 자 이상</em>
            </label>

            <label className="field">
              <span>비밀번호 확인</span>
              <input type="password" value={f.password2} onChange={set("password2")}
                     autoComplete="new-password" disabled={busy === "submit"} />
              {f.password2 && f.password !== f.password2 && <em>두 번 넣으신 값이 다릅니다</em>}
            </label>

            <label className="field">
              <span>부서</span>
              <select value={f.dept} onChange={set("dept")} disabled={busy === "submit"}>
                <option value="">부서를 선택하세요.</option>
                {STAFF_DEPTS.map((d) => (
                  <option key={d.key} value={d.key}>{d.name}</option>
                ))}
              </select>
            </label>

            <div className="field">
              <span>휴대전화 본인인증</span>
              <div className="pair">
                <input value={f.phone} onChange={set("phone")}
                       inputMode="tel" autoComplete="tel"
                       placeholder="휴대전화 번호를 입력하세요." disabled={busy === "submit" || !!verifyToken} />
                <button className="btn line" type="button"
                        disabled={f.phone.length < 10 || busy === "sendCode" || !!verifyToken}
                        onClick={sendCode}>
                  인증번호 받기
                </button>
              </div>
              <em>인증 성공 여부만 저장되며 전화번호는 별도 보관하지 않습니다.</em>

              {codeSent && !verifyToken && (
                <div className="pair">
                  <input value={f.code} onChange={set("code")}
                         inputMode="numeric" maxLength={6}
                         autoComplete="one-time-code" placeholder="인증번호 6자리"
                         disabled={busy === "verifyCode"} />
                  <button className="btn line" type="button"
                          disabled={f.code.length < 4 || busy === "verifyCode"}
                          onClick={verifyCode}>
                    확인
                  </button>
                </div>
              )}
              {verifyToken && <em>휴대전화 인증이 완료되었습니다.</em>}
            </div>

            <ul className="checks">
              <li>
                <label>
                  <input type="checkbox" checked={agree}
                         onChange={(e) => setAgree(e.target.checked)}
                         disabled={busy === "submit"} />
                  <span>개인정보 수집 및 이용에 동의합니다. (필수)</span>
                </label>
              </li>
            </ul>

            {error && <Failed error={error} />}

            <button className="btn fill" type="submit" disabled={!ready || busy === "submit"}>
              {busy === "submit" ? "신청하는 중…" : "가입 신청"}
            </button>
          </form>
        </Card>

        <p className="login-note">
          제출 후 관리자 승인이 있어야 로그인할 수 있습니다.
        </p>

        <button className="btn ghost" type="button" onClick={onBack} disabled={busy === "submit"}>
          로그인으로
        </button>
      </div>
    </main>
  );
}

function Failed({ error }) {
  return (
    <div className="login-err" role="alert">
      <b>{error.detail || error.message}</b>
      <small>
        {error.code}
        {error.traceId && <> · {error.traceId}</>}
      </small>
    </div>
  );
}
