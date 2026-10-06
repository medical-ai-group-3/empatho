import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import Logo from "../lib/Logo";

/* 01 · 로그인
 *
 * 앱을 열면 여기가 첫 화면이다. 아래 탭도 뒤로가기도 없다 — 아직 들어온
 * 것이 아니라서 돌아갈 곳이 없다.
 *
 * 실패를 뭉뚱그리지 않는다. 「아이디 또는 비밀번호가 다릅니다」는 맞지만,
 * 계정이 잠겼거나 서버가 죽은 것까지 그 문구로 덮으면 사람이 같은 것을
 * 열 번 다시 친다. 그래서 서버가 준 code · detail 을 그대로 보여준다.
 */
export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // 로그인 전에 가려던 곳. 없으면 홈이다.
  const back = loc.state?.from || "/";

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.login(id.trim(), pw);
      nav(back, { replace: true });
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="pane mid">
        <div className="brand">
          <Logo size="md" />
          <p className="tag">조기 발견이, 더 많은 내일을 만듭니다.</p>
        </div>

        {/* form 으로 감싸는 이유 — 휴대폰 자판의 «완료»와 엔터가 그냥 먹는다.
            div 로 두고 단추만 달면 자판에서 한 번 더 눌러야 한다 */}
        <form className="form" onSubmit={submit}>
          <label className="field">
            <span>아이디</span>
            <input
              value={id}
              onChange={(e) => setId(e.target.value)}
              autoComplete="username"
              autoCapitalize="off"
              placeholder="아이디"
              disabled={busy}
            />
          </label>

          <label className="field">
            <span>비밀번호</span>
            <input
              type="password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              autoComplete="current-password"
              disabled={busy}
              placeholder="비밀번호"
            />
          </label>

          {err && (
            <div className="card flag">
              <span className="k">{err.code || "오류"}</span>
              <span className="s">{err.detail || err.message}</span>
            </div>
          )}

          <button className="btn" type="submit" disabled={!id || !pw || busy}>
            {busy ? "확인 중…" : "로그인"}
          </button>
        </form>

        <p className="note c">
          처음이신가요?{" "}
          <Link className="lnk" to="/signup">
            가입하기
          </Link>
        </p>
      </div>

      <p className="note c foot-note">
        아이디나 비밀번호를 잊으셨다면 접수처에 문의해 주세요.
      </p>
    </>
  );
}
