import { useCallback, useEffect, useRef, useState } from "react";
import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import { ensureCornerstoneInit } from "./cornerstoneInit";
import { loadManifest } from "./manifest";
import { Shape } from "../Stage";

/* 맘모 DICOM을 Cornerstone3D STACK 뷰포트로 보여준다 — 공통 영상 Viewer
 * 설계(2026-09-17) 3단계.
 *
 * MRI(DicomMprPanel)는 한 Volume을 세 방향(Axial/Coronal/Sagittal)으로
 * 잘라 보여주지만, 맘모는 애초에 볼륨이 아니다 — R-CC·R-MLO·L-CC·L-MLO
 * 네 장이 서로 다른 촬영(뷰)이다. 그래서 여기는 뷰포트 하나짜리 STACK이고,
 * "슬라이스 이동"이 아니라 "뷰 전환"이다(휠로 넘긴다 — StackScrollTool).
 *
 * ⚠ **아직 실제 맘모 DICOM 샘플이 이 저장소에 없다.** MRI 쪽
 *   (public/dicom/breast-mri-018)만 있다. manifestUrl/baseUrl이 오면
 *   그대로 그리지만, 진짜 맘모 자료가 붙기 전까지는 mock에서 임시로
 *   같은 폴더 파일 몇 장을 돌려쓰는 자리표시자다(mock/hospital.json
 *   참고 주석).
 *
 * props는 MRI 쪽과 계약을 맞췄다 — { manifestUrl, baseUrl, mode }.
 * mode="diagnostic"|"review"도 DicomMprPanel과 완전히 같은 원칙이다:
 * review는 탐색(창값·이동·확대)만 남고 측정·ROI·마스크는 등록조차 안 한다.
 *
 * ── AI 도형 겹치기 (09-28) ───────────────────────────────────
 *   overlay(sop) → { shapes } | null
 *     지금 보이는 장(SOP Instance UID)에 얹을 도형. 좌표는 **원본 픽셀**
 *     (lib/Stage.jsx 의 boxesFromLesions · polygonsFromAi 가 만든 것).
 *     cornerstone 의 이미지→화면 변환을 SVG matrix 로 옮겨 그리므로
 *     이동·확대·창 크기 변화에 같이 따라간다.
 *   pick · focusSop
 *     고른 도형 id 와 그 도형이 있는 장. focusSop 이 바뀌면 그 장으로
 *     넘기고, pick 인 도형을 밝힌다(「영상에서 보기」).
 *   onInstance(sop, index)
 *     장이 바뀔 때마다 알린다 — 판독 화면이 지금 장의 AI 결과를 고른다.
 *   manifest 항목은 "<SOP UID>?ticket=…" 꼴이다(Go getDicomSeriesInstances).
 *   물음표 앞이 SOP UID 다.
 *
 * ── 뷰 넘기기 (09-28) ─────────────────────────────────────────
 *   「뷰 1 / 4」만 있고 넘길 손잡이가 휠뿐이라, 휠을 모르는 사람은 네 장 중
 *   한 장만 보고 판독했다. 이제 셋이다 — ‹ › 단추 · 키보드(←/→ · PageUp/
 *   PageDown · Home/End, 뷰어에 초점이 있을 때) · 뷰 띠(R-CC · L-CC …).
 *   views = [{ sop, label }]
 *     이 순서로 늘어놓고 이 이름으로 부른다. 판독 응답 images[] 의
 *     laterality · view_position 에서 만든다(dept/radiology.jsx stackViews).
 *     순서는 판독 관례의 hanging order — **R-CC · L-CC · R-MLO · L-MLO**.
 *     같은 방향의 좌우를 잇달아 봐야 비대칭이 보인다(2×2 에서도 위가 CC,
 *     아래가 MLO, 왼쪽 칸이 오른쪽 유방). 모르는 장은 manifest 순서대로
 *     뒤에 붙고 「뷰 n」으로 부른다. views 가 없으면(유방외과 검사 종합 등)
 *     manifest 순서 그대로다.
 *   전체 보기(2×2) — 장이 2~4장이면 네 장을 한 번에 띄운다. 칸마다 따로
 *     뷰포트(창값만)라 AI 박스도 그 장 것만 얹힌다. 칸 이름을 누르면 그 뷰를
 *     크게 본다. 측정 · 박스 · 마스크 도구는 한 장 보기에서만 쓴다. */
const RENDERING_ENGINE_ID = "dicomStackRenderingEngine";
const VIEWPORT_ID = "DICOM_STACK_VIEWPORT";
const TOOL_GROUP_ID = "dicomStack2dToolGroup";
const SEGMENTATION_ID = "dicomStackSegmentation";
const GRID_TOOL_GROUP_ID = "dicomStackGridToolGroup";
/* 뷰 띠는 이 장 수까지만 — 초음파처럼 수십 장이면 ‹ › 와 숫자만 둔다 */
const STRIP_MAX = 12;

const sopOf = (f) => String(f).split("?")[0];

/* manifest 를 views 순서로 늘어놓는다. views 에 없는 장은 원래 순서대로 뒤에 */
function orderFiles(files, views) {
  if (!views?.length) return files;
  const rank = new Map(views.map((v, i) => [v.sop, i]));
  return files
    .map((f, i) => ({ f, i, r: rank.has(sopOf(f)) ? rank.get(sopOf(f)) : views.length + i }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.f);
}

/* 이미지 픽셀 → 화면 픽셀 affine. 이미지 (0,0)·(1,0)·(0,1) 세 점을 화면으로
   보내 보면 한 벌이 나온다 — 회전·반전이 있어도 맞는다 */
function affineOf(vp) {
  const imageId = vp?.getCurrentImageId?.();
  if (!imageId) return null;
  const at = (x, y) => vp.worldToCanvas(cornerstone.utilities.imageToWorldCoords(imageId, [x, y]));
  const o = at(0, 0); const ax = at(1, 0); const ay = at(0, 1);
  const m = [ax[0] - o[0], ax[1] - o[1], ay[0] - o[0], ay[1] - o[1], o[0], o[1]];
  return m.every(Number.isFinite) ? m : null;
}
const sameXf = (a, b) => Boolean(a && b) && a.every((v, i) => Math.abs(v - b[i]) < 1e-6);

/* AI 도형 한 겹 — 도구(창값·이동·측정)를 가리지 않게 마우스는 통과시킨다 */
function Overlay({ xf, shapes, pick }) {
  if (!xf || !shapes?.length) return null;
  const zoom = Math.hypot(xf[0], xf[1]) || 1;
  return (
    <svg className="dicom-stack-overlay" aria-hidden="true">
      <g transform={`matrix(${xf.join(" ")})`}>
        {shapes.map((s) => <Shape key={s.id} s={s} on={pick === s.id} scale={zoom} />)}
      </g>
    </svg>
  );
}

const TOOLS = [
  { key: "wl", label: "W/L", toolName: "WindowLevel" },
  { key: "pan", label: "이동", toolName: "Pan" },
  { key: "zoom", label: "확대", toolName: "Zoom" },
  { key: "length", label: "길이 측정", toolName: "Length" },
  { key: "rect", label: "박스 그리기", toolName: "RectangleROI" },
  { key: "brush", label: "마스크", toolName: "Brush" },
];

export default function DicomStackViewer({
  manifestUrl, baseUrl, mode = "diagnostic", onAnnotation,
  overlay, pick = null, focusSop = null, onInstance, views,
}) {
  const isReview = mode === "review";
  const wrapRef = useRef(null);
  const elRef = useRef(null);
  const [imageIds, setImageIds] = useState([]);
  const [grid, setGrid] = useState(false);
  /* views 는 부를 때마다 새 배열이다 — 내용이 같으면 다시 불러오지 않는다 */
  const viewsRef = useRef(views);
  useEffect(() => { viewsRef.current = views; }, [views]);
  const viewsKey = (views ?? []).map((v) => `${v.sop}:${v.label ?? ""}`).join("|");
  const sopsRef = useRef([]);           // manifest 순서의 SOP UID (이벤트 처리용)
  const [sops, setSops] = useState([]); // 같은 것 — 그리기용
  const viewportRef = useRef(null);
  const [xf, setXf] = useState(null);   // 이미지 픽셀 → 화면 픽셀 (SVG matrix)
  const onInstanceRef = useRef(onInstance);
  useEffect(() => { onInstanceRef.current = onInstance; }, [onInstance]);

  /* 지금 장의 변환을 다시 잰다. 이미지 (0,0)·(1,0)·(0,1) 세 점을 화면으로
     보내 보면 affine 한 벌이 나온다 — 회전·반전이 있어도 맞는다 */
  const measure = useCallback(() => {
    try {
      const m = affineOf(viewportRef.current);
      setXf((prev) => (m == null ? null : sameXf(prev, m) ? prev : m));
    } catch { setXf(null); }
  }, []);
  const [status, setStatus] = useState("loading"); // loading | ready | error | empty
  const [error, setError] = useState(null);
  const [activeTool, setActiveTool] = useState("wl");
  const [viewIndex, setViewIndex] = useState(0);
  const [viewCount, setViewCount] = useState(0);

  useEffect(() => {
    if (!onAnnotation || mode === "review") return;
    const done = (event) => {
      const annotation = event.detail?.annotation;
      const tool = annotation?.metadata?.toolName;
      if (tool !== "Length" && tool !== "RectangleROI") return;
      onAnnotation({ kind: tool === "Length" ? "length" : "rect", handles: annotation.data?.handles?.points ?? [] });
    };
    cornerstone.eventTarget.addEventListener(cornerstoneTools.Enums.Events.ANNOTATION_COMPLETED, done);
    return () => cornerstone.eventTarget.removeEventListener(cornerstoneTools.Enums.Events.ANNOTATION_COMPLETED, done);
  }, [mode, onAnnotation]);

  useEffect(() => {
    if (!manifestUrl || !baseUrl) {
      setStatus("empty");
      return;
    }

    let cancelled = false;
    let renderingEngine;
    let resizeObserver;

    async function run() {
      setStatus("loading");
      setError(null);
      try {
        await ensureCornerstoneInit();
        if (cancelled) return;

        /* ⚠ 여기서 그냥 res.json() 을 하면, 샘플 자료가 없는 사람에게
           「Unexpected token '<'」 가 그대로 뜬다 — Vite 가 404 에
           index.html 을 돌려주기 때문이다. loadManifest 가 그걸 가려내고
           「자료가 없습니다」로 바꿔 준다 (lib/dicom/manifest.js) */
        const files = orderFiles(await loadManifest(manifestUrl), viewsRef.current);
        sopsRef.current = files.map(sopOf);
        setSops(sopsRef.current);
        const imageIds = files.map((f) => `wadouri:${baseUrl}/${f}`);
        setImageIds(imageIds);
        if (imageIds.length === 0) { setStatus("empty"); return; }

        cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
        renderingEngine = new cornerstone.RenderingEngine(RENDERING_ENGINE_ID);
        if (cancelled) { renderingEngine.destroy(); return; }

        const { ViewportType } = cornerstone.Enums;
        renderingEngine.setViewports([
          { viewportId: VIEWPORT_ID, type: ViewportType.STACK, element: elRef.current },
        ]);

        const viewport = renderingEngine.getViewport(VIEWPORT_ID);
        viewportRef.current = viewport;
        await viewport.setStack(imageIds, 0);
        if (cancelled) return;

        /* ⚠ TOOL_GROUP_ID도 DicomMprPanel과 같은 이유로 마운트마다
         * 지우고 새로 만든다 — diagnostic에서 review로 넘어올 때
         * Length/ROI/Brush가 그대로 남아 있으면 안 된다. */
        try { cornerstoneTools.ToolGroupManager.destroyToolGroup(TOOL_GROUP_ID); }
        catch { /* 첫 마운트라 없을 수 있다 */ }
        const toolGroup = cornerstoneTools.ToolGroupManager.createToolGroup(TOOL_GROUP_ID);

        toolGroup.addTool(cornerstoneTools.StackScrollTool.toolName);
        toolGroup.setToolActive(cornerstoneTools.StackScrollTool.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Wheel }],
        });

        toolGroup.addTool(cornerstoneTools.WindowLevelTool.toolName);
        toolGroup.addTool(cornerstoneTools.PanTool.toolName);
        toolGroup.addTool(cornerstoneTools.ZoomTool.toolName);
        toolGroup.setToolActive(cornerstoneTools.WindowLevelTool.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Primary }],
        });
        toolGroup.setToolPassive(cornerstoneTools.PanTool.toolName);
        toolGroup.setToolPassive(cornerstoneTools.ZoomTool.toolName);

        if (!isReview) {
          toolGroup.addTool(cornerstoneTools.LengthTool.toolName);
          toolGroup.setToolPassive(cornerstoneTools.LengthTool.toolName);
          toolGroup.addTool(cornerstoneTools.RectangleROITool.toolName);
          toolGroup.setToolPassive(cornerstoneTools.RectangleROITool.toolName);
          toolGroup.addTool(cornerstoneTools.BrushTool.toolName);
          toolGroup.setToolPassive(cornerstoneTools.BrushTool.toolName);
        }
        toolGroup.addViewport(VIEWPORT_ID, RENDERING_ENGINE_ID);

        /* 마스크(Brush) — 스택 하나짜리 라벨맵. diagnostic만 만든다.
         * ⚠ 실 맘모 DICOM으로 아직 검증 못 했다 — 실패해도 나머지
         *   도구(창값·이동·확대·측정·ROI)는 그대로 쓸 수 있게 감싼다. */
        if (!isReview) {
          try {
            try { cornerstoneTools.segmentation.state.removeSegmentation(SEGMENTATION_ID); }
            catch { /* 처음 마운트라 없을 수 있다 */ }
            await cornerstoneTools.volumeLoader?.createAndCacheDerivedLabelmapVolume?.(
              undefined, { volumeId: SEGMENTATION_ID }
            );
          } catch (segErr) {
            console.warn("[DicomStackViewer] 마스크(Brush) 세그멘테이션 준비 실패 — " +
              "나머지 도구는 정상 동작합니다.", segErr);
          }
        }

        setViewCount(imageIds.length);
        setViewIndex(0);
        setGrid(false);
        onInstanceRef.current?.(sopsRef.current[0] ?? null, 0);
        setActiveTool("wl");
        viewport.render();
        if (!cancelled) setStatus("ready");

        const observed = elRef.current;
        if (observed) {
          resizeObserver = new ResizeObserver(() => {
            if (cancelled) return;
            renderingEngine.resize(true, false);
            renderingEngine.render();
          });
          resizeObserver.observe(observed);
        }

        /* ⚠ 이벤트 이름은 Enums 에서 꺼낸다. 전에는 "cornerstoneStackNewImage"
           를 손으로 적어 두었는데 실제 이름은 CORNERSTONE_STACK_NEW_IMAGE 라
           한 번도 안 불렸다 — 「뷰 1 / 4」가 휠을 굴려도 그대로였다. */
        const { Events } = cornerstone.Enums;
        const el = elRef.current;
        el?.addEventListener(Events.STACK_NEW_IMAGE, () => {
          const idx = viewport.getCurrentImageIdIndex();
          setViewIndex(idx);
          onInstanceRef.current?.(sopsRef.current[idx] ?? null, idx);
        });
        el?.addEventListener(Events.IMAGE_RENDERED, measure);
        el?.addEventListener(Events.CAMERA_MODIFIED, measure);
        measure();
      } catch (e) {
        console.error("[DicomStackViewer]", e);
        if (!cancelled) { setError(e.message || String(e)); setStatus("error"); }
      }
    }

    run();

    return () => {
      cancelled = true;
      viewportRef.current = null;
      resizeObserver?.disconnect();
      try {
        cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_ID)?.removeViewports(RENDERING_ENGINE_ID);
      } catch { /* 툴그룹이 아직 없을 수 있다 */ }
      cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
    };
  }, [manifestUrl, baseUrl, isReview, measure, viewsKey]);

  /* 「영상에서 보기」 — 고른 병변이 있는 장으로 넘긴다 */
  useEffect(() => {
    if (status !== "ready" || !focusSop) return;
    const idx = sops.indexOf(focusSop);
    const vp = viewportRef.current;
    if (idx < 0 || !vp || vp.getCurrentImageIdIndex?.() === idx) return;
    Promise.resolve(vp.setImageIdIndex(idx)).catch(() => {});
  }, [status, focusSop, pick, sops]);

  /* 「영상에서 보기」는 한 장 보기로 돌아와 그 장을 연다 — 고른 것이 바뀐
     그때 한 번만(그리는 중에 앞 값과 견준다) */
  const focusKey = focusSop ? `${focusSop}|${typeof pick === "object" ? JSON.stringify(pick) : pick}` : null;
  const [focusSeen, setFocusSeen] = useState(focusKey);
  if (focusKey !== focusSeen) {
    setFocusSeen(focusKey);
    if (focusKey && grid) setGrid(false);
  }

  /* ‹ › · 키보드 · 뷰 띠가 모두 여기로 온다. 끝에서 멈춘다(돌아 넘기지 않는다) —
     네 장째에서 한 번 더 눌러 첫 장이 뜨면 「다음 장」으로 읽힌다 */
  const go = useCallback((idx) => {
    const vp = viewportRef.current;
    const n = sopsRef.current.length;
    if (!vp || n === 0) return;
    const i = Math.max(0, Math.min(n - 1, idx));
    if (vp.getCurrentImageIdIndex?.() === i) return;
    Promise.resolve(vp.setImageIdIndex(i)).catch((e) => console.warn("[DicomStackViewer] 뷰 넘기기 실패", e));
  }, []);

  function onKey(e) {
    if (status !== "ready" || viewCount < 2) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const tag = e.target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const cur = viewportRef.current?.getCurrentImageIdIndex?.() ?? viewIndex;
    const to = {
      ArrowLeft: cur - 1, PageUp: cur - 1, ArrowRight: cur + 1, PageDown: cur + 1,
      Home: 0, End: viewCount - 1,
    }[e.key];
    if (to == null) return;
    e.preventDefault();
    go(to);
  }

  /* 뷰 이름 — views 가 준 것, 없으면 「뷰 n」 */
  const labelOf = new Map((views ?? []).map((v) => [v.sop, v.label]));
  const names = sops.map((u, i) => labelOf.get(u) || `뷰 ${i + 1}`);
  const named = (i) => Boolean(labelOf.get(sops[i]));
  const canGrid = viewCount >= 2 && viewCount <= 4;

  const sop = sops[viewIndex] ?? null;
  const layer = status === "ready" && overlay && sop ? overlay(sop) : null;
  const shapes = layer?.shapes ?? [];

  function selectTool(key) {
    const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_ID);
    if (!toolGroup) return;
    TOOLS.forEach((t) => {
      if (t.key === key) {
        toolGroup.setToolActive(t.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Primary }],
        });
      } else if (t.key !== "brush" || !isReview) {
        toolGroup.setToolPassive(t.toolName);
      }
    });
    setActiveTool(key);
  }

  const visibleTools = isReview ? TOOLS.filter((t) => ["wl", "pan", "zoom"].includes(t.key)) : TOOLS;

  const multi = status === "ready" && viewCount > 1;

  return (
    /* 초점을 받는 자리 — 뷰어를 한 번 누르면 ←/→ 로 넘긴다. cornerstone 가
       mousedown 을 막아 초점이 안 옮겨 오므로 눌릴 때 직접 준다 */
    <div className="dicom-stack-wrap" ref={wrapRef} tabIndex={multi ? 0 : undefined}
         onKeyDown={onKey}
         onPointerDownCapture={(e) => {
           if (multi && e.target.closest?.(".dicom-stack-cell")) wrapRef.current?.focus({ preventScroll: true });
         }}
         aria-label={multi ? `DICOM 뷰어 — ${names[viewIndex] ?? ""}. ←/→ 키로 뷰를 넘깁니다` : undefined}>
      {status === "ready" && (
        <div className="dicom-stack-toolbar">
          {visibleTools.map((t) => (
            <button
              key={t.key}
              type="button"
              className={activeTool === t.key ? "on" : ""}
              disabled={grid}
              title={grid ? "한 장 보기에서 사용할 수 있습니다" : undefined}
              onClick={() => selectTool(t.key)}
            >
              {t.label}
            </button>
          ))}
          {multi && (
            <span className="dicom-stack-nav">
              {canGrid && (
                <button type="button" className={grid ? "on" : ""} aria-pressed={grid}
                        onClick={() => setGrid((v) => !v)}
                        title={grid ? "한 장씩 크게 봅니다" : "모든 뷰를 한 번에 봅니다"}>
                  {grid ? "한 장 보기" : "전체 보기"}
                </button>
              )}
              {!grid && (
                <>
                  <button type="button" className="dicom-stack-step" aria-label="이전 뷰"
                          title="이전 뷰 (← · PageUp)" disabled={viewIndex <= 0}
                          onClick={() => go(viewIndex - 1)}>‹</button>
                  <span className="dicom-stack-count" aria-live="polite">
                    {named(viewIndex) && <b>{names[viewIndex]}</b>}
                    뷰 {viewIndex + 1} / {viewCount}
                  </span>
                  <button type="button" className="dicom-stack-step" aria-label="다음 뷰"
                          title="다음 뷰 (→ · PageDown)" disabled={viewIndex >= viewCount - 1}
                          onClick={() => go(viewIndex + 1)}>›</button>
                </>
              )}
            </span>
          )}
        </div>
      )}

      <div className="dicom-stack-cell">
        {status === "empty" && <div className="dicom-stack-message">표시할 DICOM 영상이 없습니다</div>}
        {status === "loading" && <div className="dicom-stack-message">불러오는 중…</div>}
        {status === "error" && <div className="dicom-stack-message dicom-stack-error">{error}</div>}
        <div ref={elRef} style={{ width: "100%", height: "100%", display: status === "ready" ? "block" : "none" }} />
        {/* AI 도형 — 고르는 것은 AI 소견 패널이 한다 */}
        {!grid && <Overlay xf={xf} shapes={shapes} pick={pick} />}
        {/* 전체 보기 — 한 장 뷰포트는 그대로 두고 위에 덮는다. 내렸다 올리면
            도구 · 창값 · 세그멘테이션을 다시 만들어야 해서다 */}
        {grid && status === "ready" && (
          <GridView imageIds={imageIds} sops={sops} names={names}
                    current={viewIndex} overlay={overlay} pick={pick}
                    onOpen={(i) => { setGrid(false); go(i); }} />
        )}
      </div>

      {/* 뷰 띠 — 지금 뷰가 밝다. 전체 보기에서 누르면 그 뷰를 크게 연다 */}
      {multi && viewCount <= STRIP_MAX && (
        <div className="dicom-stack-strip" role="group" aria-label="뷰 선택">
          {names.map((n, i) => (
            <button key={sops[i] ?? i} type="button" className={!grid && i === viewIndex ? "on" : ""}
                    aria-current={!grid && i === viewIndex ? "true" : undefined}
                    onClick={() => { setGrid(false); go(i); }}>
              {n}
            </button>
          ))}
          <span className="dicom-stack-keys">←/→ 키로 넘깁니다</span>
        </div>
      )}

      <style>{`
        .dicom-stack-wrap { display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0; gap: 8px; }
        .dicom-stack-toolbar { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .dicom-stack-toolbar button {
          padding: 5px 10px; border: 1px solid #343a40; border-radius: 5px;
          background: #111518; color: #aeb4ba; font-size: 11.5px; cursor: pointer;
        }
        .dicom-stack-toolbar button:hover { border-color: #596169; color: #ffffff; }
        .dicom-stack-toolbar button.on { background: #343a40; border-color: #6488ff; color: #ffffff; }
        .dicom-stack-wrap:focus { outline: none; }
        .dicom-stack-wrap:focus-visible .dicom-stack-cell { border-color: #6488ff; }
        .dicom-stack-toolbar button:disabled { opacity: .4; cursor: default; }
        .dicom-stack-toolbar button:disabled:hover { border-color: #343a40; color: #aeb4ba; }
        .dicom-stack-nav { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; }
        .dicom-stack-toolbar .dicom-stack-step { width: 30px; padding: 3px 0; font-size: 16px; line-height: 1; }
        .dicom-stack-count { font-size: 11px; color: #8e959c; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .dicom-stack-count b { color: #ffffff; font-weight: 600; margin-right: 6px; }
        .dicom-stack-strip { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .dicom-stack-strip button {
          min-width: 58px; padding: 5px 10px; border: 1px solid #343a40; border-radius: 5px;
          background: #111518; color: #aeb4ba; font-size: 11.5px; cursor: pointer; font-variant-numeric: tabular-nums;
        }
        .dicom-stack-strip button:hover { border-color: #596169; color: #ffffff; }
        .dicom-stack-strip button.on { background: #343a40; border-color: #6488ff; color: #ffffff; font-weight: 600; }
        .dicom-stack-keys { margin-left: auto; font-size: 11px; color: #596169; }
        .dicom-stack-grid {
          position: absolute; inset: 0; z-index: 1; display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: 1fr;
          gap: 2px; background: #000000;
        }
        .dicom-stack-gcell { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: #111518; }
        .dicom-stack-gcell.on::after {
          content: ""; position: absolute; inset: 0; border: 1px solid #6488ff; pointer-events: none; z-index: 2;
        }
        .dicom-stack-gview { position: absolute; inset: 0; }
        .dicom-stack-glabel {
          position: absolute; left: 6px; top: 6px; z-index: 3; padding: 2px 8px; border-radius: 4px;
          border: 1px solid #343a40; background: rgba(17,21,24,.85); color: #ffffff; font-size: 11px; cursor: pointer;
        }
        .dicom-stack-glabel:hover { border-color: #6488ff; }
        .dicom-stack-cell {
          position: relative; flex: 1; min-height: 0; overflow: hidden;
          border: 1px solid #596169; border-radius: 8px; background: #111518;
          display: flex; align-items: center; justify-content: center;
        }
        .dicom-stack-message { color: #596169; font-size: 12px; }
        .dicom-stack-overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: hidden; }
        .dicom-stack-overlay .shp { pointer-events: none; }
        /* Shape 는 선 굵기를 배율로 나눠 속성에 적는데, 여기서는 non-scaling-stroke
           라 그 값이 곧 화면 픽셀이 된다(축소 배율이면 수십 px). CSS 가 속성보다
           앞서므로 여기서 화면 2px 로 못 박는다. 글자 크기는 배율 나눗셈이 맞다 */
        .dicom-stack-overlay .shp rect, .dicom-stack-overlay .shp path { stroke-width: 2px; }
        .dicom-stack-error { max-width: 90%; text-align: center; color: #c9828c; line-height: 1.5; }
      `}</style>
    </div>
  );
}

/* ── 전체 보기(2×2) ──────────────────────────────────────────
 * 칸마다 STACK 뷰포트 하나에 장 하나. 툴그룹은 따로다 — 한 뷰포트는
 * 툴그룹 하나에만 들어간다. 도구는 창값(왼쪽 끌기)만.
 * ⚠ 렌더링 엔진은 한 장 보기의 것에 뷰포트만 더한다(enableElement). 엔진을
 *   하나 더 만들면 엔진마다 WebGL 문맥을 7개씩 잡아 브라우저 한도(16)를
 *   넘고, 가장 오래된 문맥 — 한 장 보기 것 — 이 끊겨 닫은 뒤 화면이 죽었다.
 * 영상은 한 장 보기가 이미 받아 캐시에 있어 다시 받지 않는다(처음 보는
 * 장만 받는다). 칸 이름 단추 · 두 번 누르기로 그 뷰를 크게 연다. */
function GridView({ imageIds, sops, names, current, overlay, pick, onOpen }) {
  const cells = useRef([]);
  const vps = useRef([]);
  const [xfs, setXfs] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let ro;
    const cleanups = [];
    const engine = cornerstone.getRenderingEngine(RENDERING_ENGINE_ID);
    const ids = imageIds.map((_, i) => `DICOM_GRID_${i}`);

    const measureAt = (i) => {
      try {
        const m = affineOf(vps.current[i]);
        setXfs((prev) => {
          if (m == null ? prev[i] == null : sameXf(prev[i], m)) return prev;
          const next = [...prev]; next[i] = m; return next;
        });
      } catch { /* 다음 그리기에서 */ }
    };

    (async () => {
      try {
        if (!engine) throw new Error("뷰어가 아직 준비되지 않았습니다");
        const { ViewportType, Events } = cornerstone.Enums;
        ids.forEach((viewportId, i) => engine.enableElement({
          viewportId, type: ViewportType.STACK, element: cells.current[i],
        }));
        vps.current = ids.map((viewportId) => engine.getViewport(viewportId));
        await Promise.all(vps.current.map((vp, i) => vp.setStack([imageIds[i]], 0)));
        if (cancelled) return;
        /* ⚠ 엔진에 뷰포트를 더한 직후라 카메라가 엉뚱하게 멀리(배율 1/100)
           잡혀 칸이 새까맸다. 장을 얹은 뒤 한 번 맞춘다 */
        vps.current.forEach((vp) => vp.resetCamera());

        try { cornerstoneTools.ToolGroupManager.destroyToolGroup(GRID_TOOL_GROUP_ID); }
        catch { /* 처음이라 없을 수 있다 */ }
        const tg = cornerstoneTools.ToolGroupManager.createToolGroup(GRID_TOOL_GROUP_ID);
        tg.addTool(cornerstoneTools.WindowLevelTool.toolName);
        tg.setToolActive(cornerstoneTools.WindowLevelTool.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Primary }],
        });
        ids.forEach((viewportId) => tg.addViewport(viewportId, RENDERING_ENGINE_ID));

        imageIds.forEach((_, i) => {
          const el = cells.current[i];
          const f = () => measureAt(i);
          el?.addEventListener(Events.IMAGE_RENDERED, f);
          el?.addEventListener(Events.CAMERA_MODIFIED, f);
          cleanups.push(() => {
            el?.removeEventListener(Events.IMAGE_RENDERED, f);
            el?.removeEventListener(Events.CAMERA_MODIFIED, f);
          });
        });
        engine.renderViewports(ids);
        imageIds.forEach((_, i) => measureAt(i));

        const box = cells.current[0]?.parentElement?.parentElement;
        if (box) {
          ro = new ResizeObserver(() => {
            if (cancelled) return;
            engine.resize(true, false);
            engine.render();
          });
          ro.observe(box);
        }
      } catch (e) {
        console.error("[DicomStackViewer grid]", e);
        if (!cancelled) setErr(e.message || String(e));
      }
    })();

    return () => {
      cancelled = true;
      ro?.disconnect();
      cleanups.forEach((f) => f());
      try { cornerstoneTools.ToolGroupManager.destroyToolGroup(GRID_TOOL_GROUP_ID); }
      catch { /* 이미 없다 */ }
      /* 한 장 보기 엔진이 먼저 내려갔으면(뷰어째 닫힘) 할 일이 없다 */
      const live = cornerstone.getRenderingEngine(RENDERING_ENGINE_ID);
      if (live && live === engine && !live.hasBeenDestroyed) {
        ids.forEach((viewportId) => { try { live.disableElement(viewportId); } catch { /* 이미 없다 */ } });
      }
      vps.current = [];
    };
  }, [imageIds]);

  return (
    <div className="dicom-stack-grid" role="group" aria-label="전체 보기">
      {err && <div className="dicom-stack-message dicom-stack-error">{err}</div>}
      {imageIds.map((id, i) => {
        const layer = overlay && sops[i] ? overlay(sops[i]) : null;
        return (
          <div key={id} className={`dicom-stack-gcell${i === current ? " on" : ""}`}
               onDoubleClick={() => onOpen(i)}>
            <div className="dicom-stack-gview" ref={(el) => { cells.current[i] = el; }} />
            <Overlay xf={xfs[i]} shapes={layer?.shapes ?? []} pick={pick} />
            <button type="button" className="dicom-stack-glabel" title="이 뷰를 크게 봅니다"
                    onClick={() => onOpen(i)}>{names[i]}</button>
          </div>
        );
      })}
    </div>
  );
}
