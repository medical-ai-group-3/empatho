import { useCallback, useEffect, useRef, useState } from "react";
import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";

/* 뷰어에 그린 표시를 지운다 — 맘모(DicomStackViewer) · MRI(DicomMprPanel) 공용
 * ════════════════════════════════════════════════════════════════
 *
 * 전에는 한 번 그리면 지울 길이 없었다(「뷰어에서 한번 그리면 삭제가 안
 * 된다」). 이제 셋이다 — 「선택 지우기」 · 「모두 지우기」 · Delete/Backspace.
 *
 * 지우는 것은 **의사가 그린 것만**이다.
 *   Length · RectangleROI   cornerstone 주석. 도구 이름으로 가려낸다
 *   Brush(마스크)           세그멘테이션 라벨맵. 「모두 지우기」만 비운다
 * ⚠ 십자선(Crosshairs)도 cornerstone 주석이다 — 도구 이름으로 거르지 않으면
 *   「모두 지우기」가 십자선을 지워 MPR 탐색이 죽는다. AI 도형은 우리가
 *   SVG 로 따로 그리는 것이라 여기 닿지 않는다.
 *
 * ⚠ 주석은 cornerstone 전역 저장소에 산다(뷰어를 내려도 남는다). 그래서
 *   「이 뷰어 것」을 mine(annotation) 으로 가려 받는다 — 맘모는 지금 스택의
 *   imageId, MRI 는 볼륨의 FrameOfReferenceUID.
 *
 * ── 판독 화면에 알리는 것(onAnnotation) ──────────────────────
 *   그리기를 마치면 그 표시를 올린다(전과 같다 — 「병변 등록」의 재료).
 *   마지막으로 올린 표시가 지워지면 null 을 올린다 → 「병변 등록」이 꺼진다.
 *   ⚠ 남은 앞 표시를 대신 올리지 않는다. 앞 표시는 이미 병변으로 등록했을
 *     수 있는데 여기서는 그걸 모른다 — 다시 올리면 같은 병변이 두 번
 *     등록된다. 앞 표시를 쓰려면 다시 그린다.
 */

export const DRAW_TOOLS = new Set(["Length", "RectangleROI"]);

const { state, selection } = cornerstoneTools.annotation;
const toolOf = (a) => a?.metadata?.toolName;

export const toMark = (a) => ({
  kind: toolOf(a) === "Length" ? "length" : "rect",
  handles: a.data?.handles?.points ?? [],
});

function drawn(mine) {
  return (state.getAllAnnotations() ?? []).filter((a) => DRAW_TOOLS.has(toolOf(a)) && mine(a));
}
function picked(mine) {
  return selection.getAnnotationsSelected()
    .map((uid) => state.getAnnotation(uid))
    .filter((a) => a && DRAW_TOOLS.has(toolOf(a)) && mine(a));
}

/* ⚠ 고른 것 풀기 → 지우기 순서다. removeAnnotation 은 고른 목록에서 빼
   주지 않아, 지운 UID 가 「골라져 있음」으로 남는다. 뒤에 풀려고 하면
   deselectAnnotation 이 없는 주석을 만져 터진다 */
function drop(list) {
  list.forEach((a) => {
    if (selection.isAnnotationSelected(a.annotationUID)) selection.deselectAnnotation(a.annotationUID);
    state.removeAnnotation(a.annotationUID);
  });
}

function rerender(ids) {
  try { cornerstoneTools.utilities.triggerAnnotationRenderForViewportIds(ids ?? []); }
  catch { /* 뷰포트가 이미 내려갔다 */ }
}

/* 라벨맵을 0 으로 비운다. ⚠ clearSegmentValue 는 쓰지 않는다 — 비우면서
   구획 연결(segment binding)까지 떼어, 라벨맵 층이 통째로 빠질 수 있다.
   그러면 다음 붓질이 칠할 자리가 없다. 값만 0 으로 덮는다 */
function clearLabelmap(segmentationId) {
  const seg = cornerstoneTools.segmentation.state.getSegmentation(segmentationId);
  if (!seg) return false;
  const volumeId = seg.representationData?.Labelmap?.volumeId ?? segmentationId;
  const vm = cornerstone.cache.getVolume(volumeId)?.voxelManager;
  if (!vm?.setCompleteScalarDataArray) return false;
  vm.setCompleteScalarDataArray(new Uint8Array(vm.getScalarDataLength()));
  cornerstoneTools.segmentation.triggerSegmentationEvents.triggerSegmentationDataModified(segmentationId);
  return true;
}

/* enabled  — review 모드면 false. 알림도 지우개도 없다
 * ready    — 뷰어가 다 뜬 뒤 true. 그때 남은 표시를 다시 센다
 * mine     — (annotation) => boolean. 이 뷰어 것인가
 * viewportIds — 지운 뒤 다시 그릴 뷰포트
 * segmentationId — 마스크 라벨맵(없으면 마스크는 안 센다) */
export function useMarkEraser({ enabled, ready, mine, viewportIds, segmentationId, onAnnotation }) {
  const [selected, setSelected] = useState(0);
  const [total, setTotal] = useState(0);
  const [painted, setPainted] = useState(false);
  const mineRef = useRef(mine);
  const idsRef = useRef(viewportIds);
  const onRef = useRef(onAnnotation);
  const reportedRef = useRef(null);   // 마지막으로 올린 표시의 UID
  const clearingRef = useRef(false);  // 우리가 비우는 중 — 붓질로 세지 않는다
  useEffect(() => {
    mineRef.current = mine;
    idsRef.current = viewportIds;
    onRef.current = onAnnotation;
  });

  const sync = useCallback(() => {
    setSelected(picked(mineRef.current).length);
    setTotal(drawn(mineRef.current).length);
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    const E = cornerstoneTools.Enums.Events;
    const done = (event) => {
      const a = event.detail?.annotation;
      if (a && DRAW_TOOLS.has(toolOf(a)) && mineRef.current(a)) {
        reportedRef.current = a.annotationUID;
        onRef.current?.(toMark(a));
      }
      sync();
    };
    /* 우리가 지웠든 cornerstone 이 지웠든 여기로 온다 */
    const removed = (event) => {
      const uid = event.detail?.annotation?.annotationUID;
      if (uid && uid === reportedRef.current) {
        reportedRef.current = null;
        onRef.current?.(null);
      }
      sync();
    };
    const brushed = (event) => {
      if (segmentationId && event.detail?.segmentationId === segmentationId && !clearingRef.current) {
        setPainted(true);
      }
    };
    const t = cornerstone.eventTarget;
    t.addEventListener(E.ANNOTATION_COMPLETED, done);
    t.addEventListener(E.ANNOTATION_REMOVED, removed);
    t.addEventListener(E.ANNOTATION_SELECTION_CHANGE, sync);
    t.addEventListener(E.SEGMENTATION_DATA_MODIFIED, brushed);
    return () => {
      t.removeEventListener(E.ANNOTATION_COMPLETED, done);
      t.removeEventListener(E.ANNOTATION_REMOVED, removed);
      t.removeEventListener(E.ANNOTATION_SELECTION_CHANGE, sync);
      t.removeEventListener(E.SEGMENTATION_DATA_MODIFIED, brushed);
    };
  }, [enabled, segmentationId, sync]);

  /* 새로 뜰 때마다 라벨맵은 빈 것으로 다시 만든다 — 붓질 표시도 내린다 */
  useEffect(() => {
    if (!ready) return;
    setPainted(false);
    sync();
  }, [ready, sync]);

  const removeSelected = useCallback(() => {
    const list = picked(mineRef.current);
    if (list.length === 0) return false;
    drop(list);
    rerender(idsRef.current);
    sync();
    return true;
  }, [sync]);

  const removeAll = useCallback(() => {
    const list = drawn(mineRef.current);
    const n = list.length + (painted ? 1 : 0);
    if (n === 0) return;
    if (n > 1) {
      const what = painted
        ? (list.length ? `그린 표시 ${list.length}개와 마스크` : "마스크")
        : `그린 표시 ${list.length}개`;
      if (!window.confirm(`${what}를 모두 지웁니다. 지운 것은 되돌릴 수 없습니다.`)) return;
    }
    drop(list);
    if (painted) {
      clearingRef.current = true;
      try {
        if (!clearLabelmap(segmentationId)) console.warn("[useMarkEraser] 마스크를 비우지 못했습니다", segmentationId);
      } catch (e) {
        console.warn("[useMarkEraser] 마스크 비우기 실패", e);
      } finally {
        clearingRef.current = false;
      }
      setPainted(false);
    }
    rerender(idsRef.current);
    sync();
  }, [painted, segmentationId, sync]);

  /* Delete · Backspace — 뷰어에 초점이 있을 때. 입력칸에서 글자를 지우는
     키를 가로채면 안 된다. 처리했으면 true */
  const onEraseKey = useCallback((e) => {
    if (e.key !== "Delete" && e.key !== "Backspace") return false;
    if (e.altKey || e.ctrlKey || e.metaKey) return false;
    const tag = e.target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) return false;
    if (!removeSelected()) return false;
    e.preventDefault();
    return true;
  }, [removeSelected]);

  return { selected, total: total + (painted ? 1 : 0), removeSelected, removeAll, onEraseKey };
}
