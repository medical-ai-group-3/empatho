import { koMatch } from "../../lib/koSearch";

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
  [/안연고/, "eye", "안연고"],
  [/점안/, "eye", "점안액"],
  [/흡입|에어로|네뷸/, "inhalation", "흡입제"],
  [new RegExp(`주사|프리필드|주${END}`), "injection", "주사제"],
  [/크림/, "topical", "크림제"],
  [/연고/, "topical", "연고제"],
  [/겔|젤/, "topical", "겔제"],
  [/로션/, "topical", "로션제"],
  [/패치|첩부|플라스타/, "topical", "첩부제"],
  /* 좌제 · 질정은 경로표에 따로 없다 — 「기타」. ⚠ 질정은 「정」 규칙보다 앞 */
  [/좌제|좌약|좌${END}/, "other", "좌제"],
  [/질정|질${END}/, "other", "질정"],
  [/캡슐/, "oral", "캡슐제"],
  [/시럽/, "oral", "시럽제"],
  [/과립/, "oral", "과립제"],
  [/현탁/, "oral", "현탁액"],
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

/* 제형 제안 — 흔한 한글 제형. [제형, 경로]. **서버 값이 아니다**(서버는 form 을
 * 자유 글로 받는다). 목록 밖 제형도 그대로 적을 수 있다 */
export const FORMS = [
  ["정제", "oral"], ["필름코팅정", "oral"], ["서방정", "oral"], ["장용정", "oral"],
  ["츄어블정", "oral"], ["구강붕해정", "oral"], ["발포정", "oral"], ["설하정", "oral"],
  ["캡슐제", "oral"], ["연질캡슐제", "oral"], ["서방성캡슐제", "oral"],
  ["시럽제", "oral"], ["건조시럽제", "oral"], ["현탁액", "oral"], ["내용액제", "oral"],
  ["산제", "oral"], ["과립제", "oral"],
  ["주사제", "injection"], ["동결건조주사제", "injection"], ["프리필드주사제", "injection"],
  ["크림제", "topical"], ["연고제", "topical"], ["겔제", "topical"], ["로션제", "topical"],
  ["외용액제", "topical"], ["패치제", "topical"], ["첩부제", "topical"],
  ["흡입제", "inhalation"], ["흡입용캡슐", "inhalation"], ["흡입분말제", "inhalation"],
  ["네뷸라이저용액", "inhalation"],
  ["점안액", "eye"], ["점안겔", "eye"], ["안연고", "eye"],
  ["좌제", "other"], ["질정", "other"],
];

/* 제형 글 → 투여 경로. 목록에 있으면 그 값, 없으면 이름 짐작 규칙, 그래도
 * 모르면 경구 — 먹는 약이 제일 흔하다. ⚠ 경로 칸이 **비어 있을 때만** 쓴다 */
export function formRoute(form) {
  const f = String(form ?? "").trim();
  if (!f) return "";
  return FORMS.find(([k]) => k === f)?.[1] ?? routeOf(f)?.route ?? "oral";
}

/* 제형 제안 목록. 친 글자로 거르고(앞머리 · 포함 · 초성 — koMatch),
 * 고른 경로와 맞는 것을 먼저 둔다(점안을 골랐으면 점안액 · 점안겔이 위) */
export function formHints(q, route) {
  const s = String(q ?? "").trim();
  const out = FORMS.map(([form, r], i) => ({ form, route: r, i }))
    .filter((x) => !s || koMatch(x.form, s));
  const rank = (x) => (route && x.route === route ? 0 : 2)
    + (s && x.form.startsWith(s) ? 0 : 1);
  return out.sort((a, b) => rank(a) - rank(b) || a.i - b.i);
}

/* 염 · 수화물 꼬리 → 기본 성분. DUR 은 기본 성분 이름으로 찾는다 —
 * 「메토트렉세이트나트륨」은 0건, 「메토트렉세이트」는 찾는다.
 * ⚠ 긴 꼬리부터 본다(「브롬화수소산염」을 「염」 따위로 먼저 자르지 않게).
 * ⚠ 꼬리를 떼고 남는 것이 무기 음이온뿐이면 떼지 않는다 — 「탄산칼슘」을
 *   「탄산」으로, 「염화칼륨」을 「염화」로 만들면 없는 성분이 된다.
 * ⚠ 끝의 함량(「20mg」)도 뗀다 — 성분명 칸에 함량을 같이 적는 일이 흔하다. */
const SALT_TAILS = [
  "브롬화수소산염", "타르타르산염", "시트르산염", "푸마르산염", "메실산염", "말레산염",
  "베실산염", "숙신산염", "토실산염", "아세트산염", "락트산염", "글루콘산염",
  "옥살산염", "염산염", "황산염", "인산염", "질산염",
  "브롬화물", "염화물", "요오드화물",
  "마그네슘", "나트륨", "칼륨", "칼슘",
  "세스퀴수화물", "반수화물", "일수화물", "이수화물", "삼수화물", "사수화물", "오수화물",
  "수화물", "무수물",
].sort((a, b) => b.length - a.length);
const BARE_ANION = new Set([
  "탄산", "탄산수소", "황산", "인산", "인산수소", "질산", "초산", "염화", "산화",
  "수산화", "불화", "요오드화", "브롬화", "구연산", "시트르산", "아세트산",
  "글루콘산", "락트산", "젖산",
]);
const DOSE_TAIL = /\s*\d[\d.,]*\s*(mg|g|mcg|μg|µg|iu|ml|%|밀리그램|밀리그람|마이크로그램|그램|단위)\s*$/i;

export function baseIngredient(name) {
  let s = String(name ?? "").trim().replace(DOSE_TAIL, "").trim();
  for (let n = 0; n < 4; n += 1) {
    const tail = SALT_TAILS.find((t) => s.endsWith(t));
    if (!tail) break;
    const rest = s.slice(0, -tail.length).trim();
    if ([...rest].length < 2 || BARE_ANION.has(rest)) break;
    s = rest;
  }
  return s;
}

/* 복합제(「트라마돌염산염 · 아세트아미노펜」)는 성분마다 떼고 다시 잇는다 */
export const splitIngredients = (s) => String(s ?? "").split(/\s*[·,/+]\s*/).map((x) => x.trim()).filter(Boolean);
export const baseIngredients = (s) => splitIngredients(s).map(baseIngredient).join(" · ");

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

/** 성분명 제안 — ① 적은 값에 염 꼬리가 있으면 기본 성분(DUR 조회용)
 * ② 약 검색 결과의 괄호 속 성분 ③ 이 환자의 지난 처방에 쓴 성분 ④ 자주 쓰는 목록 */
export function ingredientHints(q, hints = [], used = []) {
  const n = norm(q);
  const seen = new Set();
  const out = [];
  const push = (ko, en, from) => {
    const key = norm(ko);
    if (!key || seen.has(key)) return;
    if (n && !norm(ko).includes(n) && !norm(en).includes(n) && !koMatch(ko, String(q).trim())) return;
    seen.add(key);
    out.push({ ko, en, from });
  };
  hints.forEach((h) => push(h, "", "검색한 약"));
  used.forEach((u) => push(u, "", "이전 처방"));
  INGREDIENTS.forEach(([ko, en]) => push(ko, en, null));
  /* 앞머리가 맞는 것을 먼저 — 「아세트」에 고세렐린아세트산염이 먼저 뜨지 않게.
     검색한 약에서 온 것은 그 안에서도 앞에 둔다(정렬은 안정적이다) */
  const head = (x) => (n && (norm(x.ko).startsWith(n) || norm(x.en).startsWith(n)) ? 0 : 1);
  const list = out.sort((a, b) => head(a) - head(b));
  /* 기본 성분은 거르지 않고 맨 앞 — 친 글자에서 나온 것이라 늘 맞는다 */
  const base = baseIngredients(q);
  if (base && norm(base) !== n) {
    return [{ ko: base, en: "", from: "DUR 조회용 기본 성분", base: true },
      ...list.filter((x) => norm(x.ko) !== norm(base))].slice(0, 8);
  }
  return list.slice(0, 8);
}
