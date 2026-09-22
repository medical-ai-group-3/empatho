import { useRef } from "react";
import { useNavigate } from "react-router-dom";
import { apiInfo, login as doLogin } from "../../api";
import { ROOT } from "../../nav";
import { signIn } from "../../lib/session";
import EmpathoLogin from "./EmpathoLogin";

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
 * ── 화면은 EmpathoLogin 이 그린다 ─────────────────────────────
 * 상자 모양과 문 열리는 전환은 그쪽 것이고, **안쪽 내용만 우리 것으로
 * 갈았다**(그 파일 머리 주석 참고). 이 파일은 인증만 맡는다.
 *
 * ⚠ **연출은 인증이 성공한 뒤에만 돈다.** `onAuthenticate` 가 throw 하면
 *   영상이 재생되지 않고 그 메시지가 상자 안에 그대로 뜬다.
 * ⚠ **`onEnter` 는 전환이 다 끝난 뒤**에 불린다. 거기서 옮겨야 문이
 *   열리다 만 채로 화면이 바뀌지 않는다.
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
export default function Login({ onSignup }) {
  const navigate = useNavigate();
  const got = useRef(null);

  async function authenticate({ loginId, password }) {
    try {
      /* 본문에는 access 하나만 온다. refresh 는 httpOnly 쿠키로 따로
         내려와서 JS 가 못 본다 — 받을 것이 없다 */
      const { access } = await doLogin(loginId, password);
      /* ⚠ **여기서 signIn 을 부르면 안 된다.** 토큰이 들어가는 순간 Boot
         가 다시 서면서 이 화면이 통째로 언마운트되고, 문이 열리기도 전에
         전환이 끊긴다(토큰은 들어갔는데 화면은 그대로인 상태가 된다).
         받아만 두고 전환이 끝난 뒤에 넣는다 */
      got.current = access;
    } catch (e) {
      /* 상자가 Error.message 를 그대로 띄운다. 내부 오류 코드·추적
         번호는 로그인 화면에 노출하지 않는다 — 해결이 되는 문구만 */
      throw new Error(message(e));
    }
  }

  return (
    <EmpathoLogin
      onAuthenticate={authenticate}
      /* 토큰이 들어가면 Boot 가 다시 서면서 /me 를 부른다. 로그아웃한
         위치가 /hospital/me 였더라도 그대로 복귀하지 않고, 루트의
         homeDept() 리다이렉트로 해당 계정의 대시보드를 연다 */
      onEnter={() => {
        /* 전환이 다 끝난 뒤다. 이제 토큰을 넣으면 Boot 가 /me 를
           부르고, 루트의 homeDept() 가 그 계정의 대시보드를 연다 */
        signIn({ access: got.current });
        navigate(ROOT, { replace: true });
      }}
      onSignup={onSignup}
      /* 배지는 목업일 때만 — 실서버에서 「목업」이 떠 있으면 안 된다 */
      showDemoBadge={apiInfo.mock}
    />
  );
}

function message(error) {
  if (error.status === 0) return "서버에 연결하지 못했습니다.";
  /* 서버가 사정을 적어 보내면 그대로 쓴다 — 승인 대기 · 정지처럼
     비밀번호와 무관한 이유가 여기로 온다 */
  if (error.detail) return error.detail;
  return "아이디 또는 비밀번호가 올바르지 않습니다.";
}
