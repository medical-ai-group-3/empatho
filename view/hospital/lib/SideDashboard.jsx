import { useState } from "react";
import { Card } from "./Page";

/* 과 공용 "내 업무" 패널 — 목록 옆(또는 아래)에 두는 캘린더·TODO·오늘
 * 현황 위젯 묶음이다. 원래 유방외과 대기 화면 하나에만 있었는데(2026-09-18),
 * 같은 형식을 간호과·병리과·영상의학과에도 쓰기로 해서 여기 lib/로
 * 옮겨 공용으로 만들었다. 과마다 목록 모양이 다르므로(환자·검체·오더)
 * 원본 데이터 대신 이미 계산된 stats 배열을 받는다 — 과 화면이 자기
 * 데이터에서 무엇을 셀지 정한다.
 *
 * ⚠ 아직 저장할 서버 자리가 없다(2026-09-18 확정 — DB·API는 필요할 때
 *   만든다). TODO·캘린더 이동은 로컬 상태다 — 새로고침하거나 다른
 *   화면으로 나가면(이 컴포넌트가 마운트 해제되면) 사라진다. 서버
 *   리소스가 생기면 useApi 로 갈아 끼운다. */
export default function SideDashboard({ stats = [] }) {
  return (
    <Card title="내 업무" className="b-dash" pad={false}>
      <div className="b-dash-body">
        {stats.length > 0 && <TodaySummary stats={stats} />}
        <MiniCalendar />
        <TodoList />
      </div>
    </Card>
  );
}

function TodaySummary({ stats }) {
  return (
    <div className="b-dash-summary">
      {stats.map((s) => (
        <div className="b-dash-stat" key={s.label}>
          <span className={`b-dash-num ${s.warn ? "warn" : ""}`}>{s.value}</span>
          <span className="b-dash-label">{s.label}</span>
        </div>
      ))}
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
