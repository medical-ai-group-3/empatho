import { useState } from "react";

/* 틸리 — 앱의 건강 파트너 캐릭터
 * ════════════════════════════════════════════════════════════════
 *
 * 파일은 `public/tilly/`의 표정 PNG(로더는 GIF)를 본다. **없으면 아무것도 안 그린다** —
 * 빌드가 깨지지 않고, 파일을 넣는 순간 나타난다 (lib/Logo 와 같은 방식).
 *
 * public/ 에 두는 이유 — import 로 끌어오면 파일이 없을 때 빌드가 통째로
 * 실패한다. 그림 하나 때문에 앱이 안 뜨면 안 된다.
 *
 * ── 넣을 파일 ────────────────────────────────────────────────
 *
 *   public/tilly/hello.png      안녕하세요!            인사 · 홈 머리
 *   public/tilly/wait.png       조금만 기다려주세요!    불러오는 중
 *   public/tilly/ask.png        궁금한 게 있으세요?     챗봇 첫 화면
 *   public/tilly/checking.png   확인해볼게요!          챗봇이 답 찾는 중
 *   public/tilly/done.png       도움이 되었길 바라요!   답을 마친 뒤
 *   public/tilly/bye.png        또 만나요!             로그아웃
 *   public/tilly/face.png       얼굴만                 떠 있는 상담 단추
 *   public/tilly/alarm.png      알람                   알림이 없을 때
 *   public/tilly/rest.png       기대기                 목록이 비었을 때
 *   public/tilly/guide.png      안내 팻말              (아직 안 쓴다)
 *   public/tilly/tilly_loading_spinner.gif  동그라미 로더  불러오는 중
 *
 * 투명 PNG/GIF 로, 화면 배율이 다양하니 **찍힐 크기의 3배**로 주면 안전하다
 * (홈 머리의 틸리가 56px 이면 168px 짜리).
 *
 * ── 어디에 쓰고 어디에 안 쓰나 ───────────────────────────────
 *
 * ⚠ **검사 결과 · 안내문 화면에는 넣지 않는다.** 「도움이 되었길 바라요!」
 *   같은 표정이 악성 소견 옆에 뜨면 안 된다. 그 화면에서 캐릭터는 위로가
 *   아니라 실례가 된다.
 *
 *   쓰는 곳    스플래시 · 소개 · 홈 인사 · 챗봇 · 빈 화면
 *   안 쓰는 곳 검사 결과 · 안내문 · 오류 · 경고
 *
 * 이 규칙은 코드로 강제하지 않는다 — 부르는 쪽이 지킨다. 다만 새 화면에
 * 넣기 전에 이 주석을 한 번 읽기를 바란다.
 */

const FILE = {
  loading: "tilly_loading_spinner.gif",
  hello: "tily_hello.png",
  alarm: "tily_alarm.png",
  rest: "tily_rest.png",
  chatbot: "tilly_chatbot.png",
  chatbotBanner: "tily_chatbot_baner.png",
  chatbotProfile: "tily_chatbot_profile.png",
  hi: "tily_hi.png",
};

/* 표정 이름 → 읽어 주는 기계에 들려줄 말.
 * 장식이 아니라 «지금 무슨 상태인가»를 같이 지는 그림이라, 눈으로 못 보는
 * 사람에게도 그 뜻이 가야 한다. 다만 옆에 같은 말이 글로 있으면 부르는
 * 쪽이 alt="" 로 꺼서 두 번 읽히지 않게 한다. */
const SAY = {
  hello: "틸리가 인사하고 있어요",
  wait: "틸리가 기다리고 있어요",
  ask: "틸리가 궁금한 것을 묻고 있어요",
  checking: "틸리가 찾아보고 있어요",
  done: "틸리가 웃고 있어요",
  bye: "틸리가 손을 흔들고 있어요",
  face: "틸리",
  alarm: "틸리가 종을 들고 있어요",
  rest: "틸리가 쉬고 있어요",
  guide: "틸리가 안내 팻말을 들고 있어요",
  loading: "틸리가 불러오는 중이에요",
  chatbot: "안내 챗봇 틸리",
  chatbotBanner: "안내 챗봇 틸리",
  chatbotProfile: "안내 챗봇 틸리",
  hi: "틸리가 인사하고 있어요",
};

/** 틸리 한 마리.
 *
 *  mood  위 표정 이름 (기본 hello)
 *  size  sm | md | lg — 실제 크기는 tokens.css 의 --tilly-* 가 정한다
 *  alt   읽어 주는 기계에 들려줄 말. 옆에 같은 말이 글로 있으면 "" 를 준다
 */
export default function Tilly({ mood = "hello", size = "md", alt }) {
  const [failed, setFailed] = useState(false);

  /* 그림이 없으면 **자리를 비운다.** 회색 네모나 «이미지 없음» 아이콘을
     대신 두면 고장 난 것처럼 보인다 — 없는 것은 없는 대로 두는 편이 낫다 */
  if (failed) return null;

  return (
    <img
      className={`tilly ${size}`}
      src={`/tilly/${FILE[mood] ?? `${mood}.png`}`}
      alt={alt ?? SAY[mood] ?? ""}
      aria-hidden={alt === "" ? "true" : undefined}
      draggable={false}
      onError={() => setFailed(true)}
    />
  );
}
