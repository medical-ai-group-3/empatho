import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Head } from "../lib/Screen";
import Triri from "../lib/Triri";

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
const EGS = ["미세석회가 뭔가요?", "조직검사는 아픈가요?", "양성이면 괜찮은 건가요?"];

export default function Chat() {
  const [msgs, setMsgs] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

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
            {/* 트리리가 먼저 묻는다. 빈 화면에 「무엇을 물어야 하나」를
                사람이 혼자 고민하지 않게 하는 자리다 */}
            <div className="chat-tri">
              <Triri mood="ask" size="md" alt="" />
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
            <div className="chips">
              {EGS.map((e) => (
                <button key={e} className="chip" onClick={() => ask(e)}>
                  {e}
                </button>
              ))}
            </div>
          </>
        ) : (
          msgs.map((m, i) => (
            <div key={i} className={`bub ${m.who}${m.err ? " err" : ""}`}>
              <p>{m.text}</p>
              {m.note && <small>{m.note}</small>}
            </div>
          ))
        )}

        {busy && (
          <div className="bub bot wait" aria-live="polite">
            <Triri mood="checking" size="sm" alt="" />
            <p>답을 찾고 있습니다…</p>
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
