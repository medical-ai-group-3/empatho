import { useState } from "react";
import Anatomy3DViewer from "./Anatomy3DViewer";
import Tumor3DViewer from "./Tumor3DViewer";
import DicomMprPanel from "./DicomMprPanel";

export default function MRIReviewGrid({
  /* ⚠ 기본값을 **빈 배열**로 둔다.
   *
   * 전에는 DEFAULT_LESIONS — DUKE 공개 데이터셋 환자의 종괴 메시 네 개가
   * 기본값이었다. 호출부가 lesions 를 안 넘기거나 서버가 병변을 안 주면
   * (undefined) 그 순간 **남의 환자 종괴가 이 환자 화면에 뜬다.**
   * 판독 화면에서 화면만 봐서는 진짜인지 구분할 수 없다.
   *
   * (그 .stl 파일들은 저장소에 없어서 지금은 404 로 안 그려질 뿐이었다.
   * 누가 public/models/duke/ 를 채우는 순간 조용히 진짜처럼 보이게 된다.)
   *
   * 비면 아무것도 안 그린다. 그게 맞는 상태다. */
  lesions = [],
  selectedLesion: selectedLesionProp,
  onLesionChange,
  study,
}) {
  const [localSelectedLesion, setLocalSelectedLesion] =
    useState(
      selectedLesionProp !== undefined
        ? selectedLesionProp
        : null
    );

  const selectedLesion =
    localSelectedLesion;

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
        <DicomMprPanel
          manifestUrl={study?.volume_manifest}
          baseUrl={study?.volume_base}
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
          display: flex;
        }

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
