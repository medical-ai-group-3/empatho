/* 이름 대조 — 화면에 띄우기 전에 잡는다
 * ════════════════════════════════════════════════════════════════
 *
 * `npm run check` 가 브라우저로 좌표를 재기 **전에** 돈다. 좌표 검사는
 * 증상만 보여 준다 — 달력이 칸 밖으로 나간 두 번 다 진짜 원인은
 * **이름**이었다.
 *
 *   .cal 이 예약 캘린더 화면의 .cal 과 겹쳤다   → 달력이 2단 격자가 됐다
 *   .cal-dot 하나만 안 갈렸다                    → 점이 규칙을 잃었다
 *
 * 그래서 JSX 가 뱉는 클래스 이름을 모아 CSS 에 규칙이 있는지 본다.
 *
 * **이름은 두 종류다.** 클래스만 보는 것은 절반만 보는 것이다 —
 * `--prow-no-gap` 과 `--prow-3-fs` 를 그렇게 놓쳤다. 정의된 적이 없는데
 * 접수 현황판과 환자 상세가 몇 달째 쓰고 있었고, 클래스 이름에는 아무
 * 문제가 없어서 이 검사가 통과시켰다. 그래서 `var(--…)` 도 같이 센다.
 *
 * ⚠ **규칙 없는 이름이 곧 버그는 아니다.** querySelector 손잡이일 수도,
 *   검사용 선택자일 수도 있다. 그래서 지금 걸리는 것은
 *   `scripts/known-unstyled.txt` 에 적어 두고 **새로 느는 것만** 실패로
 *   본다. 목적은 이름 충돌을 나기 전에 잡는 것뿐이다.
 *
 * ⚠ 목록에 있는데 더는 안 걸리는 줄은 **경고로 알린다.** 안 그러면
 *   목록이 썩어서 나중에 아무도 못 믿는다.
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const SRC = join(ROOT, "hospital");
const LIST = join(HERE, "known-unstyled.txt");
const HOLE = "@";   /* ${...} 가 있던 자리. 클래스 이름에는 못 쓰는 글자다 */

/* 규칙이 없어도 되는 것 — 상태만 나타내는 수식어. 부모와 짝지어 쓴다
   (`.trow.done` 처럼) 거나, 아예 JS 만 보는 이름이다 */
const MODIFIER = new Set([
  "on", "off", "now", "past", "done", "going", "unsure", "none", "shut",
  "mine", "void", "grow", "err", "dim", "small", "muted", "sm", "fill",
  "line", "dot", "ink", "ring", "dark", "flush", "callout", "big",
]);

/* ── 파일 훑기 ─────────────────────────────────────────────── */
async function walk(dir, out = []) {
  const { readdir } = await import("node:fs/promises");
  for (const it of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, it.name);
    if (it.isDirectory()) await walk(full, out);
    else out.push(full);
  }
  return out;
}

const files = await walk(SRC);
/* 주석을 지우되 **줄바꿈은 남긴다.** 통째로 지우면 뒤쪽 줄 번호가 전부
   밀려서, 잡아 놓고도 엉뚱한 줄을 가리킨다 */
const noComments = (t) =>
  t.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
const lineAt = (text, at) => text.slice(0, at).split("\n").length;

/* CSS 에 규칙이 있는 이름 · 정의된 토큰 */
const defined = new Set();
const tokens = new Set();
for (const f of files.filter((x) => x.endsWith(".css"))) {
  const text = noComments(readFileSync(f, "utf-8"));
  for (const m of text.matchAll(/([^{}]+)\{/g)) {
    if (m[1].trimStart().startsWith("@")) continue;
    for (const c of m[1].matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) defined.add(c[1]);
  }
  for (const m of text.matchAll(/(--[A-Za-z_][\w-]*)\s*:/g)) tokens.add(m[1]);
}

/* ── 토큰 대조 ─────────────────────────────────────────────────
 * 클래스 이름만 보면 절반만 보는 것이다. `--prow-no-gap` 과
 * `--prow-3-fs` 를 이렇게 놓쳤다 — **정의된 적이 없는데** 접수 현황판과
 * 환자 상세가 몇 달째 쓰고 있었다.
 *
 * 정의가 없으면 브라우저는 그 **선언을 통째로 버린다.** `gap:var(--없음)`
 * 은 오류가 아니라 그냥 없던 일이 된다 — 화면은 조금 이상해 보일 뿐이라
 * 눈으로는 못 잡고, 좌표 검사도 「1px 어긋남」 같은 증상만 준다.
 *
 * ⚠ `var(--x, 대비값)` 은 세지 않는다. 대비값이 있으면 선언이 안 버려진다.
 * ⚠ JSX 안의 <style> 도 본다. 거기 적힌 것도 브라우저가 읽는 CSS 다.
 * ⚠ **JSX 가 인라인으로 매기는 것도 정의다** — `style={{"--resv-cols": n}}`
 *   처럼 화면이 값을 넣어 주는 토큰이 있다. CSS 만 보면 없는 줄 알고
 *   멀쩡한 것을 잡는다(예약 판 주간 칸 수가 그랬다).
 * ⚠ **어디서 정의됐는지는 안 본다.** `.breast{--x:…}` 처럼 좁은 곳에서만
 *   정의된 토큰을 밖에서 쓰면 이 검사는 통과시킨다. 그건 좌표 검사 몫이다.
 */
for (const f of files.filter((x) => /\.jsx?$/.test(x))) {
  const text = noComments(readFileSync(f, "utf-8"));
  for (const m of text.matchAll(/["'](--[A-Za-z_][\w-]*)["']\s*:/g)) tokens.add(m[1]);
}

const vars = new Map();       /* 대비값 없이 쓰는 곳 */
let fallbacks = 0;
for (const f of files.filter((x) => /\.(css|jsx?)$/.test(x))) {
  const text = noComments(readFileSync(f, "utf-8"));
  const where = relative(ROOT, f).split("\\").join("/");
  for (const m of text.matchAll(/var\(\s*(--[A-Za-z_][\w-]*)\s*([,)])/g)) {
    if (m[2] === ",") { fallbacks += 1; continue; }
    if (tokens.has(m[1]) || vars.has(m[1])) continue;
    vars.set(m[1], `${where}:${lineAt(text, m.index)}`);
  }
}

/* JSX 가 뱉는 이름 */
const used = new Map();
for (const f of files.filter((x) => /\.jsx?$/.test(x))) {
  const text = noComments(readFileSync(f, "utf-8"));
  const where = relative(ROOT, f).split("\\").join("/");
  const take = (raw, at) => {
    const line = lineAt(text, at);
    for (const name of raw.replace(/\$\{[^}]*\}/g, HOLE).split(/\s+/)) {
      if (!name || name.includes(HOLE)) continue;      /* `w${i}` 같은 조각 */
      if (!/^[A-Za-z_][\w-]*$/.test(name)) continue;
      if (!used.has(name)) used.set(name, `${where}:${line}`);
    }
  };
  for (const m of text.matchAll(/className\s*=\s*(\{`([^`]*)`\}|\{?"([^"]*)"\}?)/g)) {
    take(m[2] ?? m[3] ?? "", m.index);
  }
  /* 헬퍼가 문자열로 만들어 내는 것도 줍는다 — dotClass() 같은 자리 */
  for (const m of text.matchAll(/return\s+["`]([a-z][\w -]*)["`]/g)) {
    if (m[1].includes("-")) take(m[1], m.index);
  }
}

/* 걸리는 것 하나로 모은다 — 클래스는 `이름`, 토큰은 `--이름` 으로 들어가
   예외 목록에서도 한눈에 갈린다 */
const orphans = new Map();
for (const [name, at] of used) {
  if (defined.has(name) || MODIFIER.has(name)) continue;
  if (/^[kw]\d$/.test(name)) continue;                 /* .w0 .k1 — 번호 수식어 */
  orphans.set(name, at);
}
const classCount = orphans.size;
for (const [name, at] of vars) orphans.set(name, at);

/* ── 예외 목록 ─────────────────────────────────────────────── */
const known = new Map();
if (existsSync(LIST)) {
  for (const raw of readFileSync(LIST, "utf-8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const [name, ...rest] = line.split(/\s+/);
    known.set(name, rest.join(" "));
  }
}

const fresh = [...orphans].filter(([n]) => !known.has(n));
const stale = [...known.keys()].filter((n) => !orphans.has(n));
const mark = (n) => (n.startsWith("--") ? n : `.${n}`);

console.log(`이름 대조 — CSS 규칙 ${defined.size}개 · JSX 이름 ${used.size}개 · `
  + `규칙 없는 이름 ${classCount}개`);
console.log(`토큰 대조 — 정의 ${tokens.size}개 · var() ${vars.size + tokens.size}종 · `
  + `정의 없는 것 ${vars.size}개 (대비값 있는 var() ${fallbacks}군데는 안 센다)`);
console.log(`적어 둔 예외 ${known.size}개`);

if (stale.length > 0) {
  console.log(`\n경고 — 목록에 있는데 더는 안 걸리는 줄 ${stale.length}개`);
  console.log("     고쳤거나 지운 것이다. scripts/known-unstyled.txt 에서 빼라");
  for (const n of stale) console.log(`     ${mark(n)}`);
}

if (fresh.length > 0) {
  const nt = fresh.filter(([n]) => n.startsWith("--")).length;
  console.log(`\n실패 — 새로 생긴 것 ${fresh.length}개`
    + (nt > 0 ? ` (그중 정의 없는 토큰 ${nt}개)` : ""));
  for (const [n, at] of fresh) console.log(`     ${mark(n)}  ${at}`);
  console.log("\n     토큰이면 tokens.css 에 값을 넣어라 — 정의가 없으면 그"
    + "\n     선언은 통째로 버려진다. 클래스면 CSS 에 규칙을 더하든지,"
    + "\n     손잡이라면 known-unstyled.txt 에 적어라.");
  process.exit(1);
}

console.log("\n새로 생긴 이름 없음");
