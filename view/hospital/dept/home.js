/* 과 홈이 쓰는 줄 만들기 — 과마다 자료 모양이 달라도 화면은 하나다
 * ════════════════════════════════════════════════════════════════
 *
 * 배치는 `docs/mockup/*Home.html` 이 정한다. 다섯 과의 본문 마크업이
 * **완전히 같고 자료만 다르다** — 그래서 화면은 lib/Home.jsx 하나고,
 * 여기가 서버 응답을 그 자료 모양으로 바꾸는 자리다.
 *
 *   큐 줄   {id, name, meta, chip, chipTone, sub, at, to}
 *   확인    {tag, text, count, to}
 *   한 일   {id, at, text, to}
 *   달력 점 {date, kind}
 *
 * ⚠ **없는 값은 만들지 않는다.** 서버가 안 주면 그 조각을 빼고, 「—」나
 *   0 으로 채워 있는 것처럼 보이게 하지 않는다.
 *
 * ⚠ **「몇 분 기다렸는지」는 없다.** 목업에 「평균 대기 23분」 「(38′)」 이
 *   있지만 서버가 그 값을 주지 않는다. 요청 시각만 적는다.
 */

/* 「2026-09-21T14:27:31+09:00」 → 「14:27」. 없으면 안 그린다 */
export function at(value) {
  return value ? String(value).slice(11, 16) : null;
}

const SEX = { F: "여", M: "남", female: "여", male: "남" };

/* 큐 줄의 「51 · 여」 — 이름 바로 옆에 온다 */
export function who(r) {
  const sex = r.sex ? (SEX[r.sex] ?? r.sex) : null;
  const age = r.age != null ? String(r.age) : null;
  return [age, sex].filter(Boolean).join(" · ") || null;
}

/* 이름 — 목록마다 칸 이름이 다르다. 없으면 환자번호로라도 부른다.
 *
 * ⚠ **빈 글자도 «없는 것»으로 본다.** `?? ` 로만 받으면 ""가 그대로 통과해
 *   줄에 이름 자리가 통째로 빈다 — 병리 큐가 지금 그렇다. api.js 의
 *   pathSpecimenRow 가 서버가 이미 준 patient_name 을 자기 조회 결과로
 *   덮어쓰는데, 그 조회가 비면 ""가 남는다.
 */
export function nameOf(r) {
  const name = r.patient_name || r.name;
  if (name) return name;
  const id = r.patient ?? r.patient_id;
  return id != null ? `환자 #${id}` : "이름 없음";
}

export function noOf(r) {
  return r.patient_no ?? r.patient_number ?? null;
}

/* 알레르기 — **값이 있다고 말할 때만** 띄운다. 확인한 적 없는 것을
   「없음」으로 찍으면 확인한 것처럼 읽힌다 */
export function allergy(r) {
  const it = r.contrast_allergy
    ?? (r.has_allergy === true ? (r.allergy_note || true) : null);
  if (!it) return null;
  return it === true ? "조영제 알레르기" : String(it);
}

/* 목록 응답이 세 모양으로 온다 — 배열 · {items} · {results}.
   과마다 풀어 쓰면 한 곳만 빠뜨린다.

   ⚠ **총 개수를 같이 들고 온다.** api.js 의 unwrapList 를 안 거치는 목록이
     있어서(nursing.scheduledToday · rad.queue 처럼) 여기서도 얹는다.
     한 쪽 20건이라 배열 길이를 세면 스물에서 멈춘다 — 세는 자리는 `.total`
     을 읽는다. 배열이 이미 들고 있으면 그대로 둔다 */
export function rows(raw) {
  const arr = Array.isArray(raw) ? raw : (raw?.items ?? raw?.results ?? []);
  /* ⚠ 배열로 들어온 것에도 채운다. soft() 가 실패하면 맨 배열 `[]` 을 주는데
     거기엔 total 이 없어서, 세는 자리가 `undefined` 를 그대로 찍었다 */
  if (arr.total === undefined) {
    Object.defineProperty(arr, "total",
      { value: Array.isArray(raw) ? arr.length
        : (raw?.count ?? raw?.total ?? arr.length) });
  }
  return arr;
}

/* ── 검사 진행 점 ──────────────────────────────────────────────
 *
 *   ●  끝남      ◐  하는 중      ○  아직
 *   점 없음      **모른다** — 이 목록으로는 알 수 없다
 *
 * ⚠ **모르는 것을 ○ 로 찍지 않는다.** ○ 는 「아직 안 했다」는 말이고,
 *   그건 확인한 사람만 할 수 있는 말이다.
 *
 * `/patients/today-status` 의 stage 하나가 흐름 전체를 말한다 — 단계가
 * 줄지어 있어서 앞 단계는 끝난 것이 확실하다.
 */
const EXAM = ["촬영", "AI", "판독"];
const STAGE = {
  "접수 대기":         ["none", "none", "none"],
  "영상의학과 대기":   ["none", "none", "none"],
  "영상의학과 촬영중": ["going", "none", "none"],
  "AI 분석중":         ["done", "going", "none"],
};

export function stageSteps(stage) {
  const states = STAGE[stage];
  return states ? EXAM.map((name, i) => [name, states[i]]) : null;
}

/* ── 곁가지 자료 ───────────────────────────────────────────────
 *
 * 홈은 서너 곳을 한꺼번에 부른다. 그걸 Promise.all 로 묶으면 **하나만
 * 죽어도 홈 전체가 오류 화면**이 된다 — 판독 대기가 멀쩡한데 추적 콜
 * 경로가 404 라서 아무것도 못 보는 꼴이다.
 *
 * 그래서 옆 칸을 채우는 호출은 이걸로 감싼다. **주 큐는 감싸지 않는다** —
 * 그건 못 부르면 진짜로 보여 줄 것이 없는 것이라 오류가 맞다.
 *
 * ⚠ 삼키면 그 칸이 「0건」으로 보인다. 권한이 없어서 못 부른 것과 정말
 *   없는 것이 화면에서 같아진다 — 8장 1번(GET /home)이 붙으면 한 번에
 *   받아 오므로 이 함수가 통째로 없어진다.
 */
export function soft(promise) {
  return Promise.resolve(promise).catch(() => []);
}

const pad = (n) => String(n).padStart(2, "0");

export function iso(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/* 오늘인가 — 「오늘 한 일」이 쓴다. 서버가 날짜로 걸러 주지 않아 화면이 센다.
   ⚠ toISOString 을 쓰면 UTC 라 오전 9시 이전이 어제가 된다 */
export function isToday(value) {
  if (!value) return false;
  return String(value).slice(0, 10) === iso(new Date());
}

/* 오늘 며칠인지 · 지금 몇 시인지 — 예약 시각이 지났는지 볼 때 쓴다.
   ⚠ 서버가 주는 두 값(예약 시각 · 지금)을 견주는 것이지, 서버가 안 주는
     「몇 분 기다렸는지」를 만드는 것이 아니다 */
export function isPast(when) {
  if (!when) return false;
  return new Date(String(when)).getTime() < Date.now();
}

/* 오늘 · 이번 주(오늘부터 7일) 안에 드는가 — 추적 기한을 쪼갤 때 쓴다 */
export function dueBucket(when) {
  if (!when) return null;
  const day = String(when).slice(0, 10);
  const today = iso(new Date());
  if (day < today) return "over";
  if (day === today) return "today";
  const week = iso(new Date(Date.now() + 7 * 86400000));
  return day <= week ? "week" : null;
}

/* 제목 옆에 붙는 날짜 — 「2026-09-21 (월)」 */
const DAY = ["일", "월", "화", "수", "목", "금", "토"];

export function today(now = new Date()) {
  return `${iso(now)} (${DAY[now.getDay()]})`;
}

/* ── 달력 ──────────────────────────────────────────────────────
 *
 * 한 달을 요일에 맞춰 돌려준다. 앞뒤 빈 칸까지 채워 일곱씩 떨어지게 —
 * 화면이 다시 세면 달을 넘길 때마다 요일이 밀린다.
 *
 * ⚠ **점은 과가 아는 날짜만** 찍는다. 목업은 「판독 당번 · 학회」를
 *   찍지만 서버에 근무표가 없다. 없는 점은 안 찍는다.
 */
export function monthGrid(year, month) {
  const first = new Date(year, month, 1);
  const days = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < first.getDay(); i += 1) cells.push(null);
  for (let d = 1; d <= days; d += 1) {
    const date = new Date(year, month, d);
    cells.push({ d, iso: iso(date), dow: date.getDay() });
  }
  while (cells.length % 7 !== 0) cells.push(null);
  return { label: `${year}년 ${month + 1}월`, cells };
}

/* 과가 준 `[{date, kind}]` 를 날짜별로 묶는다. 같은 날 둘이면 점도 둘 */
export function byDate(marks = []) {
  const out = new Map();
  marks.forEach((m) => {
    const key = String(m.date ?? "").slice(0, 10);
    if (!key) return;
    const kinds = out.get(key) ?? [];
    if (!kinds.includes(m.kind)) kinds.push(m.kind);
    out.set(key, kinds);
  });
  return out;
}
