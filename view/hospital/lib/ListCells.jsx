/* 목록 칸 — 좁은 목록 칸(.split.third, 440~500px)에서 칸이 넘치지 않게
 * ════════════════════════════════════════════════════════════════
 *
 * 09-28 — 영상의학과 「검사 목록」이 다섯 칸이라 「테스터1 (26/남)」이
 * 두 줄로 꺾이고, 끝 칸 칩 「미열람」이 목록 밖으로 밀려 잘렸다. 성별이
 * 비면 「(51/)」처럼 빈 자리가 그대로 보였다.
 *
 *   · 칸을 줄인다 — 덜 중요한 값은 **둘째 줄**(작고 흐리게)로 내린다
 *   · 첫 칸(환자)만 남는 폭을 받고, 넘치면 말줄임한다. 나머지 칸은 값
 *     폭만큼만 차지하고 꺾이지 않는다(Table 의 cls: "c-grow" / "c-fit")
 *   · 빈 값은 안 쓴다 — 「51 · 여」는 있는 것만(H.who)
 *
 * 짧은 일시(shortAt)는 lib/shortAt.js — 부품만 내보내야 fast refresh 가 된다
 */

/* 두 줄 칸 — 위는 본 값, 아래는 작은 곁 값. 곁 값이 없으면 한 줄 */
export function Two({ main, sub, strong = false, title }) {
  const M = strong ? "b" : "span";
  return (
    <span className="c2" title={title}>
      <M className="c2-m">{main}</M>
      {sub ? <span className="c2-s">{sub}</span> : null}
    </span>
  );
}

/* 유방외과 열람 — 칩 대신 점 하나와 글자. 칩은 테두리 · 여백만큼 칸을
   더 먹어 끝 칸이 목록 밖으로 밀렸다.
   ⚠ 「확인」이 아니라 「열람」이다(자동 기록) */
export function Seen({ at }) {
  return at
    ? <span className="seen on" title={String(at).slice(0, 16).replace("T", " ")}>열람</span>
    : <span className="seen">미열람</span>;
}

/* 정렬 — 고르개 하나. 알약 다섯 개가 한 줄을 통째로 먹던 것 */
export function SortSelect({ items, value, onChange }) {
  return (
    <label className="lst-sort">
      <span className="sorts-k">정렬</span>
      <select value={value} onChange={(e) => onChange?.(e.target.value)}>
        {items.map((it) => (
          <option key={it.key ?? it} value={it.key ?? it}>{it.label ?? it}</option>
        ))}
      </select>
    </label>
  );
}
