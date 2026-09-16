import { useEffect, useState } from "react";
import Anatomy3DViewer from "./Anatomy3DViewer";
import Tumor3DViewer from "./Tumor3DViewer";
import NiftiSliceViewer from "./NiftiSliceViewer";
import { useNiftiVolume } from "../lib/useNiftiVolume";

const NIFTI_URL = "/samples/duke/duke_001_0000.nii";

/* 실제 segmentation mask NIfTI가 준비되면 이 값을 경로로 교체한다. */
const MASK_URL = null;

const DEFAULT_LESIONS = [
  {
    lesion_id: "L-001",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion01.stl",
    color: "#C9828C",
    location: "병변 01",
  },
  {
    lesion_id: "L-002",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion02.stl",
    color: "#8FA8C2",
    location: "병변 02",
  },
  {
    lesion_id: "L-003",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion03.stl",
    color: "#B59A6A",
    location: "병변 03",
  },
  {
    lesion_id: "L-004",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion04.stl",
    color: "#9B8FB5",
    location: "병변 04",
  },
];

export default function MRIReviewGrid({
  lesions = DEFAULT_LESIONS,
  selectedLesion: selectedLesionProp,
  onLesionChange,
}) {
  const [localSelectedLesion, setLocalSelectedLesion] =
    useState(
      selectedLesionProp !== undefined
        ? selectedLesionProp
        : null
    );

  const selectedLesion =
    localSelectedLesion;

  // 세 단면이 같은 볼륨·같은 crosshair 좌표를 공유한다 — 한 곳을
  // 클릭/드래그하면 나머지 두 단면의 슬라이스와 crosshair가 같이 움직인다.
  const { volume, loading, error } = useNiftiVolume(NIFTI_URL);
  const { volume: maskVolume, loading: maskLoading, error: maskError } = useNiftiVolume(MASK_URL);
  const [showMask, setShowMask] = useState(true);
  const [maskOpacity, setMaskOpacity] = useState(0.45);
  const [cursor, setCursor] = useState({ x: 0, y: 0, z: 0 });

  useEffect(() => {
    if (!volume) return;
    const [nx, ny, nz] = volume.dims;
    setCursor({
      x: Math.floor(nx / 2),
      y: Math.floor(ny / 2),
      z: Math.floor(nz / 2),
    });
  }, [volume]);

  const updateCursor = (partial) =>
    setCursor((prev) => ({ ...prev, ...partial }));

  const validLesions = Array.isArray(lesions)
    ? lesions.filter(
        (lesion) =>
          lesion &&
          (lesion.mesh_url ||
            lesion.mesh_image_id)
      )
    : [];

  const selectLesion = (index) => {
    const next =
      index === "all"
        ? null
        : Number(index);

    setLocalSelectedLesion(next);
    onLesionChange?.(next);
  };

  return (
    <div className="mri-review-grid">
      <section className="mri-review-panel anatomy-panel">
        <PanelTitle title="병변 위치" />

        <Anatomy3DViewer
          lesions={validLesions}
          selectedLesion={selectedLesion}
          showBody
        />
      </section>

      <section className="mri-review-panel tumor-panel">
        <PanelTitle title="병변 3D" />

        <div
          className="lesion-selector"
          aria-label="병변 선택"
        >
          <button
            type="button"
            className={
              selectedLesion === null
                ? "active"
                : ""
            }
            onMouseDown={(e) =>
              e.stopPropagation()
            }
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              selectLesion("all");
            }}
          >
            전체
          </button>

          {validLesions.map(
            (lesion, index) => (
              <button
                type="button"
                key={
                  lesion.lesion_id ||
                  index
                }
                className={
                  selectedLesion === index
                    ? "active"
                    : ""
                }
                onMouseDown={(e) =>
                  e.stopPropagation()
                }
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  selectLesion(index);
                }}
                title={
                  lesion.location ||
                  lesion.site ||
                  lesion.lesion_id ||
                  `병변 ${index + 1}`
                }
              >
                <span
                  className="lesion-dot"
                  style={{
                    background:
                      lesion.color ||
                      [
                        "#C9828C",
                        "#8FA8C2",
                        "#B59A6A",
                        "#9B8FB5",
                      ][index % 4],
                  }}
                />
                병변{" "}
                {String(index + 1).padStart(
                  2,
                  "0"
                )}
              </button>
            )
          )}
        </div>

        <Tumor3DViewer
          lesions={validLesions}
          selectedLesion={selectedLesion}
        />
      </section>

      <div className="mri-review-2d">
        <div className="mri-overlay-toolbar">
          <div className="mri-overlay-left">
            <span className="mri-overlay-label">AI SEGMENTATION</span>
            <span className={`mri-mask-status ${maskVolume ? "connected" : "pending"}`}>
              {maskVolume ? "연결됨" : "MASK 대기"}
            </span>
          </div>
          <label className="mri-mask-toggle">
            <input type="checkbox" checked={showMask} onChange={(e) => setShowMask(e.target.checked)} disabled={!maskVolume} />
            <span>Mask</span>
          </label>
          <label className="mri-opacity-control">
            <span>Opacity</span>
            <input type="range" min="0" max="1" step="0.05" value={maskOpacity} onChange={(e) => setMaskOpacity(Number(e.target.value))} disabled={!maskVolume || !showMask} />
            <span>{Math.round(maskOpacity * 100)}%</span>
          </label>
        </div>

        <NiftiSliceViewer
          title="Axial"
          axis="axial"
          volume={volume}
          maskVolume={maskVolume}
          maskLoading={maskLoading}
          loading={loading}
          error={error}
          maskError={maskError}
          cursor={cursor}
          showMask={showMask}
          maskOpacity={maskOpacity}
          selectedLesion={selectedLesion}
          onCursorChange={updateCursor}
        />

        <NiftiSliceViewer
          title="Coronal"
          axis="coronal"
          volume={volume}
          maskVolume={maskVolume}
          maskLoading={maskLoading}
          loading={loading}
          error={error}
          maskError={maskError}
          cursor={cursor}
          showMask={showMask}
          maskOpacity={maskOpacity}
          selectedLesion={selectedLesion}
          onCursorChange={updateCursor}
        />

        <NiftiSliceViewer
          title="Sagittal"
          axis="sagittal"
          volume={volume}
          maskVolume={maskVolume}
          maskLoading={maskLoading}
          loading={loading}
          error={error}
          maskError={maskError}
          cursor={cursor}
          showMask={showMask}
          maskOpacity={maskOpacity}
          selectedLesion={selectedLesion}
          onCursorChange={updateCursor}
        />
      </div>

      <style>{`
        .mri-review-grid {
          width: 100%;
          height: 100%;
          min-height: 680px;
          display: grid;
          grid-template-columns:
            minmax(0, 1.08fr)
            minmax(0, 0.92fr);
          grid-template-rows:
            minmax(0, 1fr)
            minmax(0, 1fr);
          gap: 10px;
          background: #111518;
        }

        .mri-review-panel,
        .nifti-viewer {
          position: relative;
          min-width: 0;
          min-height: 0;
          overflow: hidden;
          border: 1px solid #596169;
          border-radius: 8px;
          background: #111518;
        }

        .anatomy-panel {
          grid-column: 1;
          grid-row: 1;
        }

        .tumor-panel {
          grid-column: 1;
          grid-row: 2;
        }

        .mri-review-2d {
          grid-column: 2;
          grid-row: 1 / span 2;
          min-width: 0;
          min-height: 0;
          display: grid;
          grid-template-rows:
            repeat(3, minmax(0, 1fr));
          gap: 10px;
        }

        .mri-overlay-toolbar {
          position: absolute; z-index: 200; top: 7px; left: 9px; right: 9px;
          height: 28px; display: flex; align-items: center; justify-content: flex-end;
          gap: 10px; padding: 0 8px; border: 1px solid #343a40; border-radius: 5px;
          background: rgba(17, 21, 24, 0.96); color: #fff; pointer-events: auto;
        }
        .mri-overlay-left { margin-right: auto; display: flex; align-items: center; gap: 6px; min-width: 0; }
        .mri-overlay-label { color: #aeb4ba; font-size: 9px; letter-spacing: .06em; white-space: nowrap; }
        .mri-mask-status { padding: 2px 5px; border: 1px solid #596169; border-radius: 3px; color: #8e959c; font-size: 8px; white-space: nowrap; }
        .mri-mask-status.connected { color: #fff; }
        .nifti-mask-badge {
          padding: 2px 4px; border: 1px solid #596169; border-radius: 3px;
          color: #c9828c; font-size: 8px; letter-spacing: .04em;
        }
        .nifti-mask-loading {
          position: absolute; z-index: 50; top: 42px; right: 10px;
          padding: 4px 6px; border: 1px solid #343a40; border-radius: 4px;
          background: rgba(17,21,24,.9); color: #8e959c; font-size: 9px;
        }
        .mri-mask-toggle, .mri-opacity-control { display: flex; align-items: center; gap: 5px; color: #aeb4ba; font-size: 9px; white-space: nowrap; }
        .mri-mask-toggle input { margin: 0; accent-color: #c9828c; }
        .mri-opacity-control input[type="range"] { width: 70px; margin: 0; accent-color: #c9828c; cursor: pointer; }
        .mri-opacity-control input[type="range"]:disabled { opacity: .35; cursor: default; }
        .mri-opacity-control > span:last-child { width: 28px; text-align: right; color: #fff; font-variant-numeric: tabular-nums; }

        .mri-panel-title,
        .nifti-title {
          position: absolute;
          z-index: 40;
          top: 9px;
          left: 10px;
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 3px 6px;
          border-radius: 4px;
          background:
            rgba(17, 21, 24, 0.84);
          color: #ffffff;
          font-size: 12px;
          font-weight: 600;
          pointer-events: none;
        }

        .nifti-axis-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          flex: 0 0 7px;
        }

        .lesion-selector {
          position: absolute;
          z-index: 100;
          top: 7px;
          right: 9px;
          display: flex;
          align-items: center;
          gap: 3px;
          padding: 3px;
          max-width:
            calc(100% - 95px);
          overflow-x: auto;
          border: 1px solid #343a40;
          border-radius: 5px;
          background:
            rgba(17, 21, 24, 0.94);
          pointer-events: auto;
        }

        .lesion-selector button {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          flex: 0 0 auto;
          border: 1px solid transparent;
          border-radius: 3px;
          padding: 4px 7px;
          background: transparent;
          color: #8e959c;
          font-size: 10px;
          line-height: 1;
          cursor: pointer;
          pointer-events: auto;
          user-select: none;
          white-space: nowrap;
        }

        .lesion-selector button:hover {
          color: #ffffff;
          border-color: #596169;
        }

        .lesion-selector button.active {
          color: #ffffff;
          background: #343a40;
          border-color: #596169;
        }

        .lesion-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          flex: 0 0 7px;
          border:
            1px solid
            rgba(255,255,255,0.35);
        }

        .nifti-canvas-wrap {
          position: absolute;
          inset: 0;
          bottom: 40px;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
        }

        .nifti-canvas {
          display: block;
          max-width: 100%;
          max-height: 100%;
          width: auto;
          height: auto;
          object-fit: contain;
          image-rendering: auto;
          cursor: crosshair;
          touch-action: none;
        }

        .nifti-message {
          color: #596169;
          font-size: 12px;
        }

        .nifti-error {
          max-width: 90%;
          text-align: center;
          color: #c9828c;
          line-height: 1.5;
        }

        .nifti-slice-control {
          position: absolute;
          z-index: 30;
          left: 10px;
          right: 10px;
          bottom: 8px;
          height: 24px;
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 0 7px;
          border-radius: 5px;
          background:
            rgba(17, 21, 24, 0.94);
          border: 1px solid #343a40;
        }

        .nifti-slice-control > span:first-child {
          color: #8e959c;
          font-size: 10px;
          white-space: nowrap;
        }

        .nifti-slice-control input[type="range"] {
          flex: 1;
          min-width: 0;
          cursor: pointer;
          accent-color: #c9828c;
        }

        .nifti-slice-control input[type="range"]:disabled {
          cursor: default;
          opacity: 0.45;
        }

        .nifti-count {
          min-width: 54px;
          text-align: right;
          color: #aeb4ba;
          font-size: 10px;
          font-variant-numeric: tabular-nums;
        }
      `}</style>
    </div>
  );
}

function PanelTitle({ title }) {
  return (
    <div className="mri-panel-title">
      {title}
    </div>
  );
}
