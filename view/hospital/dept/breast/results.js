import { MODALITY, label, modality as asModality } from "../../codes";

/* 결과 글자 만들기 — 대기 환자 · 환자 상세 · 치료 방침 · 전체 환자가 같이
 * 쓴다. 그리는 쪽은 components/Results.jsx.
 * ⚠ 색으로 등급을 말하지 않는다 — 글자로 적는다(Waiting.jsx 머리). */

/* 수용체 — 「ER+ · PR− · HER2 2+ · Ki-67 30%」.
   서버 값이 positive/negative 로 오든 +/− 로 오든 받는다. 모르는 값은 그대로 */
const SIGN = { positive: "+", pos: "+", "+": "+", negative: "−", neg: "−", "-": "−", "−": "−" };

function sign(name, v) {
  if (v == null || v === "") return null;
  const s = SIGN[String(v).toLowerCase()];
  if (s) return `${name}${s}`;
  if (String(v).toLowerCase() === "equivocal") return `${name} 경계`;
  return `${name} ${v}`;
}

export function receptors(r) {
  if (!r) return [];
  return [
    sign("ER", r.er), sign("PR", r.pr), sign("HER2", r.her2),
    r.ki67 != null && r.ki67 !== "" ? `Ki-67 ${Number(r.ki67)}%` : null,
  ].filter(Boolean);
}

/* 병리 한 건의 부가 값 — 조직형 · Nottingham 등급 · sTIL(병리의 입력) */
export function pathExtras(r) {
  return [
    r.histologic_type,
    r.nottingham_grade != null && r.nottingham_grade !== "" ? `G${r.nottingham_grade}` : null,
    r.stil != null && r.stil !== "" ? `sTIL ${Number(r.stil)}%` : null,
  ].filter(Boolean);
}

export const upper = (g) => (g == null ? null : String(g).toUpperCase());

/* 진행 중 오더 — 「초음파 요청됨 · 판독 대기」 */
const RUN_SAY = { ordered: "요청됨", accepted: "접수됨", in_progress: "촬영 중" };

export function pendingOf(orders = []) {
  return (orders ?? [])
    .filter((o) => o.modality && RUN_SAY[o.order_status])
    .map((o) => ({
      id: o.exam_order_id ?? o.id,
      text: `${label(MODALITY, asModality(o.modality))} ${RUN_SAY[o.order_status]} · 판독 대기`,
      at: o.ordered_at ?? o.scheduled_at ?? null,
    }));
}

/* 한 줄 요약 — 「유방촬영 BI-RADS 4c · B2 양성 — 섬유선종 · ER+」 */
export function briefOf(p) {
  const rad = p?.readings?.radiology?.[0];
  const pat = p?.readings?.pathology?.[0];
  return [
    rad?.grade ? `${label(MODALITY, asModality(rad.modality)) || "영상"} BI-RADS ${rad.grade}` : null,
    pat?.grade ? `${upper(pat.grade)}${pat.note ? ` ${pat.note}` : ""}` : null,
    ...receptors(pat),
  ].filter(Boolean).join(" · ") || null;
}

/* AI 병변 한 줄 — 판독의가 잰 크기가 먼저, AI 크기 · AI 등급은 참고로.
   ⚠ 악성 확률(malignancy_p)은 **내지 않는다** — 서버도 일부러 안 준다 */
export function lesionText(l, withMod = false) {
  const mm = (v) => (v != null && v !== "" && Number.isFinite(Number(v)) ? `${Number(v)} mm` : null);
  const measured = mm(l.measured_size_mm ?? l.size_mm);
  const ai = mm(l.ai_size_mm);
  return [
    withMod ? label(MODALITY, asModality(l.modality)) : null,
    l.label ?? l.site ?? null,
    measured ?? (ai ? `AI ${ai}` : null),
    measured && ai ? `AI ${ai}` : null,
    l.birads_model ? `AI BI-RADS ${l.birads_model}` : null,
  ].filter(Boolean).join(" · ");
}
