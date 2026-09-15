import { Chip, Fold } from "../../lib/Parts";

/* 병리 AI 소견 — 등급이 아니라 **정량 지표**다.
 *
 * ── 화면에 내지 않는 것 ──────────────────────────────────────
 *   **stil_nucleus (비보정 sTIL)** — 임상 기준의 약 1/12 값이다. 그대로
 *     보여주면 「TIL 이 거의 없다」로 잘못 읽힌다. 보정값만 낸다
 *
 * ── 평균을 내지 않는다 ───────────────────────────────────────
 * 크롭 여러 장이면 **장마다 나란히** 보여준다. 자른 자리에 따라 값이 크게
 * 흔들리는데, 평균은 **우리가 만든 값이지 모델이 낸 값이 아니다.**
 *
 * ── 간질이 없으면 0% 가 아니다 ───────────────────────────────
 * stroma_status=absent 면 sTIL 이 null 이다. 간질이 없어서 **잴 수 없는
 * 것**이지 TIL 이 없는 것이 아니다. 「평가 불가」로 적는다.
 *
 * ── 기권은 실패가 아니다 ─────────────────────────────────────
 * abstained=true 는 「분석 실패」가 아니라 「판정 못 함」이다. 사유를
 * 함께 띄운다.
 */
const LEVEL = { low: "낮음", mid: "중등도", high: "높음" };

export default function AiFindings({ ai, crops }) {
  if (!ai) {
    return <p className="ai-note">AI 결과가 없습니다.</p>;
  }

  return (
    <div className="ai">
      <div className="ai-h">
        <b>AI 소견</b>
        <Chip tone="dot">{ai.results.length}장 분석</Chip>
      </div>

      {ai.results.map((r, i) => (
        <Fold key={r.id} title={`크롭 ${i + 1} · ${crops[i]?.name ?? ""}`}
              open={i === 0}>
          {r.abstained ? (
            /* 실패가 아니다. 판정을 못 한 것이고 사유가 있다 */
            <>
              <p className="ai-big">판정하지 못했습니다</p>
              <p className="ai-note">{r.abstain_reason}</p>
            </>
          ) : (
            <dl className="ai-kv">
              <div>
                <dt>sTIL</dt>
                <dd>{r.stroma_status === "absent"
                  ? <span className="ai-na">평가 불가 — 간질 없음</span>
                  : <>{r.stil_calibrated}% <em>({LEVEL[r.stil_level] ?? r.stil_level})</em></>}</dd>
              </div>
              <div><dt>TSR</dt><dd>{r.tsr_percent}%</dd></div>
              <div><dt>세포 수</dt><dd>{r.cell_counts.total.toLocaleString()}</dd></div>
              <div><dt>TIL</dt><dd>{r.cell_counts.til.toLocaleString()}
                <em> (간질 내 {r.cell_counts.til_stromal.toLocaleString()})</em></dd></div>
              <div><dt>간질 상태</dt><dd>{r.stroma_status === "absent" ? "없음" : "있음"}</dd></div>
            </dl>
          )}
        </Fold>
      ))}

      <p className="ai-fine">
        TSR 에는 신뢰구간이 없습니다 — 모델에 dropout 이 없어 산출할 수 없습니다.
      </p>
      {ai.disclaimer && <p className="ai-fine">{ai.disclaimer}</p>}
    </div>
  );
}
