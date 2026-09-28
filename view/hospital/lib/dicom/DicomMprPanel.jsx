import { useEffect, useRef, useState } from "react";
import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import { ensureCornerstoneInit } from "./cornerstoneInit";
import { loadManifest } from "./manifest";

/* DICOM Series를 Cornerstone3D Volume으로 읽어 Axial/Coronal/Sagittal
 * 세 방향(ORTHOGRAPHIC)으로 보여준다. CrosshairsTool이 세 뷰포트를 같은
 * 3D 좌표에 묶어줘서, 한 곳에서 슬라이스를 옮기면 나머지 두 곳도 같이
 * 움직인다.
 *
 * 유방외과 MRI 리뷰(MRIReviewGrid)와 영상의학과 MRI 판독 화면 둘 다
 * 쓴다 — 과 하나에 묶인 컴포넌트가 아니라서 hospital/lib/ 로 옮겨 왔다
 * (원래 dept/breast/components/에 있었다).
 *
 * ⚠ manifest.json은 InstanceNumber로 미리 정렬돼 있어야 한다(wadouri는
 *   cornerstone이 순서를 다시 안 잡아준다 — scripts/sort-dicom-manifest.cjs).
 *
 * ── mode: "diagnostic" | "review" ────────────────────────────────
 * 공통 영상 Viewer 설계(2026-09-17)의 핵심 — 엔진은 하나, 기능은 역할로
 * 가른다. 영상의학과(diagnostic)는 탐색(Crosshairs) + 측정(Length) +
 * ROI + 마스크(Brush)를 다 쓴다. 유방외과(review, 기본 아님 — 명시로
 * 켠다)는 **탐색만** 살아 있고, 측정·ROI·마스크 도구는 아예 등록하지
 * 않는다 — disabled가 아니라 unmount다("존재하면 안 되는 개념"이라
 * 눌러도 안 되는 게 아니라 버튼 자체가 없어야 한다).
 *
 * ⚠ "저장된 측정값·마스크를 읽기 전용으로 보여준다"는 목표(설계 문서
 *   To-Be)는 아직 여기 없다 — 지금은 애초에 서버에서 측정/마스크 결과를
 *   불러오는 경로 자체가 없다(항상 빈 라벨맵으로 시작). review 모드는
 *   당장은 "편집 도구를 안 준다"까지만 하고, 결과 조회는 이후 별도
 *   작업(마스크 데이터 fetch)이 생기면 채운다. */
const RENDERING_ENGINE_ID = "dicomMprRenderingEngine";
const VOLUME_ID = "cornerstoneStreamingImageVolume:dicomMpr";
const IDS = {
  axial: "DICOM_MPR_AXIAL",
  coronal: "DICOM_MPR_CORONAL",
  sagittal: "DICOM_MPR_SAGITTAL",
};
const AXIS_COLOR = {
  axial: "rgb(255, 86, 86)",
  coronal: "rgb(90, 150, 255)",
  sagittal: "rgb(70, 210, 120)",
};
const TOOL_GROUP_ID = "dicomMpr2dToolGroup";
const SEGMENTATION_ID = "dicomMprSegmentation";

/* 판독 도구 모음 — key는 내부 상태값, toolName은 cornerstoneTools가 아는
 * 이름, cursor는 활성화됐을 때 캔버스 커서(사용자가 «지금 그리는 중»을
 * 알 수 있게). 탐색(Crosshairs)이 기본이고, 나머지는 골라야 켜진다 —
 * 셋 다 기본으로 켜 두면 실수로 측정선이 그려진다. */
const TOOLS = [
  { key: "crosshairs", label: "탐색", toolName: "Crosshairs" },
  { key: "length", label: "길이 측정", toolName: "Length" },
  { key: "rect", label: "박스 그리기", toolName: "RectangleROI" },
  { key: "brush", label: "마스크", toolName: "Brush" },
];

export default function DicomMprPanel({ manifestUrl, baseUrl, mode = "diagnostic", onAnnotation, focusSlice = null }) {
  const isReview = mode === "review";
  const axialRef = useRef(null);
  const coronalRef = useRef(null);
  const sagittalRef = useRef(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error | empty

  /* AI 소견의 「근거 단면」 버튼 → 축상면을 그 장으로 옮긴다(09-28).
     모델의 slice_index 는 볼륨 축상 순번이다. 볼륨이 다 올라온 뒤에만 옮긴다 */
  useEffect(() => {
    if (status !== "ready" || focusSlice == null || !axialRef.current) return;
    cornerstone.utilities.jumpToSlice(axialRef.current, { imageIndex: focusSlice })
      .catch((e) => console.warn("jumpToSlice", e));
  }, [status, focusSlice]);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [activeTool, setActiveTool] = useState("crosshairs");

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
      setProgress(0);
      setError(null);
      try {
        await ensureCornerstoneInit();
        if (cancelled) return;

        /* ⚠ res.json() 을 바로 하면 안 된다 — DicomStackViewer 와 같은 사정.
           자료가 없으면 Vite 가 index.html 을 돌려줘서 「Unexpected token
           '<'」 가 화면에 뜬다 (lib/dicom/manifest.js) */
        const files = await loadManifest(manifestUrl);
        const imageIds = files.map((f) => `wadouri:${baseUrl}/${f}`);

        cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
        renderingEngine = new cornerstone.RenderingEngine(RENDERING_ENGINE_ID);
        if (cancelled) { renderingEngine.destroy(); return; }

        const { ViewportType, OrientationAxis } = cornerstone.Enums;
        renderingEngine.setViewports([
          { viewportId: IDS.axial, type: ViewportType.ORTHOGRAPHIC, element: axialRef.current,
            defaultOptions: { orientation: OrientationAxis.AXIAL, background: [0, 0, 0] } },
          { viewportId: IDS.coronal, type: ViewportType.ORTHOGRAPHIC, element: coronalRef.current,
            defaultOptions: { orientation: OrientationAxis.CORONAL, background: [0, 0, 0] } },
          { viewportId: IDS.sagittal, type: ViewportType.ORTHOGRAPHIC, element: sagittalRef.current,
            defaultOptions: { orientation: OrientationAxis.SAGITTAL, background: [0, 0, 0] } },
        ]);

        const volume = await cornerstone.volumeLoader.createAndCacheVolume(VOLUME_ID, { imageIds });
        if (cancelled) return;

        volume.load((evt) => {
          if (cancelled || !evt?.numberOfFrames) return;
          setProgress(Math.round((evt.framesProcessed / evt.numberOfFrames) * 100));
        });

        await cornerstone.setVolumesForViewports(
          renderingEngine,
          [{ volumeId: VOLUME_ID }],
          [IDS.axial, IDS.coronal, IDS.sagittal]
        );
        if (cancelled) return;

        /* ⚠ TOOL_GROUP_ID는 모드에 상관없이 같은 전역 상수다 — 판독
         * 화면(diagnostic)을 한 번 열고 나면 조회 화면(review)이 나중에
         * 마운트돼도 getToolGroup()이 그 툴그룹을 그대로 돌려준다. 예전
         * 코드처럼 "없으면만 만든다"로 두면 review 모드가 diagnostic이
         * 남긴 Length/ROI/Brush 도구(와 마지막 활성 도구)를 그대로
         * 물려받는다 — 조회 모드에 판독 도구가 새는 것이다. 그래서 마운트
         * 때마다 툴그룹을 지우고 **지금 mode에 맞게 새로 만든다**
         * (renderingEngine을 매번 destroy 후 재생성하는 것과 같은 이유). */
        try { cornerstoneTools.ToolGroupManager.destroyToolGroup(TOOL_GROUP_ID); }
        catch { /* 첫 마운트라 없을 수 있다 */ }
        const toolGroup = cornerstoneTools.ToolGroupManager.createToolGroup(TOOL_GROUP_ID);
        toolGroup.addTool(cornerstoneTools.StackScrollTool.toolName);
        toolGroup.setToolActive(cornerstoneTools.StackScrollTool.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Wheel }],
        });
        toolGroup.addTool(cornerstoneTools.CrosshairsTool.toolName, {
          getReferenceLineColor: (viewportId) =>
            AXIS_COLOR[
              viewportId === IDS.axial ? "axial" : viewportId === IDS.coronal ? "coronal" : "sagittal"
            ] ?? "rgb(200, 200, 0)",
        });
        toolGroup.setToolActive(cornerstoneTools.CrosshairsTool.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Primary }],
        });

        /* review 모드는 여기서 끝 — 측정·ROI·마스크 도구 자체를 이
         * 툴그룹에 등록하지 않는다(disabled 아님, 존재 안 함). */
        if (!isReview) {
          /* 측정·주석 도구 — 눌러서 고르기 전까지는 "켜져만 있는"
           * 상태(passive)다. Primary 버튼을 안 물고 있으니 탐색(십자선)을
           * 방해하지 않는다. 실제 Primary 바인딩은 selectTool()이
           * 버튼 클릭에 맞춰 그때그때 옮긴다. */
          toolGroup.addTool(cornerstoneTools.LengthTool.toolName);
          toolGroup.setToolPassive(cornerstoneTools.LengthTool.toolName);
          toolGroup.addTool(cornerstoneTools.RectangleROITool.toolName);
          toolGroup.setToolPassive(cornerstoneTools.RectangleROITool.toolName);
          toolGroup.addTool(cornerstoneTools.BrushTool.toolName);
          toolGroup.setToolPassive(cornerstoneTools.BrushTool.toolName);
        }
        [IDS.axial, IDS.coronal, IDS.sagittal].forEach((id) =>
          toolGroup.addViewport(id, RENDERING_ENGINE_ID));

        /* 마스크 도구(Brush)가 칠할 자리 — review 모드는 Brush 자체가
         * 없으니 세그멘테이션도 만들 필요가 없다. diagnostic만 만든다.
         * 원본 Volume과 같은 크기의 빈 라벨맵을 하나 만들어 세그멘테이션
         * 으로 등록한다. 이전 마운트에서 만든 게 남아 있으면(같은
         * SEGMENTATION_ID) 지우고 새로 만든다 — 환자가 바뀌면 마스크도
         * 새로 시작해야 맞다. */
        if (!isReview) {
          try { cornerstoneTools.segmentation.state.removeSegmentation(SEGMENTATION_ID); }
          catch { /* 처음 마운트라 없을 수 있다 */ }

          await cornerstone.volumeLoader.createAndCacheDerivedLabelmapVolume(
            VOLUME_ID, { volumeId: SEGMENTATION_ID }
          );
          if (cancelled) return;

          cornerstoneTools.segmentation.addSegmentations([{
            segmentationId: SEGMENTATION_ID,
            representation: {
              type: cornerstoneTools.Enums.SegmentationRepresentations.Labelmap,
              data: { volumeId: SEGMENTATION_ID },
            },
          }]);

          /* ⚠ 뷰포트마다 addSegmentationRepresentations를 따로 부르면(3번)
           * 그때마다 색 LUT를 새로 하나씩 할당한다 — 맨 처음(0번)만 실제
           * 색이 채워져 있고 나머지(1·2번)는 빈 LUT라 그 뷰포트에 칠한
           * 건 데이터는 남는데 화면엔 완전 투명으로 보인다(직접 겪은 버그).
           * 뷰포트 맵으로 한 번에 등록해야 셋이 같은 LUT를 쓴다. */
          cornerstoneTools.segmentation.addLabelmapRepresentationToViewportMap({
            [IDS.axial]: [{ segmentationId: SEGMENTATION_ID }],
            [IDS.coronal]: [{ segmentationId: SEGMENTATION_ID }],
            [IDS.sagittal]: [{ segmentationId: SEGMENTATION_ID }],
          });
          cornerstoneTools.segmentation.segmentIndex.setActiveSegmentIndex(SEGMENTATION_ID, 1);
        }

        setActiveTool("crosshairs");
        renderingEngine.render();
        if (!cancelled) setStatus("ready");

        /* Suspense(지연 로딩)로 마운트되는 화면 안에 있으면, setViewports
         * 시점에 컨테이너가 아직 레이아웃을 못 받아 0 크기였을 수 있다 —
         * 그러면 캔버스가 기본값(300×150)으로 굳어 새까맣게 보인다. 또한
         * 옆 패널이 접히고 펼쳐질 때도 뷰포트 크기가 바뀐다.
         * ResizeObserver로 실제 크기 변화를 감지해 매번 다시 맞춘다. */
        const observed = [axialRef.current, coronalRef.current, sagittalRef.current]
          .filter(Boolean);
        resizeObserver = new ResizeObserver(() => {
          if (cancelled) return;
          renderingEngine.resize(true, false);
          renderingEngine.render();
        });
        observed.forEach((el) => resizeObserver.observe(el));
      } catch (e) {
        console.error("[DicomMprPanel]", e);
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

  /* 버튼 하나 고르면 그 도구만 Primary(좌클릭)를 받고, 나머지는 passive로
   * 물러난다 — 동시에 두 도구가 좌클릭을 다투면 클릭마다 뭐가 그려질지
   * 예측할 수 없다. 휠(StackScroll)은 항상 따로 살아 있어서 도구를
   * 고르는 중에도 슬라이스는 넘길 수 있다. */
  function selectTool(key) {
    const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_ID);
    if (!toolGroup) return;
    TOOLS.forEach((t) => {
      if (t.key === key) {
        toolGroup.setToolActive(t.toolName, {
          bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Primary }],
        });
      } else {
        toolGroup.setToolPassive(t.toolName);
      }
    });
    setActiveTool(key);
  }

  /* review 모드는 등록된 도구가 탐색(Crosshairs)뿐이라 고를 게 없다 —
   * 버튼 하나짜리 Toolbar를 보여주는 대신 아예 숨긴다. */
  return (
    <div className="dicom-mpr-wrap">
      {status === "ready" && !isReview && (
        <div className="dicom-mpr-toolbar">
          {TOOLS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={activeTool === t.key ? "on" : ""}
              onClick={() => selectTool(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="dicom-mpr-rows">
        <Panel title="Axial" axis="axial" elRef={axialRef} status={status} progress={progress} error={error} />
        <Panel title="Coronal" axis="coronal" elRef={coronalRef} status={status} progress={progress} error={error} />
        <Panel title="Sagittal" axis="sagittal" elRef={sagittalRef} status={status} progress={progress} error={error} />
      </div>

      <style>{`
        .dicom-mpr-wrap {
          display: flex;
          flex-direction: column;
          width: 100%;
          height: 100%;
          min-width: 0;
          min-height: 0;
          gap: 8px;
        }

        .dicom-mpr-toolbar {
          flex: 0 0 auto;
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
        }

        .dicom-mpr-toolbar button {
          padding: 5px 10px;
          border: 1px solid #343a40;
          border-radius: 5px;
          background: #111518;
          color: #aeb4ba;
          font-size: 11.5px;
          cursor: pointer;
        }

        .dicom-mpr-toolbar button:hover {
          border-color: #596169;
          color: #ffffff;
        }

        .dicom-mpr-toolbar button.on {
          background: #343a40;
          border-color: #6488ff;
          color: #ffffff;
        }

        .dicom-mpr-rows {
          flex: 1;
          min-height: 0;
          display: grid;
          grid-template-rows: repeat(3, minmax(0, 1fr));
          gap: 8px;
        }

        .dicom-mpr-cell {
          position: relative;
          min-width: 0;
          min-height: 0;
          overflow: hidden;
          border: 1px solid #596169;
          border-radius: 8px;
          background: #111518;
        }

        .dicom-mpr-title {
          position: absolute;
          z-index: 40;
          top: 9px;
          left: 10px;
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 3px 6px;
          border-radius: 4px;
          background: rgba(17, 21, 24, 0.84);
          color: #ffffff;
          font-size: 12px;
          font-weight: 600;
          pointer-events: none;
        }

        .dicom-mpr-axis-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          flex: 0 0 7px;
        }

        .dicom-mpr-canvas-wrap {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
        }

        .dicom-mpr-message {
          color: #596169;
          font-size: 12px;
        }

        .dicom-mpr-error {
          max-width: 90%;
          text-align: center;
          color: #c9828c;
          line-height: 1.5;
        }
      `}</style>
    </div>
  );
}

function Panel({ title, axis, elRef, status, progress, error }) {
  return (
    <div className="dicom-mpr-cell">
      <div className="dicom-mpr-title">
        {title}
        <span className="dicom-mpr-axis-dot" style={{ background: AXIS_COLOR[axis] }} />
      </div>

      <div className="dicom-mpr-canvas-wrap">
        {status === "empty" && (
          <div className="dicom-mpr-message">DICOM Series가 없습니다</div>
        )}
        {status === "loading" && (
          <div className="dicom-mpr-message">
            불러오는 중{progress > 0 ? ` ${progress}%` : "…"}
          </div>
        )}
        {status === "error" && (
          <div className="dicom-mpr-message dicom-mpr-error">{error}</div>
        )}
        <div
          ref={elRef}
          style={{
            width: "100%",
            height: "100%",
            display: status === "ready" ? "block" : "none",
          }}
        />
      </div>
    </div>
  );
}
