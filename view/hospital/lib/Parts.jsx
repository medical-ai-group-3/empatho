import { useEffect, useRef, useState } from "react";

/* 화면 스물한 개가 나눠 쓰는 조각들.
 *
 * 여기 있는 것은 **뼈대와 동작**이고 자료는 밖에서 넣는다. 화면이 실제로
 * 만들어질 때 이 부품들을 그대로 쓰고 안을 채우면 된다.
 */

/* ── 상태 칩 ──────────────────────────────────────────────────
   상태 색을 따로 만들지 않는다는 것이 이 판의 규칙이다. 그래서 셋으로
   가른다 — **채움**(지금 하는 중) · **외곽선**(끝남) · **시안 점**(기계가
   도는 중). 색을 못 가려도 모양이 다르다. */
export function Chip({ tone = "line", children }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

/* ── 정렬 pill ────────────────────────────────────────────── */
export function Sort({ items, value, onChange }) {
  return (
    <div className="sorts" role="group" aria-label="정렬">
      <span className="sorts-k">정렬</span>
      {items.map((it) => (
        <button key={it} className={`pill ${value === it ? "on" : ""}`}
                onClick={() => onChange?.(it)}>{it}</button>
      ))}
    </div>
  );
}

export function Search({ placeholder = "검색", value, onChange }) {
  return (
    <label className="search">
      <span aria-hidden="true">⌕</span>
      <input value={value ?? ""} placeholder={placeholder}
             onChange={(e) => onChange?.(e.target.value)} />
    </label>
  );
}

/* ── 두 단 — 왼쪽 목록, 오른쪽 상세 ───────────────────────────
   원무 · 간호 · 영상 · 병리가 전부 이 모양이다. 오른쪽은 **고른 것이
   없으면 비어 있지 않고** 무엇을 고르라고 말한다. */
export function Split({ side = "normal", left, right, empty = "왼쪽에서 하나를 고르세요" }) {
  return (
    <div className={`split ${side === "wide" ? "wide" : ""}`}>
      <div className="split-l">{left}</div>
      <aside className="split-r">
        {right ?? <div className="slot"><b>{empty}</b></div>}
      </aside>
    </div>
  );
}

/* ── 대기열 ───────────────────────────────────────────────────
   **선착순 큐다.** 병리과 전체가 함께 보고, 누가 집으면 다른 사람
   화면에서 사라진다.

   ⚠ 순번은 **표시 전용**이다. 끌어서 못 옮긴다 — 채취 순서(collected_at)가
     곧 순서이고, 그것을 손으로 바꾸면 «내 화면에서만» 바뀐 것이 된다.
     여럿이 보는 큐에서 각자 순서를 바꾸면 같은 화면이 아니게 된다.

   대신 **검색**을 둔다. 순서를 안 바꾸고 건너뛰어 찾을 수 있게. */
export function Queue({ items, value, onPick, foot, onSearch, q }) {
  return (
    <div className="queue">
      {onSearch && (
        <div className="q-search">
          <Search placeholder="환자 · 검체번호" value={q} onChange={onSearch} />
        </div>
      )}
      <ul>
        {items.map((it, i) => (
          <li key={it.id} className={value === it.id ? "on" : undefined}>
            <button className="q-row" onClick={() => onPick?.(it.id)}>
              <i className="no">{it.no ?? i + 1}</i>
              <span className="q-tx">
                <b>{it.title}</b>
                {it.sub && <span>{it.sub}</span>}
              </span>
              {it.chip && <Chip tone={it.chipTone}>{it.chip}</Chip>}
            </button>
          </li>
        ))}
        {items.length === 0 && (
          <li><div className="q-empty">대기 중인 검체가 없습니다</div></li>
        )}
      </ul>
      {foot && <div className="q-foot">{foot}</div>}
    </div>
  );
}

/* ── 접었다 펴는 덩어리 ───────────────────────────────────────
   판독 화면의 세 패널(검체 정보 · AI 소견 · 의사 소견)이 쓴다.
   접힘/펼침은 **화면 상태라 서버가 모른다** — 저장하지 않는다. */
export function Fold({ title, open = true, right, children }) {
  const [on, setOn] = useState(open);
  return (
    <section className={`fold ${on ? "" : "shut"}`}>
      <button className="fold-h" onClick={() => setOn(!on)} aria-expanded={on}>
        <i aria-hidden="true">{on ? "▾" : "▸"}</i>
        <b>{title}</b>
        {right && <span className="fold-r">{right}</span>}
      </button>
      {on && <div className="fold-b">{children}</div>}
    </section>
  );
}

/* ── 표 목록 ──────────────────────────────────────────────── */
export function Table({ cols, rows, value, onPick }) {
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>{cols.map((c) => <th key={c.key} style={c.w ? { width: c.w } : undefined}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={value === r.id ? "on" : undefined}
                onClick={() => onPick?.(r.id)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") onPick?.(r.id); }}>
              {cols.map((c) => <td key={c.key}>{r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── 편집 모드 ────────────────────────────────────────────────
   판독 화면 · 정정 화면 · 환자 상세가 같이 쓴다.

   **임시저장과 저장을 나란히 둔다.** 둘의 차이를 아래 한 줄로 적는다 —
   저장을 누르면 다른 과로 나간다는 것을 모르고 누르면 안 된다. */
export function Save({ hint, onDraft, onSave, saveLabel = "저장", busy }) {
  return (
    <div className="save">
      {hint && <p className="hint">{hint}</p>}
      <div className="save-b">
        <button className="btn line" onClick={onDraft} disabled={busy}>임시저장</button>
        <button className="btn fill" onClick={onSave} disabled={busy}>{saveLabel}</button>
      </div>
    </div>
  );
}

/* 진행 막대. 업로드와 AI 분석이 같이 쓴다 */
export function Bar({ value = 0, label }) {
  return (
    <div className="barwrap">
      {label && <span className="bar-k">{label}</span>}
      <span className="bar"><i style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></span>
    </div>
  );
}

/* ── 뷰어 껍데기 ──────────────────────────────────────────────
   **이 판에서 어두운 곳은 여기뿐이다.** 판독 영상은 주변이 밝으면
   눈이 계속 조절해야 해서 오래 못 본다.

   양옆 패널은 접힌다. 접으면 손잡이만 남아서 다시 펼 수 있다 —
   완전히 사라지면 「그게 어디 갔지」가 된다. */
export function Viewer({ tools, tabs, children, leftPanel, rightPanel,
                         leftName = "AI 소견", rightName = "의사 소견",
                         leftOpen = true, rightOpen = true }) {
  const [L, setL] = useState(leftOpen);
  const [R, setR] = useState(rightOpen);

  return (
    <div className="vwrap">
      {leftPanel && (L
        ? <aside className="vside">
            <div className="vside-h"><b>{leftName}</b>
              <button className="x" onClick={() => setL(false)} aria-label="접기">‹</button></div>
            <div className="vside-b">{leftPanel}</div>
          </aside>
        : <button className="vtab" onClick={() => setL(true)}>{leftName}</button>)}

      <div className="viewer">
        {tabs && <div className="vtabs">{tabs}</div>}
        <div className="vstage">
          {tools && <div className="vtools">{tools}</div>}
          {children}
        </div>
      </div>

      {rightPanel && (R
        ? <aside className="vside">
            <div className="vside-h"><b>{rightName}</b>
              <button className="x" onClick={() => setR(false)} aria-label="접기">›</button></div>
            <div className="vside-b">{rightPanel}</div>
          </aside>
        : <button className="vtab" onClick={() => setR(true)}>{rightName}</button>)}
    </div>
  );
}

/* 미끄럼 손잡이 하나. 배율에도 쓰고 마스크 투명도에도 쓴다.
   투명도는 **저장하지 않는다** — 보는 사람의 지금 형편이지 판독 내용이
   아니다. */
export function Slide({ label, value, onChange, min = 0, max = 100, unit = "%" }) {
  return (
    <div className="zoom">
      <span>{label}</span>
      <input type="range" min={min} max={max} value={value}
             onChange={(e) => onChange?.(Number(e.target.value))} />
      <b>{value}{unit}</b>
    </div>
  );
}
