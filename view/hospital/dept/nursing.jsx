import { nursing as api } from "../api";
import { go } from "../nav";
import * as H from "./home";

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

  /* ── 홈 (docs/mockup/NursingHome.html) ───────────
   *
   * 다섯 과 목업은 본문 마크업이 같고 자료만 다르다. 이 과가
   * 제일 꿉 찬 쪽이라 틀의 기준이다.
   *
   * ⚠ **선생님별 배정 현황은 아직 못 그린다.** `?primary_staff=` 가
   *   "me" 만 받고, 목록 응답에 primary_staff 가 없어 화면에서
   *   나눌 수도 없다. 배정이 간호의 주 업무라 제일 아쉬운 자리다.
   */
  home: {
    /* 추적 콜은 옆 칸(확인이 필요한 것 · 달력)만 채운다. 못 불러도 내원
       대기 목록은 멀쩡히 보여야 한다 */
    load: () => Promise.all([api.waitingArrived(), H.soft(api.followups())])
      .then(([arrived, follow]) => ({
        arrived: H.rows(arrived), follow: H.rows(follow),
      })),

    primary: { label: "문진 · 배정", to: go.nursing.waiting(),
               need: "nursing.waiting.view" },

    queue: ({ arrived }) => ({
      title: "내원한 대기 환자",
      hint: "접수 순 · 순서 고정",
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
      })),
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
         것만 준다(status=bound) */
    ],

    /* ⚠ 배정·문진·콜을 오늘 몇 건 했는지 세어 주는 자리가 없다.
       추적 콜만 called_at 이 남지만 그것도 내 것만 거르지 못한다(8장 1번) */
    done: () => ({ empty: "아직 없습니다" }),

    /* 추적 콜 예정일만 찍는다. 「예약 방문」은 오늘 치만 받을 수 있어서
       (scheduled_on=today) 달에 뿌릴 수가 없다 */
    marks: ({ follow }) => follow
      .filter((r) => r.due_at)
      .map((r) => ({ date: r.due_at, kind: "추적 콜 예정" })),
  },
};

export default nursing;
