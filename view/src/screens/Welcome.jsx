import { useNavigate } from "react-router-dom";
import { markWelcomeSeen } from "../lib/seen";
import Logo from "../lib/Logo";
import Tilly from "../lib/Tilly";
import Icon from "../lib/Icon";

/* 00 · 소개 — 한 장이다.
 *
 * 전에는 세 장짜리 슬라이드였는데 **사람들이 다 건너뛴다**는 피드백을
 * 받았다. 당연한 일이다 — 아직 앱을 안 써 봤으니 「검사 결과를 쉬운 말로」가
 * 무슨 말인지 감이 없고, 감이 없는 설명은 읽을 이유가 없다.
 *
 * 그래서 여기서는 **이 앱이 무엇인지만** 말한다. 쓰는 법은 홈에 들어간 뒤
 * 그 자리에서 짚어 준다(lib/Coach).
 *
 * 건너뛰기 단추가 없다. 한 장이라 건너뛸 것이 없다.
 *
 * ── 배치 ─────────────────────────────────────────────────────
 * 위 · 가운데 · 아래 셋으로 나눈다.
 *
 *   위      로고(크게) + 서식 한 줄
 *   가운데  틸리. **남는 자리를 여기가 먹는다** — 폰이 길면 여백이
 *           틸리 둘레로 붙고, 짧으면 여기부터 줄어든다
 *   아래    시작하기 + 면책 한 줄
 *
 * 전에는 「할 수 있는 일」 세 줄이 가운데 있었는데 뺐다. 로고 · 서식 ·
 * 캐릭터 · 단추 넷으로 끝나는 편이 첫 화면답다 — 할 수 있는 일은
 * 들어간 뒤 홈에서 타일로 보인다.
 */
export default function Welcome() {
  const nav = useNavigate();

  function start() {
    markWelcomeSeen();
    nav("/login", { replace: true });
  }

  return (
    <div className="wel">
      {/* 위·가운데·아래 셋으로 나눈다. 가운데가 늘어나며 남는 자리를
          먹으므로, 폰이 길든 짧든 로고는 위쪽 · 단추는 아래쪽에 앉는다 */}
      <div className="wel-top">
        {/* ⚠ 받은 logo.svg 는 **E 마크 하나뿐**이다. 가이드의 첫 화면은
            그 아래 워드마크와 서식이 같이 서는 조합이라, 없는 두 줄을
            글자로 세운다. 워드마크가 들어간 SVG 가 오면 이 두 줄을
            지우고 그림 하나로 바꾸면 된다 */}
        <div className="lockup">
          <Logo size="xl" />
          <p className="lockup-nm">EMPATHO</p>
          <p className="lockup-sub">FOR A KINDER TOMORROW</p>
        </div>
        {/* 서식은 **명조**로 간다. 이 앱에서 명조는 안내문에만 쓰는
            글꼴이라 「읽는 글」의 결이 있다 — 브랜드 한 줄에 그 결을
            빌려 오면 고딕으로 쓴 것보다 차분하게 앉는다 */}
        <p className="wel-tag">공감이 만드는<br />더 건강한 내일</p>
      </div>

      <div className="wel-mid">
        <Tilly mood="hello" size="xl" alt="틸리가 인사하고 있어요" />
      </div>

      <div className="wel-foot">
        <button className="btn wel-cta" onClick={start}>
          <span>함께, 더 건강한 내일로</span>
          <b>시작하기 <Icon name="arrowRight" /></b>
        </button>
        <p className="note c">
          이 앱의 안내는 진단서가 아닙니다. 최종 판단은 진료 때 의료진이 합니다.
        </p>
      </div>
    </div>
  );
}
