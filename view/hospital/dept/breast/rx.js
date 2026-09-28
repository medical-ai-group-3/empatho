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
  purpose: "", how: "", watch: "",
  hints: [],   /* 약 이름 검색 결과에서 뽑은 성분 — 보내지 않는다 */
});

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

