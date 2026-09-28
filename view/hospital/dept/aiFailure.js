/* AI 가 «판정을 못 한» 까닭 가르기 — 영상 · 병리 AI 소견이 같이 쓴다 (09-28)
 * ────────────────────────────────────────────────────────────────
 *
 * 「판정 못 함」에는 두 가지가 섞여 온다.
 *
 *   모델이 판정을 거부했다   검출 없음 · 임계값 미달 · 화질 — 결과다. 그대로 적는다.
 *   서버가 잠깐 못 받았다    GPU 메모리 부족 · 시간 초과 · 연결 실패 — 결과가 아니다.
 *                            다시 돌리면 된다.
 *
 * ⚠ 뒤쪽이 서버 예외 글 그대로 화면에 찍혔다 — 「predict_failed : OutOfMemoryError:
 *   CUDA out of memory. Tried to allocate 1.60 GiB. GPU 0 has …」가 칸을 넘쳐
 *   옆으로 굴렀고, 판독의가 읽을 말이 아니었다. 뜻만 한국어 한 줄로 적고,
 *   원문은 「자세히」 안에 접어 둔다(서버 쪽 진단용 — 지우지 않는다).
 *
 *   서버는 GPU 메모리 부족 · 5xx 를 스스로 두 번 더 건다(core/tasks.py
 *   RETRY_COUNTDOWNS). 여기까지 온 것은 그래도 안 된 것이다.
 */

const KINDS = [
  { kind: "oom",
    re: /out\s*of\s*memory|outofmemory|cuda error/i,
    title: "AI 서버 GPU 메모리가 부족해 분석하지 못했습니다(서버 과부하). 잠시 뒤 다시 실행해 주세요." },
  { kind: "timeout",
    re: /soft_time_limit|time_?limit|timelimitexceeded|timed?\s*out|timeout/i,
    title: "분석 시간이 초과됐습니다. 잠시 뒤 다시 실행해 주세요." },
  { kind: "conn",
    re: /urlerror|httperror|connection|remotedisconnected|incompleteread|errno|refused|unreachable|getaddrinfo|name or service|broken\s*pipe|bad gateway|service unavailable/i,
    title: "AI 서버에 연결하지 못했습니다. 잠시 뒤 다시 실행해 주세요." },
];

/* 서버 예외 글처럼 생겼나 — 「predict_failed」 · 「XxxError: …」 · Traceback */
const LOOKS_TECH = /predict_failed|traceback|exception|\b[A-Z]\w*(Error|Exception)\b/;

/* ai → null(서버 실패가 아님) | { kind, title, raw }
   run_status 가 failed 면 사유와 상관없이 실패다. done 인데 기권이면
   사유 글을 보고 가른다 — 모델 기권(검출 없음 등)은 null 을 돌려준다 */
export function aiFailure(ai) {
  if (!ai) return null;
  const raw = [ai.abstain_reason, ai.reason].find((v) => typeof v === "string" && v.trim()) ?? null;
  const failed = ai.run_status === "failed";
  const hit = raw ? KINDS.find((k) => k.re.test(raw)) : null;
  if (hit) return { kind: hit.kind, title: hit.title, raw };
  if (failed || (raw && LOOKS_TECH.test(raw))) {
    return { kind: "other", title: "AI 분석에 실패했습니다.", raw };
  }
  return null;
}

/* 아직 도는 중인가 — 다시 실행 뒤, 또는 서버가 스스로 다시 거는 동안 */
export const aiRunning = (ai) => Boolean(ai) && (ai.run_status === "queued" || ai.run_status === "running");
