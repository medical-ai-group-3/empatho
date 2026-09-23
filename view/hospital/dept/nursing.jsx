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
    intake: true,

    /* 주 큐의 앞 탭만 진짜다. 나머지는 옆 칸을 채우는 것이라 못 불러도
       화면이 서야 한다 */
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
      arrived: H.rows(arrived), today: H.rows(today), booked: H.rows(booked),
      asks: H.rows(asks), follow: H.rows(follow), schedule: H.rows(schedule),
      bound: H.rows(bound),
      thisWeek: H.rows(thisWeek), tomorrow: H.rows(tomorrow),
    })),

    primary: { label: "문진 · 배정", to: go.nursing.intake(),
               need: "nursing.waiting.view" },

    queue: ({ arrived, today, booked, asks }) => ({
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
            /* ⚠ 위 id 는 **오더 번호**다 — 「최근 본 환자」는 환자 번호로
               담아야 한다(lib/recent.js) */
            pid: r.patient ?? null,
            why: "문진 · 배정",
          })) },

        /* ⚠ **지금 전화할 사람.** 오늘 예약인데 그 시각이 이미 지났고 아직
           안 왔다. 예약 시각과 지금 시각을 견주는 것이라 「몇 분 기다렸나」
           와는 다르다 — 둘 다 서버가 주는 값이다 */
        { key: "late", name: "안 오심",
          empty: "예약 시각이 지난 분이 없습니다",
          rows: booked.filter((r) => H.isPast(r.scheduled_at)).map((r) => ({
            id: r.exam_order_id ?? r.id,
            name: H.nameOf(r),
            no: H.noOf(r),
            meta: H.who(r),
            chip: r.visit_type,
            sub: `예약 ${H.at(r.scheduled_at) ?? "시각 미정"} · 아직 안 오심`,
            at: H.at(r.scheduled_at),
            to: r.patient != null ? go.patient(r.patient) : null,
            /* ⚠ 위 id 는 **오더 번호**다 — 「최근 본 환자」는 환자 번호로
               담아야 한다(lib/recent.js) */
            pid: r.patient ?? null,
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
            /* ⚠ 위 id 는 **오더 번호**다 — 「최근 본 환자」는 환자 번호로
               담아야 한다(lib/recent.js) */
            pid: r.patient_id ?? null,
          })) },

        /* 오늘 오기로 했는데 아직 안 온 사람 전부(시각이 안 지난 것도) */
        { key: "booked", name: "오늘 예약",
          empty: "오늘 남은 예약이 없습니다",
          rows: booked.map((r) => ({
            id: r.exam_order_id ?? r.id,
            name: H.nameOf(r),
            no: H.noOf(r),
            meta: H.who(r),
            chip: r.visit_type,
            sub: "아직 안 오셨습니다",
            at: H.at(r.scheduled_at),
            to: r.patient != null ? go.patient(r.patient) : null,
            /* ⚠ 위 id 는 **오더 번호**다 — 「최근 본 환자」는 환자 번호로
               담아야 한다(lib/recent.js) */
            pid: r.patient ?? null,
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

    /* ── 가운데 위 — 오늘 흐름 ────────────────────────────────
     * 지금 병원 어디에 사람이 몰려 있는지. today-status 의 stage 를 세기만
     * 하면 나오는 값이라 **지어낸 것이 하나도 없다.**
     *
     * ⚠ 단계 이름은 서버가 쓰는 말 그대로다. 옮겨 부르면 서버가 단계를
     *   하나 늘렸을 때 그 사람들이 어느 줄에도 안 잡힌다 */
    flow: ({ today }) => {
      const by = new Map();
      for (const r of today) {
        const k = r.stage || "그 밖";
        by.set(k, (by.get(k) ?? 0) + 1);
      }
      return {
        title: "오늘 흐름",
        summary: `오늘 온 사람 ${today.total}`,
        items: [...by].map(([name, count]) => ({ name, count })),
      };
    },

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

    /* ⚠ 접수·배정·문진·콜을 오늘 몇 건 했는지 세어 주는 자리가 없다(8장 1번) */
    done: () => ({ empty: "아직 없습니다" }),

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
