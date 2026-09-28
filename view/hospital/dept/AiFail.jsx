/* AI 서버 실패 · 도는 중 한 칸 — 가르는 규칙은 aiFailure.js */

/* 실패 한 칸.
   compact — 판독 화면 오른쪽 맨 위 요약 줄(한 줄 + 단추)
   rerun   — { run, busy, msg } · 권한이 없거나 확정된 건이면 Read.jsx 가 null 을 준다 */
export function AiFailNote({ f, rerun = null, compact = false }) {
  return (
    <div className={`ai-fail${compact ? " compact" : ""}`} role="status">
      <p className="ai-fail-t">
        <b>{compact ? "AI 분석 실패" : "AI 결과가 없습니다"}</b>
        <span>{f.title}</span>
      </p>
      {!compact && (
        <p className="muted small">「정상」이라는 뜻이 아닙니다. 직접 판독하시거나 AI를 다시 실행해 주세요.</p>
      )}
      {rerun && (
        <div className="ai-fail-act">
          <button type="button" className="btn line sm" disabled={rerun.busy}
                  onClick={rerun.run} title="같은 영상으로 AI 분석을 다시 실행합니다">
            {rerun.busy ? "AI 분석 중…" : "AI 다시 실행"}
          </button>
          {rerun.msg && <span className="warnline">{rerun.msg}</span>}
        </div>
      )}
      {f.raw && (
        <details className="ai-fail-raw">
          <summary>자세히</summary>
          <code>{f.raw}</code>
        </details>
      )}
    </div>
  );
}

/* 도는 중 한 줄 */
export function AiRunningNote({ compact = false }) {
  return (
    <p className={`ai-run${compact ? " compact" : ""}`} role="status">
      <b>AI 분석 중…</b>
      <span>분석이 끝나면 여기에 결과가 표시됩니다. 서버가 바쁘면 잠시 뒤 자동으로 다시 시도합니다.</span>
    </p>
  );
}
