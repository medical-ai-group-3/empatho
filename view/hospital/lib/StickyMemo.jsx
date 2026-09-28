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
 * 돌아온다.
 *
 * ⚠ **처음엔 접힌 알약으로, 왼쪽 아래에 뜬다**(09-28 점검). 펼친 채
 *   오른쪽 아래에 두었더니 1600×950 에서 거의 모든 화면의 주 단추
 *   (목록 [판독 화면] · 판독 입력칸 · [처분 확정] · 정정 [저장] · 접수)를
 *   덮었다. 화면들은 주 단추를 오른쪽 아래에 모은다 — 그 자리를 비운다.
 *   사람이 한 번이라도 펴거나 옮기면(picked) 그 뒤로는 그 선택을 따른다. */
const KEY = "hospital.stickyMemo.v1";
const EDGE = 12;

/* 저장된 좌표와 드래그 좌표 모두 이 함수만 통과시킨다. 화면 크기가
   달라져도 메모 전체가 브라우저 안에 남아, 화면 밖으로 보내 버리는 일이
   없다. */
function keepInView(v, seen) {
  const width = Math.min(v.w ?? DEFAULT.w, Math.max(200, window.innerWidth - EDGE * 2));
  const height = Math.min(v.h ?? DEFAULT.h, Math.max(160, window.innerHeight - EDGE * 2));

  /* ⚠ **가두는 기준은 «지금 화면에 떠 있는 것»의 크기다.**
   *
   *   접힌 탭은 작은 알약인데 펼친 창의 260×220 으로 재고 있었다. 그래서
   *   접었을 때 오른쪽 약 250px · 아래 약 210px 이 «못 가는 띠»가 됐다 —
   *   그쪽으로 끌면 손은 따라가는데 메모만 도로 튕겨 나온다. 좁은 창에서는
   *   띠가 화면 절반이라 아예 안 움직이는 것처럼 보인다(09-23).
   *
   * ⚠ **펼친 창의 저장된 크기(w·h)는 그대로 둔다.** 탭 크기로 덮어쓰면
   *   다시 펼칠 때 창이 알약만 해진다. 아래 반환값이 width·height 를
   *   쓰는 이유다 — seen 은 좌표를 가둘 때만 쓴다. */
  const fitW = seen?.w ?? width;
  const fitH = seen?.h ?? height;

  const maxX = Math.max(EDGE, window.innerWidth - fitW - EDGE);
  const maxY = Math.max(EDGE, window.innerHeight - fitH - EDGE);
  /* 기본 자리는 왼쪽 아래 — 오른쪽 아래는 화면들의 주 단추 자리다 */
  const x = v.x == null ? EDGE : Math.min(maxX, Math.max(EDGE, v.x));
  const y = v.y == null ? maxY : Math.min(maxY, Math.max(EDGE, v.y));
  return { ...v, x, y, w: width, h: height };
}

function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (typeof s !== "object" || s === null) return null;
    /* ⚠ 예전 기본값은 «펼친 채 오른쪽 아래»였다. 사람이 고른 적 없는
       저장값(picked 없음)은 그 기본값이 저장된 것뿐이라 자리·펼침을
       버리고 새 기본(접힘 · 왼쪽 아래)으로 뜬다. 글과 크기는 남긴다 */
    if (!s.picked) return { ...s, open: false, x: null, y: null };
    return s;
  } catch {
    return null;
  }
}

function saveState(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* 못 쓰면 그냥 이번 세션만 산다 */ }
}

/* picked — 사람이 펴거나 접거나 옮긴 적이 있다. 있으면 그 자리·펼침을 믿는다 */
const DEFAULT = { text: "", open: false, x: null, y: null, w: 260, h: 220, picked: false };

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

  /* 좌표를 가둘 때 쓸 «지금 떠 있는 것»의 크기.
   *
   * ⚠ **펼친 창은 재지 않고 저장된 크기를 쓴다.** 창도 탭도 left 만 잡힌
   *   fixed 라, 오른쪽으로 갈수록 실제 폭이 남은 자리만큼 줄어든다. 그
   *   줄어든 폭으로 다시 가두면 더 오른쪽까지 갈 수 있게 되고, 그러면 또
   *   줄어든다 — 끌수록 밀려 나가는 악순환이다. 창은 저장된 w·h 가
   *   「원래 이만하다」는 값이라 그것으로 잰다.
   *   탭은 저장된 크기가 없어서 재야 하는데, 이제 줄바꿈을 막아 뒀으므로
   *   (hospital.css 의 white-space:nowrap) 폭이 위치와 상관없이 일정하다. */
  function fit(v) {
    if (v.open) return keepInView(v);
    const el = boxRef.current;
    return keepInView(v, el ? { w: el.offsetWidth, h: el.offsetHeight } : null);
  }

  /* 첫 렌더엔 위치가 없다(x·y null) — 왼쪽 아래 기본 자리를
     뷰포트 기준으로 한 번 잡아 둔다. */
  useEffect(() => {
    setS((v) => keepInView(v));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ⚠ 위 첫 자리는 펼친 창 크기(260×220)로 잡힌다 — 접힌 알약이면 바닥에서
     200px 넘게 떠 있었다. 알약이 그려진 뒤 제 크기로 한 번 더 가둔다 */
  const placed = s.x != null;
  useEffect(() => {
    if (!placed) return;
    setS((v) => (v.picked ? v : fit({ ...v, y: null })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed]);

  /* 접었다 펼 때 크기가 확 달라진다 — 그때마다 다시 가둔다. 탭을 오른쪽
     끝까지 끌어 두고 펼치면 창이 화면 밖으로 나가기 때문이다. */
  useEffect(() => {
    setS((v) => fit(v));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.open]);

  /* 창을 줄였을 때 이전의 오른쪽 좌표가 화면 밖에 남지 않게 보정한다. */
  useEffect(() => {
    const onResize = () => setS((v) => fit(v));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* onTap — 접힌 탭은 버튼이라 «눌렀다 뗐다»가 "펼치기"도 되고
     "옮기기"도 된다. 드래그 중 몇 픽셀이라도 움직였으면 뗄 때 펼치지
     않는다 — 안 그러면 옮기려고 누를 때마다 같이 펼쳐진다. */
  /* ⚠ **마우스 전용이었다.** mousedown/mousemove 만 듣고 있어서 터치
     화면이나 펜에서는 끌어도 꿈쩍하지 않았다 — 포인터 이벤트는 마우스 ·
     손가락 · 펜을 한 길로 받는다(09-23). */
  function startDrag(e, onTap) {
    dragRef.current = {
      startX: e.clientX, startY: e.clientY, origX: s.x, origY: s.y, moved: false, onTap,
    };
    window.addEventListener("pointermove", onDrag);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("pointercancel", stopDrag);
  }
  function onDrag(e) {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;
    if (!d.moved) return;
    setS((v) => fit({ ...v, x: d.origX + dx, y: d.origY + dy, picked: true }));
  }
  function stopDrag() {
    const d = dragRef.current;
    dragRef.current = null;
    window.removeEventListener("pointermove", onDrag);
    window.removeEventListener("pointerup", stopDrag);
    window.removeEventListener("pointercancel", stopDrag);
    if (d && !d.moved) d.onTap?.();
  }

  /* 크기조절은 네이티브 resize:both 핸들을 쓴다 — 놓을 때 실제 크기를
     읽어 상태에 반영해야 다음에 열 때도 그 크기로 뜬다. */
  function onResizeEnd() {
    const el = boxRef.current;
    if (!el) return;
    if (el.offsetWidth === s.w && el.offsetHeight === s.h) return; // 안 바뀐 클릭까지 picked 로 치지 않는다
    setS((v) => fit({ ...v, w: el.offsetWidth, h: el.offsetHeight, picked: true }));
  }

  if (s.x == null) return null; // 첫 위치 계산 전 프레임엔 안 그린다(깜빡임 방지)

  if (!s.open) {
    return (
      <button type="button" ref={boxRef} className="sticky-memo-tab"
        style={{ left: s.x, top: s.y }}
        onPointerDown={(e) => startDrag(e, () => setS((v) => ({ ...v, open: true, picked: true })))}>
        <i className="memo-swatch" aria-hidden="true" />메모
      </button>
    );
  }

  return (
    <div ref={boxRef} className="sticky-memo"
      style={{ left: s.x, top: s.y, width: s.w, height: s.h }}
      onMouseUp={onResizeEnd}>
      <div className="sticky-memo-head" onPointerDown={(e) => startDrag(e)}>
        <span>메모</span>
        <button type="button" aria-label="접기" onClick={() => setS((v) => ({ ...v, open: false, picked: true }))}>
          −
        </button>
      </div>
      <textarea
        value={s.text}
        onChange={(e) => setS((v) => ({ ...v, text: e.target.value }))}
        onBlur={saveRemote}
        placeholder="여기에 적은 메모는 다른 화면으로 이동해도 유지됩니다"
      />
    </div>
  );
}
