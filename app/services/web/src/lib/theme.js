import { useEffect, useState } from "react";

/* 밝은 판 · 어두운 판 — 고르는 곳은 여기 하나다.
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
