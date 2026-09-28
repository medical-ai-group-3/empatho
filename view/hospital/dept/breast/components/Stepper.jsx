import { Btn } from "../../../lib/Page";

/* 진료 단계 줄 — flow.js 가 센 단계를 그린다. 대기 환자 · 환자 상세 ·
 * 치료 방침 · 안내 팝업 · 전체 환자가 같은 줄을 쓴다.
 *
 *   ✓ 끝남   ● 지금   … 남(영상 · 병리)이 하는 중   ○ 아직   – 해당 없음
 *
 * ⚠ **색으로 뜻을 나르지 않는다**(tokens.css). 지금 단계만 cyan 테두리,
 *   끝난 것은 채움, 나머지는 글자와 기호로 가른다.
 * col — 세로 줄(오른쪽 320px 레일). 기본은 가로 한 줄이고 좁으면 접힌다. */
const MARK = { done: "✓", now: "●", wait: "…", todo: "○", skip: "–", opt: "○" };
const SAY = { done: "끝남", now: "지금", wait: "진행 중", todo: "아직", skip: "해당 없음", opt: "선택" };

export default function Stepper({ steps, col = false }) {
  return (
    <ol className={`bf-steps${col ? " col" : ""}`} aria-label="진료 단계">
      {steps.map((s) => (
        <li key={s.key} className={`bf-step ${s.state}`}
            aria-current={s.state === "now" ? "step" : undefined}
            title={`${s.label} — ${SAY[s.state] ?? ""}`}>
          <i aria-hidden="true">{MARK[s.state] ?? "○"}</i>
          <b>{s.label}</b>
          <small>{s.note ?? SAY[s.state]}</small>
        </li>
      ))}
    </ol>
  );
}

/* 단계 줄 + 다음 할 일 한 칸. 주 단추는 **하나뿐이다** — 다음 할 일.
 * run(next) 가 팝업(act) · 이동(to)을 부르는 쪽 사정대로 처리한다.
 * extra — 주 단추 옆에 붙는 보조 단추들(흐름 순서대로 넘겨준다). */
export function FlowBar({ flow, run, extra = null, col = false, button = true }) {
  const next = flow?.next;
  if (!flow) return null;
  /* button=false — 주 단추를 부르는 쪽 단추 줄이 들고 있을 때(대기 환자) */
  const can = button && next && (next.to || next.act);
  return (
    <section className={`bf-flow${col ? " col" : ""}`}>
      <Stepper steps={flow.steps} col={col} />
      <div className="bf-next">
        <span className="bf-next-k">다음 할 일</span>
        <b>{next?.label ?? "—"}</b>
        {next?.why && <p>{next.why}</p>}
        <span className="home-fill" />
        {extra}
        {can
          ? next.to && !next.act
            ? <Btn kind="fill" to={next.to}>{next.label} →</Btn>
            : <Btn kind="fill" onClick={() => run?.(next)}>{next.label}</Btn>
          : null}
      </div>
    </section>
  );
}
