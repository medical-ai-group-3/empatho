import { NavLink, Outlet, useLocation } from "react-router-dom";
import Tilly from "./lib/Tilly";
import Icon from "./lib/Icon";

/* 로그인한 뒤의 껍데기 — 아래 탭은 여기 한 곳에만 있다.
 *
 * 전에는 「로그인 · 회원가입에서는 감춘다」는 목록을 들고 있었는데,
 * 이제 그 두 화면은 이 껍데기를 아예 안 쓴다(Bare 를 쓴다). 화면 이름을
 * 목록으로 관리하면 새 화면을 더할 때마다 그 목록을 손봐야 하고,
 * 잊으면 로그인 화면에 탭이 뜬다. */
/* ⚠ **챗봇이 탭에서 빠졌다.** 대신 오른쪽 아래 동그란 단추로 떠 있다.
 *
 * 브랜드 가이드의 아래 탭이 넷인데(홈·상담·일정·마이페이지) 그대로 옮기면
 * **「결과」가 갈 곳이 없다.** 검사 결과를 받아 보는 것이 이 앱의 본래
 * 목적이라 그 자리를 뺄 수 없었다.
 *
 * 그래서 챗봇을 띄웠다. 결과를 챗봇에 합치는 길도 있었지만 **그건 안 된다** —
 * 챗봇은 회원님의 검사 결과를 보지 않는 것이 규칙이고(screens/Chat 참고),
 * 한자리에 두면 거기서 들은 말을 진료 결과로 알아듣는다. 둘은 섞으면
 * 안 되는 것이다.
 *
 * 떠 있는 자리가 챗봇에 더 맞기도 하다 — 「지금 보는 화면에 대해 물어본다」는
 * 쓰임이라 늘 손에 닿는 곳에 있는 편이 낫다. */
const TABS = [
  { to: "/",        ic: "home",     label: "홈"     },
  { to: "/results", ic: "results",  label: "결과"   },
  { to: "/book",    ic: "calendar", label: "예약"   },
  { to: "/me",      ic: "user",     label: "내 정보" },
];

export default function App() {
  return (
    <div className="app">
      <div className="screens"><Outlet /></div>
      <ChatFab />
      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/"}
            className={({ isActive }) => (isActive ? "on" : undefined)}
            /* 코치마크가 짚을 자리. 클래스로 찾으면 디자인을 고칠 때
               조용히 끊긴다 */
            data-coach={`tab-${t.to.replace("/", "") || "home"}`}
          >
            <Icon className="ic" name={t.ic} />
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

/* 떠 있는 챗봇 단추.
 *
 * 아래 탭 **위에** 얹는다. 탭과 겹치지 않게 자리는 index.css 가 잡는다.
 *
 * ⚠ 챗봇 화면에서는 안 그린다 — 이미 거기 있는데 또 부르는 단추가 있으면
 *   눌러도 아무 데도 안 가서 고장으로 읽힌다. */
function ChatFab() {
  const { pathname } = useLocation();
  if (pathname === "/chat") return null;

  return (
    <NavLink className="chatfab" to="/chat" data-coach="chatbot"
             aria-label="안내 챗봇에게 묻기" title="안내 챗봇에게 묻기">
      {/* **원에 가두지 않는다.** 틸리의 제 윤곽선 그대로 떠 있다.
          동그라미로 오려 내면 스티커를 붙인 것처럼 보이고, 틸리가
          단추 «안에» 갇힌다.

          ⚠ 얼굴만 따로 떠내지 못했다 — 이 캐릭터는 머리와 몸통이 한
            덩어리라 목에서 자르면 잘린 단면이 그대로 보인다. 그래서
            **완성된 실루엣**을 쓴다. 머리만 있는 그림이 따로 오면
            mood 만 바꾸면 된다.

          글자를 빼도 되는 이유는 틸리가 이 앱에서 유일한 얼굴이라서다.
          눈으로 못 보는 사람에게는 aria-label 이 대신 말한다 */}
      <Tilly mood="chatbot" size="fab" alt="" />
    </NavLink>
  );
}

/* 탭 없는 껍데기 — 로그인 · 본인 확인이 쓴다. */
export function Bare() {
  return (
    <div className="app">
      <div className="screens"><Outlet /></div>
    </div>
  );
}
