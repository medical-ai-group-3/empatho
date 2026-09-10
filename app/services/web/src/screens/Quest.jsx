import { useState } from "react";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";

/* 04 · 자가검진 문진
 *
 * 검사 **전에** 받아야 하는 것이라 홈에서도 맨 위에 있다. 조영제 알레르기 ·
 * 보형물 · 임신 여부처럼 촬영 방법을 바꾸는 답이 섞여 있어서, 검사실에서
 * 물어보는 것보다 미리 받아 두는 편이 낫다.
 *
 * **중간에 저장된다.** 다 못 채워도 답한 만큼 남는다 — 다섯 문항을 한 번에
 * 다 채워야만 저장된다면, 하나 막힐 때 앞의 넷까지 날아간다.
 *
 * 고른 것은 색만으로 말하지 않는다. 동그라미가 차는 모양이 같이 바뀐다 —
 * 색을 구분 못 하는 사람에게 색만 쓰면 아무 말도 안 한 것이 된다.
 */
export default function Quest() {
  const { loading, data, error, reload } = useApi(() => api.questionnaire());

  return (
    <>
      <Head title="자가검진 문진" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </>
  );
}

function Inner({ d }) {
  const sections = d.sections ?? [];

  // 서버가 준 답을 출발점으로 삼는다. 이후 편집은 여기서만 일어난다.
  const [ans, setAns] = useState(() =>
    Object.fromEntries(sections.map((s) => [s.id, s.answer ?? null])));
  const [saved, setSaved] = useState(() =>
    Object.fromEntries(sections.map((s) => [s.id, s.answer ?? null])));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);   // { ok, text }

  const answered = Object.values(ans).filter(Boolean).length;
  const total = d.total ?? sections.length;
  const pct = total ? Math.round((answered / total) * 100) : 0;

  // 아직 안 고른 것 중 «꼭 필요한» 것이 몇 개인가
  const leftCritical = sections.filter((s) => s.critical && !ans[s.id]).length;
  const dirty = sections.some((s) => ans[s.id] !== saved[s.id]);

  function pick(id, choice) {
    setAns((a) => ({ ...a, [id]: choice }));
    setMsg(null);
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.saveQuestionnaire({ answers: ans });
      setSaved(ans);
      setMsg({ ok: true, text: r.detail || "저장했습니다" });
    } catch (e) {
      setMsg({ ok: false, text: e.detail || e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <span className="k">작성 상태</span>
        <span className="v">{answered} / {total} 문항</span>
        <span className="prog"><i style={{ width: `${pct}%` }} /></span>
        <span className="s">
          {answered >= total
            ? "다 작성하셨습니다"
            : leftCritical > 0
              ? `꼭 답해야 하는 문항이 ${leftCritical}개 남았습니다`
              : `${total - answered}개 남았습니다`}
        </span>
      </div>

      {msg && (
        <div className={msg.ok ? "card accent" : "card flag"}>
          <span className="s">{msg.text}</span>
        </div>
      )}

      {sections.map((s) => (
        <div key={s.id} className="card">
          <div className="qhead">
            <span className="q">{s.question}</span>
            {s.critical && <span className="pill req">꼭 필요</span>}
          </div>
          {s.hint && <span className="s">{s.hint}</span>}

          {/* role=radiogroup — 하나만 고르는 묶음이라고 읽어 주는 기계에
              알려 준다. 안 그러면 단추 세 개가 따로 노는 것으로 읽힌다 */}
          <div className="opts" role="radiogroup" aria-label={s.question}>
            {s.choices.map((c) => {
              const on = ans[s.id] === c.id;
              return (
                <button key={c.id} type="button" role="radio" aria-checked={on}
                        className={on ? "opt on" : "opt"}
                        onClick={() => pick(s.id, c.id)}>
                  <i aria-hidden="true" />
                  {c.label}
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <button className="btn" disabled={!dirty || busy} onClick={save}>
        {busy ? "저장 중…" : dirty ? "저장하기" : "저장할 내용이 없습니다"}
      </button>

      <p className="note">
        답하신 내용은 진료와 검사에만 쓰입니다. 언제든 다시 고칠 수 있고,
        <b> 다 채우지 않아도 답한 만큼 저장됩니다.</b>
      </p>
    </>
  );
}
