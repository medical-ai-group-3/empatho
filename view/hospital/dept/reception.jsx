import { reception as api } from "../api";
import { go } from "../nav";

/* 원무과 설정 — 병리·영상의 다섯 장 틀을 안 쓴다
 * ════════════════════════════════════════════════════════════════
 *
 * 원무는 **환자를 시스템에 들여보내는 입구**다. 집는 절차도, 올리는
 * 단계도, 판독도 없다. 그래서 유방외과처럼 화면을 따로 갖는다.
 *
 * 원무가 정하지 않는 것
 *   modality · exam_purpose · ordered_by  — 의학적 판단이라 유방외과 몫이다.
 *   DB CHECK 이 그것을 허용한다 (order_status 가 requested · cancelled 일
 *   때만 세 칸이 비어도 된다).
 *
 * 화면은 지금 1장뿐이다. 캘린더 · 환자 목록 · 예약 확인이 뒤에 온다.
 */
export const reception = {
  key: "reception",
  name: "원무과",
  api,
  go: go.reception,
};

export default reception;
