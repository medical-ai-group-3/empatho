import { useEffect, useRef, useState } from "react";
import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import { ensureCornerstoneInit } from "../depts/breast/components/cornerstoneInit";

/* MRIReviewGrid의 오른쪽 2D 세 칸(Axial/Coronal/Sagittal) — 예전엔
 * NiftiSliceViewer(nifti-reader-js + <canvas>)로 만든 임시 뷰어였다.
 * 실제 MRI는 (맘모처럼) DICOM Series로 들어오기로 했으니, 입력 자체를
 * DICOM 기준으로 갈아탄다: cornerstone3D가 여러 DICOM Instance를 하나의
 * Volume으로 구성하고, 그 Volume을 세 방향(ORTHOGRAPHIC)으로 잘라
 * 보여준다. CrosshairsTool이 세 뷰포트를 같은 3D 좌표에 묶어주므로,
 * 우리가 NIfTI 버전에서 직접 구현했던 공유 cursor 로직이 더 이상
 * 필요 없다 — cornerstone이 대신 해준다.
 *
 * NiftiSliceViewer.jsx / duke_001_0000.nii는 지우지 않았다 — 지금까지
 * 뷰어 테스트에 쓰던 샘플로 남겨두고, MRI 메인 경로에서만 뺀다.
 *
 * ⚠ manifest.json은 InstanceNumber로 미리 정렬돼 있어야 한다(wadouri는
 *   cornerstone이 순서를 다시 안 잡아준다 — scripts/sort-dicom-manifest.cjs). */
const RENDERING_ENGINE_ID = "breastMprRenderingEngine";
const VOLUME_ID = "cornerstoneStreamingImageVolume:breastMpr";
const IDS = {
  axial: "BREAST_MPR_AXIAL",
  coronal: "BREAST_MPR_CORONAL",
  sagittal: "BREAST_MPR_SAGITTAL",
};
// NiftiSliceViewer 때 쓰던 축 색 배정과 통일 — "이 색 = 이 단면" 규칙이
// 컴포넌트를 갈아 끼워도 안 흔들리게.
const AXIS_COLOR = {
  axial: "rgb(255, 86, 86)",
  coronal: "rgb(90, 150, 255)",
  sagittal: "rgb(70, 210, 120)",
};
const TOOL_GROUP_ID = "breastMpr2dToolGroup";

export default function DicomMprPanel({ manifestUrl, baseUrl }) {
  const axialRef = useRef(null);
  const coronalRef = useRef(null);
  const sagittalRef = useRef(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error | empty
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!manifestUrl || !baseUrl) {
      setStatus("empty");
      return;
    }

    let cancelled = false;
    let renderingEngine;

    async function run() {
      setStatus("loading");
      setProgress(0);
      setError(null);
      try {
        await ensureCornerstoneInit();
        if (cancelled) return;

        const res = await fetch(manifestUrl);
        if (!res.ok) throw new Error(`manifest 요청 실패 (${res.status})`);
        const files = await res.json();
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

        let toolGroup = cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_ID);
        if (!toolGroup) {
          toolGroup = cornerstoneTools.ToolGroupManager.createToolGroup(TOOL_GROUP_ID);
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
        }
        [IDS.axial, IDS.coronal, IDS.sagittal].forEach((id) =>
          toolGroup.addViewport(id, RENDERING_ENGINE_ID));

        renderingEngine.render();
        if (!cancelled) setStatus("ready");
      } catch (e) {
        console.error("[DicomMprPanel]", e);
        if (!cancelled) { setError(e.message || String(e)); setStatus("error"); }
      }
    }

    run();

    return () => {
      cancelled = true;
      try {
        cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_ID)?.removeViewports(RENDERING_ENGINE_ID);
      } catch { /* 툴그룹이 아직 없을 수 있다 */ }
      cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
    };
  }, [manifestUrl, baseUrl]);

  return (
    <>
      <Panel title="Axial" axis="axial" elRef={axialRef} status={status} progress={progress} error={error} />
      <Panel title="Coronal" axis="coronal" elRef={coronalRef} status={status} progress={progress} error={error} />
      <Panel title="Sagittal" axis="sagittal" elRef={sagittalRef} status={status} progress={progress} error={error} />
    </>
  );
}

function Panel({ title, axis, elRef, status, progress, error }) {
  return (
    <div className="nifti-viewer">
      <div className="nifti-title">
        {title}
        <span className="nifti-axis-dot" style={{ background: AXIS_COLOR[axis] }} />
      </div>

      <div className="nifti-canvas-wrap" style={{ bottom: 0 }}>
        {status === "empty" && (
          <div className="nifti-message">DICOM Series가 없습니다</div>
        )}
        {status === "loading" && (
          <div className="nifti-message">
            불러오는 중{progress > 0 ? ` ${progress}%` : "…"}
          </div>
        )}
        {status === "error" && (
          <div className="nifti-message nifti-error">{error}</div>
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
