/* 화면 등록표 — 어떤 화면이 있고, 무엇을 하는 자리이고, 무슨 권한이 필요한가
 * ────────────────────────────────────────────────────────────────
 *
 * **화면을 더하거나 주소를 바꿀 일이 생기면 이 파일만 고친다.**
 * 상단 메뉴도, 권한에 따라 메뉴를 감추는 것도 여기 표에서 만들어진다.
 *
 * 병리과와 영상의학과는 화면 1~4장의 구조가 같다. 같은 번호끼리
 * 짝이 맞게 두었으니 한쪽을 고치면 다른 쪽도 같이 보면 된다.
 *
 *   1장  대기 큐      아직 아무도 안 집은 것. 집으면 남의 화면에서 사라진다
 *   2장  업로드       파일을 올리고 AI 분석을 건다. 분석이 여기서 끝난다
 *   3장  판독         원본 + 마스크를 보고 소견을 쓴다. 저장하면 유방외과로
 *   4장  전체 목록    지난 것까지 전부. 찾아보는 자리
 *
 * ⚠ **5장(판독 정정)은 영상의학과에만 있다.** 병리는 확정 사양서 §8-2로
 *   정정 경로를 두지 않기로 했다 — 확정 후 오류는 새 검체로 처리한다.
 *
 * ⚠ **유방외과는 이 다섯 장과 모양이 다르다.** 집는 절차가 없고(내 환자가
 *   곧 큐다) 올리는 단계도 없다. 대신 검사 오더 · 검체 바인딩 · 수술 결정 ·
 *   불일치 처분이 있다. 그래서 화면 수도 구성도 다르다 — 이걸 담으려고
 *   라우트를 「다섯 장 고정」에서 use 기반으로 바꿨다 (main.jsx 참고).
 */

import { can, getMe } from "./perm";

export const HOSPITAL = "미래 대학병원";
export const PRODUCT = "EMPATHO";
export const ROOT = "/hospital";

/* ── 부서 ──────────────────────────────────────────────────────
 *
 * key      주소에 쓰이는 이름 · 권한 키의 앞머리와 같다
 * name     화면에 보일 이름
 * who      지금 로그인한 사람 (목업. 실제로는 GET /me)
 * screens  아래 표
 *
 * screens 의 각 줄
 *   key    라우트 조각. "" 면 그 부서의 첫 화면
 *   use    **어느 화면 뼈대를 쓰는가.** main.jsx 의 SCREENS 표에 있는 이름.
 *          과마다 화면 수와 구성이 다를 수 있어서 위치가 아니라 이름으로
 *          고른다 — 전에는 «다섯 장이 이 순서»라고 박아 두었는데, 그러면
 *          다섯 장이 아닌 과를 못 넣는다
 *   menu   상단 메뉴에 보일 짧은 이름
 *   title  화면 제목
 *   sub    한 줄 설명 — **이 화면이 무엇을 하는 자리인지**
 *   need   이 화면을 열 수 있는 권한. 없으면 메뉴에서 감춘다
 *   deep   주소에 :id 가 들어가는 화면이라 메뉴에 안 띄운다
 */
/* 간호과 사람의 열쇠. 원무 열쇠든 간호 열쇠든 **하나만 있어도 이 과
   사람**이다 — 원무는 과가 아니라 간호과가 하는 일 중 하나다.
   can() 이 배열을 받아 하나만 있으면 통과시킨다(perm.js) */
export const DESK = ["reception.intake.view", "nursing.waiting.view"];

const DEPTS = [
  /* ⚠ **원무과를 없애고 그 일을 간호과에 넣었다**(6.1). 접수 → 내원 대기 →
     호출 → 문진 → 유방외과 배정은 실제로는 환자 한 명을 이어서 다루는 한
     줄인데, 따로 두면 중간에 과 탭을 건너뛰어야 했다. 작은 검진 기관에서는
     같은 사람이 둘 다 한다.

     이름은 **간호과** 하나다. 「접수·간호」처럼 둘을 병기하면 아직 두 과인
     것처럼 읽힌다 — 원무는 과가 아니라 간호과가 하는 일 중 하나다.

     **한 과면 화면도 한 벌이다.** 여섯 줄 전부 DESK 열쇠로 연다 — 접수만
     하는 사람도 내원 대기를 보고, 간호만 하는 사람도 예약 판을 본다.
     서버 권한이 아직 `reception.*` 과 `nursing.*` 로 완전히 갈려 있어
     (RECEPTION_PERMS · NURSING_PERMS 가 안 겹친다) 한쪽 열쇠만 걸면 합친
     과가 사람마다 반쪽으로 보인다.

     ⚠ **보는 것과 하는 것은 다르다.** 화면 안의 단추는 제 열쇠로 그대로
       잠긴다(useCan). 서버도 MATRIX 로 또 막는다 — 간호는 patient_pii 가
       NONE 이라 이름·전화를 못 고치고, 원무는 followup 이 R 이라 추적 콜을
       못 남긴다. 화면이 보이는 것과 쓸 수 있는 것은 여기서 갈린다.

     ⚠ 과 key 는 `nursing` 이다. 주소가 바뀐 것은 원무 쪽 세 화면뿐이다
     (`/hospital/reception/*` → `/hospital/nursing/*`). */
  {
    key: "nursing",
    name: "간호과",
    who: { name: "정다은", role: "간호사" },
    screens: [
      { key: "", use: "home", menu: "홈", title: "홈", need: DESK },

      { key: "intake", use: "reception.intake", menu: "접수", title: "접수",
        need: DESK },

      { key: "waiting", use: "nursing.waiting", menu: "내원 대기", title: "내원 대기",
        need: DESK },

      { key: "patients", use: "reception.patients", menu: "환자 목록", title: "환자 목록",
        need: DESK },

      /* 예약 판. 앱 신청 확인은 화면을 따로 안 두고 **이 판 안의 탭**이다 —
         둘 다 예약이고 신청은 「앱에서 들어온 것」일 뿐이다. 화면 줄이
         일곱이 되면 내비게이터 둘째 줄이 꽉 찬다(6.1) */
      { key: "reservations", use: "reception.reservations", menu: "예약 판", title: "예약 판",
        need: DESK },

      { key: "followups", use: "nursing.followups", menu: "추적 관리", title: "추적 관리",
        need: DESK },
    ],
  },
  {
    key: "radiology",
    name: "영상의학과",
    who: { name: "김지현", role: "교수" },
    screens: [
      { key: "", use: "home", menu: "홈", title: "홈",
        need: "radiology.queue.view" },

      { key: "queue", use: "queue", menu: "촬영 대기", title: "촬영 대기",
        need: "radiology.queue.view" },

      { key: "patients", use: "list", menu: "환자 목록", title: "환자 목록",
        need: "radiology.list.view" },

      { key: "studies/:id/upload", use: "upload", menu: "업로드", title: "업로드",
        need: "radiology.upload.view", deep: true },

      { key: "read/:id", use: "read", menu: "판독", title: "판독",
        need: "radiology.read.view", deep: true },

      { key: "read/:id/amend", use: "amend", menu: "판독 정정", title: "판독 정정",
        need: "radiology.amend.view", deep: true },
    ],
  },

  {
    key: "pathology",
    name: "병리과",
    who: { name: "박민재", role: "교수" },
    screens: [
      { key: "", use: "home", menu: "홈", title: "홈",
        need: "pathology.queue.view" },

      { key: "queue", use: "queue", menu: "검체 접수", title: "검체 접수",
        need: "pathology.queue.view" },

      { key: "specimens", use: "list", menu: "환자 목록", title: "환자 목록",
        need: "pathology.list.view" },

      { key: "specimens/:id/upload", use: "upload", menu: "업로드", title: "업로드",
        need: "pathology.upload.view", deep: true },

      { key: "read/:id", use: "read", menu: "판독", title: "판독",
        need: "pathology.read.view", deep: true },

      /* 판독 정정(5장) 없음 — 확정 사양서 §8-2, 병리는 정정 경로를
         두지 않는다. 서버에 route 자체가 없다 */
    ],
  },

  {
    key: "breast",
    name: "유방외과",
    who: { name: "서나영", role: "교수" },
    screens: [
      { key: "", use: "home", menu: "홈", title: "홈",
        need: "breast.waiting.view" },

      { key: "waiting", use: "breast.waiting", menu: "대기 환자", title: "대기 환자",
        need: "breast.waiting.view" },

      { key: "patients", use: "breast.patients", menu: "전체 환자", title: "전체 환자",
        need: "breast.waiting.view" },

      { key: "patients/:id/review", use: "breast.review", menu: "검사 종합", title: "검사 종합",
        need: "breast.review.view", deep: true },

      { key: "patients/:id/decision", use: "breast.decision", menu: "수술 결정", title: "수술 결정",
        need: "breast.decision.view", deep: true },

      { key: "discordances/:id", use: "breast.discordance", menu: "판정 불일치", title: "판정 불일치",
        need: "breast.discordance.view", deep: true },
    ],
  },

  /* 관리자 — 화면이 하나뿐이고 그 하나도 Django admin 으로 넘기는 자리다.
     우리가 관리자 화면을 짓지 않기로 했기 때문이다. 그래도 과 하나로 두는
     이유는, 그래야 메뉴 · 권한 · 첫 화면(homeDept)이 전부 지금 틀대로
     굴러가고 admin 만 따로 다루는 코드가 안 생긴다 */
  {
    key: "admin",
    name: "관리자",
    screens: [
      { key: "", use: "admin.console", menu: "관리자", title: "관리자",
        need: "admin.console.open" },
    ],
  },

];

export { DEPTS };
export const HOME = DEPTS[0];

/* 회원가입 폼의 부서 선택지 — 위 DEPTS 와 다른 목록이다.
   DEPTS 는 「화면이 있는 과」만 담는 라우팅 표라 원무·간호가 없다.
   가입은 병원 전체 직원이 하는 것이라 다섯 과 모두 있어야 한다.

   ⚠ key 는 화면 라우팅 키(breast)가 아니라 signup_staff 의 role
   값이다 (2026-09-16 백엔드 확인) — 유방외과가 "surgery" 다. */
export const STAFF_DEPTS = [
  /* ⚠ **원무과는 화면에선 없어졌지만 여기엔 남는다.** 이 목록은 가입
     폼의 선택지이고 key 는 서버의 `account.role` 값이다 — 서버가 아직
     `reception` 역할을 쓰고 `RECEPTION_PERMS` 를 그 역할에 준다.
     여기서 빼면 원무 직원이 가입을 못 한다. 서버가 역할을 합치면
     그때 같이 뺀다 */
  { key: "reception", name: "원무과" },
  { key: "nursing",   name: "간호과" },
  { key: "radiology", name: "영상의학과" },
  { key: "surgery",   name: "유방외과" },
  { key: "pathology", name: "병리과" },
];

export function findDept(key) {
  return DEPTS.find((d) => d.key === key) ?? null;
}

export function deptPath(d) {
  return `${ROOT}/${d.key}`;
}

export function screenPath(d, s) {
  return s.key ? `${ROOT}/${d.key}/${s.key}` : `${ROOT}/${d.key}`;
}

/* 상단 메뉴에 띄울 화면만 — :id 가 들어가는 화면은 뺀다 */
export function menuScreens(d) {
  return d.screens.filter((s) => !s.deep);
}

/* ── 내가 갈 수 있는 곳 ────────────────────────────────────────
 *
 * 화면이 하나라도 열리면 그 과는 보인다. 권한이 하나도 없는 과는 아예
 * 안 띄운다 — 눌러 봐야 「열람 권한이 없습니다」만 나온다.
 */
export function myDepts() {
  return DEPTS.filter((d) => d.screens.some((s) => can(s.need)));
}

/* 첫 화면으로 갈 곳.
 *
 * ⚠ **DEPTS[0] 로 고정하면 안 된다.** 그러면 원무 계정이 로그인하자마자
 *   병리과로 떨어진다. 그 과에는 권한이 없어 메뉴가 비고, 갈 수 있는 과가
 *   하나뿐이라 과 전환 드롭다운도 안 뜬다(Top.jsx) — 주소를 직접 치지
 *   않는 한 빠져나올 수가 없다.
 *
 * 권한이 하나도 없으면 HOME 으로 떨어뜨린다. 거기서 「열람 권한이
 * 없습니다」를 보는 편이 빈 화면보다 낫다.
 */
export function homeDept() {
  /* 로그인 응답의 소속을 먼저 따른다. 백엔드 배포본마다 dept ·
     department · dept_name 중 어느 칸을 내려줄지 달랐고, 한글 과명도
     그대로 오는 계정이 있다. 그 차이 때문에 인식하지 못하면 DEPTS의
     첫 항목(pathology)으로 떨어졌다. 여기서 모두 라우트 키로 맞춘다. */
  const me = getMe() ?? {};
  const declared = me.dept || me.department || me.dept_key || me.dept_name || me.role;
  const key = deptKey(declared) ?? deptFromPerms(me.perms);
  const own = key ? findDept(key) : null;
  /* 소속은 권한 목록보다 우선한다. 실제 서버에서 화면별 perms가 아직
     늦게 내려오거나 일부만 내려와도, 원무과가 DEPTS 첫 항목인 병리과로
     떨어지면 안 된다. 소속 대시보드에서 권한이 없는 동작만 따로 막는다. */
  if (own) return own;
  return myDepts()[0] ?? HOME;
}

/* 서버 코드·한글 표시명·예전 surgery 코드를 모두 화면 라우트 키로 번역한다. */
function deptKey(value) {
  const raw = String(value ?? "").trim().toLowerCase();
  const names = {
    pathology: "pathology", "병리": "pathology", "병리과": "pathology",
    radiology: "radiology", "영상의학": "radiology", "영상의학과": "radiology",
    breast: "breast", surgery: "breast", "유방외과": "breast",
    /* 원무과는 없어지고 그 일이 간호과로 갔다(6.1). 계정 소속이
       「원무과」로 와도 간호과로 보낸다 — 안 그러면 첫 화면을 못 찾는다 */
    reception: "nursing", "원무": "nursing", "원무과": "nursing",
    nursing: "nursing", "간호": "nursing", "간호과": "nursing",
    admin: "admin", "관리자": "admin",
  };
  return names[raw] ?? null;
}

/* 소속 칸이 아직 없는 서버도 화면별 권한은 내려줄 수 있다. 그때는
   권한 앞머리에서 가장 많이 나타나는 과를 소속으로 쓴다. */
function deptFromPerms(perms) {
  if (!Array.isArray(perms)) return null;
  const counts = new Map();
  for (const permission of perms) {
    const key = deptKey(String(permission).split(".")[0]);
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

/* ── 주소 만들기 ───────────────────────────────────────────────
 *
 * 화면에서 주소 문자열을 직접 쓰지 않는다. 항상 이 함수를 통한다.
 * 주소가 바뀌면 여기만 고치면 된다.
 *
 *   go.pathology.upload("s-1")  →  /hospital/pathology/specimens/s-1/upload
 *   go.radiology.read("st-9")   →  /hospital/radiology/read/st-9
 */
const P = `${ROOT}/pathology`;
const R = `${ROOT}/radiology`;
const B = `${ROOT}/breast`;
const N = `${ROOT}/nursing`;

export const go = {
  /* ⚠ 과 바깥이다. 사람은 과에 딸린 것이 아니라서 /hospital/me 로 둔다 */
  me: () => `${ROOT}/me`,

  /* 환자 상세도 과 바깥이다. 다섯 과가 같은 화면을 보고, 홈의 환자 줄이
     전부 여기로 온다 (5.2 · 6.5) */
  patient: (id) => `${ROOT}/patients/${id}`,

  /* ⚠ 과의 맨 앞(`${P}` 처럼 과 주소 그대로)은 이제 **홈**이다. 일하던
     화면들은 이름 있는 주소로 내려갔다 — 여기 안 고치면 「촬영 대기」를
     눌렀는데 홈이 뜬다 */
  pathology: {
    home:   () => P,
    queue:  () => `${P}/queue`,
    list:   () => `${P}/specimens`,
    upload: (id) => `${P}/specimens/${id}/upload`,
    read:   (id) => `${P}/read/${id}`,
    /* amend 없음 — 확정 사양서 §8-2, 병리는 정정 경로를 두지 않는다 */
  },
  radiology: {
    home:   () => R,
    queue:  () => `${R}/queue`,
    list:   () => `${R}/patients`,
    upload: (id) => `${R}/studies/${id}/upload`,
    read:   (id) => `${R}/read/${id}`,
    amend:  (id) => `${R}/read/${id}/amend`,
  },

  /* ⚠ 유방외과는 이름이 다르다. queue/list/upload/read/amend 를 억지로
     맞추면 「read 가 뭐였지」를 매번 되묻게 된다 */
  breast: {
    home:        () => B,
    queue:       () => `${B}/waiting`,
    waiting:     () => `${B}/waiting`,
    patients:    () => `${B}/patients`,
    review:      (id) => `${B}/patients/${id}/review`,
    decision:    (id) => `${B}/patients/${id}/decision`,
    discordance: (id) => `${B}/discordances/${id}`,
  },

  /* 간호과 — 원무 일도 여기 있다(6.1). 원무 쪽 화면도 이 주소를 쓴다.
     ⚠ go.reception 은 없앴다. 두 이름을 남겨 두면 어느 쪽이 진짜인지
       매번 헷갈리고, 한쪽만 고치는 일이 생긴다 */
  nursing: {
    home:      () => N,
    intake:    () => `${N}/intake`,
    waiting:   () => `${N}/waiting`,
    patients:  () => `${N}/patients`,
    reservations: () => `${N}/reservations`,
    followups: () => `${N}/followups`,
  },
};
