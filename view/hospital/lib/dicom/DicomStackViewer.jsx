import { useEffect, useRef, useState } from "react";
import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import { ensureCornerstoneInit } from "./cornerstoneInit";
import { loadManifest } from "./manifest";

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
 * review는 탐색(창값·이동·확대)만 남고 측정·ROI·마스크는 등록조차 안 한다. */
const RENDERING_ENGINE_ID = "dicomStackRenderingEngine";
const VIEWPORT_ID = "DICOM_STACK_VIEWPORT";
const TOOL_GROUP_ID = "dicomStack2dToolGroup";
const SEGMENTATION_ID = "dicomStackSegmentation";

const TOOLS = [
  { key: "wl", label: "창값", toolName: "WindowLevel" },
  { key: "pan", label: "이동", toolName: "Pan" },
  { key: "zoom", label: "확대", toolName: "Zoom" },
  { key: "length", label: "길이 측정", toolName: "Length" },
  { key: "rect", label: "박스 그리기", toolName: "RectangleROI" },
  { key: "brush", label: "마스크", toolName: "Brush" },
];

export default function DicomStackViewer({ manifestUrl, baseUrl, mode = "diagnostic", onAnnotation }) {
  const isReview = mode === "review";
  const elRef = useRef(null);
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
        const files = await loadManifest(manifestUrl);
        const imageIds = files.map((f) => `wadouri:${baseUrl}/${f}`);
        if (imageIds.length === 0) { setStatus("empty"); return; }

        cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
        renderingEngine = new cornerstone.RenderingEngine(RENDERING_ENGINE_ID);
        if (cancelled) { renderingEngine.destroy(); return; }

        const { ViewportType } = cornerstone.Enums;
        renderingEngine.setViewports([
          { viewportId: VIEWPORT_ID, type: ViewportType.STACK, element: elRef.current },
        ]);

        const viewport = renderingEngine.getViewport(VIEWPORT_ID);
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

        elRef.current?.addEventListener("cornerstoneStackNewImage", () => {
          setViewIndex(viewport.getCurrentImageIdIndex());
        });
      } catch (e) {
        console.error("[DicomStackViewer]", e);
        if (!cancelled) { setError(e.message || String(e)); setStatus("error"); }
      }
    }

    run();

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      try {
        cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_ID)?.removeViewports(RENDERING_ENGINE_ID);
      } catch { /* 툴그룹이 아직 없을 수 있다 */ }
      cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
    };
  }, [manifestUrl, baseUrl, isReview]);

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

  return (
    <div className="dicom-stack-wrap">
      {status === "ready" && (
        <div className="dicom-stack-toolbar">
          {visibleTools.map((t) => (
            <button
              key={t.key}
              type="button"
              className={activeTool === t.key ? "on" : ""}
              onClick={() => selectTool(t.key)}
            >
              {t.label}
            </button>
          ))}
          {viewCount > 1 && (
            <span className="dicom-stack-count">뷰 {viewIndex + 1} / {viewCount}</span>
          )}
        </div>
      )}

      <div className="dicom-stack-cell">
        {status === "empty" && <div className="dicom-stack-message">DICOM Stack이 없습니다</div>}
        {status === "loading" && <div className="dicom-stack-message">불러오는 중…</div>}
        {status === "error" && <div className="dicom-stack-message dicom-stack-error">{error}</div>}
        <div ref={elRef} style={{ width: "100%", height: "100%", display: status === "ready" ? "block" : "none" }} />
      </div>

      <style>{`
        .dicom-stack-wrap { display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0; gap: 8px; }
        .dicom-stack-toolbar { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .dicom-stack-toolbar button {
          padding: 5px 10px; border: 1px solid #343a40; border-radius: 5px;
          background: #111518; color: #aeb4ba; font-size: 11.5px; cursor: pointer;
        }
        .dicom-stack-toolbar button:hover { border-color: #596169; color: #ffffff; }
        .dicom-stack-toolbar button.on { background: #343a40; border-color: #6488ff; color: #ffffff; }
        .dicom-stack-count { margin-left: auto; font-size: 11px; color: #8e959c; font-variant-numeric: tabular-nums; }
        .dicom-stack-cell {
          position: relative; flex: 1; min-height: 0; overflow: hidden;
          border: 1px solid #596169; border-radius: 8px; background: #111518;
          display: flex; align-items: center; justify-content: center;
        }
        .dicom-stack-message { color: #596169; font-size: 12px; }
        .dicom-stack-error { max-width: 90%; text-align: center; color: #c9828c; line-height: 1.5; }
      `}</style>
    </div>
  );
}
