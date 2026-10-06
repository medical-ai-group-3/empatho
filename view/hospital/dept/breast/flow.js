import { go } from "../../nav";
import { MODALITY, label, modality as asModality } from "../../codes";

/* 유방외과 진료 흐름 — 한 환자가 지금 어디이고 다음에 무엇을 하나
 * ════════════════════════════════════════════════════════════════
 *
 *   접수 · 문진 → 검사 오더 → 촬영 · AI → 판독 → 병리 → 판정 불일치
 *   → 종합 리포트 → 치료 방침 → 환자 설명(잠금 해제) → 처방
 *   → 진료 완료 → 추적 · 재진
 *
 * **판단은 여기 한 곳이다.** 대기 환자 · 환자 상세 · 치료 방침 · 안내 팝업 ·
 * 전체 환자 · 홈이 같은 줄을 같은 말로 보여 줘야 한다. 전에는 Waiting.jsx
 * 의 nextCareStep 이 네 칸짜리 검사 진행만 따로 셌고, 나머지 화면은 각자
 * 「다음」을 짐작했다.
 *
 * 두 갈래로 센다.
 *   worklist   서버 GET /surgery/worklist 한 줄(item.next_step). 서버가 세면
 *              그것을 믿는다 — 화면이 판정 규칙을 또 하나 갖지 않게
 *   되짚기     그 경로가 없는 서버(옛 판 · 목업 일부)면 이미 불러 둔 환자
 *              상세(breast.patient) · 진료 이력 · 처방으로 여기서 센다
 *
 * ⚠ 되짚기는 「미확인」을 못 센다 — 누가 결과를 봤는지는 서버만 안다.
 *   그래서 되짚기에는 review 가 안 나온다.
 * ⚠ 처방은 **고를 수 있는 단계**다. 약이 필요 없는 환자가 많다 —
 *   되짚기는 처방을 「다음」으로 세우지 않고 단계 줄에 「선택」으로 둔다.
 *   서버가 prescription 을 주면 그대로 따른다.
 */

export const STEPS = [
  { key: "intake",       label: "접수 · 문진" },
  { key: "exam",         label: "검사 오더" },
  { key: "imaging",      label: "촬영 · AI" },
  { key: "read",         label: "판독" },
  { key: "path",         label: "병리" },
  { key: "discordance",  label: "판정 불일치" },
  { key: "report",       label: "종합 리포트" },
  { key: "decision",     label: "치료 방침" },
  { key: "explain",      label: "환자 설명" },
  { key: "prescription", label: "처방" },
  { key: "close",        label: "진료 완료" },
  { key: "followup",     label: "추적 · 재진" },
];

/* 서버 next_step 열 가지 → 단계 줄의 자리 · 단추 글자 · 홈 집계 이름 */
export const NEXT = {
  exam:         { step: "exam",         label: "검사 오더",         name: "검사 오더 필요" },
  wait_results: { step: "read",         label: "결과 대기 중",      name: "결과 대기" },
  review:       { step: "read",         label: "새 결과 확인",      name: "새 결과 미확인" },
  discordance:  { step: "discordance",  label: "불일치 처분하기",   name: "판정 불일치" },
  report:       { step: "report",       label: "종합 리포트 만들기", name: "리포트 작성 전" },
  decision:     { step: "decision",     label: "치료 방침 결정",    name: "방침 미결정" },
  explain:      { step: "explain",      label: "환자 설명",         name: "설명 대기" },
  prescription: { step: "prescription", label: "처방",              name: "처방 대기" },
  close:        { step: "close",        label: "진료 완료",         name: "진료 완료 대기" },
  followup:     { step: "followup",     label: "재진 예약",         name: "재진 · 추적" },
};

/* 홈 「진료 흐름」 칸에 세는 순서 — 의사가 손대야 하는 것만. 결과 대기는
   남(영상 · 병리)의 차례라 뺀다 */
export const PENDING_KEYS = ["review", "discordance", "report", "decision", "explain", "prescription"];

/* 오더가 아직 결과 전인가. requested 는 방문(접수) 오더라 검사가 아니다 */
const RUNNING = new Set(["ordered", "accepted", "in_progress"]);

/* ── 사실 모으기 ──────────────────────────────────────────────
 * 모르는 것은 undefined 로 둔다. **null(없다)과 다르다** — 단계 줄이
 * 모르는 것을 「안 했다」로 찍지 않게(dept/home.js stageSteps 와 같은 규칙) */
function factsOfPatient(p, { timeline, rx } = {}) {
  const rad = p.readings?.radiology ?? [];
  const pat = p.readings?.pathology ?? [];
  const orders = Array.isArray(p.orders) ? p.orders : (p.current_order ? [p.current_order] : []);
  const ev = Array.isArray(timeline) ? timeline : null;
  const pending = orders.filter((o) => o.modality && RUNNING.has(o.order_status));
  const done = new Set(pat.map((r) => String(r.specimen_id)));
  (ev ?? []).filter((e) => e.type === "병리 확진").forEach((e) => done.add(String(e.specimen_id)));
  const pendingPath = (ev ?? [])
    .filter((e) => e.type === "검체 채취" && e.specimen_id != null && !done.has(String(e.specimen_id)))
    .map((e) => e.specimen_id);
  /* 결정은 판독 행에 덮어써진다 — 이력의 마지막 「치료 결정」이 지금 값이다 */
  const decided = ev ? [...ev].reverse().find((e) => e.type === "치료 결정") ?? null : undefined;
  const report = p.report ?? null;
  /* 종합 소견서는 의사용(p.report) · 환자용(p.patient_report) 두 벌이다. 치료
     방침 화면은 설명 · 잠금 해제를 **환자용**에 건다(09-28) — 둘 중 하나라도
     설명 기록이 있으면 설명한 것이다. 옛 서버는 한 벌에만 적는다 */
  const pair = [report, p.patient_report].filter(Boolean);
  const pairIds = new Set(pair.map((r) => String(r.report_id)));
  const explained = report
    ? Boolean(pair.some((r) => r.explained_at || (r.patient_confirmed && r.explain_method))
      || (ev ?? []).some((e) => e.type === "결과 설명" && pairIds.has(String(e.report_id))))
    : false;
  const rxCount = Array.isArray(rx) ? rx.length
    : ev ? ev.filter((e) => e.type === "처방").length : undefined;
  return {
    pid: p.patient_id,
    rad, pat,
    grade: rad[0]?.grade != null ? String(rad[0].grade).toLowerCase() : null,
    pending, pendingCount: pending.length, pendingPath,
    visited: orders.some((o) => o.visited_at),
    visitOpen: orders.some((o) => o.visited_at && o.order_status === "requested"),
    closed: orders.some((o) => o.visited_at && o.order_status === "completed")
      && !orders.some((o) => o.visited_at && o.order_status === "requested"),
    disc: p.open_discordance ?? null,
    report: Boolean(report),
    unlocked: Boolean((p.patient_report ?? report)?.is_unlocked),
    decision: decided === undefined ? undefined : (decided?.decision_value ?? null),
    explained, rxCount,
  };
}

function factsOfItem(it) {
  return {
    pid: it.patient_id,
    pendingCount: it.pending_orders ?? undefined,
    unseen: it.unseen_results ?? undefined,
    disc: it.open_discordance ? (typeof it.open_discordance === "object" ? it.open_discordance
      : { discordance_id: it.open_discordance === true ? null : it.open_discordance }) : null,
    report: it.final_report_id != null,
    explained: Boolean(it.report_explained),
    decision: it.decision ?? null,
    rxCount: it.prescription_count ?? undefined,
    serverNext: it.next_step ?? null,
  };
}

/* ── 다음 할 일 (되짚기) ───────────────────────────────────────
 * 순서가 곧 우선순위다. 불일치가 열려 있으면 **다른 무엇보다 먼저** —
 * 엇갈린 채로 방침을 정하면 안 된다(Discordance.jsx 머리말) */
function deriveNext(f) {
  if (f.disc) return { key: "discordance" };
  const noResult = !f.rad.length && !f.pat.length;
  if (noResult) {
    return f.pendingCount || f.pendingPath.length
      ? { key: "wait_results", why: waitWhy(f) }
      : { key: "exam", modality: "mammo", why: "확정된 영상 판독이 없습니다. 필요한 촬영을 요청해 주세요." };
  }
  if (f.grade === "0" && !f.pendingCount) {
    return { key: "exam", modality: asModality(f.rad[0].modality) === "us" ? "mri" : "us",
             why: "BI-RADS 0 — 추가 영상이 필요합니다." };
  }
  if (/^[45]/.test(f.grade ?? "") && !f.pat.length) {
    return f.pendingPath.length
      ? { key: "wait_results", step: "path", why: "검체를 보냈습니다. 병리 확진을 기다립니다." }
      : { key: "exam", specimen: true, why: `BI-RADS ${f.grade} — 조직검사 검체를 등록해 병리과로 보내 주세요.` };
  }
  if (f.pendingCount || f.pendingPath.length) return { key: "wait_results", why: waitWhy(f) };
  if (!f.report) return { key: "report" };
  if (f.decision === null) return { key: "decision" };
  if (!f.explained) return { key: "explain" };
  if (f.visitOpen) return { key: "close" };
  return { key: "followup",
           why: f.grade === "3" ? "BI-RADS 3 — 6개월 뒤 추적 검사를 예약해 주세요." : null };
}

function waitWhy(f) {
  const mods = [...new Set(f.pending.map((o) => label(MODALITY, asModality(o.modality))))];
  const parts = [
    mods.length ? `${mods.join(" · ")} 판독` : null,
    f.pendingPath.length ? "병리 확진" : null,
  ].filter(Boolean);
  return parts.length ? `${parts.join(" · ")}을 기다립니다.` : "결과를 기다립니다.";
}

const SAY = {
  discordance: "영상과 병리 판정이 엇갈립니다. 처분하기 전에는 치료 방침을 정할 수 없습니다.",
  review: "새로 확정된 결과가 있습니다. 환자 상세에서 확인해 주세요.",
  report: "결과가 모두 나왔습니다. 확정된 판독문으로 AI 종합 리포트를 만들어 주세요.",
  decision: "리포트를 보고 수술 여부와 결정 사유를 남겨 주세요.",
  explain: "환자에게 결과와 치료 계획을 설명하고 기록하면 환자 리포트 잠금을 해제할 수 있습니다.",
  prescription: "필요한 약이 있으면 처방해 주세요. 환자 앱 복약 관리에 표시됩니다.",
  close: "진료를 완료하면 대기 목록과 환자 앱 예약에서 빠집니다.",
  followup: "진료가 끝났습니다. 재진 · 추적 일정을 잡아 주세요.",
  exam: "필요한 검사를 요청해 주세요.",
  wait_results: "결과를 기다립니다.",
};

/* ── 단계 줄 ─────────────────────────────────────────────────── */
const ORDER = STEPS.map((s) => s.key);

function stateOf(key, f, nowStep) {
  const nowAt = ORDER.indexOf(nowStep);
  const at = ORDER.indexOf(key);
  if (key === nowStep) return "now";
  const pos = at < nowAt ? "done" : "todo";
  switch (key) {
    case "intake":
      return f.visited || f.rad?.length || f.pat?.length ? "done" : pos;
    case "exam":
      return f.pendingCount || f.rad?.length || f.pat?.length || f.pendingPath?.length ? "done" : pos;
    case "imaging":
    case "read":
      if (f.rad?.length) return f.pendingCount ? "wait" : "done";
      if (f.pendingCount) return "wait";
      /* 영상 없이 지나온 자리(병리만 있는 환자)는 「안 했다」가 아니라 건너뜀 */
      return f.rad && pos === "done" ? "skip" : pos;
    case "path":
      if (f.pat?.length) return f.pendingPath?.length ? "wait" : "done";
      if (f.pendingPath?.length) return "wait";
      /* 판독이 있고 조직검사 대상(4 · 5 · 6)이 아니면 병리는 해당 없음 */
      if (f.rad?.length && !/^[456]/.test(f.grade ?? "")) return "skip";
      return pos;
    case "discordance":
      return f.disc ? "now" : "skip";
    case "report":
      return f.report ? "done" : pos;
    case "decision":
      return f.decision ? "done" : f.decision === undefined ? pos : (at < nowAt ? "todo" : pos);
    case "explain":
      return f.explained ? "done" : pos;
    case "prescription":
      return f.rxCount > 0 ? "done" : "opt";
    case "close":
      return f.closed ? "done" : pos;
    default:
      return pos;
  }
}

/* 단계마다 붙는 짧은 값 — 「BI-RADS 4c」 「B2」 「2건 대기」 */
function noteOf(key, f) {
  switch (key) {
    case "read": return f.grade ? `BI-RADS ${f.grade}` : f.pendingCount ? `${f.pendingCount}건 대기` : null;
    case "imaging": return f.pendingCount ? `${f.pendingCount}건 진행` : null;
    case "path": return f.pat?.[0]?.grade ? String(f.pat[0].grade).toUpperCase()
      : f.pendingPath?.length ? "확진 대기" : null;
    case "discordance": return f.disc ? "처분 대기" : null;
    case "decision": return f.decision ? ({ yes: "수술", no: "수술 안 함", defer: "보류" }[f.decision] ?? f.decision) : null;
    case "explain": return f.unlocked ? "공개됨" : null;
    case "prescription": return f.rxCount > 0 ? `${f.rxCount}건` : "선택";
    default: return null;
  }
}

/** 한 환자의 흐름.
 *  src — { p, item, timeline, rx }. item(worklist 한 줄)이 있으면 그 next_step
 *  을 따르고, p(환자 상세)가 있으면 단계 줄을 더 자세히 채운다. */
export function flowOf({ p = null, item = null, timeline, rx } = {}) {
  const fp = p ? factsOfPatient(p, { timeline, rx }) : null;
  const fi = item ? factsOfItem(item) : null;
  /* 둘 다 있으면 서버 집계(fi)가 센 값을 앞세우고, 모르는 칸만 상세로 채운다 */
  const f = { ...(fp ?? {}), ...Object.fromEntries(Object.entries(fi ?? {}).filter(([, v]) => v !== undefined)) };
  const derived = fp ? deriveNext(fp) : null;
  const key = fi?.serverNext && NEXT[fi.serverNext] ? fi.serverNext : derived?.key ?? null;
  const base = key ? NEXT[key] : null;
  const pid = f.pid;
  const same = derived && derived.key === key ? derived : {};
  const step = same.step ?? base?.step ?? null;
  const discId = f.disc?.discordance_id ?? null;

  const next = base && {
    key, step,
    label: same.specimen ? "검체 등록" : same.modality
      ? `${label(MODALITY, same.modality)} 촬영 요청` : base.label,
    why: same.why ?? SAY[key] ?? null,
    modality: same.modality ?? null,
    act: key === "exam" ? (same.specimen ? "specimen" : "exam")
      : key === "close" ? "close"
      : key === "followup" ? "book" : null,
    to: pid == null ? null
      : key === "review" ? go.breast.review(pid)
      : key === "discordance" ? (discId != null ? go.breast.discordance(discId) : go.breast.review(pid))
      : ["report", "decision", "explain", "prescription"].includes(key) ? go.breast.decision(pid, key)
      : null,
  };

  const steps = STEPS.map((s) => ({
    ...s,
    state: step ? stateOf(s.key, f, step) : "todo",
    note: noteOf(s.key, f),
  }));
  return { steps, next, facts: f };
}

/* 불일치가 열려 있는 동안 막히는 단계 — 치료 방침 화면의 ④ ~ ⑥ */
export const BLOCKED_BY_DISCORDANCE = new Set(["decision", "explain", "prescription"]);

/* worklist 가 없을 때 홈 · 목록이 쓰는 한 줄 요약 */
export function nextName(key) {
  return NEXT[key]?.name ?? null;
}
