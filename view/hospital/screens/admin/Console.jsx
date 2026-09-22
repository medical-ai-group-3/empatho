import { useState } from "react";
import { adminSession, apiInfo } from "../../api";
import { Page, Card, Btn } from "../../lib/Page";
import { Warn } from "../../lib/Parts";
import { useMe } from "../../lib/useMe";

/* 관리자 — Django admin 으로 넘어가는 자리
 * ════════════════════════════════════════════════════════════════
 *
 * 관리자 화면은 우리가 짓지 않는다. Django admin 을 쓴다.
 * 여기가 하는 일은 하나뿐이다 — **로그인을 두 번 하지 않게 해 주는 것.**
 *
 *   [관리자 화면 열기]
 *     → POST /admin-session   서버가 role 을 보고 auth_user 세션을 심는다
 *     → 새 탭으로 /admin/
 *
 * Django admin 의 인증 주체는 auth_user 이고 우리 API 의 주체는 account 라
 * 서로 모른다. 그 사이를 서버가 잇는다.
 *
 * ── 새 탭을 «먼저» 여는 이유 ────────────────────────────────────
 * 브라우저는 클릭에서 바로 이어진 window.open 만 허용한다. await 뒤에 열면
 * 클릭과 끊긴 것으로 보여 **팝업 차단에 걸린다.** 그래서 클릭하자마자 빈 탭을
 * 열어 두고, 세션이 생기면 그 탭의 주소를 /admin/ 으로 바꾼다.
 *
 * 빈 탭으로 여는 것이지 /admin/ 으로 먼저 여는 것이 아니다. 먼저 /admin/ 을
 * 열면 세션이 아직 없어서 Django 로그인 화면이 뜨는데, cdss_admin 의
 * 비밀번호는 아무도 모르므로 거기서 막힌다.
 */
export default function Console() {
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  /* 팝업이 막혔을 때 손으로 누를 주소. 그냥 「열지 못했습니다」로 끝내면
     세션은 이미 생겼는데 갈 곳이 없다 */
  const [manual, setManual] = useState(null);

  async function open() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setManual(null);

    /* ① 클릭과 이어진 자리에서 빈 탭을 먼저 연다 (위 주석 참고)
       ⚠ **noopener 를 주면 안 된다.** 그 옵션은 새 탭과의 연결을 끊는 것이
         목적이라 window.open 이 늘 null 을 돌려준다 — 탭은 열리는데 주소를
         바꿀 손잡이가 없다. 우리 주소(/admin/)를 여는 것이라 끊을 이유도 없다 */
    const tab = window.open("", "_blank");

    try {
      const { admin_url: url } = await adminSession();
      if (tab) {
        tab.location.href = url;
      } else {
        setManual(url);          // 차단됐다. 주소를 손에 쥐여 준다
      }
    } catch (e) {
      tab?.close();              // 열어 둔 빈 탭을 남기지 않는다
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page
      crumb={["관리자"]}
      title="관리자"
    >
      <Card title="관리자 화면">
        <p className="note">
          {me?.name ? <b>{me.name}</b> : null} 님으로 들어갑니다.
          다시 로그인하지 않아도 됩니다.
        </p>

        <div className="save-b">
          <Btn kind="fill" onClick={open} disabled={busy}>
            {busy ? "여는 중…" : "관리자 화면 열기"}
          </Btn>
        </div>

        {manual && (
          <div className="slot" role="status">
            <b>새 탭이 열리지 않았습니다</b>
            <span>브라우저가 팝업을 막은 것 같습니다. 세션은 만들어졌으니 아래로 들어가세요.</span>
            <Btn onClick={() => { window.location.href = manual; }}>
              관리자 화면으로 이동
            </Btn>
          </div>
        )}

        {error && <Failed error={error} />}

        {/* Django admin 은 목업으로 흉내 낼 수 없다 — 진짜 화면이고 세션
            쿠키로 돈다. 목업 모드에서는 /admin 을 로컬 Django 로 넘긴다
            (vite.config.js). 안 띄워 뒀으면 새 탭이 연결 오류를 보여 준다 */}
        {apiInfo.mock && (
          <Warn>
            지금은 목업으로 도는 중입니다. 관리자 화면은 흉내 낼 수 없어
            <b> 로컬 Django</b> 로 넘깁니다 — 안 띄워 두셨으면 새 탭이 연결
            오류를 보여 줍니다. <code>python manage.py runserver 8000</code>
          </Warn>
        )}
      </Card>

      <Card title="관리자 화면에서 하는 일">
        <ul className="bullets">
          <li>
            <b>계정 승인</b> — 직원이 가입하면 <code>pending</code> 으로 서고
            로그인이 막힙니다. 여기서 승인해야 들어옵니다.
          </li>
          <li><b>권한 부여</b> — 역할 기본 권한 위에 사람별로 더 얹습니다.</li>
          <li><b>자료 조회</b> — 환자 · 검사 · 판독 · 리포트를 표로 봅니다.</li>
        </ul>

        {/* 이 한계는 숨기지 않는다. 「누가 고쳤나」를 admin 이력으로 찾으려다
            못 찾고 나서 알게 되면 그때는 이미 늦다 */}
        <Warn>
          관리자 화면의 변경 이력은 관리자가 여럿이어도 <b>한 계정으로 남습니다.</b>
          누가 고쳤는지는 가려지지 않습니다. 계정 승인 이력만은 따로 남습니다.
        </Warn>
      </Card>
    </Page>
  );
}

function Failed({ error }) {
  return (
    <div className="slot bad" role="alert">
      <b>{error.detail || error.message}</b>
      <span>{error.code}{error.traceId && <> · {error.traceId}</>}</span>
    </div>
  );
}
