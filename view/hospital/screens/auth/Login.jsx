import { useState } from "react";
import { apiInfo, login as doLogin } from "../../api";
import { Card } from "../../lib/Page";
import { HOSPITAL, PRODUCT } from "../../nav";
import { signIn } from "../../lib/session";

/* 직원 로그인
 * ────────────────────────────────────────────────────────────────
 *
 * 환자 앱과 계정 체계가 다르다. 같은 account 표를 쓰지만 토큰 스코프가
 * 갈린다 (백엔드 core/api/auth.py 의 scope_for). 그래서 화면도 따로 둔다.
 *
 * 여기서 하는 일은 **토큰을 받아 넣는 것까지**다. 누구인지와 권한(perms)은
 * 토큰이 들어간 뒤 Boot 의 useLoadMe() 가 GET /me 로 가져온다 — 두 가지를
 * 한 화면에서 다 하면, 로그인은 됐는데 권한만 못 받은 상태를 다룰 곳이
 * 없어진다.
 *
 * ── 실패를 뭉개지 않는다 ──────────────────────────────────────
 * 아이디가 틀렸는지 비밀번호가 틀렸는지는 **일부러 안 가른다.** 서버도 둘 다
 * UNAUTHENTICATED 로 같은 문구를 준다 — 가르면 어느 아이디가 있는지 밖에서
 * 알아낼 수 있다.
 *
 * 다만 **승인 대기와 비밀번호 오류는 다르다.** 승인 전 계정은 아무리 맞게
 * 쳐도 안 들어가는데, 그때 「아이디 또는 비밀번호가 올바르지 않습니다」만
 * 뜨면 사람이 비밀번호를 계속 다시 친다. 서버가 사정을 적어 보내면 그대로
 * 보여준다 (0012 의 account_status 가 그 자리다).
 */
export default function Login() {
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const ready = loginId.trim() && password && !busy;

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      /* 본문에는 access 하나만 온다. refresh 는 httpOnly 쿠키로 따로
         내려와서 JS 가 못 본다 — 받을 것이 없다 */
      const { access } = await doLogin(loginId.trim(), password);
      /* 토큰이 들어가면 Boot 가 다시 서면서 /me 를 부른다 */
      signIn({ access });
    } catch (e2) {
      setError(e2);
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <div className="login-box">
        <div className="login-mark">
          <span aria-hidden="true">◈</span>
          <b>{HOSPITAL} {PRODUCT}</b>
          <small>의료진용</small>
        </div>

        <Card>
          <form onSubmit={submit}>
            <label className="field">
              <span>아이디</span>
              <input value={loginId} onChange={(e) => setLoginId(e.target.value)}
                     autoComplete="username" autoFocus disabled={busy} />
            </label>

            <label className="field">
              <span>비밀번호</span>
              <input type="password" value={password}
                     onChange={(e) => setPassword(e.target.value)}
                     autoComplete="current-password" disabled={busy} />
            </label>

            {error && <Failed error={error} />}

            <button className="btn fill" type="submit" disabled={!ready}>
              {busy ? "확인하는 중…" : "로그인"}
            </button>
          </form>
        </Card>

        <p className="login-note">
          계정은 관리자가 만들고 승인합니다. 승인 전에는 로그인되지 않습니다.
        </p>

        {apiInfo.mock && (
          <p className="login-note mock">
            목업입니다 — 비밀번호는 아무거나 됩니다.
            아이디 앞머리로 과가 갈립니다 · path1 · rad1 · admin1 · rec1 · nur1 ·
            sur1 (pending… 으로 시작하면 승인 대기)
          </p>
        )}
      </div>
    </main>
  );
}

/* 실패 한 줄. code 와 trace_id 를 같이 낸다 —
   문구만 뜨면 백엔드에서 로그를 찾을 단서가 없다. */
function Failed({ error }) {
  return (
    <div className="login-err" role="alert">
      <b>{message(error)}</b>
      <small>
        {error.code}
        {error.traceId && <> · {error.traceId}</>}
      </small>
    </div>
  );
}

function message(error) {
  if (error.status === 0) return "서버에 연결하지 못했습니다.";
  /* 서버가 사정을 적어 보내면 그대로 쓴다 — 승인 대기 · 정지처럼
     비밀번호와 무관한 이유가 여기로 온다 */
  if (error.detail) return error.detail;
  return "아이디 또는 비밀번호가 올바르지 않습니다.";
}
