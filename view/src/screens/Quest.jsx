import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Choices from "../lib/Choices";
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
 * 문항 하나를 그리는 일은 lib/Choices 가 한다. 예약 신청도 같은 부품을
 * 쓰므로, 물음이 화면마다 다르게 생기지 않는다.
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
  const nav = useNavigate();
  const sections = d.sections ?? [];

  // 서버가 준 답을 출발점으로 삼는다. 이후 편집은 여기서만 일어난다.
  const [ans, setAns] = useState(() =>
    Object.fromEntries(sections.map((s) => [s.id, s.answer ?? null])));
  const [saved, setSaved] = useState(() =>
    Object.fromEntries(sections.map((s) => [s.id, s.answer ?? null])));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);   // { ok, text }
  const [leaving, setLeaving] = useState(false);

  /* 저장하면 홈으로 돌아간다. 여기 머물 이유가 없다 — 볼일이 끝났다.
     다만 곧바로 나가면 「저장했습니다」를 아무도 못 본다. 잠깐 보여주고
     나간다. 홈의 문진 카드가 늘어난 것이 진짜 확인이다. */
  useEffect(() => {
    if (!leaving) return;
    const t = setTimeout(() => nav("/", { replace: true }), 700);
    return () => clearTimeout(t);
  }, [leaving, nav]);

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
      const r = await api.saveQuestionnaire(ans);
      setSaved(ans);
      setMsg({ ok: true, text: r.detail || "저장했습니다" });
      setLeaving(true);
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
        <Choices key={s.id} q={s} value={ans[s.id]} disabled={busy}
                 onPick={(c) => pick(s.id, c)} />
      ))}

      <button className="btn" disabled={!dirty || busy || leaving} onClick={save}>
        {leaving ? "돌아가는 중…"
                 : busy ? "저장 중…"
                 : dirty ? "저장하기" : "저장할 내용이 없습니다"}
      </button>

      <p className="note">
        답하신 내용은 진료와 검사에만 쓰입니다. 언제든 다시 고칠 수 있고,
        <b> 다 채우지 않아도 답한 만큼 저장됩니다.</b>
      </p>
    </>
  );
}
