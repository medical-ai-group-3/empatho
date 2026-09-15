import { Chip } from "./Parts";

/* AI 소견 패널 — **문구 규격이 코드로 들어간 자리.**
 *
 * 판독 화면 셋(영상 · 병리 · 유방외과)이 같이 쓴다. 화면마다 따로 그리면
 * 어느 하나가 「정상」이라고 쓰게 된다. 그래서 상태 가르기를 여기 한 곳에
 * 가둔다.
 *
 * ── 지켜야 하는 것 ───────────────────────────────────────────
 *   ① **검출 0건을 「정상」으로 쓰지 않는다.** 검출기가 놓친 병변은 이
 *      화면에 안 나타난다. 0건은 «못 찾았다»이지 «없다»가 아니다
 *   ② **못 찾은 것과 못 본 것을 가른다.** 모델이 보고 0건인 것과 모델을
 *      못 올린 것은 다른 화면이어야 한다. 같은 문구로 덮으면 「AI 가
 *      확인했다」로 잘못 읽힌다
 *   ③ **못 채운 항목을 빈칸으로 두지 않는다.** 빈칸은 «확인했는데
 *      문제없음»으로 읽힌다. 사유를 그대로 띄운다
 *   ④ **수치를 화면에 박지 않는다.** 민감도는 모델 쪽 disclaimer 에
 *      들어 있고 작동점이 바뀌면 같이 바뀐다. 받은 문자열을 그대로 쓴다
 *
 * ── 쓰는 법 ──────────────────────────────────────────────────
 *   <AiPanel r={소켓응답} onFalsePositive={...} onLocate={...} />
 *   응답이 없으면(아직 안 돌았으면) r 을 안 넘기면 된다.
 */

/* 화면에 내지 않는 값. 규격의 「금지 표현」이 여기 대응한다.
 *   score        검출기 점수이지 확률이 아니다
 *   malignancy_p 화면 비노출로 정해진 값 */
const HIDE = new Set(["score", "malignancy_p"]);

export default function AiPanel({ r, busy, onLocate, onFalsePositive }) {
  /* ① 아직 안 돌았다 */
  if (!r && busy) {
    return <Wrap state="분석 중"><p className="ai-note">AI 분석이 진행 중입니다.</p></Wrap>;
  }
  if (!r) {
    return <Wrap state="대기"><p className="ai-note">아직 분석하지 않았습니다.</p></Wrap>;
  }

  /* ② 모델을 못 올렸다 — 「못 찾았다」와 다른 화면이어야 한다 */
  if (r.summary?.abstain_reason === "load_failed") {
    return (
      <Wrap state="불러오지 못함">
        <p className="ai-big">AI 소견을 불러오지 못했습니다</p>
        <p className="ai-note">
          판독에는 영향이 없습니다. 잠시 후 다시 시도하거나 그대로 판독하십시오.
        </p>
      </Wrap>
    );
  }

  /* ③ 모델이 보고 0건 — **여기에 「정상」이라고 쓰지 말 것** */
  if (r.summary?.abstained) {
    return (
      <Wrap state="검출 없음">
        <p className="ai-big">AI 가 표시할 병변을 찾지 못했습니다</p>
        <p className="ai-note">
          판정이 아닙니다. 찾지 못한 병변은 이 화면에 나타나지 않습니다.
        </p>
        {r.disclaimer && <p className="ai-fine">{r.disclaimer}</p>}
        <Limits limits={r.limitations} />
      </Wrap>
    );
  }

  /* ④ 검출이 있다 */
  const sum = r.summary ?? {};
  return (
    <Wrap state="완료">
      {r.metrics?.length > 0 && (
        <dl className="ai-kv">
          {r.metrics.filter((m) => !HIDE.has(m.key)).map((m) => (
            <div key={m.key}>
              <dt>{m.label}</dt>
              <dd>{m.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {sum.max_birads && (
        <dl className="ai-kv">
          <div>
            {/* 「BI-RADS 4c」로만 적으면 확정 판정으로 읽힌다 */}
            <dt>모델 BI-RADS</dt><dd>{sum.max_birads}</dd>
          </div>
          <div><dt>조직검사 권고</dt><dd>{sum.biopsy ? "예" : "아니오"}</dd></div>
        </dl>
      )}

      {(r.lesions ?? []).map((l) => (
        <div className="ai-les" key={l.id}>
          <div className="ai-les-h">
            <i className="no">{l.id}</i>
            <b>{l.label ?? l.kind}</b>
            {l.confidence === "low" && <Chip tone="line">직접 확인</Chip>}
          </div>

          {l.descriptors && (
            <ul className="ai-desc">
              {Object.entries(l.descriptors).map(([ax, v]) => (
                <li key={ax}>
                  <span>{ax}</span>
                  <b>{v.value}</b>
                  {/* 확률은 **그 축에 대한 값**이다. 병변 전체의 확신도로
                      읽히지 않게 축 옆에 붙인다 */}
                  <em>({v.confidence?.toFixed?.(2) ?? v.confidence})</em>
                  {v.verify && <span className="warn">확인</span>}
                </li>
              ))}
            </ul>
          )}

          {/* 미세석회는 상자가 병변 크기가 아니다. 크기를 주장하지 않는다 */}
          {l.display?.claims_extent === false && (
            <p className="ai-fine">위치 표식 — 크기를 나타내지 않습니다</p>
          )}

          <div className="ai-les-b">
            <button className="pill" onClick={() => onLocate?.(l)}>영역 보기</button>
            <button className="pill" onClick={() => onFalsePositive?.(l)}>오탐 표시</button>
          </div>
        </div>
      ))}

      {r.disclaimer && <p className="ai-fine">{r.disclaimer}</p>}
      <Limits limits={r.limitations} />
    </Wrap>
  );
}

/* 못 채운 항목 — **빈칸으로 두지 않는다.** 소켓이 사유를 문장으로
   실어 보내므로 화면은 문장을 짓지 말고 받은 것을 그대로 쓴다. */
function Limits({ limits }) {
  const rows = Object.entries(limits ?? {});
  if (rows.length === 0) return null;
  return (
    <details className="ai-lim">
      <summary>제공하지 않는 항목 {rows.length}</summary>
      <dl>
        {rows.map(([k, why]) => (
          <div key={k}><dt>{k}</dt><dd>{why}</dd></div>
        ))}
      </dl>
    </details>
  );
}

function Wrap({ state, children }) {
  return (
    <div className="ai">
      <div className="ai-h">
        <b>AI 소견</b>
        <Chip tone={state === "완료" ? "dot" : "line"}>{state}</Chip>
      </div>
      {children}
    </div>
  );
}
