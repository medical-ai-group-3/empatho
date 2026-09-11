import { useTheme } from "./theme";

/* 밝은 판 · 어두운 판 단추.
 *
 * 셋을 돌아가며 고른다 — 자동 → 어둡게 → 밝게 → 자동.
 * 「자동」이 기본이자 첫 자리다. 대부분은 기기 설정을 그대로 쓰면 되고,
 * 그게 안 맞는 사람만 두 번째·세 번째로 넘어간다.
 *
 * 지금은 홈 머리말에 있다. **「내 정보」가 생기면 그리로 옮긴다** —
 * 설정은 설정 자리에 있는 것이 맞다. 옮길 때 이 부품을 그대로 가져가면
 * 되고, 색이나 저장은 손댈 것이 없다.
 */
const NEXT = { system: "dark", dark: "light", light: "system" };
const FACE = {
  system: { ic: "◐", say: "화면 밝기 · 기기 설정을 따름" },
  dark:   { ic: "☾", say: "화면 밝기 · 어둡게" },
  light:  { ic: "☀", say: "화면 밝기 · 밝게" },
};

export default function ThemeButton() {
  const [theme, setTheme] = useTheme();
  const f = FACE[theme] ?? FACE.system;

  return (
    <button
      className={theme === "system" ? "icon" : "icon on"}
      onClick={() => setTheme(NEXT[theme])}
      aria-label={f.say}
      title={f.say}
    >
      {f.ic}
    </button>
  );
}
