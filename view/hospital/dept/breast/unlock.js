/* 잠금 해제 조건 읽기 — components/Unlock.jsx 가 그린다. 머리말은 그 파일 */

const KEYS = [
  { key: "records_final", label: "모든 결과 확정", old: ["all_finalized", "records_final"] },
  { key: "discordance_closed", label: "판정 불일치 종결", old: ["discordance_closed"] },
  { key: "explained", label: "대면 설명 완료", old: ["explained"] },
];

/** 서버 응답 → 세 조건(늘 이 순서) */
export function unlockConds(status) {
  const c = status?.conditions;
  if (Array.isArray(c)) {
    const by = Object.fromEntries(c.filter(Boolean).map((row) => [row.key, row]));
    return KEYS.map(({ key, label: l }) => ({
      key, label: by[key]?.label ?? l, met: by[key] ? Boolean(by[key].met) : null,
      items: Array.isArray(by[key]?.items) ? by[key].items : null,
    }));
  }
  if (c && typeof c === "object") {
    return KEYS.map(({ key, label: l, old }) => {
      const hit = old.find((k) => k in c);
      return { key, label: l, met: hit ? Boolean(c[hit]) : null, items: null };
    });
  }
  return KEYS.map(({ key, label: l }) => ({ key, label: l, met: null, items: null }));
}

export const RUNNING = new Set(["ordered", "accepted", "in_progress"]);
const RULE = { rule1: "영상 의심 · 병리 양성 (위양성 검토)", rule2: "영상 저위험 · 병리 악성 (위음성 검토)" };
export const ruleText = (d) => d?.review_note || RULE[d?.violated_rule] || d?.violated_rule || "영상 · 병리 판정이 엇갈림";

