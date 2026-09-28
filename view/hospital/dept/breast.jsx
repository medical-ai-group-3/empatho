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
   * 오늘 내 대기 환자 · 내 담당 전체 두 탭과 월간 예약 캘린더.
   *
   * ⚠ 09-28 전까지 이 큐는 patients()(status=all) 를 불렀다 — **과 전체
   *   목록**이라 유방외과 계정 누구로 들어가도 같은 줄이 「내 환자」로
   *   떴다. 09-27 서버가 primary_staff=me 와 status 를 같이 보게 고쳐서
   *   이제 「내 것」과 「오늘 온 것」을 따로 부를 수 있다.
   *
   * 줄의 접수 시각 · 진행 단계는 today-status 에서 붙인다. 환자 목록
   * 응답에는 그 칸이 없고, 환자마다 오더를 따로 부르면 대기 인원만큼
   * 요청이 난다. today-status 는 오늘 온 오더 전부를 한 번에 준다.
   */
  home: {
    load: () => Promise.all([
      api.waiting(),
      H.soft(api.mine()),
      H.soft(reception.todayStatus()),
      H.soft(reception.schedule(...monthBounds())),
    ]).then(([waiting, mine, status, schedule]) => ({
      waiting: H.rows(waiting),
      mine: H.rows(mine),
      status: lastVisitByPatient(H.rows(status)),
      schedule: H.rows(schedule),
    })),

    primary: { label: "다음 환자 진료", to: go.breast.waiting(),
               need: "breast.waiting.view" },

    queue: ({ waiting, mine, status }) => ({
      title: "내 환자",
      hint: "누르면 환자 상세",
      /* 열 이름. 공통 머리(「구분」·「상태」)로는 이 과 줄이 무엇인지
         안 읽힌다는 말을 들었다(09-28) */
      cols: { chip: "주의", sub: "진행", r: "환자번호 · 접수" },
      tabs: [
        { key: "waiting", name: "오늘 대기",
          empty: "지금 기다리는 환자가 없습니다",
          /* 먼저 온 사람이 위다 — 「다음 환자 진료」와 같은 순서 */
          rows: [...waiting]
            .sort((a, b) => visitKey(status, a).localeCompare(visitKey(status, b)))
            .map((r) => row(r, status.get(String(r.patient_id)))) },
        { key: "mine", name: "담당 전체",
          empty: "배정된 환자가 없습니다",
          rows: mine.map((r) => row(r, null)) },
      ],
    }),

    stuck: ({ mine }) => [
      { tag: "불일치", text: "판정 불일치를 처분하지 않은 내 환자",
        count: mine.filter((r) => r.has_open_discordance).length,
        to: go.breast.patients() },
      { tag: "알레르기", text: "조영제 알레르기 표시가 있는 내 환자",
        count: mine.filter((r) => H.allergy(r)).length,
        to: go.breast.patients() },
      /* ⚠ 목업의 「설명」·「동의」는 못 센다. 결과 설명 기록과 검사 동의는
         표가 없다 */
    ],

    /* 오늘 한 일은 별도 목록으로 제공하지 않는다. 홈의 이 영역은
       공용 Todo(할 일) 카드가 차지한다. */

    marks: ({ schedule }) => (schedule ?? [])
      .filter((row) => row.scheduled_at)
      .map((row) => ({ date: row.scheduled_at, kind: "예약 있음" })),
  },
};

/* 큐 한 줄. visit 은 그 환자의 오늘 오더(today-status 한 줄) — 담당 전체
   탭처럼 오늘 안 온 사람은 null 이라 시각·진행 칸이 빈다 */
function row(r, visit) {
  return {
    id: r.patient_id,
    name: H.nameOf(r),
    no: H.noOf(r),
    meta: H.who(r),
    chip: H.allergy(r) ? "알레르기" : null,
    sub: [visit ? (visit.stage_detail ?? visit.stage) : null,
          r.has_open_discordance ? "판정 불일치" : null].filter(Boolean).join(" · "),
    at: visit ? H.at(visit.visited_at) : null,
    /* 유방외과가 이 줄에서 할 일이 검사 종합 확인이고, 그 화면이 이 과에
       따로 있다(09-23). 권한이 없으면 그 화면이 Locked 로 알려 준다 */
    to: go.breast.review(r.patient_id),
    pid: r.patient_id,
    why: "환자 상세",
  };
}

/* 환자별 오늘 마지막 오더. 서버가 visited_at 순으로 주므로 뒤에 온 것이
   남는다 — 하루에 두 번 접수된 환자는 지금 진행 중인 쪽을 본다 */
function lastVisitByPatient(list) {
  const out = new Map();
  for (const r of list) if (r.patient_id != null) out.set(String(r.patient_id), r);
  return out;
}

/* 정렬 열쇠 — 접수 시각이 없는 줄은 맨 뒤로 */
function visitKey(status, r) {
  return String(status.get(String(r.patient_id))?.visited_at ?? "~");
}

function monthBounds(now = new Date()) {
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return [H.iso(first), H.iso(last)];
}

export default breast;
