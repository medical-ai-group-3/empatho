/* 처방 입력의 값 규칙 — components/Prescription.jsx 가 그린다.
 * 서버 계약: core/serializers/prescription.py PrescriptionDrugRowSerializer
 * (times = ["HH:MM", …] · 겹침 없음 · 하나 이상). */

export const FREQ = [
  { k: "QD",  label: "1일 1회", times: ["09:00"] },
  { k: "BID", label: "1일 2회", times: ["09:00", "21:00"] },
  { k: "TID", label: "1일 3회", times: ["08:00", "13:00", "19:00"] },
  { k: "QID", label: "1일 4회", times: ["08:00", "12:00", "17:00", "21:00"] },
  { k: "HS",  label: "취침 전", times: ["22:00"] },
];

/* 성분명 제안 — 유방외과에서 자주 쓰는 것. **서버 값이 아니다**(화면에 둔 목록).
 * 저장되는 값은 한글 이름이다(환자 앱 「어떤 약인가요」가 그대로 보여 준다). */
export const INGREDIENTS = [
  ["타목시펜시트르산염", "tamoxifen citrate"],
  ["레트로졸", "letrozole"],
  ["아나스트로졸", "anastrozole"],
  ["엑스메스탄", "exemestane"],
  ["고세렐린아세트산염", "goserelin acetate"],
  ["아세트아미노펜", "acetaminophen"],
  ["이부프로펜", "ibuprofen"],
  ["덱시부프로펜", "dexibuprofen"],
  ["세레콕시브", "celecoxib"],
  ["트라마돌염산염", "tramadol HCl"],
  ["트라마돌염산염 · 아세트아미노펜", "tramadol/acetaminophen"],
  ["세파졸린나트륨", "cefazolin sodium"],
  ["세파클러", "cefaclor"],
  ["아목시실린 · 클라불란산칼륨", "amoxicillin/clavulanate"],
  ["온단세트론", "ondansetron"],
  ["메토클로프라미드", "metoclopramide"],
  ["레바미피드", "rebamipide"],
  ["파모티딘", "famotidine"],
  ["탄산칼슘 · 콜레칼시페롤", "calcium carbonate/cholecalciferol"],
];

export const emptyDrug = () => ({
  name: "", ingredient: "", dose: "", times: [], days: "",
  route: "", form: "",   /* 투여 경로(codes.js ROUTE) · 제형 — 둘 다 선택 */
  purpose: "", how: "", watch: "",
  hints: [],   /* 약 이름 검색 결과에서 뽑은 성분 — 보내지 않는다 */
});

/* 품목명 → 투여 경로 · 제형 짐작. 「타이레놀정500밀리그람(…)」의 「정」처럼
 * 제형 글자는 함량 숫자 바로 앞이나 이름 끝에 온다.
 *
 * ⚠ **짐작일 뿐이다.** 빈 칸에만 채우고 사람이 고친다(Prescription.jsx).
 * ⚠ 앞에서부터 본다 — 「점안」 「흡입」 「주사」가 「정」 「액」보다 먼저다.
 *   「…주사액」을 액제로 읽으면 안 된다.
 * ⚠ 「정」 「산」 「주」는 한 글자라 이름 속에도 흔하다(정로환 · 산부인과…).
 *   그래서 **뒤에 숫자 · 공백 · 괄호 · 끝**이 올 때만 제형으로 본다. */
const END = String.raw`(?=[\d\s(]|$)`;
const FORM_RULES = [
  [/점안/, "eye", "점안제"],
  [/흡입|에어로|네뷸/, "inhalation", "흡입제"],
  [new RegExp(`주사|프리필드|주${END}`), "injection", "주사제"],
  [/크림/, "topical", "크림제"],
  [/연고/, "topical", "연고제"],
  [/겔|젤/, "topical", "겔제"],
  [/패치|첩부|플라스타/, "topical", "첩부제"],
  [/캡슐/, "oral", "캡슐제"],
  [/시럽/, "oral", "시럽제"],
  [/과립/, "oral", "과립제"],
  [/현탁/, "oral", "현탁제"],
  [new RegExp(`정${END}`), "oral", "정제"],
  [new RegExp(`산${END}`), "oral", "산제"],
];
export function routeOf(name) {
  /* 끝 괄호(성분) 는 뺀다 — 성분명에 「…산」 「…정」이 들어 있다 */
  const base = String(name ?? "").replace(/\([^()]*\)\s*$/, "").trim();
  if (!base) return null;
  const hit = FORM_RULES.find(([re]) => re.test(base));
  return hit ? { route: hit[1], form: hit[2] } : null;
}

/* DUR 에 보낼 성별 — 서버는 F · M 만 받는다. 모르면 보내지 않는다 */
export function durSex(sex) {
  const s = String(sex ?? "").trim().toLowerCase();
  return s === "f" || s === "female" || s === "여" ? "F"
    : s === "m" || s === "male" || s === "남" ? "M" : undefined;
}

/* e약은요 품목명은 끝 괄호에 성분을 적는다 — 「타이레놀정500밀리그람(아세트아미노펜)」.
 * 그 괄호만 꺼낸다. 수출명 같은 다른 괄호면 비워 둔다(틀린 성분보다 빈칸이 낫다). */
export function ingredientOf(name) {
  const m = /\(([^()]+)\)\s*$/.exec(name ?? "");
  return m && !m[1].includes("수출명") ? m[1].trim() : "";
}

export const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
export const sorted = (times) => [...times].sort();
const same = (a, b) => a.length === b.length && sorted(a).every((t, i) => t === sorted(b)[i]);

/** 이 시각들이 어느 복용 횟수인가. 손으로 고쳤으면 null */
export function freqOf(times) {
  return FREQ.find((f) => same(f.times, times))?.k ?? null;
}

/** 저장 전에 한 번 더 — 서버와 같은 규칙. 문제가 없으면 null */
export function timesProblem(times) {
  if (!times.length) return "복용 횟수를 골라 주세요";
  if (times.some((t) => !HHMM.test(t))) return "비어 있거나 잘못된 시각이 있습니다";
  if (new Set(times).size !== times.length) return "같은 시각이 두 번 있습니다";
  return null;
}

export const norm = (s) => String(s ?? "").toLowerCase().replace(/[\s·/,()-]/g, "");

/** 성분명 제안 — 약 검색 결과의 괄호 속 성분이 앞, 그다음 자주 쓰는 목록 */
export function ingredientHints(q, hints = []) {
  const n = norm(q);
  const seen = new Set();
  const out = [];
  const push = (ko, en, from) => {
    const key = norm(ko);
    if (!key || seen.has(key)) return;
    if (n && !norm(ko).includes(n) && !norm(en).includes(n)) return;
    seen.add(key);
    out.push({ ko, en, from });
  };
  hints.forEach((h) => push(h, "", "검색한 약"));
  INGREDIENTS.forEach(([ko, en]) => push(ko, en, null));
  /* 앞머리가 맞는 것을 먼저 — 「아세트」에 고세렐린아세트산염이 먼저 뜨지 않게.
     검색한 약에서 온 것은 그 안에서도 앞에 둔다(정렬은 안정적이다) */
  const head = (x) => (n && (norm(x.ko).startsWith(n) || norm(x.en).startsWith(n)) ? 0 : 1);
  return out.sort((a, b) => head(a) - head(b)).slice(0, 8);
}

