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

export const CATALOG = [
  ...deptPerms("pathology", "병리"),
  ...deptPerms("radiology", "영상"),

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
