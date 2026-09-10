import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Head } from "../lib/Screen";

/* 12 · 안내 챗봇
 *
 * 안내문에 모르는 말이 나왔을 때 묻는 자리다. 「미세석회」가 무엇인지
 * 같은 것 말이다.
 *
 * ── 무엇을 하지 않는지가 먼저다 ───────────────────────────────
 * 이 챗봇은 **회원님의 검사 결과를 보지 않는다.** 낱말의 뜻을 풀어 줄
 * 뿐이고, 「제 결과는 어떤가요」에는 답할 수 없다. 그 경계가 흐리면
 * 환자가 여기서 들은 말을 진료 결과로 알아듣는다.
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
            <div className="card">
              <span className="k">묻기 전에</span>
              <span className="s">
                안내문에 나온 <b>낱말의 뜻</b>을 풀어 드립니다.
                회원님의 검사 결과는 보지 않으므로,
                결과에 대한 질문은 담당 주치의에게 문의해 주세요.
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
            <p>답을 찾고 있습니다…</p>
          </div>
        )}

        {/* 스크롤이 따라 내려갈 바닥 자리 */}
        <div ref={endRef} />
      </div>

      {/* form 으로 감싼다 — 휴대폰 자판의 «완료»와 엔터가 그냥 먹는다 */}
      <form className="askbar" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <div className="askrow">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="모르는 말을 물어보세요"
            aria-label="질문"
            disabled={busy}
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
