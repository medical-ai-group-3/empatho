/* 화면 검사 — 눈이 아니라 수로 본다
 * ════════════════════════════════════════════════════════════════
 *
 * build 도 lint 도 **배치가 깨진 것을 못 잡는다.** 달력이 칸 밖으로 101px
 * 나가 있어도 번들은 멀쩡히 만들어진다. 그래서 진짜 브라우저에 띄워
 * 좌표를 재는 검사를 따로 둔다.
 *
 *   npm run check            목업 서버를 직접 띄워서 검사한다
 *   node scripts/check-screens.mjs http://localhost:5173
 *
 * ⚠ **설치하는 것이 없다.** Node 의 기본 WebSocket 으로 이미 깔린 크롬을
 *   CDP 로 몬다 — playwright 를 넣으면 브라우저 바이너리가 따라온다.
 *
 * 재는 것 일곱
 *   1 넘침        scrollWidth > clientWidth
 *   2 화면 밖     뷰포트 오른쪽·왼쪽을 넘어간 요소
 *   3 겹침        elementFromPoint 가 자기가 아닌 것을 집는다
 *   4 줄 중심     같은 줄에 선 것들의 세로 중심이 2px 넘게 벌어진다
 *   5 칸 변       한 단 안 칸들의 왼쪽변, 단마다 첫 칸의 윗변이 어긋난다
 *   6 튀어나옴    자식 상자가 부모 상자를 벗어난다 (1번이 못 보는 자리)
 *   7 잘림        말줄임 없이 글자가 잘린다
 */
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.argv[2] ?? "http://localhost:5199";
const DEPTS = ["nursing", "radiology", "pathology", "breast"];
/* 과 바깥 화면도 같이 본다. 환자는 목업에 타임라인이 있는 사람으로 고른다 —
   빈 화면만 보면 줄이 넘치는지 알 수 없다 */
const LOOSE = ["nursing/intake", "nursing/patients", "nursing/reservations",
  "patients/P-1001", "me"];
const WIDTHS = [1440, 1920];
const PORT = 9321;

/* 목업 로그인은 아이디 접두만 본다. all → accounts.local.json 의 전체보기.
   그 파일이 없는 기계에서는 고정 응답으로 떨어져 권한이 좁아진다 */
const TOKEN = "mock.all";

const CHROMES = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 서버가 없으면 목업으로 직접 띄운다. 주소를 손으로 넘겼으면 그건 남의
   서버라 건드리지 않는다 — 끝나고 죽이면 안 된다 */
async function up(url) {
  try {
    await fetch(`${url}/hospital.html`);
    return null;
  } catch { /* 없다 — 우리가 띄운다 */ }
  if (process.argv[2]) throw new Error(`${url} 에 아무도 없다`);

  /* ⚠ npx 나 .cmd 를 셸로 부르지 않는다. 윈도에서 셸을 끼면 인자가 그대로
       이어 붙어 위험하고(Node 가 경고한다), 셸을 빼면 .cmd 를 못 연다.
       노드로 vite 본체를 바로 부르면 둘 다 없다 */
  const port = new URL(url).port;
  const vite = new URL("../node_modules/vite/bin/vite.js", import.meta.url);
  const proc = spawn(process.execPath,
    [vite.pathname.replace(/^\/([A-Za-z]:)/, "$1"),
      "--mode", "mock", "--port", port, "--strictPort"],
    { stdio: "ignore" });
  for (let i = 0; i < 60; i += 1) {
    await sleep(300);
    try { await fetch(`${url}/hospital.html`); return proc; } catch { /* 아직 */ }
  }
  proc.kill();
  throw new Error("목업 서버가 안 떴다");
}

function browser() {
  const found = CHROMES.find((p) => existsSync(p));
  if (!found) throw new Error("크롬도 엣지도 못 찾았다");
  return found;
}

async function connect() {
  const profile = mkdtempSync(join(tmpdir(), "empatho-check-"));
  const proc = spawn(browser(), [
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    "--headless=new", "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "about:blank",
  ], { stdio: "ignore" });

  let url;
  for (let i = 0; i < 60 && !url; i += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      url = list.find((t) => t.type === "page")?.webSocketDebuggerUrl;
    } catch { /* 아직 안 떴다 */ }
    if (!url) await sleep(250);
  }
  if (!url) { proc.kill(); throw new Error("크롬이 안 떴다"); }

  const ws = new WebSocket(url);
  await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });

  let id = 0;
  const waiting = new Map();
  const events = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
    else if (m.method) events.push(m);
  };
  const send = (method, params = {}) => new Promise((r) => {
    const n = ++id;
    waiting.set(n, r);
    ws.send(JSON.stringify({ id: n, method, params }));
  });

  return { send, events, close: () => { ws.close(); proc.kill(); } };
}

/* ── 브라우저 안에서 도는 자 ──────────────────────────────────
 * 문자열로 넣는다. 밖의 변수를 못 쓰니 필요한 것은 안에서 다 만든다.
 */
const PROBE = `(() => {
  const out = [];
  const W = window.innerWidth;
  const add = (kind, el, px, note) => out.push({
    kind, el: name(el), px: Math.round(px * 10) / 10, note: note ?? null,
  });

  /* 어느 요소인지 사람이 알아볼 수 있게 — 태그 + 클래스 + 앞 글자 */
  function name(el) {
    if (!el) return "(없음)";
    const cls = typeof el.className === "string" && el.className
      ? "." + el.className.trim().split(/\\s+/).join(".") : "";
    const tx = (el.textContent ?? "").trim().replace(/\\s+/g, " ").slice(0, 18);
    return el.tagName.toLowerCase() + cls + (tx ? ' "' + tx + '"' : "");
  }

  const all = [...document.querySelectorAll(".page *")].filter((el) => {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });

  /* 1 넘침 — 스스로 굴리게 해 둔 자리는 뺀다 */
  for (const el of all) {
    const s = getComputedStyle(el);
    if (s.overflowX === "auto" || s.overflowX === "scroll") continue;
    const over = el.scrollWidth - el.clientWidth;
    if (over > 1) add("넘침", el, over,
      el.clientWidth + " 칸에 " + el.scrollWidth + " 가 들었다");
  }

  /* 2 화면 밖 */
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.right > W + 1) add("화면 밖", el, r.right - W, "오른쪽 끝 " + Math.round(r.right));
    else if (r.left < -1) add("화면 밖", el, -r.left, "왼쪽 끝 " + Math.round(r.left));
  }

  /* 3 겹침 — 누를 것과 글자가 남에게 가리는지. 가운데 점을 집어 본다.
     ⚠ 떠 있는 메모지(lib/StickyMemo)는 뺀다. 사람이 끌어다 놓는 것이고
       **위에 있는 것이 제 일**이다. 자리도 사람마다 다르다 */
  const float = (el) => el.closest('[role="note"], .sticky-memo') !== null;
  const hit = [...document.querySelectorAll(
    ".page a, .page button, .page input, .page time, .page .hcard-n, .page h2")];
  for (const el of hit) {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > W || y > window.innerHeight) continue;
    const top = document.elementFromPoint(x, y);
    if (!top) continue;
    if (top === el || el.contains(top) || top.contains(el)) continue;
    if (float(top)) continue;
    add("겹침", el, 0, name(top) + " 가 위에 있다");
  }

  /* 4 같은 줄 세로 중심 — 2px 넘게 벌어지면 줄이 안 맞아 보인다 */
  const ROWS = [".home-head", ".recent", ".hcard-h", ".qrow", ".srow", ".drow"];
  for (const sel of ROWS) {
    for (const row of document.querySelectorAll(sel)) {
      const kids = [...row.children].filter((k) => {
        const s = getComputedStyle(k);
        if (s.display === "none") return false;
        const r = k.getBoundingClientRect();
        /* 자리만 먹는 빈 칸(.home-fill)과 높이 없는 것은 뺀다 */
        return r.width > 0 && r.height > 0 && (k.textContent ?? "").trim() !== "";
      });
      if (kids.length < 2) continue;
      const mid = kids.map((k) => {
        const r = k.getBoundingClientRect();
        return { k, c: r.top + r.height / 2 };
      });
      const lo = Math.min(...mid.map((m) => m.c));
      const hi = Math.max(...mid.map((m) => m.c));
      if (hi - lo > 2) {
        const worst = mid.reduce((a, b) =>
          Math.abs(b.c - lo) > Math.abs(a.c - lo) ? b : a);
        add("줄 중심", worst.k, hi - lo, sel + " 안에서 " + kids.length + "개가 어긋난다");
      }
    }
  }

  /* 5 칸의 변 — 한 단 안은 왼쪽변, 단끼리는 첫 칸 윗변 */
  const panes = [...document.querySelectorAll(".pane")];
  for (const pane of panes) {
    const cards = [...pane.querySelectorAll(":scope > .hcard")];
    if (cards.length < 2) continue;
    const lefts = cards.map((c) => c.getBoundingClientRect().left);
    const gap = Math.max(...lefts) - Math.min(...lefts);
    if (gap > 1) add("칸 왼쪽변", cards[1], gap, "같은 단 안에서 어긋난다");
  }
  if (panes.length > 1) {
    const tops = panes.map((p) => {
      const c = p.querySelector(":scope > .hcard");
      return c ? c.getBoundingClientRect().top : null;
    }).filter((t) => t !== null);
    const gap = Math.max(...tops) - Math.min(...tops);
    if (gap > 1) add("칸 윗변", panes[0], gap, "단마다 첫 칸이 어긋난다");
  }
  /* 6 튀어나옴 — 자식 상자가 부모 상자를 벗어난다
     ⚠ **1번(scrollWidth)으로는 안 보인다.** overflow 가 visible 이면
       넘쳐도 scrollWidth·scrollHeight 가 안 는다. 달력 오늘 칸에서 숫자가
       위로 3.8px 나가 있었는데 이 검사가 없어서 그냥 통과했다.
     ⚠ 스스로 굴리는 부모와 띄운 자식(absolute·fixed)은 뺀다 — 굴리는 자리는
       넘치는 것이 제 일이고, 띄운 것은 애초에 부모 상자를 안 따른다 */
  for (const el of all) {
    const s = getComputedStyle(el);
    if (s.overflowX !== "visible" || s.overflowY !== "visible") continue;
    const p = el.getBoundingClientRect();
    for (const kid of el.children) {
      const ks = getComputedStyle(kid);
      if (ks.position === "absolute" || ks.position === "fixed") continue;
      if (ks.display === "none" || ks.visibility === "hidden") continue;
      const r = kid.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const out = Math.max(p.top - r.top, r.bottom - p.bottom,
                           p.left - r.left, r.right - p.right);
      if (out > 1) {
        const side = [
          [p.top - r.top, "위"], [r.bottom - p.bottom, "아래"],
          [p.left - r.left, "왼쪽"], [r.right - p.right, "오른쪽"],
        ].reduce((a, b) => (b[0] > a[0] ? b : a));
        add("튀어나옴", kid, out, name(el) + " 의 " + side[1] + "으로");
      }
    }
  }

  /* 7 말줄임 없는 잘림 */
  for (const el of all) {
    if (el.children.length > 0) continue;
    const s = getComputedStyle(el);
    if (s.textOverflow === "ellipsis") continue;
    if (s.overflowX === "auto" || s.overflowX === "scroll") continue;
    const cut = el.scrollWidth - el.clientWidth;
    if (cut > 1 && s.overflow !== "visible") add("잘림", el, cut, "말줄임이 없다");
  }

  return JSON.stringify(out);
})()`;

/* ── 돌린다 ──────────────────────────────────────────────────── */
const server = await up(BASE);
const cdp = await connect();
await cdp.send("Page.enable");
await cdp.send("Runtime.enable");
await cdp.send("Log.enable");

await cdp.send("Page.navigate", { url: `${BASE}/hospital.html` });
await sleep(1500);
await cdp.send("Runtime.evaluate", {
  expression: `sessionStorage.setItem("empatho_staff_token", ${JSON.stringify(TOKEN)})`,
});

let bad = 0;
for (const width of WIDTHS) {
  await cdp.send("Emulation.setDeviceMetricsOverride",
    { width, height: 855, deviceScaleFactor: 1, mobile: false });

  for (const dept of [...DEPTS, ...LOOSE]) {
    cdp.events.length = 0;
    await cdp.send("Page.navigate", { url: `${BASE}/hospital/${dept}` });
    await sleep(2200);

    const res = await cdp.send("Runtime.evaluate",
      { expression: PROBE, returnByValue: true });
    const thrown = res.result?.exceptionDetails;
    const found = thrown ? [] : JSON.parse(res.result.result.value);

    const errs = cdp.events.filter((e) =>
      e.method === "Runtime.exceptionThrown"
      || (e.method === "Log.entryAdded" && e.params.entry.level === "error")
      || (e.method === "Runtime.consoleAPICalled" && e.params.type === "error"));

    const where = `${width}px · ${dept}`;
    if (thrown) {
      bad += 1;
      console.log(`\n실패 ${where}\n     검사 자체가 터졌다 — ${thrown.text}`);
      continue;
    }
    if (found.length === 0 && errs.length === 0) {
      console.log(`OK   ${where}`);
      continue;
    }

    bad += 1;
    console.log(`\n실패 ${where}`);
    for (const e of errs.slice(0, 3)) {
      const t = e.method === "Runtime.exceptionThrown"
        ? (e.params.exceptionDetails.exception?.description ?? e.params.exceptionDetails.text)
        : e.method === "Log.entryAdded"
          ? `${e.params.entry.text} ${e.params.entry.url ?? ""}`
          : e.params.args.map((a) => a.description ?? a.value).join(" ");
      console.log(`     콘솔  ${String(t).split("\n")[0]}`);
    }
    /* 같은 종류가 스물씩 나오면 원인 하나를 못 찾는다 — 종류마다 셋까지 */
    const byKind = new Map();
    for (const f of found) {
      const list = byKind.get(f.kind) ?? [];
      list.push(f);
      byKind.set(f.kind, list);
    }
    for (const [kind, list] of byKind) {
      for (const f of list.slice(0, 3)) {
        console.log(`     ${kind}  ${f.el}  ${f.px}px`
          + (f.note ? `  (${f.note})` : ""));
      }
      if (list.length > 3) console.log(`     ${kind}  … 그 밖 ${list.length - 3}개`);
    }
  }
}

console.log(bad === 0
  ? `\n다섯 과 × ${WIDTHS.join("·")} 모두 통과`
  : `\n${bad}판 실패`);
cdp.close();
server?.kill();
process.exit(bad === 0 ? 0 : 1);
