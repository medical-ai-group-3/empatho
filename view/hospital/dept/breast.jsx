import { breast as api, reception } from "../api";
import { go } from "../nav";
import * as H from "./home";

/* 유방외과 설정 — 병리·영상과 **모양이 다른 과**다
 * ════════════════════════════════════════════════════════════════
 *
 * pathology.jsx · radiology.jsx 는 공통 화면 다섯 장(screens/)에 끼워
 * 넣을 「다른 점」을 모아 둔 파일이다. 유방외과는 그 다섯 장을 안 쓴다 —
 * 화면을 dept/breast/screens/ 에 통째로 따로 갖고 있다.
 *
 * 왜 다른가
 *   집는 절차가 없다   주치의로 배정된 환자가 곧 큐다. 남이 먼저 집어
 *                      가는 일이 없어서 assign · 409 가 아예 없다
 *   올리는 단계가 없다  파일을 올리는 쪽이 아니라 **일을 내보내는** 쪽이다.
 *                      검사 오더는 영상의학과 큐로, 검체 바인딩은 병리과
 *                      큐로 넘어간다
 *   판독이 아니라 결정  소견을 쓰는 게 아니라 치료 방침을 정하고 리포트를
 *                      확정한다
 *
 * 그래서 이 파일은 얇다. 공통 화면이 읽을 값이 없기 때문이다. 화면이
 * cfg 를 받긴 하지만 유방외과 화면들은 자기 것을 직접 안다.
 *
 * ⚠ 이 파일을 pathology.jsx 처럼 살찌우지 말 것. 다섯 장 틀에 억지로
 *   맞추면 쓰지 않는 설정이 늘기만 한다.
 */
export const breast = {
  key: "breast",
  name: "유방외과",
  api,
  go: go.breast,

  /* ── 홈 (docs/mockup/SurgeryHome.html) ──────────────
   *
   * 환자 목록과 예약 오더를 함께 받아, 내 환자 큐와 월간 예약 캘린더를
   *   같은 홈에서 구성한다.
   *
   * ⚠ waiting() 과 patients() 가 **같은 줄을 돌려준다.** 서버가
   *   `?primary_staff=me` 면 status 를 안 보고 바로 돌아간다 —
   *
   *     PatientViewSet.get_queryset()
   *         if primary_staff_param == "me":
   *             return qs.filter(primary_staff=staff)     ← 여기서 끝난다
   *
   *   그래서 목록을 한 번만 부른다(8장 10번).
   */
  home: {
    load: () => Promise.all([
      api.patients(),
      H.soft(reception.schedule(...monthBounds())),
    ]).then(([all, schedule]) => ({
      all: H.rows(all),
      schedule: H.rows(schedule),
    })),

    primary: { label: "다음 환자 진료", to: go.breast.waiting(),
               need: "breast.waiting.view" },

    queue: ({ all }) => ({
      title: "내 환자",
      hint: "누르면 환자 상세",
      empty: "배정된 환자가 없습니다",
      /* ⚠ **시각도, 초진/재진도, 한 줄 요약도 없다.** 환자 목록 응답
         (PatientListSerializer)이 번호·이름·생년월일·성별·알레르기
         다섯 칸뿐이다. 칩 자리에는 아는 것 하나만 — 알레르기 표시.
         ⚠ 오더 쪽(/exam-orders)으로 바꿔 시각·검사 진행을 채우려 했는데
           **주치의로 거르는 조건이 없다** — status·visited·scheduled_*·
           patient·ordering 뿐이고 응답에 primary_staff 도 없다. 전부 받아
           화면에서 가르면 한 쪽 20건이라 조용히 빠진다(8장 10번) */
      rows: all.map((r) => ({
        id: r.patient_id,
        name: H.nameOf(r),
        no: H.noOf(r),
        meta: H.who(r),
        chip: H.allergy(r) ? "알레르기" : null,
        /* 줄에 「검사 종합」이라고 적어 놓고 **일반 환자 화면**으로 보내고
           있었다(09-23 확인). 유방외과가 이 줄에서 할 일이 바로 검사 종합
           확인이고, 그 화면이 이 과에 따로 있다 — 적힌 대로 보낸다.
           권한이 없으면 그 화면이 Locked 로 알려 준다(main.jsx) */
        to: go.breast.review(r.patient_id),
        pid: r.patient_id,
        why: "검사 종합",
      })),
    }),

    stuck: ({ all }) => [
      { tag: "알레르기", text: "조영제 알레르기 표시가 있는 환자",
        count: all.filter((r) => H.allergy(r)).length,
        to: go.breast.patients() },
      /* ⚠ 목업의 「불일치」·「설명」·「동의」는 못 센다. 불일치는 서버에
         GET /discordances 가 있지만 api.js 에 없고 새 경로는 8장에 적는
         것이 규칙이다(8장 4번). 결과 설명 기록과 검사 동의는 표가 없다 */
    ],

    /* 오늘 한 일은 별도 목록으로 제공하지 않는다. 홈의 이 영역은
       공용 Todo(할 일) 카드가 차지한다. */

    marks: ({ schedule }) => (schedule ?? [])
      .filter((row) => row.scheduled_at)
      .map((row) => ({ date: row.scheduled_at, kind: "예약 있음" })),
  },
};

function monthBounds(now = new Date()) {
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return [H.iso(first), H.iso(last)];
}

export default breast;
