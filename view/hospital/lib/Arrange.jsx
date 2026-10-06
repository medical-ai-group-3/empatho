import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

/* 칸 배치 — 끌어서 옮기기 · 편집 모드 · 저장
 * ════════════════════════════════════════════════════════════════
 *
 * 홈(lib/Home.jsx)에서 쓰던 것을 떼어 냈다(09-28). 칸으로 짜인 화면이면
 * 어디서든 쓴다.
 *
 *   const lay = useArrange("patient", base);      // base = [[칸 id…], …] 단마다
 *   <ArrangeBar lay={lay} />                       // 머리 오른쪽의 「배치 편집」
 *   <Panes lay={lay} cards={{ id: <칸/> }} className="…" paneClass="…" />
 *   칸 안에서는 <Grip title="…" /> 를 머리 맨 앞에 둔다(편집 중에만 보인다)
 *
 * ⚠ **평소에는 손잡이도 막대도 없다.** 「배치 편집」을 눌러야 손잡이가 나오고
 *   [기본 배치로] [취소] [저장] 막대가 뜬다. 저장 · 취소하면 막대가 사라진다 —
 *   예전에는 한 번 옮기면 「기본 배치로」 줄이 계속 남아 화면 위가 비었다.
 * ⚠ 배치는 이 브라우저에 화면별로 남긴다(localStorage). 환자 정보가 없고
 *   칸 이름의 순서뿐이라 공용 PC 에 남아도 된다.
 */

const KEY = (name) => `empatho.layout.${name}`;
/* 홈은 예전 열쇠를 그대로 읽는다 — 이미 옮겨 둔 배치가 날아가지 않게 */
const LEGACY = (name) => (name.startsWith("home.") ? `empatho.home.layout.${name.slice(5)}` : null);

function read(name) {
  try {
    const raw = localStorage.getItem(KEY(name)) ?? (LEGACY(name) && localStorage.getItem(LEGACY(name)));
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function write(name, v) {
  try {
    if (v == null) {
      localStorage.removeItem(KEY(name));
      if (LEGACY(name)) localStorage.removeItem(LEGACY(name));
    } else localStorage.setItem(KEY(name), JSON.stringify(v));
  } catch { /* 못 쓰면 이번 화면에서만 바뀐다 */ }
}

/* 저장된 배치를 지금 있는 칸에 맞춘다. 없어진 칸은 버리고, 새로 생긴
   칸은 기본 자리 단의 끝에 붙인다 — 화면이 바뀌어도 칸이 사라지지 않게 */
export function fit(saved, base) {
  if (!Array.isArray(saved) || saved.length !== base.length) return base;
  const all = new Set(base.flat());
  const used = new Set();
  const out = saved.map((ids) => (Array.isArray(ids) ? ids : [])
    .filter((id) => all.has(id) && !used.has(id) && used.add(id)));
  base.forEach((ids, p) => ids.forEach((id) => { if (!used.has(id)) out[p].push(id); }));
  return out;
}

export function useArrange(name, base) {
  const baseKey = JSON.stringify(base);
  const [saved, setSaved] = useState(() => read(name));
  const [draft, setDraft] = useState(null);      /* 편집 중일 때만 배열 */
  const [dragging, setDragging] = useState(null);
  const [over, setOver] = useState(null);         /* { pane, id, after } */
  const focusNext = useRef(null);
  const settled = useMemo(() => fit(saved, JSON.parse(baseKey)), [saved, baseKey]);
  const editing = draft != null;
  const panes = editing ? fit(draft, JSON.parse(baseKey)) : settled;

  useEffect(() => {
    if (!focusNext.current) return;
    document.querySelector(`[data-grip="${focusNext.current}"]`)?.focus();
    focusNext.current = null;
  }, [panes]);

  function place(id, pane, at) {
    const next = panes.map((ids) => ids.filter((x) => x !== id));
    next[pane].splice(Math.max(0, Math.min(at, next[pane].length)), 0, id);
    setDraft(next);
  }

  function where(id) {
    const p = panes.findIndex((ids) => ids.includes(id));
    return [p, p < 0 ? -1 : panes[p].indexOf(id)];
  }

  function drop() {
    if (dragging && over) {
      const { pane, id, after } = over;
      if (id == null) place(dragging, pane, Infinity);
      else if (id !== dragging) {
        const rest = panes[pane].filter((x) => x !== dragging);
        place(dragging, pane, rest.indexOf(id) + (after ? 1 : 0));
      }
    }
    setDragging(null); setOver(null);
  }

  function key(id, e) {
    const [p, i] = where(id);
    const to = {
      ArrowUp:    [p, i - 1],
      ArrowDown:  [p, i + 1],
      ArrowLeft:  [p - 1, i],
      ArrowRight: [p + 1, i],
    }[e.key];
    if (!to || to[0] < 0 || to[0] >= panes.length) return;
    e.preventDefault();
    focusNext.current = id;
    place(id, to[0], Math.max(0, to[1]));
  }

  const slot = (id) => editing ? ({
    id,
    dragging: dragging === id,
    mark: over?.id === id && dragging !== id ? (over.after ? "after" : "before") : null,
    start: (e, el) => {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", id);   /* 파이어폭스는 이게 없으면 안 끈다 */
      if (el) e.dataTransfer.setDragImage(el, 24, 20);
      setDragging(id);
    },
    end: () => { setDragging(null); setOver(null); },
    over: (e, el) => {
      if (!dragging) return;
      e.preventDefault(); e.stopPropagation();
      const box = el.getBoundingClientRect();
      const after = e.clientY > box.top + box.height / 2;
      const [p] = where(id);
      if (over?.id !== id || over.after !== after) setOver({ pane: p, id, after });
    },
    drop: (e) => { e.preventDefault(); e.stopPropagation(); drop(); },
    key: (e) => key(id, e),
  }) : null;

  return {
    panes, editing, dragging, over, slot, drop,
    hover: (pane, id) => { if (over?.pane !== pane || over.id !== id) setOver({ pane, id }); },
    custom: saved != null && JSON.stringify(settled) !== baseKey,
    edit: () => setDraft(settled),
    cancel: () => { setDraft(null); setDragging(null); setOver(null); },
    /* 기본 배치로 — 편집 중인 판을 기본으로 돌린다. 저장해야 남는다 */
    reset: () => setDraft(JSON.parse(baseKey)),
    save: () => {
      const next = fit(draft, JSON.parse(baseKey));
      const isBase = JSON.stringify(next) === baseKey;
      setSaved(isBase ? null : next);
      write(name, isBase ? null : next);
      setDraft(null); setDragging(null); setOver(null);
    },
  };
}

/* 칸이 자기 손잡이와 끌어 놓기 처리를 꺼내 쓰는 자리 */
export const Slot = createContext(null);
export const useSlot = () => useContext(Slot);

/* 머리 오른쪽의 「배치 편집」 · 편집 중이면 [기본 배치로] [취소] [저장].
   ⚠ 편집 중이 아닐 때는 **단추 하나**뿐이라 줄을 따로 차지하지 않는다 */
export function ArrangeBar({ lay, className = "" }) {
  if (!lay.editing) {
    return (
      <button type="button" className={`arr-edit ${className}`.trim()} onClick={lay.edit}
              title="칸 배치를 바꿉니다">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1" />
          <rect x="9" y="1.5" width="5.5" height="5.5" rx="1" />
          <rect x="1.5" y="9" width="5.5" height="5.5" rx="1" />
          <rect x="9" y="9" width="5.5" height="5.5" rx="1" />
        </svg>
        배치 편집
      </button>
    );
  }
  return (
    <div className={`arr-bar ${className}`.trim()} role="toolbar" aria-label="칸 배치 편집">
      <span className="arr-hint">칸 왼쪽 위 ⠿ 를 끌거나 방향키로 옮깁니다</span>
      <button type="button" className="btn line sm" onClick={lay.reset}>기본 배치로</button>
      <button type="button" className="btn line sm" onClick={lay.cancel}>취소</button>
      {/* 검은 채움 — 시안은 그 화면의 주 동작(머리의 [다음 검사 시작] 등)
          몫이라 여기까지 시안이면 한 줄에 주 동작이 둘로 읽혔다(09-28) */}
      <button type="button" className="btn dark sm" onClick={lay.save}>저장</button>
    </div>
  );
}

/* 단들을 그린다. cards[id] 가 비면(권한 · 자료 없음) 그 칸은 안 세운다.
 *
 * cols — 단마다 격자 폭(["minmax(0,1.5fr)", …]). 주면 **빈 단을 접는다**:
 *   평소에는 칸이 하나도 없는 단을 안 그리고 남은 단이 폭을 나눠 갖는다 —
 *   칸을 다 옮긴 단이 빈 세로줄로 남던 것(09-28). 편집 중에는 다시 끌어다
 *   놓을 수 있게 빈 단도 세운다.
 *   cols 의 한 자리가 null 이면 그 단은 세로줄이 아니라 **폭을 다 쓰는 줄**
 *   이다(grid-column 1 / -1, .arr-span) — 두 단 밑에 가로로 긴 칸 하나.
 *
 * only — 이 자리에서 그릴 단 번호([0] 등). 단들이 화면의 서로 다른 곳에
 *   흩어져 있으면(왼쪽 아래 · 오른쪽 단) 같은 lay 로 Panes 를 여러 번
 *   부른다. 옮기기 · 저장은 lay 하나라 단 사이로 그대로 옮겨진다 */
export function Panes({ lay, cards, className = "", paneClass = "", cols = null, only = null }) {
  const live = lay.panes.map((ids) => ids.filter((id) => cards[id]));
  const show = live.map((ids, p) => (!only || only.includes(p))
    && (lay.editing || ids.length > 0 || !cols));
  const style = cols
    ? { gridTemplateColumns: cols.filter((c, i) => show[i] && c != null).join(" ") || undefined }
    : undefined;
  return (
    <div className={`${className}${lay.editing ? " arr-on" : ""}`.trim()} style={style}>
      {lay.panes.map((ids, p) => show[p] && (
        <div className={`${paneClass}${lay.over?.pane === p && lay.over.id == null ? " drop-end" : ""}${
               live[p].length === 0 ? " arr-empty" : ""}${cols && cols[p] == null ? " arr-span" : ""}`.trim()}
             key={p} data-pane={p}
             onDragOver={(e) => lay.dragging && (e.preventDefault(), lay.hover(p, null))}
             onDrop={(e) => { e.preventDefault(); lay.drop(); }}>
          {ids.filter((id) => cards[id]).map((id) => (
            <Slot.Provider key={id} value={lay.slot(id)}>
              <Wrap>{cards[id]}</Wrap>
            </Slot.Provider>
          ))}
        </div>
      ))}
    </div>
  );
}

/* 칸 하나를 끌어 놓기 받는 틀로 감싼다 — 칸 컴포넌트가 Grip 을 안 그려도
   (예: 기존 카드) 편집 중에는 틀 위에 손잡이가 선다. display:contents 가
   아닌 이유: 드래그 이벤트를 받을 상자가 있어야 한다 */
function Wrap({ children }) {
  const slot = useSlot();
  const self = useRef(null);
  if (!slot) return children;
  const cls = ["arr-slot", slot.dragging && "dragging", slot.mark && `drop-${slot.mark}`]
    .filter(Boolean).join(" ");
  return (
    <div ref={self} className={cls}
         onDragOver={(e) => slot.over(e, self.current)} onDrop={slot.drop}>
      <span className="arr-grip" role="button" tabIndex={0} draggable data-grip={slot.id}
            aria-label="칸 옮기기 — 끌거나 방향키" title="끌어서 옮기기 · 방향키로도 옮깁니다"
            onDragStart={(e) => slot.start(e, self.current)} onDragEnd={slot.end}
            onKeyDown={slot.key}>⠿</span>
      {children}
    </div>
  );
}
