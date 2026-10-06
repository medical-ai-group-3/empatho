import { breast as api, reception } from "../api";
import { go } from "../nav";
import * as H from "./home";
import { Chip } from "../lib/Parts";
import { NEXT, PENDING_KEYS, flowOf } from "./breast/flow";

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
 * 진료 흐름(다음 할 일) 판단은 dept/breast/flow.js 한 곳이다.
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
   * 대기 중인 환자(내 담당 · 과 전체 · 오늘 완료) · 진료 흐름(내가 할 일) ·
   * 오늘 예약 · 할 일 · 달력 · 인계.
   *
   * ⚠ 09-28 전까지 이 큐는 patients()(status=all) 를 「내 환자」라는 이름으로
   *   불렀다 — **과 전체 목록**이라 유방외과 누구로 들어가도 같은 줄이었다.
   *   「지금 기다리는 사람」을 보는 자리라 대기로 바꿨다.
   *
   * 줄마다 「다음 할 일」은 서버 GET /surgery/worklist 의 next_step 이다.
   * 그 경로가 없는 서버면 내 담당 대기 몇 명만 환자 상세로 되짚는다
   * (flow.js) — 과 전체 줄은 그때 그 칸이 빈다.
   *
   * 줄의 내원 시각 · 진행 단계는 today-status 에서 붙인다. 환자 목록
   * 응답에는 그 칸이 없고, 환자마다 오더를 따로 부르면 대기 인원만큼
   * 요청이 난다. today-status 는 오늘 온 오더 전부를 한 번에 준다.
   */
  home: {
    load: () => Promise.all([
      api.waiting(),
      H.soft(api.waitingAll()),
      H.soft(api.mine()),
      H.soft(reception.todayStatus()),
      H.soft(reception.schedule(...monthBounds())),
      api.worklist().catch(() => null),
    ]).then(async ([waiting, all, mine, status, schedule, wl]) => {
      const rows = H.rows(waiting);
      const items = wl ? H.rows(wl) : await guessItems(rows);
      return {
        waiting: rows,
        all: H.rows(all),
        mine: H.rows(mine),
        status: lastVisitByPatient(H.rows(status)),
        rawStatus: H.rows(status),
        schedule: H.rows(schedule),
        items: new Map(items.map((it) => [String(it.patient_id), it])),
        itemList: items,
        counts: wl?.counts ?? null,
        guessed: !wl,
      };
    }),

    primary: { label: "다음 환자 진료", to: go.breast.waiting(),
               need: "breast.waiting.view" },

    /* 기본 배치 — 진료 순서대로 읽힌다: 기다리는 사람(큐) 바로 밑에 그
       사람들에게 남은 일(흐름). 가운데는 오늘 예약 · 내 할 일, 오른쪽은
       달력 밑에 인계. 단마다 맨 아래 칸이 남는 높이를 받는다(hospital.css
       .pane > .hcard:last-child) — 큐가 혼자 한 단을 먹어 셋뿐인 줄 밑이
       통째로 비던 것(09-28)을 흐름 칸이 받는다.
       ⚠ 칸 이름이 바뀌었다(stuck → flow). 옛 저장 배치는 아래에서 지운다 */
    /* 09-28 가운데 단을 뒤집었다 — 할 일이 맨 아래라 남는 높이를 다 받아
       빈 상자가 가운데 한 단을 먹었다. 이제 할 일이 위(제 줄만큼)이고,
       남는 높이는 **다가오는 예약**(오늘 남은 것 + 두 주)이 받는다 */
    layout: [["queue", "flow"], ["todo", "side"], ["calendar", "handover"]],

    queue: ({ waiting, all, status, items, rawStatus, itemList }) => ({
      title: "대기 중인 환자",
      hint: "누르면 환자 상세로 이동",
      /* 열 이름. 공통 머리(「구분」·「상태」)로는 이 과 줄이 무엇인지
         안 읽힌다는 말을 들었다(09-28) */
      cols: { chip: "주의", sub: "진행" },
      extra: [{ key: "next", name: "다음 할 일" }, { key: "visit", name: "내원" },
              { key: "doctor", name: "주치의" }],
      tabs: [
        { key: "mine", name: "내 환자",
          empty: "지금 기다리는 내 환자가 없습니다",
          rows: byVisit(waiting, status, items) },
        { key: "all", name: "과 전체",
          empty: "지금 기다리는 환자가 없습니다",
          rows: byVisit(all, status, items) },
        /* 오늘 진료를 마친 사람 — worklist 의 today_stage, 없으면 today-status */
        { key: "done", name: "오늘 완료",
          empty: "오늘 진료를 마친 환자가 아직 없습니다",
          rows: doneToday(itemList, rawStatus) },
      ],
    }),

    /* 진료 흐름 — 내 담당 환자에게 남은 일을 다음 할 일별로 센다. 줄을 누르면
       대기 환자가 그 일만 걸러서 연다(?next=). 결과 대기는 남(영상 · 병리)의
       차례라 세지 않는다. 0 인 줄도 세운다 — 어느 칸이 비었는지가 곧 정보다 */
    flow: (bag) => {
      if (!bag) return { items: [] };
      const count = (k) => bag.counts?.[k]
        ?? bag.itemList.filter((it) => it.next_step === k).length;
      return {
        title: "진료 흐름 · 내가 할 일",
        summary: bag.guessed ? `대기 ${Math.min(bag.waiting.length, GUESS_MAX)}명 기준 추정` : "전체 집계",
        items: PENDING_KEYS.map((k) => ({
          name: NEXT[k].name, count: count(k),
          to: `${go.breast.waiting()}?next=${k}`,
        })),
      };
    },

    /* 다가오는 예약 — 오늘 예약했고 아직 안 온 사람, 그 뒤 두 주 안의 예약.
       내원하면 위 대기로 넘어간다. 오늘 것은 시각, 뒷날 것은 날짜를 앞에 둔다.
       ⚠ 09-28 전에는 오늘 것만이라 한두 줄 밑이 통째로 비었다. 값은 같은
         예약 목록(GET /exam-orders?scheduled_from=…)이고 범위만 두 주 늘렸다 */
    side: ({ schedule }) => {
      const until = H.iso(new Date(Date.now() + UPCOMING_DAYS * 86400000));
      return {
        title: "다가오는 예약",
        empty: "2주 안에 잡힌 예약이 없습니다",
        rows: schedule
          .filter((r) => r.scheduled_at && !r.visited_at && r.order_status !== "cancelled"
            && String(r.scheduled_at).slice(0, 10) <= until
            && (H.isToday(r.scheduled_at) || String(r.scheduled_at).slice(0, 10) > H.iso(new Date())))
          .sort((a, b) => String(a.scheduled_at).localeCompare(String(b.scheduled_at)))
          .map((r) => {
            const pid = r.patient ?? r.patient_id;
            const today = H.isToday(r.scheduled_at);
            return {
              id: r.exam_order_id ?? r.id,
              name: H.nameOf(r),
              meta: H.who(r),
              sub: today ? (H.isPast(r.scheduled_at) ? "오늘 · 시간 지남" : "오늘") : H.at(r.scheduled_at),
              at: today ? H.at(r.scheduled_at) : H.day(r.scheduled_at),
              to: pid != null ? go.breast.review(pid) : null,
            };
          }),
      };
    },

    /* 09-28 「확인이 필요한 것」(stuck)을 뺐다 — 불일치 · 알레르기 두 줄이었고
       이제 흐름 칸(판정 불일치)과 큐 줄의 칩(알레르기)이 말한다.
       ⚠ 예전 주석의 「설명 · 동의는 못 센다」는 틀렸다 — 결과 설명은 리포트의
       explained_at 으로 센다(worklist 의 report_explained). 흐름 칸의
       「설명 대기」가 그것이다. 검사 동의만 여전히 표가 없다 */

    marks: ({ schedule }) => (schedule ?? [])
      .filter((row) => row.scheduled_at)
      .map((row) => ({ date: row.scheduled_at, kind: "예약 있음" })),
  },
};

/* 옛 배치 지우기 — 칸 이름이 바뀌면 Home 의 fit() 이 없어진 칸을 버리고 새
   칸을 끝에 붙이긴 하지만, 큐가 혼자 한 단을 먹던 옛 모양이 그대로 남는다.
   「stuck」이 든 저장 배치는 한 번 지운다(열쇠는 lib/Home.jsx 의 LAYOUT_KEY) */
try {
  const k = "empatho.home.layout.breast";
  if (/"stuck"/.test(localStorage.getItem(k) ?? "")) localStorage.removeItem(k);
} catch { /* 저장소가 막혔으면 지울 것도 없다 */ }

/* worklist 가 없는 서버 — 내 담당 대기를 몇 명만 환자 상세로 되짚는다.
   ⚠ 환자 상세 한 번이 요청 예닐곱 개다. 홈은 30초마다 다시 부르므로
     1분 동안 들고 있고, 많아야 GUESS_MAX 명만 본다 */
const GUESS_MAX = 8;
const GUESS_TTL = 60000;
const guessCache = new Map();

async function guessItems(rows) {
  const now = Date.now();
  const out = await Promise.all(rows.slice(0, GUESS_MAX).map(async (r) => {
    const k = String(r.patient_id);
    const hit = guessCache.get(k);
    if (hit && now - hit.at < GUESS_TTL) return hit.item;
    try {
      const [p, line] = await Promise.all([api.patient(r.patient_id), H.soft(api.timeline(r.patient_id))]);
      const f = flowOf({ p, timeline: H.rows(line) });
      const item = { patient_id: r.patient_id, next_step: f.next?.key ?? null,
                     open_discordance: Boolean(p.open_discordance) };
      guessCache.set(k, { at: now, item });
      return item;
    } catch { return null; }
  }));
  return out.filter(Boolean);
}

/* 큐 한 줄. visit 은 그 환자의 오늘 오더(today-status 한 줄) — 없으면
   worklist 의 last_visit_at, 그것도 없으면 내원 · 진행 칸이 빈다 */
function row(r, visit, it) {
  const at = visit?.visited_at ?? it?.last_visit_at ?? null;
  const next = it?.next_step ? NEXT[it.next_step] : null;
  return {
    id: r.patient_id,
    name: H.nameOf(r),
    no: H.noOf(r),
    meta: H.who(r),
    chip: H.allergy(r) || it?.has_allergy ? "알레르기" : null,
    sub: [H.dots(visit ? (visit.stage_detail ?? visit.stage) : (it?.today_stage ?? null)),
          r.has_open_discordance && it?.next_step !== "discordance" ? "판정 불일치" : null]
      .filter(Boolean).join(" · "),
    /* 다음 할 일 — 내가 손댈 차례면 채움, 남의 차례(결과 대기 · 재진)면 선 */
    next: next
      ? <Chip tone={PENDING_KEYS.includes(it.next_step) ? "fill" : "line"}>{next.name}</Chip>
      : null,
    /* 「09-28 10:20」 — 날짜까지 적는다. 자정을 넘겨 남은 줄이 오늘 온 것처럼
       읽히지 않게 */
    visit: at ? `${H.day(at)} ${H.at(at)}` : null,
    doctor: r.primary_staff_name ?? null,
    /* 유방외과가 이 줄에서 할 일이 검사 종합 확인이고, 그 화면이 이 과에
       따로 있다(09-23). 권한이 없으면 그 화면이 Locked 로 알려 준다 */
    to: go.breast.review(r.patient_id),
    pid: r.patient_id,
    why: "환자 상세",
  };
}

/* 오늘 진료를 마친 사람 — worklist 가 있으면 그 today_stage, 없으면
   today-status 의 stage 글자로 가른다 */
function doneToday(items, status) {
  const done = (v) => /완료/.test(v ?? "") || v === "completed";
  const fromWl = (items ?? []).filter((it) => done(it.today_stage));
  const list = fromWl.length ? fromWl : (status ?? []).filter((r) => done(r.stage));
  return list.map((it) => row(it, null, it.next_step ? it : null));
}

/* 먼저 온 사람이 위다 — 「다음 환자 진료」와 같은 순서 */
function byVisit(list, status, items) {
  return [...list]
    .sort((a, b) => visitKey(status, a).localeCompare(visitKey(status, b)))
    .map((r) => row(r, status.get(String(r.patient_id)), items?.get(String(r.patient_id))));
}

function lastVisitByPatient(list) {
  const out = new Map();
  for (const r of list) if (r.patient_id != null) out.set(String(r.patient_id), r);
  return out;
}

/* 정렬 열쇠 — 접수 시각이 없는 줄은 맨 뒤로 */
function visitKey(status, r) {
  return String(status.get(String(r.patient_id))?.visited_at ?? "~");
}

/* 홈이 받는 예약 범위 — 이달 첫날부터 이달 끝(달력 점)과 오늘 + 두 주
   (다가오는 예약) 가운데 늦은 날까지 */
const UPCOMING_DAYS = 14;

function monthBounds(now = new Date()) {
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const ahead = new Date(now.getFullYear(), now.getMonth(), now.getDate() + UPCOMING_DAYS);
  return [H.iso(first), H.iso(ahead > last ? ahead : last)];
}

export default breast;
