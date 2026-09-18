import { nursing as api } from "../api";
import { go } from "../nav";

/* 간호과 설정 — 유방외과처럼 **모양이 다른 과**다
 * ════════════════════════════════════════════════════════════════
 *
 * 병리·영상의 공통 화면 다섯 장(screens/)을 안 쓴다 — 집는 절차도,
 * 판독도 없다. 원무가 접수한 환자를 유방외과 의사에게 넘기고(1장),
 * BI-RADS 3 확정 환자의 추적을 관리한다(2장). 검체 바인딩(3장)은 화면이
 * 따로 없다 — 유방외과와 같은 팝업(hospital/lib/SpecimenBindingModal)을
 * 1장 안에서 연다.
 *
 * breast.jsx 와 같은 이유로 얇게 둔다 — 화면들이 자기 것을 직접 안다. */
export const nursing = {
  key: "nursing",
  name: "간호과",
  api,
  go: go.nursing,
};

export default nursing;
