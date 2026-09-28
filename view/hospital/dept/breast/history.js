import { go } from "../../nav";

/* 진료 이력 한 줄이 어디로 가나 — 유방외과 화면들이 같이 쓴다.
 *
 * ⚠ **판독 화면(go.radiology.read · go.pathology.read)으로 보내지 않는다.**
 *   유방외과는 그 권한이 없다(perm.js — 과마다 `${dept}.read.view`).
 *   보내면 잠긴 화면만 뜬다. 공용 환자 화면의 히스토리가 바로 그래서
 *   유방외과에게는 한 줄도 안 눌렸다(screens/Patient.jsx 의 eventTo).
 *
 * 대신 제 과의 환자 상세(Review)로 보낸다. 거기에 이 환자의 확정 판독 ·
 * 병리 결과가 검사 · 검체마다 한 줄씩 다 있다 — 줄이 실어 온 번호로 그
 * 건을 펴 준다.
 *
 *   PatientTimelineView(core/views/surgery.py) 가 싣는 번호
 *     촬영          study_id
 *     AI 분석 완료   study_id 또는 specimen_id (하나는 null)
 *     판독          study_id · assessment_id
 *     검체 채취     specimen_id
 *     병리 확진     specimen_id
 *
 * 번호가 없는 줄(옛 서버 · 목업)도 환자 상세로는 간다 — 과거 기록이 다
 * 그 화면에 있다. 어느 건인지만 못 짚는다. */
export function historyAt(e) {
  if (e?.specimen_id != null) return { specimen: e.specimen_id };
  if (e?.study_id != null) return { study: e.study_id };
  return null;
}

export function historyTo(pid, e) {
  return pid == null ? null : go.breast.review(pid, historyAt(e));
}
