import { nursing as nur, path, reception as rec } from "../api";
import { go } from "../nav";
import * as H from "./home";

/* 간호과 설정 — **원무과를 없애고 그 일을 여기 넣었다** (6.1)
 * ════════════════════════════════════════════════════════════════
 *
 * 접수 → 내원 대기 → 호출 → 문진 → 유방외과 배정은 실제로는 환자 한 명을
 * 이어서 다루는 한 줄이다. 따로 두면 중간에 과 탭을 건너뛰어야 했다.
 *
 * 병리·영상의 공통 화면 다섯 장(screens/)을 안 쓴다 — 집는 절차도,
 * 판독도 없다. 검체 바인딩은 화면이 따로 없다(내원 대기 안에서 팝업).
 *
 * ⚠ **권한은 한 줄도 안 바꿨다.** 화면은 여섯 줄 다 열어 두고(nav.js 의
 *   DESK), **쓰는 동작만** 제 열쇠로 잠근다 — 간호는 이름·전화를 못 고치고
 *   (patient_pii 가 NONE) 원무는 추적 콜을 못 남긴다(followup 이 R).
 *   화면이 보이는 것과 쓸 수 있는 것은 거기서 갈린다.
 *
 * ⚠ **api 를 두 벌 합쳐 준다.** 화면들이 `cfg.api.search` · `cfg.api.
 *   waitingArrived` 처럼 제 것만 부른다. 지금 이름이 겹치는 것은 없다 —
 *   겹치면 뒤엣것이 조용히 이기므로 늘릴 때 확인할 것.
 */
const api = { ...rec, ...nur };

export const nursing = {
  key: "nursing",
  name: "간호과",
  api,
  go: go.nursing,

  /* ── 홈 (docs/mockup/NursingHome.html · ReceptionHome.html) ──
   *
   * 두 목업의 본문 마크업이 같아서 합친 뒤에도 화면은 하나다. 다른 것은
   * 왼쪽 주 큐가 **탭 둘**이 된 것뿐이다 — 내원 대기와 오늘 접수.
   * 접수 카드는 원무 목업의 showIntake 자리 그대로 맨 위에 둔다.
   *
   * ⚠ **선생님별 배정 현황은 아직 못 그린다.** `?primary_staff=` 가
   *   "me" 만 받고, 목록 응답에 primary_staff 가 없어 화면에서
   *   나눌 수도 없다. 배정이 이 과의 주 업무라 제일 아쉬운 자리다.
   */
  home: {
    intake: "top",

    /* 내원 대기(현황판 2·3번 칸)만 진짜다. 나머지는 옆 칸을 채우는 것이라
       못 불러도 화면이 서야 한다 */
    load: () => Promise.all([
      api.waitingArrived(),
      H.soft(api.todayStatus()),
      H.soft(api.scheduledToday()),
      H.soft(api.requests()),
      H.soft(api.followups()),
      month(),
      /* 검체 확인 대기 — 간호가 라벨을 확인해야 병리로 넘어간다.
         병리과 큐와 **같은 목록**이다(specimen_pathology 에 간호는 R).
         ⚠ path.queue() 는 줄마다 환자를 한 번씩 더 부른다(api.js 의
           pathSpecimenRow). 큐가 짧아 지금은 견딜 만하지만 늘면 아프다 */
      H.soft(path.queue()),
      week(),
      day(1),
    ]).then(([arrived, today, booked, asks, follow, schedule,
              bound, thisWeek, tomorrow]) => ({
      arrived: H.rows(arrived), today: H.rows(today),
      /* 오늘 이미 접수한 사람의 예약은 뺀다 — 「안 오심」에 계속 뜨던 것(H.notYetCame) */
      booked: H.notYetCame(H.rows(booked), H.rows(arrived), H.rows(today)),
      /* ⚠ 추적은 **아직 걸 회차만** 남긴다 — 서버가 끝난 회차도 같이 줘서
         「기한이 지난 추적 콜」·달력 점에 연결로 끝낸 사람이 계속 셌다 */
      asks: H.rows(asks), follow: H.rows(follow).filter(H.openFollowup),
      schedule: H.rows(schedule),
      bound: H.rows(bound),
      thisWeek: H.rows(thisWeek), tomorrow: H.rows(tomorrow),
    })),

    primary: { label: "문진 · 배정", to: go.nursing.intake(),
               need: "nursing.waiting.view" },

    /* ── 배치 — 환자가 오는 순서대로 위에서 아래로(09-28 재기획) ─────
     *
     *   ① 찾아서 접수 (맨 위 한 줄)
     *   ② 오늘 현황판  1 도착 예정 → 2 접수 대기 → 3 간호·문진
     *                   → 4 검사 진행 → 5 외래 진료
     *   ③ 흐름 밖의 일  전화·예약 확인 | 확인이 필요한 것 · 할 일 | 달력 · 인계
     *
     * ⚠ 예전에는 「예약 · 신청」 탭 셋(안 오심 · 오늘 예약 · 예약 신청)과
     *   현황판이 같은 사람을 두 번 보였다. 오늘 올 사람은 현황판 1번 칸이
     *   맡고, 아래 칸은 **전화로 하는 일**(추적 콜 · 앱 신청 확정)만 남긴다.
     */
    board: ({ today, arrived, booked }) => ({ today, arrived, booked }),

    layout: [["queue"], ["stuck", "todo"], ["calendar", "handover"]],

    queue: ({ follow, asks }) => ({
      title: "전화 · 예약 확인",
      hint: "누르면 그 화면으로",
      cols: { chip: "구분", sub: "할 일", r: "기한" },
      tabs: [
        /* 기한이 지났거나 이번 주 안인 회차만, 급한 순서로 */
        { key: "calls", name: "추적 콜",
          empty: "이번 주에 걸 추적 콜이 없습니다",
          rows: follow
            .filter((r) => H.dueBucket(r.due_at))
            .sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)))
            .map((r) => ({
              id: r.id ?? r.followup_id,
              name: H.nameOf(r),
              chip: { over: "기한 지남", today: "오늘", week: "이번 주" }[H.dueBucket(r.due_at)],
              chipTone: H.dueBucket(r.due_at) === "over" ? "fill" : "line",
              sub: [r.round_no ? `${r.round_no}차 추적 콜` : "추적 콜",
                    r.call_result === "부재" ? "지난번 부재" : null].filter(Boolean).join(" · "),
              at: H.day(r.due_at),
              to: go.nursing.followups(),
              pid: r.patient_id ?? null,
            })) },

        /* 앱으로 들어온 신청 — 날짜·시간을 정해 줘야 한다 */
        { key: "asks", name: "예약 신청",
          empty: "확인할 신청이 없습니다",
          rows: asks.map((r) => ({
            id: r.exam_order_id ?? r.id,
            name: H.nameOf(r),
            no: H.noOf(r),
            meta: H.who(r),
            chip: r.visit_type,
            sub: "앱 신청 · 날짜를 정해야 합니다",
            at: H.at(r.scheduled_at),
            to: go.nursing.reservations(),
            pid: r.patient ?? r.patient_id ?? null,
          })) },
      ],
    }),

    /* **기한이 지난 것이 제일 위다.** 오늘 해야 하는 순서 그대로 내려간다 */
    stuck: ({ arrived, follow, asks, booked, bound }) => {
      const due = (k) => follow.filter((r) => H.dueBucket(r.due_at) === k).length;
      return [
        { tag: "추적 기한", text: "기한이 지난 추적 콜",
          count: due("over"), to: go.nursing.followups() },
        { tag: "안 오심", text: "예약 시각이 지났는데 아직 안 오신 분",
          count: booked.filter((r) => H.isPast(r.scheduled_at)).length,
          to: go.nursing.intake() },
        { tag: "검체", text: "병리가 아직 집지 않은 검체 — 라벨 확인이 남았습니다",
          count: bound.total, to: go.nursing.intake() },
        { tag: "예약 확인", text: "앱으로 들어온 신청 — 날짜·시간을 정해야 합니다",
          count: asks.total, to: go.nursing.reservations() },
        { tag: "추적 오늘", text: "오늘 걸어야 하는 추적 콜",
          count: due("today"), to: go.nursing.followups() },
        { tag: "추적 이번 주", text: "이번 주 안에 걸어야 하는 추적 콜",
          count: due("week"), to: go.nursing.followups() },
        { tag: "콜", text: "부재로 다시 걸어야 하는 추적 콜",
          count: follow.filter((r) => r.call_result === "부재").length,
          to: go.nursing.followups() },
        { tag: "문진", text: "접수 뒤 문진이 비어 있는 환자",
          count: arrived.filter((r) => !r.questionnaire).length,
          to: go.nursing.intake() },
        /* ⚠ **「연락처 없는 환자」는 못 센다.** 그건 서버가 거르는 조건이
           아니라 **화면이 받아 놓고 거르는** 것이라, 한 쪽(20명)만 보고
           세게 된다. 봉투의 count 는 명부 총원이지 전화번호 빈 사람 수가
           아니다 — 틀린 수를 적느니 줄을 안 세운다.
           서버에 `?has_phone=none` 같은 거르개가 생기면 그때 넣는다 */
        /* ⚠ **선생님별 오늘 배정 수는 못 낸다.** 환자 목록 응답
           (PatientListSerializer)에 `primary_staff` 가 없어서 누가 누구
           환자인지 모른다 — 「미배정 n」조차 못 센다. 배정이 이 과의 주
           업무라 제일 아쉬운 자리다(8장 10번) */
      ];
    },

    /* ⚠ 「오늘 한 일」 칸은 **안 둔다.** 접수·배정·문진·콜을 오늘 몇 건
       했는지 세어 주는 자리가 서버에 없어(8장 1번) 늘 비어 있었다.
       done 이 없으면 홈이 그 자리에 할 일을 올린다(lib/Home.jsx) */

    /* ⚠ 「오늘 예약 환자」 칸(side)은 뺐다 — 주 큐의 「오늘 예약」 탭과
       같은 줄이다(09-28 재배치) */

    /* 달력의 날을 누르면 그날 예약 판으로 */
    calTo: (iso) => `${go.nursing.reservations()}?date=${iso}`,

    /* 달력 옆 숫자 둘 — 이번 주 · 내일. 봉투의 count 를 읽어서 스무 건이
       넘어도 정확하다(api.js 의 unwrapList) */
    calNote: ({ thisWeek, tomorrow }) =>
      `이번 주 ${thisWeek.total} · 내일 ${tomorrow.total}`,

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

/* 이번 주(오늘부터 7일) · 며칠 뒤 하루. 달력 옆 숫자가 쓴다.
   ⚠ 좁게 끊어 부른다 — 한 쪽이 20건이라 범위가 넓으면 잘린다 */
function week() {
  const n = new Date();
  return H.soft(api.schedule(H.iso(n), H.iso(new Date(Date.now() + 6 * 86400000))));
}

function day(after) {
  const at = H.iso(new Date(Date.now() + after * 86400000));
  return H.soft(api.schedule(at, at));
}

/* 달력이 쓸 한 달 치 예약. 이번 달 1일부터 말일까지 한 번에 받는다 —
   날짜마다 부르면 서른 번 나간다 */
function month() {
  const n = new Date();
  const first = new Date(n.getFullYear(), n.getMonth(), 1);
  const last = new Date(n.getFullYear(), n.getMonth() + 1, 0);
  return H.soft(api.schedule(H.iso(first), H.iso(last)));
}

export default nursing;
