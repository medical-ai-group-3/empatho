import { useEffect, useRef, useState } from "react";

/* 생년월일 — 누르면 년 · 월 · 일 세 줄을 위아래로 굴려 고르는 창이 뜬다.
 *
 * 한 칸씩 멈추는 것은 CSS 스크롤 스냅이 한다(index.css 의 .wheel).
 * 휠을 JS 로 그리지 않는다 — 손가락 관성 · 접근성을 브라우저가 맡는다.
 *
 * 값은 "YYYY-MM-DD". 비어 있으면 1980-01-01 에서 시작한다.
 * 굴리는 동안은 창 안에서만 바뀌고, 「확인」을 눌러야 바깥 값이 된다.
 */
const ROW = 44;                       // .wheel li 높이와 같아야 한다
const START = "1980-01-01";
const pad = (n) => String(n).padStart(2, "0");
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
const lastDay = (y, m) => new Date(y, m, 0).getDate();

export default function DateWheel({ value, onChange, disabled }) {
  const [open, setOpen] = useState(false);
  const [y, m, d] = (value || START).split("-").map(Number);
  const [sel, setSel] = useState({ y, m, d });

  // 2월 30일 같은 날이 생기지 않게 일을 그 달 마지막 날로 줄인다
  const pick = (k) => (v) => setSel((s) => {
    const n = { ...s, [k]: v };
    return { ...n, d: Math.min(n.d, lastDay(n.y, n.m)) };
  });

  function show() { setSel({ y, m, d }); setOpen(true); }
  function done() { onChange(`${sel.y}-${pad(sel.m)}-${pad(sel.d)}`); setOpen(false); }

  return (
    <>
      <button type="button" className="date-field" onClick={show} disabled={disabled}>
        {value ? `${y}년 ${pad(m)}월 ${pad(d)}일`
               : <span className="ph">생년월일을 골라 주세요</span>}
      </button>

      {open && (
        <div className="sheet-back" onClick={() => setOpen(false)}>
          <div className="sheet" role="dialog" aria-label="생년월일 고르기"
               onClick={(e) => e.stopPropagation()}>
            <div className="wheels">
              <Wheel items={range(1900, new Date().getFullYear())} value={sel.y}
                     onPick={pick("y")} unit="년" />
              <Wheel items={range(1, 12)} value={sel.m} onPick={pick("m")} unit="월" two />
              <Wheel items={range(1, lastDay(sel.y, sel.m))} value={sel.d}
                     onPick={pick("d")} unit="일" two />
            </div>
            <button type="button" className="btn" onClick={done}>확인</button>
          </div>
        </div>
      )}
    </>
  );
}

function Wheel({ items, value, onPick, unit, two }) {
  const ref = useRef(null);

  // 열릴 때 한 번만 고른 값으로 맞춘다. 굴리는 중에 맞추면 손가락과 싸운다.
  useEffect(() => {
    ref.current.scrollTop = Math.max(0, items.indexOf(value)) * ROW;
  }, []);

  function onScroll() {
    const v = items[Math.round(ref.current.scrollTop / ROW)];
    if (v !== undefined && v !== value) onPick(v);
  }

  const go = (v) =>
    ref.current.scrollTo({ top: items.indexOf(v) * ROW, behavior: "smooth" });

  return (
    <ul className="wheel" ref={ref} onScroll={onScroll} tabIndex={0} aria-label={unit}>
      {items.map((v) => (
        <li key={v} className={v === value ? "on" : ""} onClick={() => go(v)}>
          <b>{two ? pad(v) : v}</b>{unit}
        </li>
      ))}
    </ul>
  );
}
