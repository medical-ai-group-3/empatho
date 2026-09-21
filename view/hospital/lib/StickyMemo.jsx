import { useEffect, useRef, useState } from "react";
import { notes as notesApi } from "../api";
import { useApi } from "./useApi";

/* 화면 전체에 뜨는 메모지 — 컴퓨터 바탕화면 스티커 메모처럼, 과를
 * 옮기거나 화면을 이동해도(라우트가 바뀌어도) 계속 떠 있어야 한다는
 * 요구라 여기 이 화면 하나 안에 두면 안 된다. main.jsx 의 Shell()에
 * 마운트한다 — Shell은 <Outlet/>을 감싸는 자리라 라우트가 바뀌어도
 * 다시 마운트되지 않는다.
 *
 * ⚠ 저장할 서버 자리가 없다(대시보드 TODO와 같은 사정, 2026-09-18
 *   확정 — DB·API는 필요할 때 만든다). 이건 애초에 "내 컴퓨터에서만
 *   보이는 메모"라는 성격상 서버에 안 올려도 이상하지 않다 — localStorage
 *   에 둔다. 새로고침·재접속에도 남고, 다른 기기에서는 안 보인다.
 *
 * 접었다 펼 수 있다 — 늘 펴져 있으면 화면을 가린다. 위치·크기·펼침
 * 상태·글 내용을 전부 localStorage에 따로 저장해 다음에 열 때 그대로
 * 돌아온다. */
const KEY = "hospital.stickyMemo.v1";
const EDGE = 12;

/* 저장된 좌표와 드래그 좌표 모두 이 함수만 통과시킨다. 화면 크기가
   달라져도 메모 전체가 브라우저 안에 남아, 화면 밖으로 보내 버리는 일이
   없다. */
function keepInView(v) {
  const width = Math.min(v.w ?? DEFAULT.w, Math.max(200, window.innerWidth - EDGE * 2));
  const height = Math.min(v.h ?? DEFAULT.h, Math.max(160, window.innerHeight - EDGE * 2));
  const maxX = Math.max(EDGE, window.innerWidth - width - EDGE);
  const maxY = Math.max(EDGE, window.innerHeight - height - EDGE);
  const x = v.x == null ? maxX : Math.min(maxX, Math.max(EDGE, v.x));
  const y = v.y == null ? maxY : Math.min(maxY, Math.max(EDGE, v.y));
  return { ...v, x, y, w: width, h: height };
}

function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (typeof s !== "object" || s === null) return null;
    return s;
  } catch {
    return null;
  }
}

function saveState(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* 못 쓰면 그냥 이번 세션만 산다 */ }
}

const DEFAULT = { text: "", open: true, x: null, y: null, w: 260, h: 220 };

export default function StickyMemo() {
  const [s, setS] = useState(() => ({ ...DEFAULT, ...loadState() }));
  const [noteId, setNoteId] = useState(null);
  const boxRef = useRef(null);
  const dragRef = useRef(null);
  const remote = useApi(() => notesApi.list("sticky"), []);

  useEffect(() => { saveState(s); }, [s]);

  /* 서버 메모는 다른 기기에서도 이어 보는 내용만 맡고, 창 위치·크기는
     각 기기의 화면 크기에 맞게 로컬에 둔다. */
  useEffect(() => {
    const note = remote.data?.[0];
    if (!note || noteId) return;
    setNoteId(note.note_id ?? note.id);
    const text = note.content?.text;
    if (typeof text === "string") setS((v) => ({ ...v, text }));
  }, [remote.data, noteId]);

  async function saveRemote() {
    const content = { text: s.text, color: "yellow" };
    try {
      if (noteId) await notesApi.update(noteId, content);
      else {
        const out = await notesApi.create("sticky", content);
        setNoteId(out.note_id ?? out.id);
      }
    } catch {
      /* 입력을 지우지 않는다. 다음 수정 때 다시 저장을 시도한다. */
    }
  }

  /* 첫 렌더엔 위치가 없다(x·y null) — 오른쪽 아래 기본 자리를
     뷰포트 기준으로 한 번 잡아 둔다. */
  useEffect(() => {
    setS((v) => keepInView(v));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* 창을 줄였을 때 이전의 오른쪽 좌표가 화면 밖에 남지 않게 보정한다. */
  useEffect(() => {
    const fit = () => setS((v) => keepInView(v));
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  /* onTap — 접힌 탭은 버튼이라 «눌렀다 뗐다»가 "펼치기"도 되고
     "옮기기"도 된다. 드래그 중 몇 픽셀이라도 움직였으면 뗄 때 펼치지
     않는다 — 안 그러면 옮기려고 누를 때마다 같이 펼쳐진다. */
  function startDrag(e, onTap) {
    dragRef.current = {
      startX: e.clientX, startY: e.clientY, origX: s.x, origY: s.y, moved: false, onTap,
    };
    window.addEventListener("mousemove", onDrag);
    window.addEventListener("mouseup", stopDrag);
  }
  function onDrag(e) {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;
    setS((v) => keepInView({ ...v, x: d.origX + dx, y: d.origY + dy }));
  }
  function stopDrag() {
    const d = dragRef.current;
    dragRef.current = null;
    window.removeEventListener("mousemove", onDrag);
    window.removeEventListener("mouseup", stopDrag);
    if (d && !d.moved) d.onTap?.();
  }

  /* 크기조절은 네이티브 resize:both 핸들을 쓴다 — 놓을 때 실제 크기를
     읽어 상태에 반영해야 다음에 열 때도 그 크기로 뜬다. */
  function onResizeEnd() {
    const el = boxRef.current;
    if (!el) return;
    setS((v) => keepInView({ ...v, w: el.offsetWidth, h: el.offsetHeight }));
  }

  if (s.x == null) return null; // 첫 위치 계산 전 프레임엔 안 그린다(깜빡임 방지)

  if (!s.open) {
    return (
      <button type="button" className="sticky-memo-tab"
        style={{ left: s.x, top: s.y }}
        onMouseDown={(e) => startDrag(e, () => setS((v) => ({ ...v, open: true })))}>
        📝 메모
      </button>
    );
  }

  return (
    <div ref={boxRef} className="sticky-memo"
      style={{ left: s.x, top: s.y, width: s.w, height: s.h }}
      onMouseUp={onResizeEnd}>
      <div className="sticky-memo-head" onMouseDown={(e) => startDrag(e)}>
        <span>📝 메모</span>
        <button type="button" aria-label="접기" onClick={() => setS((v) => ({ ...v, open: false }))}>
          −
        </button>
      </div>
      <textarea
        value={s.text}
        onChange={(e) => setS((v) => ({ ...v, text: e.target.value }))}
        onBlur={saveRemote}
        placeholder="여기에 적어 두면 다른 화면으로 옮겨도 그대로 있습니다"
      />
    </div>
  );
}
