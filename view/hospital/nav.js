/* 화면 표 — **이 파일이 병원 웹의 중심이다.**
 *
 * 화면이 여기 적혀 있고 상단 메뉴 · 라우팅 · 빵부스러기가 이 표에서
 * 만들어진다. 화면을 더하려면 줄 하나를 더하면 된다.
 *
 * ── 주소가 명세를 따른다 ─────────────────────────────────────
 * 병리과 화면 명세(2026-09-14)의 라우트를 그대로 옮겼다. 검체 번호가
 * **주소에 들어간다** — 물음표 뒤가 아니라 경로다. 그래야 주소만으로
 * 「어느 검체의 판독인가」가 드러나고, 링크를 주고받을 수 있다.
 *
 *   명세            우리 주소
 *   /               /hospital/pathology
 *   /specimens      /hospital/pathology/specimens
 *   /specimens/:id/upload   …/specimens/:id/upload
 *   /read/:id       …/read/:id
 *   /read/:id/amend …/read/:id/amend
 *
 * 앞에 /hospital/pathology 를 붙인 것은 부서가 늘어날 자리를 남겨 둔
 * 것이다. 명세는 병리과 문서 하나라 그 안에서 / 가 곧 병리다.
 *
 * ── 지금은 병리과만 있다 ─────────────────────────────────────
 * 부서를 더할 때는 DEPTS 에 덩어리 하나, main.jsx 의 라우트 한 줄이다.
 */

export const HOSPITAL = "미래 대학병원";
export const PRODUCT  = "EMPATHO";
export const ROOT     = "/hospital";

/* 부서. 상단바(lib/Top)가 findDept 로 찾아 쓴다 */
const DEPTS = [
  {
    key: "pathology", name: "병리과", en: "PATHOLOGY",
    who: { name: "박민재", role: "교수" },
    note: "검체 · 슬라이드 · AI 분석",
    screens: [
      { key: "",          menu: "검체 접수", title: "검체 접수 대기", page: 21 },
      { key: "specimens", menu: "환자 목록", title: "전체 환자 목록", page: 24 },
    ],
  },
];

export const HOME = DEPTS[0];

export const deptPath   = (d) => `${ROOT}/${d.key}`;
export const screenPath = (d, s) => (s.key ? `${deptPath(d)}/${s.key}` : deptPath(d));
export const findDept   = (key) => DEPTS.find((d) => d.key === key);

/* 화면 사이를 오갈 때 쓴다. 주소를 손으로 적으면 나중에 ROOT 를 바꿀 때
   놓치는 자리가 생긴다.
   ⚠ 업로드 · 판독 · 정정은 **상단 메뉴에 없다.** 검체 하나를 고른 뒤에만
     갈 수 있는 곳이라, 메뉴에 두면 「어느 검체?」가 빠진 채로 열린다. */
const P = `${ROOT}/pathology`;
export const go = {
  queue:     ()   => P,
  list:      ()   => `${P}/specimens`,
  upload:    (id) => `${P}/specimens/${id}/upload`,
  read:      (id) => `${P}/read/${id}`,
  amend:     (id) => `${P}/read/${id}/amend`,
};
