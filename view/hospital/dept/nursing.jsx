import { nursing as nur, reception as rec } from "../api";
import { go } from "../nav";
import * as H from "./home";

/* 접수·간호 설정 — **원무과와 간호과를 합친 한 과**다 (6.1)
 * ════════════════════════════════════════════════════════════════
 *
 * 접수 → 내원 대기 → 호출 → 문진 → 유방외과 배정은 실제로는 환자 한 명을
 * 이어서 다루는 한 줄이다. 따로 두면 중간에 과 탭을 건너뛰어야 했다.
 *
 * 병리·영상의 공통 화면 다섯 장(screens/)을 안 쓴다 — 집는 절차도,
 * 판독도 없다. 검체 바인딩은 화면이 따로 없다(내원 대기 안에서 팝업).
 *
 * ⚠ **권한은 한 줄도 안 바꿨다.** 화면마다 제 열쇠(`reception.*` ·
 *   `nursing.*`)를 그대로 걸어 둔다 — 한쪽 일만 하는 사람 메뉴에서는
 *   다른 쪽 화면이 알아서 빠진다(nav.js).
 *
 * ⚠ **api 를 두 벌 합쳐 준다.** 화면들이 `cfg.api.search` · `cfg.api.
 *   waitingArrived` 처럼 제 것만 부른다. 지금 이름이 겹치는 것은 없다 —
 *   겹치면 뒤엣것이 조용히 이기므로 늘릴 때 확인할 것.
 */
const api = { ...rec, ...nur };

export const nursing = {
  key: "nursing",
  name: "접수·간호",
  api,
  go: go.nursing,

  /* ── 홈 (docs/mockup/NursingHome.html · ReceptionHome.html) ──
   *
   * 두 목업의 본문 마크업이 같아서 합친 뒤에도 화면은 하나다. 다른 것은
   * 왼쪽 주 큐가 **탭 둘**이 된 것뿐이다 — 내원 대기(간호)와 오늘 접수(원무).
   * 접수 카드는 원무 목업의 showIntake 자리 그대로 맨 위에 둔다.
   *
   * ⚠ **선생님별 배정 현황은 아직 못 그린다.** `?primary_staff=` 가
   *   "me" 만 받고, 목록 응답에 primary_staff 가 없어 화면에서
   *   나눌 수도 없다. 배정이 이 과의 주 업무라 제일 아쉬운 자리다.
   */
  home: {
    intake: true,

    /* 주 큐의 앞 탭만 진짜다. 나머지는 옆 칸을 채우는 것이라 못 불러도
       화면이 서야 한다 */
    load: () => Promise.all([
      api.waitingArrived(),
      H.soft(api.todayStatus()),
      H.soft(api.followups()),
      month(),
    ]).then(([arrived, today, follow, schedule]) => ({
      arrived: H.rows(arrived), today: H.rows(today),
      follow: H.rows(follow), schedule: H.rows(schedule),
    })),

    primary: { label: "문진 · 배정", to: go.nursing.waiting(),
               need: "nursing.waiting.view" },

    queue: ({ arrived, today }) => ({
      title: "지금 와 있는 환자",
      hint: "접수 순 · 순서 고정",
      tabs: [
        { key: "waiting", name: "내원 대기",
          empty: "내원한 대기 환자가 없습니다",
          rows: arrived.map((r) => ({
            id: r.exam_order_id ?? r.id,
            name: H.nameOf(r),
            no: H.noOf(r),
            meta: H.who(r),
            chip: r.visit_type,
            /* 문진은 오더에 실려 온다(questionnaire). 있으면 배정 차례다 */
            sub: r.questionnaire ? "문진 완료 · 배정 대기" : "문진 대기",
            at: H.at(r.visited_at),
            to: r.patient != null ? go.patient(r.patient) : null,
            why: "문진 · 배정",
          })) },

        /* ⚠ 이 탭의 줄에는 나이·성별·번호·시각이 없다.
           `/patients/today-status` 응답이 네 칸뿐이다(8장 9번) */
        { key: "today", name: "오늘 접수",
          empty: "오늘 온 환자가 없습니다",
          rows: today.map((r) => ({
            id: r.exam_order_id ?? r.patient_id,
            name: H.nameOf(r),
            sub: r.stage,
            to: r.patient_id != null ? go.patient(r.patient_id) : null,
          })) },
      ],
    }),

    stuck: ({ arrived, follow }) => [
      { tag: "콜", text: "부재로 다시 걸어야 하는 추적 콜",
        count: follow.filter((r) => r.call_result === "부재").length,
        to: go.nursing.followups() },
      { tag: "문진", text: "접수 뒤 문진이 비어 있는 환자",
        count: arrived.filter((r) => !r.questionnaire).length,
        to: go.nursing.waiting() },
      /* ⚠ 목업의 「바인딩」(채취는 끝났는데 병변에 연결 안 된 검체)은 못 센다.
         검체를 그 조건으로 거르는 경로가 없다 — 병리 큐는 이미 바인딩된
         것만 준다(status=bound).
         ⚠ 원무 목업의 「예약 확인」 줄은 예약 판(6.1)이 들어올 때 붙인다 */
    ],

    /* ⚠ 접수·배정·문진·콜을 오늘 몇 건 했는지 세어 주는 자리가 없다(8장 1번) */
    done: () => ({ empty: "아직 없습니다" }),

    /* 합치고 나서 달력에 점이 둘이 된다 — 예약과 추적 콜.
       두 과가 따로일 때는 과마다 하나씩이었다 */
    marks: ({ schedule, follow }) => [
      ...schedule.filter((r) => r.scheduled_at)
        .map((r) => ({ date: r.scheduled_at, kind: "예약 있음" })),
      ...follow.filter((r) => r.due_at)
        .map((r) => ({ date: r.due_at, kind: "추적 콜 예정" })),
    ],
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

export default nursing;
