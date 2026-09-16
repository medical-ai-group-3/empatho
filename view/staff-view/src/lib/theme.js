const KEY = "staff_theme";

/* 저장된 값이 있으면 그것, 없으면 기기 설정(prefers-color-scheme)을 따른다. */
export function readTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch { /* 저장소를 못 쓰는 환경 */ }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(mode) {
  document.documentElement.dataset.theme = mode;
}

export function saveTheme(mode) {
  try { localStorage.setItem(KEY, mode); } catch { /* 저장 실패는 무시 — 이번 세션만 적용된다 */ }
}
