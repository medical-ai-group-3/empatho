import { reception as api } from "../api";
import { go } from "../nav";
import * as H from "./home";

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

  /* ── 홈 (docs/mockup/ReceptionHome.html) ──────────────────
   *
   * ⚠ **8쪽의 「오늘 현황판」은 홈이 아니다.** 그건 따로 있는 화면이고
   *   (Reception-오늘현황판.html) 원무 홈도 다른 넷과 같은 3단 격자다.
   *
   * 원무만 왼쪽 맨 위에 **접수 카드**가 더 붙는다(목업의 showIntake).
   *
   * ⚠ **큐 줄에 나이 · 성별 · 환자번호가 없다.** `/patients/today-status`
   *   응답이 네 칸(exam_order_id · patient_id · patient_name · stage)뿐이다.
   *   이름과 단계만 나온다 — 나머지를 지어내지 않는다(8장 9번).
   */
  home: {
    intake: true,

    load: () => Promise.all(
      [api.todayStatus(), H.soft(api.requests()), month()])
      .then(([today, requests, schedule]) => ({
        today: H.rows(today), requests: H.rows(requests),
        schedule: H.rows(schedule),
      })),

    primary: { label: "예약 확정", to: go.reception.requests(),
               need: "reception.requests.view" },

    queue: ({ today }) => ({
      title: "오늘 접수한 환자",
      hint: "누르면 환자 상세",
      empty: "오늘 온 환자가 없습니다",
      /* stage 는 서버가 쓰는 말 그대로 둔다 — 옮겨 부르면 서버가 단계를
         하나 늘렸을 때 그 줄만 빈칸이 된다 */
      rows: today.map((r) => ({
        id: r.exam_order_id ?? r.patient_id,
        name: H.nameOf(r),
        sub: r.stage,
        to: r.patient_id != null ? go.patient(r.patient_id) : null,
      })),
    }),

    stuck: ({ requests }) => [
      { tag: "예약 확인", text: "앱으로 들어온 예약 신청 — 날짜·시간을 정해야 합니다",
        count: requests.length, to: go.reception.requests() },
      /* ⚠ 목업의 「정보 누락」·「문진 미작성」은 못 센다. 연락처가 빈 환자를
         뽑는 조건이 없고(전체 명부를 긁어야 한다), 문진이 빈 오더를 거르는
         조건도 없다. 지어내지 않고 줄을 안 세운다 */
    ],

    /* ⚠ 「오늘 한 일」을 셀 자리가 없다. 접수·등록·예약 확정을 누가 언제
       했는지는 감사 칸(created_by·created_at)에 있지만 그것만 뽑아 주는
       경로가 없다(8장 1번) */
    done: () => ({ empty: "아직 없습니다" }),

    /* 달력 점은 이 과만 찍을 수 있다 — 한 달 치 예약을 한 번에 받는다 */
    marks: ({ schedule }) => schedule
      .filter((r) => r.scheduled_at)
      .map((r) => ({ date: r.scheduled_at, kind: "예약 있음" })),
  },
};

/* 달력이 쓸 한 달 치 예약. 이번 달 1일부터 말일까지 한 번에 받는다 —
   날짜마다 부르면 서른 번 나간다 */
function month() {
  const n = new Date();
  const first = new Date(n.getFullYear(), n.getMonth(), 1);
  const last = new Date(n.getFullYear(), n.getMonth() + 1, 0);
  return H.soft(api.schedule(H.iso(first), H.iso(last)));
}

export default reception;
