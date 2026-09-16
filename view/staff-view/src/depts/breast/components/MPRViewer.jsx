import { useEffect, useRef, useState } from "react";
import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import { ensureCornerstoneInit } from "./cornerstoneInit";
import MeshViewer from "./MeshViewer";

/* MRI는 한 방향만 찍는 게 아니라 축상(axial)·시상(sagittal)·관상(coronal)
 * 세 방향 다 봐야 한다는 요청 반영 — 2x2로 나눠 세 칸은 같은 볼륨을 서로
 * 다른 단면으로 잘라 보여준다(ORTHOGRAPHIC 뷰포트 3개).
 *
 * 네 번째 칸(3D)은 cornerstone의 VOLUME_3D 레이캐스팅 대신 MeshViewer로
 * 종양 표면 메시를 그린다 — 기본 명암의 볼륨 레이캐스팅은 뿌연 안개처럼
 * 보여서, 세그멘테이션 파이프라인이 뽑아 준 또렷한 메시로 바꿨다
 * (mesh_url이 없으면 이 칸은 안 그린다 — Empty쪽에서 처리).
 *
 * 세 2D 칸이 따로 놀지 않게 CrosshairsTool을 붙였다 — 한 칸에서 십자선을
 * 드래그하면 나머지 두 칸도 같은 3D 지점을 가리키도록 같이 움직인다(색깔
 * 기준선으로 서로의 단면 위치를 표시). 휠은 그대로 현재 칸의 슬라이스를
 * 넘긴다(StackScrollTool) — 둘 다 켜 둬도 서로 안 부딪힌다.
 *
 * ⚠ manifest.json은 InstanceNumber로 미리 정렬돼 있어야 한다(wadouri는
 *   cornerstone이 순서를 다시 안 잡아준다 — scripts/sort-dicom-manifest.cjs). */
const RENDERING_ENGINE_ID = "breastMprRenderingEngine";
const VOLUME_ID = "cornerstoneStreamingImageVolume:breast-mri-018";
const IDS = {
  axial: "BREAST_MPR_AXIAL",
  sagittal: "BREAST_MPR_SAGITTAL",
  coronal: "BREAST_MPR_CORONAL",
};
const REFERENCE_LINE_COLORS = {
  [IDS.axial]: "rgb(255, 86, 86)",
  [IDS.sagittal]: "rgb(70, 210, 120)",
  [IDS.coronal]: "rgb(90, 150, 255)",
};
const TOOL_GROUP_2D_ID = "breastMpr2dToolGroup";

export default function MPRViewer({ manifestUrl, baseUrl, meshUrl, meshSite, lesions = [] }) {
  const axialRef = useRef(null);
  const sagittalRef = useRef(null);
  const coronalRef = useRef(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [layers, setLayers] = useState({ breast: true, chestWall: false, lesion: true });

  useEffect(() => {
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
          { viewportId: IDS.sagittal, type: ViewportType.ORTHOGRAPHIC, element: sagittalRef.current,
            defaultOptions: { orientation: OrientationAxis.SAGITTAL, background: [0, 0, 0] } },
          { viewportId: IDS.coronal, type: ViewportType.ORTHOGRAPHIC, element: coronalRef.current,
            defaultOptions: { orientation: OrientationAxis.CORONAL, background: [0, 0, 0] } },
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
          [IDS.axial, IDS.sagittal, IDS.coronal]
        );
        if (cancelled) return;

        let toolGroup2d = cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_2D_ID);
        if (!toolGroup2d) {
          toolGroup2d = cornerstoneTools.ToolGroupManager.createToolGroup(TOOL_GROUP_2D_ID);
          toolGroup2d.addTool(cornerstoneTools.StackScrollTool.toolName);
          toolGroup2d.setToolActive(cornerstoneTools.StackScrollTool.toolName, {
            bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Wheel }],
          });
          toolGroup2d.addTool(cornerstoneTools.CrosshairsTool.toolName, {
            getReferenceLineColor: (viewportId) => REFERENCE_LINE_COLORS[viewportId] ?? "rgb(200, 200, 0)",
          });
          toolGroup2d.setToolActive(cornerstoneTools.CrosshairsTool.toolName, {
            bindings: [{ mouseButton: cornerstoneTools.Enums.MouseBindings.Primary }],
          });
        }
        [IDS.axial, IDS.sagittal, IDS.coronal].forEach((id) =>
          toolGroup2d.addViewport(id, RENDERING_ENGINE_ID));

        renderingEngine.render();
        if (!cancelled) setStatus("ready");
      } catch (e) {
        console.error("[MPRViewer]", e);
        if (!cancelled) { setError(e.message || String(e)); setStatus("error"); }
      }
    }

    run();

    return () => {
      cancelled = true;
      try {
        cornerstoneTools.ToolGroupManager.getToolGroup(TOOL_GROUP_2D_ID)?.removeViewports(RENDERING_ENGINE_ID);
      } catch { /* 툴그룹이 아직 없을 수 있다 */ }
      cornerstone.getRenderingEngine(RENDERING_ENGINE_ID)?.destroy();
    };
  }, [manifestUrl, baseUrl]);

  const lesionSummary = lesions.length === 0 ? "병변 없음"
    : `병변 ${lesions.length} · ${lesions.map((l) => `${l.size_mm}mm`).join(", ")}`;

  return (
    <div className="mpr-wrap">
      <div className="mpr-main">
        <div className="mpr-cell mpr-cell-3d">
          {meshUrl
            ? <MeshViewer meshUrl={meshUrl} site={meshSite} layers={layers} />
            : <div className="viewer-body" style={{ minHeight: "auto", height: "100%" }}>
                <span className="ic" aria-hidden="true">◍</span>
                <p style={{ fontSize: 12 }}>병변 메시 없음</p>
              </div>}
          <span className="mpr-label">3D ANATOMY</span>
        </div>

        <div className="mpr-2d-col">
          <div className="mpr-cell">
            <div ref={axialRef} className="mpr-canvas" />
            <span className="mpr-label">축상 · Axial</span>
          </div>
          <div className="mpr-cell">
            <div ref={coronalRef} className="mpr-canvas" />
            <span className="mpr-label">관상 · Coronal</span>
          </div>
          <div className="mpr-cell">
            <div ref={sagittalRef} className="mpr-canvas" />
            <span className="mpr-label">시상 · Sagittal</span>
          </div>
        </div>

        {status === "loading" && (
          <div className="volume3d-overlay" style={{ position: "absolute", inset: 0 }}>
            <span>볼륨 불러오는 중… {progress > 0 ? `${progress}%` : ""}</span>
            <span style={{ fontSize: 11, opacity: .7 }}>208장 · 첫 렌더링은 시간이 걸릴 수 있습니다</span>
          </div>
        )}
        {status === "error" && (
          <div className="volume3d-overlay error" style={{ position: "absolute", inset: 0 }}>
            <span>볼륨을 불러오지 못했습니다</span>
            <span style={{ fontSize: 11 }}>{error}</span>
          </div>
        )}
        {status === "ready" && (
          <p className="volume3d-hint">2D 세 칸 — 십자선 드래그로 같이 이동 · 휠로 슬라이스 · 3D는 드래그로 회전</p>
        )}
      </div>

      <div className="mpr-toolbar">
        <label className="mpr-toggle">
          <input type="checkbox" checked={layers.breast}
            onChange={(e) => setLayers((v) => ({ ...v, breast: e.target.checked }))} />
          유방조직
        </label>
        <label className="mpr-toggle">
          <input type="checkbox" checked={layers.chestWall}
            onChange={(e) => setLayers((v) => ({ ...v, chestWall: e.target.checked }))} />
          흉벽/골격
        </label>
        <label className="mpr-toggle">
          <input type="checkbox" checked={layers.lesion}
            onChange={(e) => setLayers((v) => ({ ...v, lesion: e.target.checked }))} />
          병변
        </label>
        <span className="mpr-toolbar-spacer" />
        <span className="mpr-lesion-summary">{lesionSummary}</span>
      </div>
    </div>
  );
}
