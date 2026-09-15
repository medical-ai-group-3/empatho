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
   순서가 뜻을 갖는 목록이다. 끌어서 옮길 수 있고 「다음 환자」로 넘어간다.

   ⚠ **「이전 환자」를 같이 둔다.** 와이어프레임에는 「다음」만 있었는데,
     잘못 넘기면 돌아갈 방법이 없다. 순서가 있는 화면에서 한쪽으로만
     가는 것은 거의 항상 실수다. */
export function Queue({ items, value, onPick, onMove, onPrev, onNext, foot }) {
  const drag = useRef(null);

  return (
    <div className="queue">
      <ul>
        {items.map((it, i) => (
          <li key={it.id}
              className={value === it.id ? "on" : undefined}
              draggable
              onDragStart={() => { drag.current = i; }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (drag.current !== null && drag.current !== i) onMove?.(drag.current, i);
                drag.current = null;
              }}>
            <button className="q-row" onClick={() => onPick?.(it.id)}>
              <i className="grip" aria-hidden="true">⣿</i>
              <i className="no">{i + 1}</i>
              <span className="q-tx">
                <b>{it.title}</b>
                {it.sub && <span>{it.sub}</span>}
              </span>
              {it.chip && <Chip tone={it.chipTone}>{it.chip}</Chip>}
            </button>
          </li>
        ))}
      </ul>
      <div className="q-foot">
        <span>{foot ?? "끌어서 순서를 바꿉니다"}</span>
        <span className="q-nav">
          <button className="pill" onClick={onPrev}>‹ 이전 환자</button>
          <button className="pill" onClick={onNext}>다음 환자 ›</button>
        </span>
      </div>
    </div>
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

/* ── 팝업 ─────────────────────────────────────────────────────
   촬영 요청 · 환자 검색 · 검체 신청이 쓴다. Esc 와 바깥 누르기로 닫힌다 —
   닫는 길이 ✕ 하나뿐이면 손이 먼저 바깥을 누른다. */
export function Modal({ open, title, sub, onClose, foot, children }) {
  useEffect(() => {
    if (!open) return;
    const k = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
      <button className="modal-veil" onClick={onClose} aria-label="닫기" />
      <div className="modal-box">
        <div className="modal-h">
          <div>
            <h2>{title}</h2>
            {sub && <p className="sub">{sub}</p>}
          </div>
          <button className="x" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        <div className="modal-b">{children}</div>
        {foot && <div className="modal-f">{foot}</div>}
      </div>
    </div>
  );
}

/* ── 업로드 ───────────────────────────────────────────────────
   ⚠ **WSI 는 낱장 4GB · ZIP 20GB 까지 온다.** 화면은 진행률만 그리지만,
     받는 쪽(nginx client_max_body_size · file-gateway)이 그 크기를
     받도록 맞춰져 있어야 한다. 기본값이면 413 으로 끊긴다. */
export function Drop({ title, note, accept, max, onPick }) {
  return (
    <div className="drop">
      <i aria-hidden="true">↥</i>
      <b>{title}</b>
      <span>{note}</span>
      <button className="btn line" onClick={onPick}>파일 선택</button>
      <small>지원 형식: {accept} · 최대 {max}</small>
    </div>
  );
}

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
                         leftName = "AI 소견", rightName = "의사 소견" }) {
  const [L, setL] = useState(true);
  const [R, setR] = useState(true);

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

/* 배율 슬라이더 */
export function Zoom({ value, onChange, min = 1, max = 40, unit = "x" }) {
  return (
    <div className="zoom">
      <span>배율</span>
      <input type="range" min={min} max={max} value={value}
             onChange={(e) => onChange?.(Number(e.target.value))} />
      <b>{value}{unit}</b>
    </div>
  );
}
