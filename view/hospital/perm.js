/* 권한 — 관리자가 사람마다 켜고 끄는 스위치 목록
 * ────────────────────────────────────────────────────────────────
 *
 * 이 파일은 **화면이 무엇을 잠글 수 있는지**의 전체 목록이다.
 * 누구에게 무엇을 주는지는 여기서 정하지 않는다. 그건 관리자 화면에서
 * 정하고 서버가 내려준다.
 *
 * 흐름
 *   로그인 → GET /me → { name, role, dept, perms: ["pathology.queue.view", …] }
 *   화면은 그 perms 배열만 보고 켜고 끈다.
 *
 * ⚠ **화면이 직책(role)으로 직접 판단하지 않는다.**
 *   "교수면 저장 가능" 같은 코드를 화면에 넣으면, 관리자가 권한을 바꿔도
 *   화면이 안 따라간다. 화면은 항상 perms 배열만 본다.
 *   role 은 사람 이름 옆에 적는 표시용으로만 쓴다.
 *
 * 관리자 화면 담당에게
 *   아래 CATALOG 가 그대로 「권한 부여 화면의 체크박스 목록」이다.
 *   key 를 서버에 저장하고, 로그인 응답의 perms 로 내려주면 된다.
 */

/* ── 권한 카탈로그 ──────────────────────────────────────────────
 *
 * key      서버에 저장되는 값. 바꾸면 안 된다
 * label    관리자 화면에 보일 한글 이름
 * where    이 권한이 실제로 무엇을 여는지 (팀원이 찾아보라고 적어 둔다)
 */
function deptPerms(dept, name) {
  return [
    { key: `${dept}.queue.view`,    label: `${name} 대기 큐 보기`,
      where: "1장 대기 큐 화면 자체" },
    { key: `${dept}.queue.assign`,  label: `${name} 환자 집기`,
      where: "1장 [다음 환자] 버튼" },
    { key: `${dept}.upload.view`,   label: `${name} 업로드 화면 보기`,
      where: "2장 화면 자체" },
    { key: `${dept}.upload.send`,   label: `${name} 파일 전송`,
      where: "2장 [파일 선택] · 드래그" },
    { key: `${dept}.ai.run`,        label: `${name} AI 분석 시작`,
      where: "2장 [AI 분석 시작] 버튼" },
    { key: `${dept}.ai.view`,       label: `${name} AI 소견 열람`,
      where: "3장 우측 위 AI 소견 패널. 없으면 패널이 아예 안 보인다" },
    { key: `${dept}.read.view`,     label: `${name} 판독 화면 보기`,
      where: "3장 화면 자체" },
    { key: `${dept}.read.draft`,    label: `${name} 임시저장`,
      where: "3장 [임시저장] 버튼" },
    { key: `${dept}.read.finalize`, label: `${name} 판독 확정 (유방외과 전송)`,
      where: "3장 [저장] 버튼. 되돌릴 수 없는 동작이다" },
    { key: `${dept}.list.view`,     label: `${name} 전체 환자 목록 보기`,
      where: "4장 화면 자체" },
    { key: `${dept}.amend.view`,    label: `${name} 판독 정정 화면 보기`,
      where: "5장 화면 자체" },
    { key: `${dept}.amend.save`,    label: `${name} 판독 정정 저장`,
      where: "5장 [저장] 버튼" },
  ];
}

/* 유방외과는 deptPerms 의 열두 줄을 못 쓴다.
   병리·영상은 「대기 큐에서 집어 → 올리고 → 판독」이 같은 모양인데,
   유방외과는 **집는 절차가 없다** (내 환자가 곧 큐다) 고 올리는 단계도
   없다. 대신 오더 발행 · 검체 바인딩 · 수술 결정 · 불일치 처분이 있다.
   모양이 다른 과를 억지로 같은 틀에 넣으면 쓰지 않는 권한이 생긴다. */
const BREAST = [
  { key: "breast.waiting.view",      label: "유방외과 대기 환자 보기",
    where: "1장 화면 자체" },
  { key: "breast.exam.order",        label: "유방외과 영상 검사 오더",
    where: "1장 [검사 오더] — 영상의학과 대기 큐에 새 오더를 만든다" },
  { key: "breast.review.view",       label: "유방외과 검사 종합 확인",
    where: "2장 화면 자체 — 영상·병리 결과를 함께 본다" },
  { key: "breast.decision.view",     label: "유방외과 수술 결정 보기",
    where: "3장 화면 자체" },
  { key: "breast.decision.save",     label: "유방외과 수술 결정 저장",
    where: "3장 [저장] — 되돌릴 수 없다" },
  { key: "breast.report.unlock",     label: "유방외과 리포트 잠금 해제",
    where: "3장 [잠금 해제] — 환자에게 나간 리포트를 다시 연다" },
  { key: "breast.discordance.view",  label: "유방외과 판정 불일치 보기",
    where: "4장 화면 자체 — 영상과 병리 판정이 갈린 건" },
  { key: "breast.discordance.dispose", label: "유방외과 판정 불일치 처분",
    where: "4장 [처분] — 어느 쪽을 따를지 정한다" },
];

/* 원무과 — 다섯 장 틀을 안 쓴다. 집는 절차도 판독도 없고,
   환자를 시스템에 들여보내는 입구다 */
const RECEPTION = [
  { key: "reception.intake.view",   label: "원무 접수 화면 보기",
    where: "1장 화면 자체" },
  { key: "reception.patient.search", label: "원무 환자 검색",
    where: "1장 검색창 — 이름 · 전화 · 생년월일" },
  { key: "reception.patient.create", label: "원무 환자 등록",
    where: "1장 [+] 등록 — 앱을 못 쓰는 환자를 위한 예외 경로" },
  { key: "reception.checkin",       label: "원무 접수하기",
    where: "1장 [접수하기] — 간호 큐에 올린다" },
  { key: "reception.patients.view", label: "원무 환자 목록 보기",
    where: "3장 화면 자체" },
  { key: "reception.patient.edit",  label: "원무 환자 정보 수정",
    where: "3장 오른쪽 [저장] — 성별 · 출생연도 · 알레르기" },
  { key: "reception.reserve",       label: "원무 예약 잡기",
    where: "3장 [예약] · [예약 완료]" },
  { key: "reception.requests.view", label: "원무 예약 확인 화면 보기",
    where: "4장 화면 자체 — 앱으로 들어온 신청" },
  { key: "reception.confirm",       label: "원무 예약 확정",
    where: "4장 [예약 확인] — requested 를 scheduled 로 옮긴다" },
];

/* 관리자 — 권한 하나뿐이다. 관리자 화면 안에서 무엇을 할 수 있는지는
   Django admin 이 auth_user 권한으로 따로 정한다. 여기 것은 「그 문을 열
   수 있는가」만 본다 */
const ADMIN = [
  { key: "admin.console.open", label: "관리자 화면 열기",
    where: "관리자 화면 [관리자 화면 열기] — POST /admin-session 으로 "
         + "Django admin 세션을 받는다. 서버도 role='admin' 을 다시 본다" },
];

/* 간호과 — 유방외과와 마찬가지로 집는 절차·판독이 없다. 대신 원무가
   접수한 환자를 유방외과 의사에게 배정하고, BI-RADS 3 확정 환자의
   추적(6·12·24개월)을 관리한다. 검체 바인딩은 간호과 명세 §3 참고. */
const NURSING = [
  { key: "nursing.waiting.view",     label: "간호과 내원 대기 보기",
    where: "1장 화면 자체" },
  { key: "nursing.waiting.assign",   label: "간호과 유방외과 배정",
    where: "1장 [유방외과 큐로 전송] — patient.primary_staff_id 를 지정한다" },
  { key: "nursing.followup.view",    label: "간호과 추적 대상 관리 보기",
    where: "2장 화면 자체" },
  { key: "nursing.followup.create",  label: "간호과 추적 회차 생성",
    where: "2장 [추적 회차 생성]" },
  { key: "nursing.followup.call",    label: "간호과 안내 콜 기록",
    where: "2장 [안내 콜 기록 저장]" },
];

export const CATALOG = [
  ...deptPerms("pathology", "병리"),
  ...deptPerms("radiology", "영상"),
  ...BREAST,
  ...RECEPTION,
  ...ADMIN,
  ...NURSING,

  /* 검체 바인딩 — 간호과·유방외과 둘이 같은 팝업을 쓴다(§2-4). 과별
     권한이 아니라 **단독 권한 클래스**로 둔다(간호과 명세 §3: "§15
     매트릭스에 섞지 않고 단독 권한 클래스로 막는다"). 영상의학과는
     제외하기로 팀에서 확정했다. */
  { key: "specimen.bind", label: "검체 바인딩",
    where: "간호과 1장 · 유방외과 1장의 [검체 바인딩/신청] 팝업 — 공용 컴포넌트" },

  /* 영상의학과에만 있는 것 — 병리에는 해당 동작이 없다 */
  { key: "radiology.retake",     label: "영상 재촬영 요청",
    where: "2장 [재촬영 요청] 버튼. 새 오더를 만든다" },
  { key: "radiology.lesion.add", label: "영상 병변 직접 추가",
    where: "3장 [병변 추가]. 의사가 박스를 그려 병변을 만든다" },
  { key: "radiology.lesion.fp",  label: "영상 오탐 표시",
    where: "3장 병변 카드 [오탐 표시]" },

  /* 리포트 — 직원과 환자가 같은 /reports 를 쓰고 권한으로만 갈린다.
     서버의 MatrixPermission own_only 와 짝이다.
     셋 중 하나만 주면 된다. 위로 갈수록 넓다 */
  { key: "report.view.all",  label: "리포트 — 전체 환자",
    where: "과 전체의 리포트를 연다" },
  { key: "report.view.dept", label: "리포트 — 우리 과 환자",
    where: "자기 과가 관여한 환자만" },
  { key: "report.view.own",  label: "리포트 — 내 담당 환자만",
    where: "assigned_to 가 나인 것만. 서버 own_only 와 같은 뜻" },
];

/* 빠른 조회용 — key → 카탈로그 항목 */
export const BY_KEY = Object.fromEntries(CATALOG.map((p) => [p.key, p]));

/* ── 지금 로그인한 사람 ────────────────────────────────────────
 *
 * 서버가 내려준 값을 여기 한 곳에 담아 둔다. 화면은 useMe() 로 읽는다.
 * ⚠ 토큰은 여기 두지 않는다. 토큰은 api.js 의 setToken() 이 메모리에만
 *   들고 있다 (localStorage 금지).
 */
let ME = null;
const watchers = new Set();

export function setMe(me) {
  ME = me;
  watchers.forEach((fn) => fn(me));
}

export function getMe() {
  return ME;
}

export function subscribeMe(fn) {
  watchers.add(fn);
  return () => watchers.delete(fn);
}

/* ── 물어보는 자리 ─────────────────────────────────────────────
 *
 * can("pathology.read.finalize")  →  true / false
 *
 * 아직 로그인 응답이 안 온 동안은 **전부 false** 다. 잠깐 버튼이 없다가
 * 생기는 편이, 눌러 놓고 403 을 맞는 것보다 낫다.
 */
export function can(need) {
  if (!need) return true;              // 권한을 안 건 자리는 누구나
  const perms = ME?.perms;
  if (!Array.isArray(perms)) return false;
  return Array.isArray(need)
    ? need.some((k) => perms.includes(k))   // 여럿이면 하나만 있어도 통과
    : perms.includes(need);
}

/* 리포트 범위를 한 낱말로 — 화면에 「내 담당 환자만 보입니다」를 적을 때 */
export function reportScope() {
  if (can("report.view.all"))  return { key: "all",  label: "전체 환자" };
  if (can("report.view.dept")) return { key: "dept", label: "우리 과 환자" };
  if (can("report.view.own"))  return { key: "own",  label: "내 담당 환자" };
  return null;
}

/* ── 목업 기본값 ───────────────────────────────────────────────
 *
 * ⚠ 이것은 **목업에서만** 쓴다. 실제로는 서버가 perms 를 내려준다.
 *   여기 적힌 직책 이름도 우리가 임시로 붙인 것이다 —
 *   실제 account.role 의 영문 코드로 바꾸는 것은 관리자 화면 담당의 몫이다.
 *
 * 정한 기준
 *   전공의는 **확정과 정정을 못 한다.** 되돌릴 수 없고 유방외과로 나가는
 *   동작이라 그렇다. 임시저장까지는 한다
 *   기사는 **판독을 못 한다.** 올리고 분석 거는 데까지다
 */
export function mockPerms(dept, role) {
  const d = dept;
  const base = [`${d}.queue.view`, `${d}.list.view`, `${d}.read.view`];
  const rad = d === "radiology";

  switch (role) {
    case "과장":
    case "교수":
      return [
        ...base, `${d}.queue.assign`, `${d}.upload.view`, `${d}.upload.send`,
        `${d}.ai.run`, `${d}.ai.view`, `${d}.read.draft`, `${d}.read.finalize`,
        `${d}.amend.view`, `${d}.amend.save`,
        ...(rad ? ["radiology.retake", "radiology.lesion.add", "radiology.lesion.fp"] : []),
        "report.view.all",
      ];
    case "전문의":
      return [
        ...base, `${d}.queue.assign`, `${d}.upload.view`, `${d}.upload.send`,
        `${d}.ai.run`, `${d}.ai.view`, `${d}.read.draft`, `${d}.read.finalize`,
        `${d}.amend.view`, `${d}.amend.save`,
        ...(rad ? ["radiology.retake", "radiology.lesion.add", "radiology.lesion.fp"] : []),
        "report.view.dept",
      ];
    case "전공의":
      return [
        ...base, `${d}.queue.assign`, `${d}.upload.view`, `${d}.upload.send`,
        `${d}.ai.run`, `${d}.ai.view`, `${d}.read.draft`,
        ...(rad ? ["radiology.lesion.fp"] : []),
        "report.view.own",
      ];
    case "기사":
      return [
        `${d}.queue.view`, `${d}.queue.assign`, `${d}.upload.view`,
        `${d}.upload.send`, `${d}.ai.run`, `${d}.list.view`,
        ...(rad ? ["radiology.retake"] : []),
      ];
    default:                                   // 열람
      return [...base, `${d}.ai.view`, "report.view.own"];
  }
}
