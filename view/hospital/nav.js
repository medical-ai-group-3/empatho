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
 */

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
      { key: "", menu: "검체 접수", title: "검체 접수 대기",
        sub: "간호·유방외과가 바인딩을 끝낸 검체가 순서대로 뜹니다. 집으면 다른 선생님 화면에서 사라집니다.",
        need: "pathology.queue.view" },

      { key: "specimens", menu: "환자 목록", title: "전체 환자 목록",
        sub: "지난 검체까지 전부 찾아보는 자리입니다. 판독 정정도 여기서 들어갑니다.",
        need: "pathology.list.view" },

      { key: "specimens/:id/upload", menu: "업로드", title: "조직 이미지 업로드",
        sub: "크롭 조직 이미지를 올리고 AI 분석을 겁니다. 분석이 끝나야 판독으로 넘어갑니다.",
        need: "pathology.upload.view", deep: true },

      { key: "read/:id", menu: "판독", title: "병리 판독",
        sub: "원본 조직 이미지에 AI 분할 마스크를 얹어 보고 소견을 씁니다. 저장하면 유방외과로 전송됩니다.",
        need: "pathology.read.view", deep: true },

      { key: "read/:id/amend", menu: "판독 정정", title: "병리 판독 정정",
        sub: "이미 확정한 판독을 고칩니다. 옛 값은 지워지지 않고 이력에 남습니다.",
        need: "pathology.amend.view", deep: true },
    ],
  },

  {
    key: "radiology",
    name: "영상의학과",
    who: { name: "김지현", role: "교수" },
    screens: [
      { key: "", menu: "촬영 대기", title: "촬영 대기 큐",
        sub: "유방외과가 낸 오더 중 아직 아무도 집지 않은 것이 뜹니다. 집으면 다른 선생님 화면에서 사라집니다.",
        need: "radiology.queue.view" },

      { key: "patients", menu: "환자 목록", title: "전체 환자 목록",
        sub: "지난 검사까지 전부 찾아보는 자리입니다. 판독 정정도 여기서 들어갑니다.",
        need: "radiology.list.view" },

      { key: "studies/:id/upload", menu: "업로드", title: "촬영 업로드",
        sub: "촬영본을 올리고 AI 분석을 겁니다. 분석이 끝나야 판독으로 넘어갑니다.",
        need: "radiology.upload.view", deep: true },

      { key: "read/:id", menu: "판독", title: "영상 판독",
        sub: "원본 영상에 AI 오버레이를 얹어 보고 소견을 씁니다. 저장하면 유방외과로 전송됩니다.",
        need: "radiology.read.view", deep: true },

      { key: "read/:id/amend", menu: "판독 정정", title: "영상 판독 정정",
        sub: "이미 확정한 판독을 고칩니다. 새 판독 행이 생기고 옛 행이 그것을 가리킵니다.",
        need: "radiology.amend.view", deep: true },
    ],
  },
];

export { DEPTS };
export const HOME = DEPTS[0];

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
};
