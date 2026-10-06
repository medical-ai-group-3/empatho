import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Head } from "../lib/Screen";
import Tilly from "../lib/Tilly";
import Icon from "../lib/Icon";

/* 12 · 안내 챗봇
 *
 * 안내문에 모르는 말이 나왔을 때 묻는 자리다. 「미세석회」가 무엇인지
 * 같은 것 말이다.
 *
 * ── 무엇에 답하는가 ───────────────────────────────────────────
 * 두 가지이고, 서버가 둘을 구분해서 답한다.
 *
 *   낱말의 뜻   "미세석회가 뭔가요"   일반적인 설명을 해 준다
 *   내 결과     "제 결과는 어떤가요"  **열려 있는** 검사 결과에 적힌 것만
 *
 * ⚠ 「열려 있는」이 핵심이다. 담당 의사가 대면 설명을 마친 리포트만
 *   재료로 쓴다(서버가 explained_at 으로 판정한다). 설명 전에는 결과를
 *   아예 안 보고 낱말 뜻만 답한다 — 환자가 의사보다 먼저 챗봇에서 자기
 *   결과를 읽는 일을 막는 자리다.
 *
 * ⚠ 결과를 재료로 쓴다고 해서 **진단을 하지는 않는다.** 병명·치료·예후는
 *   규칙으로 막고, 규칙을 어긴 답은 서버가 통째로 버리고 고정 문구로
 *   되돌린다. 그래도 완전하지 않다 — 그래서 이 답을 리포트 본문과 같은
 *   자리에, 같은 모양으로 그리면 안 된다.
 *
 * (2026-09-17 이전에는 결과를 아예 안 보는 낱말 전용 봇이었다. 서버가
 *  붙으면서 범위가 늘었고, 그때 이 안내문이 사실과 어긋나 있었다.)
 *
 * 그래서 경계를 **세 번** 말한다.
 *   · 첫 화면의 안내 카드 — 묻기 전에 읽는다
 *   · 답마다 서버가 함께 주는 disclaimer
 *   · 입력칸 아래 한 줄 — 물을 때마다 눈에 들어온다
 *
 * 많아 보이지만 셋 다 다른 순간에 읽힌다. 의료 화면에서 이 경계는
 * 두 번 말해서 손해 볼 것이 없다.
 *
 * ── 대화가 남지 않는다 ────────────────────────────────────────
 * 서버가 stored:false 로 답한다. 화면을 나가면 사라진다는 뜻이라,
 * 그 사실을 아래에 적어 둔다 — 「아까 물어본 것」을 찾으러 다시 들어올
 * 사람이 헛걸음하지 않게.
 *
 * 저장하지 않는 편이 맞다. 환자가 병에 대해 물어본 기록은 그 자체가
 * 민감한 자료다.
 */

/* 무엇을 물어야 할지 모르는 사람을 위한 예시. 안내문에 실제로 나오는
   말에서 골랐다 — 챗봇이 답할 수 있는 것을 물어보게 해야 첫인상이
   「모르겠습니다」가 되지 않는다. */
/* 처음 열었을 때 내미는 네 줄.
 *
 * ⚠ **생김새가 같다고 다 질문인 것은 아니다.** 「다음 일정 확인하기」는
 *   물어볼 말이 아니라 **예약 화면으로 가는 길**이다. 질문으로 보내면
 *   챗봇이 「무슨 말인지 모르겠다」고 답한다.
 *
 *   ask   그대로 물어본다
 *   go    그 화면으로 간다
 *
 * ⚠ 전에 있던 「궁금한 걸 자유롭게 물어보기」(type)는 뺐다. 하는 일이
 *   입력칸에 커서를 두는 것 하나뿐인데, 그 입력칸은 아래에 늘 보이고
 *   「모르는 말을 물어보세요」라고 이미 적혀 있다. 줄 하나를 거기 쓰느니
 *   답할 수 있는 것을 하나 더 보여 주는 편이 낫다.
 *
 *   무엇보다 **「자유롭게」가 사실과 다르다.** 이 봇은 낱말 뜻과, 설명이
 *   끝난 결과의 범위 안만 답한다. 치료·수술·예후는 규칙으로 막혀 있다.
 *   바로 위 안내 카드가 그 경계를 말하는데 그 아래 줄이 「자유롭게」라고
 *   하면 카드를 무르는 셈이다.
 *
 * ── 2026-09-18 문구를 바꿨다 ─────────────────────────────────
 *
 * 전에는 브랜드 가이드의 시안 문구를 그대로 썼다. 그런데 **봇이 답할 수
 * 없는 것을 권하고 있었다.**
 *
 *   "치료 방법이 궁금해요"   서버가 **영구히** 거절한다. 시스템 규칙 3 이
 *                            「치료 방법·수술·예후·생존율을 말하지 않는다」
 *                            이고, 치료·예후 낱말은 alwaysRisky 로 따로
 *                            막혀 있다 (gosvc 의 internal/chat). 목업이
 *                            얇아서가 아니라 **설계가 그렇다.**
 *   "검사 정보가 궁금해요"   너무 넓어서 무엇을 묻는지 알 수 없다.
 *
 * 누르면 반드시 「답을 드리기 어렵습니다」가 나오는 단추를 첫 화면에
 * 놓아 두고 있었던 셈이다. 바로 아래 주석에 스스로 적어 둔 것과 어긋난다 —
 * 「챗봇이 답할 수 있는 것을 물어보게 해야 첫인상이 모르겠습니다가 되지
 * 않는다」.
 *
 * 그래서 **안내문에 실제로 나오는 낱말**로 바꾼다. 봇의 본업이 그것이고,
 * 목업도 실서버도 답한다.
 */
const EGS = [
  { kind: "ask",  icon: "chat_microcalcification.png", tx: "미세석회가 뭔가요?" },
  { kind: "ask",  icon: "chat_biopsy.png", tx: "조직검사는 어떻게 하나요?" },
  { kind: "ask",  icon: "chat_benign.png", tx: "양성이라는 게 무슨 뜻인가요?" },
  { kind: "go",   icon: "chat_schedule.png", tx: "다음 일정 확인하기", to: "/book" },
];

/* 답을 못 드렸을 때 대신 내미는 것 — B.
 *
 * 거절만 하고 끝내면 막다른 길이다. 사람은 「그럼 뭘 물으라는 거지」에서
 * 멈추고 창을 닫는다. **물을 수 있는 것을 그 자리에서 보여 준다.**
 *
 * 위 EGS 와 따로 두는 이유 — 여기서는 «가는 길»이나 «입력칸»이 아니라
 * 물어볼 말만 내민다. 이미 한 번 물어본 사람이라 그 둘은 필요 없다. */
const RETRY_EGS = [
  "미세석회가 뭔가요?",
  "조직검사는 어떻게 하나요?",
  "양성이라는 게 무슨 뜻인가요?",
  "유방촬영과 초음파는 뭐가 다른가요?",
];

/* 이 답이 «못 드리겠습니다» 인가 — B 의 판별부.
 *
 * ⚠ **서버가 표시를 안 준다.** 응답이 { answer, disclaimer, stored } 뿐이라
 *   (core/api/chat.py) 되돌린 답인지 아닌지 알 방법이 문구밖에 없다.
 *   플래그를 하나 달아 달라고 요청해 두었다 — 오면 이 함수를 지운다.
 *
 * 그때까지는 앞머리로 본다. **틀려도 안 깨진다** — 못 알아보면 제안이
 * 안 붙을 뿐이고, 엉뚱하게 붙어도 물어볼 말이 하나 더 보이는 것뿐이다.
 * 그래서 넓게 잡지 않고 실제로 쓰는 두 문구만 적어 둔다.
 */
const REFUSALS = [
  "그 부분은 이 검사 결과만으로는",   // gosvc 의 chat.Fallback
  "죄송합니다. 그 질문에는",          // 목업 기본 answer
];
const isRefusal = (t) => REFUSALS.some((r) => (t ?? "").startsWith(r));

export default function Chat() {
  const [msgs, setMsgs] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const nav = useNavigate();

  /* 제안 한 줄을 눌렀을 때. 무엇을 하는 줄인지는 EGS 가 들고 있다 */
  function pick(e) {
    if (e.kind === "go") return nav(e.to);
    ask(e.tx);
  }

  /* 새 말이 붙으면 아래로 따라 내려간다. 안 그러면 답이 왔는데
     화면은 그대로라 «안 왔다»고 읽는다 */
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [msgs, busy]);

  async function ask(text) {
    const question = text.trim();
    if (!question || busy) return;

    setQ("");
    setMsgs((m) => [...m, { who: "me", text: question }]);
    setBusy(true);
    try {
      const r = await api.chat(question);
      setMsgs((m) => [...m, {
        who: "bot", text: r.answer, note: r.disclaimer,
        /* 못 드린 답이면 물을 수 있는 것을 같이 내민다. 거절만 하고
           끝내면 「그럼 뭘 물으라는 거지」에서 멈춘다 */
        retry: isRefusal(r.answer),
      }]);
    } catch (e) {
      // 오류도 대화 안에 둔다. 위에 빨간 띠를 띄우면 무엇에 대한
      // 오류인지 모른다 — 방금 물은 것 바로 아래여야 안다
      setMsgs((m) => [...m, {
        who: "bot", err: true,
        text: e.detail || e.message || "답을 가져오지 못했습니다.",
      }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Head title="안내 챗봇" />

      <div className="pane chat">
        {msgs.length === 0 ? (
          <>
            {/* 틸리가 먼저 묻는다. 빈 화면에 「무엇을 물어야 하나」를
                사람이 혼자 고민하지 않게 하는 자리다 */}
            <div className="chat-tri">
              <Tilly mood="chatbotBanner" size="banner" alt="" />
            </div>

            <div className="card">
              <span className="k">묻기 전에</span>
              <span className="s">
                안내문에 나온 <b>낱말의 뜻</b>을 풀어 드리고,
                담당 의사의 설명이 끝난 검사 결과에 대해서는
                <b>결과에 적힌 범위 안에서</b> 안내해 드립니다.
                진단과 치료는 담당 주치의가 정합니다.
              </span>
            </div>

            <p className="sec">이런 것을 물어보실 수 있습니다</p>
            <div className="asks">
              {EGS.map((e) => (
                <button key={e.tx} className="askrow" onClick={() => pick(e)}>
                  <img className="ask-image" src={`/tilly/${e.icon}`} alt="" aria-hidden="true" />
                  <span>{e.tx}</span>
                  <Icon className="arw" name="chevronRight" />
                </button>
              ))}
            </div>
          </>
        ) : (
          msgs.map((m, i) => (
            /* 답에는 틸리 얼굴이 붙는다 — 누가 한 말인지 자리(왼오)에 더해
               얼굴로도 보인다. 내 말에는 안 붙인다 */
            <div key={i} className={`bub ${m.who}${m.err ? " err" : ""}`}>
              {m.who === "bot" && <Tilly mood="chatbotProfile" size="profile" alt="" />}
              <span className="bub-b">
                <p>{m.text}</p>
                {m.note && <small>{m.note}</small>}

                {/* 막다른 길을 만들지 않는다 — 대신 물을 수 있는 것.
                    마지막 답에만 붙인다. 위로 스크롤했을 때 옛 제안이
                    줄줄이 남아 있으면 지금 눌러야 할 것이 어느 것인지
                    헷갈린다 */}
                {m.retry && i === msgs.length - 1 && (
                  <span className="retry">
                    <small className="retry-k">이런 것은 답해 드릴 수 있어요</small>
                    {RETRY_EGS.map((t) => (
                      <button key={t} type="button" className="retry-b"
                              onClick={() => ask(t)} disabled={busy}>
                        {t}
                      </button>
                    ))}
                  </span>
                )}
              </span>
            </div>
          ))
        )}

        {busy && (
          <div className="bub bot wait" aria-live="polite">
            <Tilly mood="loading" size="chip" alt="" />
            <span className="bub-b"><p>답을 찾고 있습니다…</p></span>
          </div>
        )}

        {/* 스크롤이 따라 내려갈 바닥 자리 */}
        <div ref={endRef} />
      </div>

      {/* form 으로 감싼다 — 휴대폰 자판의 «완료»와 엔터가 그냥 먹는다 */}
      <form className="askbar" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <div className="askrow">
          {/* 답을 기다리는 동안에도 칸은 살아 있다. 잠가 두면 자판이
              내려가고 커서가 빠져서, 다음 질문을 치려면 한 번 더
              눌러야 한다. 두 번 보내지는 것은 ask() 가 막는다 */}
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="모르는 말을 물어보세요"
            aria-label="질문"
          />
          <button className="btn narrow" type="submit" disabled={!q.trim() || busy}>
            보내기
          </button>
        </div>
        <p className="note c">
          이 대화는 저장되지 않습니다. 진단이 아니며, 최종 판단은 진료 때
          의료진이 합니다.
        </p>
      </form>
    </>
  );
}
