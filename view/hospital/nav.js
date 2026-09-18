/* 화면 등록표 — 어떤 화면이 있고, 무엇을 하는 자리이고, 무슨 권한이 필요한가
 * ────────────────────────────────────────────────────────────────
 *
 * **화면을 더하거나 주소를 바꿀 일이 생기면 이 파일만 고친다.**
 * 상단 메뉴도, 권한에 따라 메뉴를 감추는 것도 여기 표에서 만들어진다.
 *
 * 병리과와 영상의학과는 화면 다섯 장의 구조가 같다. 같은 번호끼리
 * 짝이 맞게 두었으니 한쪽을 고치면 다른 쪽도 같이 보면 된다.
 *
 *   1장  대기 큐      아직 아무도 안 집은 것. 집으면 남의 화면에서 사라진다
 *   2장  업로드       파일을 올리고 AI 분석을 건다. 분석이 여기서 끝난다
 *   3장  판독         원본 + 마스크를 보고 소견을 쓴다. 저장하면 유방외과로
 *   4장  전체 목록    지난 것까지 전부. 찾아보는 자리
 *   5장  판독 정정    이미 확정한 판독을 고친다. 이력이 남는다
 *
 * ⚠ **유방외과는 이 다섯 장과 모양이 다르다.** 집는 절차가 없고(내 환자가
 *   곧 큐다) 올리는 단계도 없다. 대신 검사 오더 · 검체 바인딩 · 수술 결정 ·
 *   불일치 처분이 있다. 그래서 화면 수도 구성도 다르다 — 이걸 담으려고
 *   라우트를 「다섯 장 고정」에서 use 기반으로 바꿨다 (main.jsx 참고).
 */

import { can } from "./perm";

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
const DEPTS = [
  {
    key: "pathology",
    name: "병리과",
    who: { name: "박민재", role: "교수" },
    screens: [
      { key: "", use: "queue", menu: "검체 접수", title: "검체 접수 대기",
        sub: "간호·유방외과가 바인딩을 끝낸 검체가 순서대로 뜹니다. 집으면 다른 선생님 화면에서 사라집니다.",
        need: "pathology.queue.view" },

      { key: "specimens", use: "list", menu: "환자 목록", title: "전체 환자 목록",
        sub: "지난 검체까지 전부 찾아보는 자리입니다. 판독 정정도 여기서 들어갑니다.",
        need: "pathology.list.view" },

      { key: "specimens/:id/upload", use: "upload", menu: "업로드", title: "조직 이미지 업로드",
        sub: "크롭 조직 이미지를 올리고 AI 분석을 겁니다. 분석이 끝나야 판독으로 넘어갑니다.",
        need: "pathology.upload.view", deep: true },

      { key: "read/:id", use: "read", menu: "판독", title: "병리 판독",
        sub: "원본 조직 이미지에 AI 분할 마스크를 얹어 보고 소견을 씁니다. 저장하면 유방외과로 전송됩니다.",
        need: "pathology.read.view", deep: true },

      { key: "read/:id/amend", use: "amend", menu: "판독 정정", title: "병리 판독 정정",
        sub: "이미 확정한 판독을 고칩니다. 옛 값은 지워지지 않고 이력에 남습니다.",
        need: "pathology.amend.view", deep: true },
    ],
  },

  {
    key: "radiology",
    name: "영상의학과",
    who: { name: "김지현", role: "교수" },
    screens: [
      { key: "", use: "queue", menu: "촬영 대기", title: "촬영 대기 큐",
        sub: "유방외과가 낸 오더 중 아직 아무도 집지 않은 것이 뜹니다. 집으면 다른 선생님 화면에서 사라집니다.",
        need: "radiology.queue.view" },

      { key: "patients", use: "list", menu: "환자 목록", title: "전체 환자 목록",
        sub: "지난 검사까지 전부 찾아보는 자리입니다. 판독 정정도 여기서 들어갑니다.",
        need: "radiology.list.view" },

      { key: "studies/:id/upload", use: "upload", menu: "업로드", title: "촬영 업로드",
        sub: "촬영본을 올리고 AI 분석을 겁니다. 분석이 끝나야 판독으로 넘어갑니다.",
        need: "radiology.upload.view", deep: true },

      { key: "read/:id", use: "read", menu: "판독", title: "영상 판독",
        sub: "원본 영상에 AI 오버레이를 얹어 보고 소견을 씁니다. 저장하면 유방외과로 전송됩니다.",
        need: "radiology.read.view", deep: true },

      { key: "read/:id/amend", use: "amend", menu: "판독 정정", title: "영상 판독 정정",
        sub: "이미 확정한 판독을 고칩니다. 새 판독 행이 생기고 옛 행이 그것을 가리킵니다.",
        need: "radiology.amend.view", deep: true },
    ],
  },

  {
    key: "breast",
    name: "유방외과",
    who: { name: "서나영", role: "교수" },
    screens: [
      { key: "", use: "breast.waiting", menu: "대기 환자", title: "대기 환자",
        sub: "내 환자 목록입니다. 병리·영상과 달리 집는 절차가 없습니다 — 주치의로 배정된 환자가 곧 큐입니다.",
        need: "breast.waiting.view" },

      { key: "patients/:id/review", use: "breast.review", menu: "검사 종합", title: "검사 종합 확인",
        sub: "영상과 병리 결과를 함께 놓고 봅니다.",
        need: "breast.review.view", deep: true },

      { key: "patients/:id/decision", use: "breast.decision", menu: "수술 결정", title: "수술 결정",
        sub: "치료 방침을 정하고 리포트를 확정합니다.",
        need: "breast.decision.view", deep: true },

      { key: "discordances/:id", use: "breast.discordance", menu: "판정 불일치", title: "판정 불일치 처분",
        sub: "영상 판정과 병리 확진이 갈린 건입니다. 어느 쪽을 따를지 정합니다.",
        need: "breast.discordance.view", deep: true },
    ],
  },

  {
    key: "reception",
    name: "원무과",
    who: { name: "한지우", role: "주임" },
    screens: [
      { key: "", use: "reception.intake", menu: "접수", title: "접수 · 방문 환자 모니터링",
        sub: "환자를 찾아 접수하면 간호 큐로 넘어갑니다. 검사 종류는 정하지 않습니다 — 의학적 판단이라 유방외과 몫입니다.",
        need: "reception.intake.view" },

      { key: "patients", use: "reception.patients", menu: "환자 목록", title: "환자 목록 · 예약",
        sub: "환자를 찾아 정보를 고치거나 예약을 잡습니다.",
        need: "reception.patients.view" },

      { key: "requests", use: "reception.requests", menu: "예약 확인", title: "예약 확인",
        sub: "앱으로 들어온 예약 신청을 확정합니다. 날짜와 시간만 정합니다.",
        need: "reception.requests.view" },
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
        sub: "계정 승인과 자료 관리는 Django 관리자 화면에서 합니다.",
        need: "admin.console.open" },
    ],
  },

  /* ⚠ 간호과도 유방외과처럼 모양이 다르다. 집는 절차도, 판독도 없다 —
     원무가 접수한 환자를 유방외과 의사에게 넘기고, 추적을 관리한다.
     검체 바인딩(3장)은 화면이 따로 없다 — 유방외과와 같은 팝업을
     1장 안에서 연다(간호과 명세 §3). */
  {
    key: "nursing",
    name: "간호과",
    who: { name: "정다은", role: "간호사" },
    screens: [
      { key: "", use: "nursing.waiting", menu: "내원 대기", title: "내원 대기 · 유방외과 배정",
        sub: "지금 와 있는 환자를 접수 순서대로 보고 유방외과 의사에게 넘깁니다.",
        need: "nursing.waiting.view" },

      { key: "followups", use: "nursing.followups", menu: "추적 관리", title: "추적 대상 관리",
        sub: "BI-RADS 3 확정 환자의 6·12·24개월 추적을 관리합니다.",
        need: "nursing.followup.view" },
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
  return myDepts()[0] ?? HOME;
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

  pathology: {
    queue:  () => P,
    list:   () => `${P}/specimens`,
    upload: (id) => `${P}/specimens/${id}/upload`,
    read:   (id) => `${P}/read/${id}`,
    amend:  (id) => `${P}/read/${id}/amend`,
  },
  radiology: {
    queue:  () => R,
    list:   () => `${R}/patients`,
    upload: (id) => `${R}/studies/${id}/upload`,
    read:   (id) => `${R}/read/${id}`,
    amend:  (id) => `${R}/read/${id}/amend`,
  },

  /* ⚠ 유방외과는 이름이 다르다. queue/list/upload/read/amend 를 억지로
     맞추면 「read 가 뭐였지」를 매번 되묻게 된다 */
  breast: {
    queue:       () => B,
    waiting:     () => B,
    review:      (id) => `${B}/patients/${id}/review`,
    decision:    (id) => `${B}/patients/${id}/decision`,
    discordance: (id) => `${B}/discordances/${id}`,
  },

  /* 원무는 지금 화면이 하나다. 캘린더 · 환자 목록 · 예약 확인이 뒤에 온다 */
  reception: {
    intake:   () => `${ROOT}/reception`,
    patients: () => `${ROOT}/reception/patients`,
    requests: () => `${ROOT}/reception/requests`,
  },

  nursing: {
    waiting:   () => N,
    followups: () => `${N}/followups`,
  },
};
