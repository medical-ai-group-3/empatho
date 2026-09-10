/* 문항 하나 — 물음과 «하나만 고르는» 선택지.
 *
 * 문진 화면과 예약 신청이 **같은 부품을 쓴다.** 두 벌로 두면 한쪽만 고쳐져서
 * 같은 질문이 화면마다 다르게 생기고, 접근성 속성도 한쪽에만 붙는다.
 *
 * 고른 것을 색으로만 말하지 않는다. 왼쪽 동그라미가 «차는» 모양이 같이
 * 바뀐다 — 색을 구분 못 하는 사람에게 색만 쓰면 아무 말도 안 한 것이 된다.
 */
export default function Choices({ q, value, onPick, disabled }) {
  return (
    <div className="card">
      <div className="qhead">
        <span className="q">{q.question}</span>
        {q.critical && <span className="pill req">꼭 필요</span>}
      </div>
      {q.hint && <span className="s">{q.hint}</span>}

      {/* role=radiogroup — 하나만 고르는 묶음이라고 읽어 주는 기계에
          알려 준다. 안 그러면 단추 셋이 따로 노는 것으로 읽힌다 */}
      <div className="opts" role="radiogroup" aria-label={q.question}>
        {q.choices.map((c) => {
          const on = value === c.id;
          return (
            <button key={c.id} type="button" role="radio" aria-checked={on}
                    className={on ? "opt on" : "opt"} disabled={disabled}
                    onClick={() => onPick(c.id)}>
              <i aria-hidden="true" />
              {c.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
