import { useEffect, useState } from "react";

/* 화면 설정 — 밝기와 글씨 크기. 고르는 곳은 여기 하나다.
 *
 * 셋 중 하나다.
 *   "system"  기기 설정을 따른다 (기본)
 *   "light"   밝은 판으로 고정
 *   "dark"    어두운 판으로 고정
 *
 * 하는 일은 <html> 의 data-theme 을 세우거나 지우는 것뿐이다. 색은
 * index.css 의 color-scheme 한 줄이 가른다 — 여기서 색을 만지지 않는다.
 *
 * localStorage 는 없을 수 있다. 사생활 보호 창이나 쿠키를 막아 둔
 * 브라우저에서는 **읽기만 해도 예외가 난다.** 그래서 다 감싼다 —
 * 저장이 안 되는 것은 불편할 뿐이지만, 예외가 새면 화면이 안 뜬다.
 */
const KEY = "empatho.theme";

export function readTheme() {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(t) {
  const el = document.documentElement;
  if (t === "system") delete el.dataset.theme;
  else el.dataset.theme = t;
}

function storeTheme(t) {
  try {
    if (t === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, t);
  } catch { /* 저장이 안 되면 이번 방문에만 적용된다 */ }
}

/* 화면에서 쓰는 것. 고르면 바로 적용되고 다음 방문에도 남는다. */
export function useTheme() {
  const [theme, set] = useState(readTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  return [theme, (t) => { storeTheme(t); set(t); }];
}


/* ── 글씨 크기 ────────────────────────────────────────────────
   다이얼 판의 --ft(글씨 배율)를 사람이 고를 수 있게 연 것이다. 화면마다
   글자 크기를 따로 손보지 않는다 — 배율 하나가 앱 전체를 같이 키운다.

   **환자 앱이라 이게 장식이 아니다.** 검사 결과를 읽는 분들 중에 작은
   글씨가 힘든 분이 많다. 폰 시스템 설정을 바꿀 줄 모르는 분도 있다.

   1.25 를 넘기지 않는다. 그 위로 가면 「9월 17일(목) 10:00 신청하기」
   같은 긴 단추 글자가 두 줄로 넘어가면서 배치가 무너진다.
*/
const FKEY = "empatho.font_scale";
export const SCALES = [
  { v: 1,    label: "보통" },
  { v: 1.12, label: "크게" },
  { v: 1.25, label: "아주 크게" },
];

export function readScale() {
  try {
    const v = parseFloat(localStorage.getItem(FKEY));
    return SCALES.some((s) => s.v === v) ? v : 1;
  } catch { return 1; }
}

export function applyScale(v) {
  // :root 에 직접 얹는다. tokens.css 의 --ft: 1 보다 이쪽이 이긴다.
  document.documentElement.style.setProperty("--ft", String(v));
}

function storeScale(v) {
  try {
    if (v === 1) localStorage.removeItem(FKEY);
    else localStorage.setItem(FKEY, String(v));
  } catch { /* 이번 방문에만 적용된다 */ }
}

export function useScale() {
  const [scale, set] = useState(readScale);
  useEffect(() => { applyScale(scale); }, [scale]);
  return [scale, (v) => { storeScale(v); set(v); }];
}
