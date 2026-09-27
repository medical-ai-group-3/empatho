import { useState } from "react";
import { can } from "../perm";

/* 병리과와 영상의학과가 나눠 쓰는 조각들.
 *
 * 여기 있는 것은 **뼈대와 동작**이고 자료는 밖에서 넣는다.
 * 두 과의 화면이 같은 모양으로 보이는 것은 전부 이 파일 덕이다.
 */

/* ── 상태 칩 ──────────────────────────────────────────────────
   상태 색을 따로 만들지 않는다는 것이 이 판의 규칙이다. 그래서 셋으로
   가른다 — **채움**(지금 하는 중) · **외곽선**(끝남) · **시안 점**(기계가
   도는 중). 색을 못 가려도 모양이 다르다. */
export function Chip({ tone = "line", children }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

/* ── 권한 ────────────────────────────────────────────────────
 *
 * 두 가지로 쓴다.
 *   <Gate need="...">      권한이 없으면 **아예 안 보인다**
 *   useCan("...")          권한이 없으면 버튼을 **끄고 이유를 붙인다**
 *
 * 어느 쪽을 쓰나 — 그 자리에 무언가 있다는 걸 알아도 되면 끄고(useCan),
 * 있다는 것조차 몰라야 하면 감춘다(Gate). 판독 확정처럼 «권한이 있어야
 * 하는 일»은 끄는 쪽이 낫다. 버튼이 사라지면 고장으로 오해한다.
 */
export function Gate({ need, children, fallback = null }) {
  return can(need) ? children : fallback;
}

export function useCan(need) {
  const ok = can(need);
  return {
    ok,
    /* 버튼에 그대로 펼쳐 넣는다 — <Btn {...useCan(k).attrs}> */
    attrs: ok ? {} : { disabled: true, title: "권한이 없습니다. 관리자에게 문의하세요" },
  };
}

/* 화면 전체가 막혔을 때 — 네 가지 상태의 넷째다(Body.jsx 참고).
   **무슨 권한이 필요한지 적는다.** 「권한이 없습니다」만 띄우면 관리자에게
   무엇을 달라고 해야 하는지 몰라서 한 번 더 물으러 와야 한다. */
export function Locked({ what = "이 화면", need }) {
  return (
    <div className="state">
      <b>열람 권한이 없습니다</b>
      <span>
        {what}을 보려면 {need ? <code>{need}</code> : "해당"} 권한이 필요합니다.
        관리자에게 문의하세요.
      </span>
    </div>
  );
}

/* ── 정렬 pill ────────────────────────────────────────────── */
export function Sort({ items, value, onChange }) {
  return (
    <div className="sorts" role="group" aria-label="정렬">
      <span className="sorts-k">정렬</span>
      {items.map((it) => (
        <button key={it.key ?? it} className={`pill ${value === (it.key ?? it) ? "on" : ""}`}
                onClick={() => onChange?.(it.key ?? it)}>{it.label ?? it}</button>
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
   1장과 4장이 같은 모양이다. 오른쪽은 **고른 것이 없으면 비어 있지 않고**
   무엇을 고르라고 말한다. */
export function Split({ side = "normal", left, right, empty = "왼쪽에서 하나를 고르세요" }) {
  return (
    <div className={`split ${side === "wide" ? "wide" : ""} ${side === "third" ? "third" : ""}`}>
      <div className="split-l">{left}</div>
      <aside className="split-r">
        {right ?? <div className="slot"><b>{empty}</b></div>}
      </aside>
    </div>
  );
}

/* ── 대기열 ───────────────────────────────────────────────────
   **선착순 큐다.** 과 전체가 함께 보고, 누가 집으면 다른 사람 화면에서
   사라진다.

   ⚠ 순번은 **표시 전용**이다. 끌어서 못 옮긴다 — 도착 순서가 곧 순서이고,
     그것을 손으로 바꾸면 «내 화면에서만» 바뀐 것이 된다. 여럿이 보는
     큐에서 각자 순서를 바꾸면 같은 화면이 아니게 된다.

   대신 **검색**을 둔다. 순서를 안 바꾸고 건너뛰어 찾을 수 있게. */
export function Queue({ items, value, onPick, foot, onSearch, q,
                        searchHint = "환자 · 번호", emptyText = "대기 중인 건이 없습니다" }) {
  return (
    <div className="queue">
      {onSearch && (
        <div className="q-search">
          <Search placeholder={searchHint} value={q} onChange={onSearch} />
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
          <li><div className="q-empty">{emptyText}</div></li>
        )}
      </ul>
      {foot && <div className="q-foot">{foot}</div>}
    </div>
  );
}

/* ── 접었다 펴는 덩어리 ───────────────────────────────────────
   접힘/펼침은 **화면 상태라 서버가 모른다** — 저장하지 않는다.

   ⚠ 접힌 머리에 등급 같은 요약을 넣지 않는다. 접었다는 것은 «보고 싶지
     않다»는 뜻이라, 접힌 채로 결론을 흘려 보여주면 접은 의미가 없다. */
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

/* ── 표 목록 ──────────────────────────────────────────────────
   판독실에서 훑어보는 자리다. 줄 높이를 키우지 않고 촘촘하게 둔다.
   고른 줄은 왼쪽에 굵은 선.

   ⚠ 빈 문구를 **부르는 쪽이 정한다.** 「해당하는 환자가 없습니다」는
     검색 결과에는 맞지만 큐에는 틀리다 — 「접수 대기 중인 검체가
     없습니다」처럼 무엇이 비었는지 말해야 다음에 할 일이 보인다. */
export function Table({ cols, rows, value, onPick,
                        emptyText = "해당하는 환자가 없습니다" }) {
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
          {rows.length === 0 && (
            <tr className="none"><td colSpan={cols.length}>{emptyText}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ── 편집 모드 ────────────────────────────────────────────────
   **임시저장과 저장을 나란히 둔다.** 둘의 차이를 아래 한 줄로 적는다 —
   저장을 누르면 다른 과로 나간다는 것을 모르고 누르면 안 된다.

   권한이 없으면 버튼을 **감추지 않고 끈다.** 사라지면 고장으로 오해한다.

   ⚠ 왼쪽 단추 이름을 받는다(draftLabel). 정정 화면(5장)은 이 자리가
     임시저장이 아니라 **판독 화면으로 되돌아가기**다. 하는 일이 다른데
     이름이 「임시저장」이면, 써 둔 정정문이 남는 줄 알고 눌렀다가
     그대로 날린다. */
export function Save({ hint, onDraft, onSave, saveLabel = "저장", busy,
                       draftLabel = "임시저장",
                       draftNeed, saveNeed, canSave = true }) {
  const d = useCan(draftNeed);
  const s = useCan(saveNeed);
  return (
    <div className="save">
      {hint && <p className="hint">{hint}</p>}
      <div className="save-b">
        <button className="btn line" onClick={onDraft}
                disabled={busy || !d.ok} title={d.attrs.title}>{draftLabel}</button>
        <button className="btn fill" onClick={onSave}
                disabled={busy || !s.ok || !canSave} title={s.attrs.title}>{saveLabel}</button>
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

   환자 정보 · 영상 Viewer · 소견 **세 칸**이다. AI 소견과 의사 소견은
   한 칸 안에서 탭으로 오간다 — 둘을 따로 세우면 옆 칸이 늘어 영상이
   작아졌다. 칸을 접으면 그 폭이 손잡이(vtab)로 줄고 가운데 Viewer
   (flex:1)가 남는 공간을 그대로 흡수한다. */
export function Viewer({
  infoName = "환자 정보", info,
  aiName = "AI 소견", ai, aiOpen = false,          /* AI 는 기본 접힘 */
  doctorName = "의사 소견", doctor, doctorOpen = true,  /* 의사는 기본 펼침 */
  tools, below, children,
}) {
  const [L, setL] = useState(true);
  /* 소견 칸은 **하나**다 — AI 소견과 의사 소견을 탭으로 오간다. 둘을 따로
     세우면 뷰어 옆으로 칸이 셋이 되어 정작 영상이 작아졌다. 처음 여는
     탭은 펼쳐 두라고 한 쪽(기본 의사 소견)이다 */
  const both = Boolean(ai && doctor);
  const [open, setOpen] = useState(Boolean(doctor ? doctorOpen : aiOpen));
  const [which, setWhich] = useState(doctor && doctorOpen ? "doctor" : ai ? "ai" : "doctor");
  const shown = which === "ai" && ai ? ai : doctor ?? ai;
  const sideName = both ? "소견" : (doctor ? doctorName : aiName);

  return (
    <div className="vwrap">
      {info && (L
        ? <aside className="vside">
            <div className="vside-h"><b>{infoName}</b>
              <button className="x" onClick={() => setL(false)} aria-label="접기">‹</button></div>
            <div className="vside-b">{info}</div>
          </aside>
        : <button className="vtab" onClick={() => setL(true)}>{infoName}</button>)}

      <div className="viewer">
        <div className="vstage">
          {tools && <div className="vtools">{tools}</div>}
          {children}
        </div>
        {below && <div className="vunder">{below}</div>}
      </div>

      {(ai || doctor) && (open
        ? <aside className="vside">
            <div className="vside-h">
              {both ? (
                <span className="vside-tabs" role="tablist">
                  <button type="button" role="tab" aria-selected={which === "doctor"}
                          className={which === "doctor" ? "on" : ""}
                          onClick={() => setWhich("doctor")}>{doctorName}</button>
                  <button type="button" role="tab" aria-selected={which === "ai"}
                          className={which === "ai" ? "on" : ""}
                          onClick={() => setWhich("ai")}>{aiName}</button>
                </span>
              ) : <b>{sideName}</b>}
              <button className="x" onClick={() => setOpen(false)} aria-label="접기">›</button>
            </div>
            <div className="vside-b">{shown}</div>
          </aside>
        : <button className="vtab" onClick={() => setOpen(true)}>{sideName}</button>)}
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

/* 정의 목록 — 「이름 : 값」이 줄줄이 있는 자리. 좌측 정보 패널이 쓴다 */
export function Facts({ items }) {
  return (
    <dl className="kv">
      {items.filter(Boolean).map(([k, v], i) => (
        <div key={i}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

/* 눈에 띄어야 하는 경고 한 줄 — 조영제 알레르기처럼 촬영 전에 반드시
   보여야 하는 값. 색을 새로 만들지 않고 채움 칩 + 굵은 글씨로 세운다 */
export function Warn({ children }) {
  return <p className="warnline"><span aria-hidden="true">⚠</span> {children}</p>;
}
