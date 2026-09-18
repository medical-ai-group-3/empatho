import { useState } from "react";

/* 대기 목록 왼쪽 칸 아래를 채우는 개인 업무 패널 — 목록 하나만 있으면
 * 환자가 몇 명 안 될 때 카드 밑이 허전하게 빈다(오른쪽 환자 상세 카드는
 * 항상 키가 크다). 여기 세 위젯(캘린더·TODO·오늘 현황)을 쌓아서
 * flex:1로 나머지 세로 공간을 채운다 — Waiting.jsx의 .b-left-col 참고.
 *
 * ⚠ 아직 저장할 서버 자리가 없다(2026-09-18 — DB·API는 필요할 때 만들기로
 *   확정). TODO는 지금은 이 화면을 벗어나면(새로고침) 사라지는 로컬
 *   상태다 — 서버 리소스가 생기면 useApi 로 갈아 끼운다. 캘린더도 지금은
 *   달만 넘기는 그리드고 일정 표시는 아직 없다(무엇을 "일정"으로 볼지
 *   — 검사 예약인지 개인 메모인지 — 확정 전에는 점을 찍을 근거가 없다).
 *   "오늘 현황"은 지어낸 로그 대신 지금 대기 목록에서 바로 셀 수 있는
 *   실제 값(대기 인원·불일치 건수)을 보여준다. */
export default function SideDashboard({ list }) {
  return (
    <div className="card b-dash">
      <div className="pt-card-head">
        <h3>내 업무</h3>
      </div>
      <div className="b-dash-body">
        <TodaySummary list={list} />
        <MiniCalendar />
        <TodoList />
      </div>
    </div>
  );
}

function TodaySummary({ list }) {
  const waiting = list?.length ?? 0;
  const urgent = list?.filter((p) => p.has_open_discordance).length ?? 0;
  return (
    <div className="b-dash-summary">
      <div className="b-dash-stat">
        <span className="b-dash-num">{waiting}</span>
        <span className="b-dash-label">오늘 대기</span>
      </div>
      <div className="b-dash-stat">
        <span className="b-dash-num warn">{urgent}</span>
        <span className="b-dash-label">불일치 확인</span>
      </div>
    </div>
  );
}

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

function MiniCalendar() {
  const today = new Date();
  const [y, setY] = useState(today.getFullYear());
  const [m, setM] = useState(today.getMonth()); // 0-based

  const first = new Date(y, m, 1);
  const startDay = first.getDay();
  const days = new Date(y, m + 1, 0).getDate();
  const cells = [...Array(startDay).fill(null), ...Array(days).keys()].map((d) => (d == null ? null : d + 1));

  function move(delta) {
    const next = new Date(y, m + delta, 1);
    setY(next.getFullYear());
    setM(next.getMonth());
  }

  const isToday = (d) => d === today.getDate() && m === today.getMonth() && y === today.getFullYear();

  return (
    <div className="b-cal">
      <div className="b-cal-head">
        <button type="button" className="b-cal-nav" onClick={() => move(-1)} aria-label="이전 달">‹</button>
        <b>{y}년 {m + 1}월</b>
        <button type="button" className="b-cal-nav" onClick={() => move(1)} aria-label="다음 달">›</button>
      </div>
      <div className="b-cal-grid b-cal-week">
        {WEEK.map((w) => <span key={w}>{w}</span>)}
      </div>
      <div className="b-cal-grid">
        {cells.map((d, i) => (
          <span key={i} className={d && isToday(d) ? "b-cal-today" : ""}>{d ?? ""}</span>
        ))}
      </div>
    </div>
  );
}

/* 상태 세 갈래 — 뱃지 색으로 바로 구분되게 한다(2026-09-18 참고 디자인:
   표 형태 · # · 이름 · 상태 뱃지 · 수정 · 삭제). 클릭 한 번으로 다음
   상태로 넘기는 게 아니라 ✎(수정)을 눌러야 바꾸게 했다 — 실수로
   지나가다 상태가 바뀌면 안 된다. */
const STATUS = [
  { v: "todo", label: "할 일" },
  { v: "doing", label: "진행 중" },
  { v: "done", label: "완료" },
];

function TodoList() {
  const [items, setItems] = useState([]);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(null); // 수정 중인 id
  const [draft, setDraft] = useState({ text: "", status: "todo" });

  function add() {
    const v = text.trim();
    if (!v) return;
    setItems((s) => [...s, { id: Date.now(), text: v, status: "todo" }]);
    setText("");
  }

  function remove(id) {
    setItems((s) => s.filter((it) => it.id !== id));
    if (editing === id) setEditing(null);
  }

  function startEdit(it) {
    setEditing(it.id);
    setDraft({ text: it.text, status: it.status });
  }

  function saveEdit(id) {
    const v = draft.text.trim();
    if (!v) { remove(id); return; }
    setItems((s) => s.map((it) => (it.id === id ? { ...it, text: v, status: draft.status } : it)));
    setEditing(null);
  }

  return (
    <div className="b-todo">
      <div className="b-todo-head">
        <span>할 일</span>
        <div className="b-todo-add">
          <input value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="할 일 추가" />
          <button type="button" className="btn ghost sm" onClick={add}>+ 추가</button>
        </div>
      </div>
      {items.length === 0 ? (
        <p className="b-todo-empty">할 일이 없습니다</p>
      ) : (
        <table className="b-todo-table">
          <thead>
            <tr><th>#</th><th>할 일</th><th>상태</th><th></th><th></th></tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={it.id}>
                {editing === it.id ? (
                  <>
                    <td>{i + 1}</td>
                    <td>
                      <input className="b-todo-edit-text" value={draft.text}
                        onChange={(e) => setDraft((d) => ({ ...d, text: e.target.value }))}
                        onKeyDown={(e) => e.key === "Enter" && saveEdit(it.id)}
                        autoFocus />
                    </td>
                    <td>
                      <select value={draft.status}
                        onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}>
                        {STATUS.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                      </select>
                    </td>
                    <td colSpan={2} className="b-todo-actions">
                      <button type="button" aria-label="저장" onClick={() => saveEdit(it.id)}>✓</button>
                      <button type="button" aria-label="취소" onClick={() => setEditing(null)}>✕</button>
                    </td>
                  </>
                ) : (
                  <>
                    <td>{i + 1}</td>
                    <td className="b-todo-name">{it.text}</td>
                    <td>
                      <span className={`b-todo-pill ${it.status}`}>
                        {STATUS.find((s) => s.v === it.status)?.label}
                      </span>
                    </td>
                    <td className="b-todo-actions">
                      <button type="button" aria-label="수정" onClick={() => startEdit(it)}>✎</button>
                    </td>
                    <td className="b-todo-actions">
                      <button type="button" aria-label="삭제" onClick={() => remove(it.id)}>🗑</button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
