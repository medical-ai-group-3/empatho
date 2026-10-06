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
   * 선생님별 배정 현황은 **접수 화면 오른쪽**(Waiting.jsx 의 Load)이 그린다 —
   * today-status 줄마다 handed_to · stage_code 가 실려 와서 센다. 홈에 또
   * 그리면 같은 수가 두 군데라 여기는 「배정 대기 n」 한 줄만 둔다(stuck).
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

    /* 09-28 — 가장 넓은 왼쪽 단은 **지금 처리할 일(확인 필요)**. 「전화 · 예약
       확인」은 비어 있는 날이 많아 넓은 자리를 차지하면 빈 상자만 커졌다 —
       가운데 위로 옮겨 제 높이만 쓰게 한다 */
    layout: [["stuck"], ["queue", "todo"], ["calendar", "handover"]],

    queue: ({ follow, asks }) => ({
      title: "전화 · 예약 확인",
      hint: "누르면 해당 화면으로 이동합니다",
      /* ⚠ 09-28(최종) 이 칸은 가운데 좁은 단(1280 에서 360px)이라 오른쪽 끝
         열이 눌려 날짜가 「09-/21」로 꺾였다. 칩은 짧게(지남 · 오늘 · 이번 주),
         날짜는 한 줄 요약 안으로 — 요약 열은 두 줄까지 접히는 자리다.
         오른쪽 끝에는 누르는 표시(›)만 남는다 */
      cols: { chip: "기한", sub: "내용", r: "" },
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
              chip: { over: "지남", today: "오늘", week: "이번 주" }[H.dueBucket(r.due_at)],
              chipTone: H.dueBucket(r.due_at) === "over" ? "fill" : "line",
              sub: [r.round_no ? `${r.round_no}회차` : "추적",
                    r.due_at && `${H.day(r.due_at)} 예정`,
                    r.call_result === "부재" ? "지난번 부재" : null].filter(Boolean).join(" · "),
              /* 그 회차를 오른쪽에 펴 둔 채로 연다(Followups.jsx 가 ?followup= 을 읽는다) */
              to: `${go.nursing.followups()}?followup=${r.followup_id ?? r.id}`,
              pid: r.patient_id ?? null,
            })) },

        /* 앱으로 들어온 신청 — 날짜·시간을 정해 줘야 한다 */
        { key: "asks", name: "예약 신청",
          empty: "확인할 신청이 없습니다",
          /* 요약은 **희망 일시**다(예전엔 시각만 적어 어느 날인지 몰랐다).
             환자번호 · 방문 구분은 뺐다 — 좁은 단에서 열이 넘쳤다. 예약 관리에서 본다 */
          rows: asks.map((r) => ({
            id: r.exam_order_id ?? r.id,
            name: H.nameOf(r),
            meta: H.who(r),
            sub: r.scheduled_at ? `희망 ${H.day(r.scheduled_at)} ${H.at(r.scheduled_at)}` : "희망일 없음",
            /* ⚠ 예약 판이 아니라 왼쪽 「앱 신청」 줄을 펴서 연다 — 판만 열리면
               어느 신청인지 다시 찾아야 했다 */
            to: `${go.nursing.reservations()}?tab=requests`,
            pid: r.patient ?? r.patient_id ?? null,
          })) },
      ],
    }),

    /* **기한이 지난 것이 제일 위다.** 오늘 해야 하는 순서 그대로 내려간다 */
    stuck: ({ arrived, follow, asks, booked, bound }) => {
      const due = (k) => follow.filter((r) => H.dueBucket(r.due_at) === k).length;
      return [
        /* 09-28(최종) 문장 끝을 맞췄다 — 몇 줄은 「…합니다」로 끝나고 몇 줄은
           이름씨로 끝나 한 목록이 두 말투였다. 전부 「무엇 — 왜」의 이름씨 */
        { tag: "추적 기한", text: "기한이 지난 추적 콜",
          count: due("over"), to: go.nursing.followups() },
        { tag: "미내원", text: "예약 시간이 지났는데 아직 내원하지 않은 환자",
          count: booked.filter((r) => H.isPast(r.scheduled_at)).length,
          to: go.nursing.intake() },
        { tag: "검체", text: "라벨을 확인할 검체 — 병리과 접수 전",
          count: bound.total, to: `${go.nursing.intake()}?tab=specimen` },
        { tag: "예약 확인", text: "날짜 · 시간을 정할 앱 예약 신청",
          count: asks.total, to: `${go.nursing.reservations()}?tab=requests` },
        { tag: "추적 오늘", text: "오늘 걸어야 하는 추적 콜",
          count: due("today"), to: go.nursing.followups() },
        { tag: "추적 이번 주", text: "이번 주 안에 걸어야 하는 추적 콜",
          count: due("week"), to: go.nursing.followups() },
        { tag: "재통화", text: "부재로 다시 걸어야 하는 추적 콜",
          count: follow.filter((r) => r.call_result === "부재").length,
          to: go.nursing.followups() },
        { tag: "문진", text: "접수 후 문진이 비어 있는 환자",
          count: arrived.filter((r) => !r.questionnaire).length,
          to: `${go.nursing.intake()}?tab=q` },
        /* 09-28 문진은 끝났는데 아직 유방외과로 안 보낸 사람. 선생님별 수는
           접수 화면 오른쪽 「배정 현황(오늘)」이 센다 */
        { tag: "배정", text: "문진을 마치고 유방외과 배정을 기다리는 환자",
          count: arrived.filter((r) => r.questionnaire).length,
          to: `${go.nursing.intake()}?tab=assign` },
        /* ⚠ **「연락처 없는 환자」는 못 센다.** 그건 서버가 거르는 조건이
           아니라 **화면이 받아 놓고 거르는** 것이라, 한 쪽(20명)만 보고
           세게 된다. 봉투의 count 는 명부 총원이지 전화번호 빈 사람 수가
           아니다 — 틀린 수를 적느니 줄을 안 세운다.
           서버에 `?has_phone=none` 같은 거르개가 생기면 그때 넣는다 */
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
