import { useNavigate } from "react-router-dom";
import { HOSPITAL } from "../brand";
import { markWelcomeSeen } from "../lib/seen";
import Logo from "../lib/Logo";
import Tilly from "../lib/Tilly";

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
 * ── 한 문단을 세 줄로 폈다 ────────────────────────────────────
 * 「검사 결과를 쉬운 말로 받아 보고, 방문을 신청하고, 문진을 미리
 * 작성하실 수 있습니다」는 한 줄로 읽으면 **셋이라는 것이 안 보인다.**
 * 그리고 화면의 반 넘게가 빈 채로 남았다.
 *
 * 말을 늘린 것이 아니다. 같은 말을 셋으로 끊어 자리를 차지하게 했다.
 * 앞의 기호는 아래 탭에서 쓰는 것과 **같은 것**이라, 홈에 들어간 뒤
 * 그 탭을 찾을 때 눈이 한 번 본 모양을 따라간다.
 */
const CAN = [
  { ic: "▤", tx: "검사 결과를 쉬운 말로 받아 보기" },
  { ic: "▦", tx: "방문할 날짜 신청하기" },
  { ic: "✓", tx: "문진 미리 작성해 두기" },
];

export default function Welcome() {
  const nav = useNavigate();

  function start() {
    markWelcomeSeen();
    nav("/login", { replace: true });
  }

  return (
    <div className="wel">
      <div className="wel-body">
        <Logo size="lg" />
        <Tilly mood="hello" size="lg" alt="틸리가 인사하고 있어요" />
        <div className="wel-tx">
          <h2>{HOSPITAL} 환자용 앱</h2>
          <p>진료와 검사에 관한 일을 여기에서 하실 수 있습니다.</p>
        </div>

        <ul className="wel-list">
          {CAN.map((c) => (
            <li key={c.tx}>
              <i className="ic" aria-hidden="true">{c.ic}</i>
              {c.tx}
            </li>
          ))}
        </ul>
      </div>

      <div className="wel-foot">
        <button className="btn" onClick={start}>시작하기</button>
        <p className="note c">
          이 앱의 안내는 진단서가 아닙니다. 최종 판단은 진료 때 의료진이 합니다.
        </p>
      </div>
    </div>
  );
}
