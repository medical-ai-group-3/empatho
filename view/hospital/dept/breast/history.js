import { go } from "../../nav";
import { AUDIENCE, DECISION_TYPE, DECISION_VALUE, READ_STAGE, REPORT_TYPE, label } from "../../codes";

/* 진료 이력 한 줄이 어디로 가나 — 유방외과 화면들이 같이 쓴다.
 *
 * ⚠ **판독 화면(go.radiology.read · go.pathology.read)으로 보내지 않는다.**
 *   유방외과는 그 권한이 없다(perm.js — 과마다 `${dept}.read.view`).
 *   보내면 잠긴 화면만 뜬다. 공용 환자 화면의 히스토리가 바로 그래서
 *   유방외과에게는 한 줄도 안 눌렸다(screens/Patient.jsx 의 eventTo).
 *
 * 대신 제 과의 환자 상세(Review)로 보낸다. 거기에 이 환자의 확정 판독 ·
 * 병리 결과가 검사 · 검체마다 한 줄씩 다 있다 — 줄이 실어 온 번호로 그
 * 건을 펴 준다. 치료 결정 · 리포트 · 결과 설명 · 처방은 치료 방침
 * (Decision)으로 가서 그 칸으로 내려간다.
 *
 *   PatientTimelineView(core/views/surgery.py) 가 싣는 번호
 *     촬영          study_id
 *     AI 분석 완료   study_id 또는 specimen_id (하나는 null)
 *     판독          study_id · assessment_id · read_stage
 *     검체 채취     specimen_id
 *     병리 확진     specimen_id
 *     치료 결정     assessment_id · study_id · decision_type · decision_value
 *     리포트        report_id · report_type · audience
 *     결과 설명     report_id
 *     처방          prescription_id · report_id
 *   (뒤 넷은 의료진에게만 온다 — 영상 · 병리 응답에는 없다)
 *
 * 번호가 없는 줄(옛 서버 · 목업)도 환자 상세로는 간다 — 과거 기록이 다
 * 그 화면에 있다. 어느 건인지만 못 짚는다. */

/* 치료 방침으로 가는 줄 → 내려갈 칸(Decision.jsx 의 focus) */
const DECIDE = {
  "치료 결정": () => "decision",
  "리포트": (e) => (e.audience === "patient" ? "patient-report" : "report"),
  "결과 설명": () => "explain",
  "처방": () => "prescription",
};

/** 이 줄이 치료 방침으로 가는가 — 부르는 쪽이 단추 글자를 고를 때 */
export const toDecision = (e) => Boolean(DECIDE[e?.type]);

export function historyAt(e) {
  /* ⚠ 치료 결정은 study_id 를 싣는다. 번호 순서로만 보면 환자 상세로
     빠진다 — 종류를 먼저 본다 */
  if (toDecision(e)) return null;
  if (e?.specimen_id != null) return { specimen: e.specimen_id };
  if (e?.study_id != null) {
    return { study: e.study_id, assessment: e.type === "판독" ? e.assessment_id ?? null : null };
  }
  return null;
}

export function historyTo(pid, e) {
  if (pid == null) return null;
  if (toDecision(e)) return go.breast.decision(pid, DECIDE[e.type](e));
  return go.breast.review(pid, historyAt(e));
}

/* 줄 아래 한 줄 글. 코드로 오는 칸은 한글로 푼다(codes.js).
   ⚠ 판독은 초안도 「판독」으로 온다 — 확정으로 읽히지 않게 단계를 붙인다 */
export function historyDetail(e) {
  const parts = e?.type === "치료 결정"
    ? [[label(DECISION_TYPE, e.decision_type), label(DECISION_VALUE, e.decision_value)]
      .filter(Boolean).join(" · "), e.detail]
    : e?.type === "리포트"
      ? [label(REPORT_TYPE, e.report_type), label(AUDIENCE, e.audience), e.detail]
      : e?.type === "판독" && e.read_stage === "draft"
        ? [e.detail, label(READ_STAGE, e.read_stage)]
        : [e?.detail];
  const out = [...new Set(parts.filter(Boolean).map(String))].join(" · ");
  return out || null;
}
