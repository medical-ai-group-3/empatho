import { useEffect, useState } from "react";
import { api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Body } from "../../../lib/Screen";
import MRIReviewGrid from "../../../components/MRIReviewGrid";

const MODALITIES = ["맘모", "초음파", "MRI", "병리"];

/*
 * 현재 프로젝트에 실제 존재하는 샘플 이미지
 */
const SAMPLE_IMAGES = {
  맘모: "/samples/mammo/mamamomo.png",
  초음파: "/samples/us/usus.png",
  병리: "/samples/pathology/patho.png",
};

export default function ReviewViewer({
  patientId,
  lesions = [],
  onModalityChange,
}) {
  const {
    loading,
    data: studies,
    error,
    reload,
  } = useApi(
    () => api.studies(patientId),
    [patientId]
  );

  /*
   * 실제로 촬영한(performed_at이 있는) modality만 탭으로 보여준다 —
   * 이 환자가 맘모만 찍었으면 맘모만, 초음파까지 찍었으면 그것까지만.
   * 전체 MODALITIES를 항상 다 보여주면 안 찍은 검사까지 탭이 떠서
   * "표시할 영상이 없습니다" 빈 화면만 늘어난다.
   */
  const availableModalities = Array.isArray(studies)
    ? MODALITIES.filter((modality) =>
        studies.some(
          (item) =>
            item.modality === modality &&
            item.performed_at
        )
      )
    : [];

  const [tab, setTab] = useState(null);

  useEffect(() => {
    setTab(null);
  }, [patientId]);

  /*
   * 환자가 바뀌면(또는 처음 로딩되면) 가장 최근에 촬영한 검사를 기본
   * 탭으로 연다 — 오른쪽 유방외과 리포트가 이 modality를 그대로
   * 따라가므로(onModalityChange), "최근 검사"와 "리포트 작성 대상"이
   * 항상 같은 걸 가리키게 된다.
   */
  useEffect(() => {
    if (tab !== null) return;
    if (!Array.isArray(studies) || availableModalities.length === 0) return;

    const completed = studies.filter(
      (study) =>
        study?.performed_at &&
        MODALITIES.includes(study.modality)
    );

    const latest = [...completed].sort(
      (a, b) => new Date(b.performed_at) - new Date(a.performed_at)
    )[0];

    const next = latest?.modality ?? availableModalities[0];
    setTab(next);
    onModalityChange?.(next);
  }, [tab, studies, availableModalities.join(","), onModalityChange]);

  /*
   * API에서 해당 modality 검사 결과를 찾는다.
   */
  const study =
    Array.isArray(studies)
      ? studies.find(
          (item) => item.modality === tab
        )
      : null;

  return (
    <div className="viewer-shell">

      {/* =====================================================
          상단 모달리티 탭
      ===================================================== */}

      <div className="viewer-tabs">
        {availableModalities.length === 0 && !loading ? (
          <span className="viewer-tabs-empty">촬영한 검사가 없습니다</span>
        ) : (
          availableModalities.map((modality) => (
            <button
              key={modality}
              type="button"
              className={
                tab === modality ? "on" : ""
              }
              onClick={() => {
                setTab(modality);
                onModalityChange?.(modality);
              }}
            >
              {modality}
            </button>
          ))
        )}
      </div>


      {/* =====================================================
          Viewer
      ===================================================== */}

      <div className="viewer-content">
        <Body
          loading={loading}
          error={error}
          onRetry={reload}
        >
          {tab === null ? null : tab === "MRI" ? (
            <MRIReviewGrid
              lesions={lesions}
              study={study}
            />
          ) : (
            <GenericImageViewer
              modality={tab}
              study={study}
            />
          )}
        </Body>
      </div>


      <style>{`

        /* ===================================================
           전체 Viewer
        =================================================== */

        .viewer-shell {
          width: 100%;
          height: 100%;
          min-width: 0;
          min-height: 0;

          display: flex;
          flex-direction: column;

          overflow: hidden;

          background: #111518;

          border: 1px solid #596169;
          border-radius: 8px;
        }


        /* ===================================================
           모달리티 탭
        =================================================== */

        .viewer-tabs {
          flex: 0 0 42px;

          height: 42px;

          display: flex;
          align-items: center;

          gap: 3px;

          padding: 5px 8px;

          background: #171b1f;

          border-bottom: 1px solid #343a40;
        }

        .viewer-tabs button {
          height: 30px;

          padding: 0 18px;

          border: 1px solid transparent;
          border-radius: 5px;

          background: transparent;

          color: #8e959c;

          font-size: 12px;
          font-weight: 500;

          cursor: pointer;

          transition:
            background 0.12s ease,
            color 0.12s ease,
            border-color 0.12s ease;
        }

        .viewer-tabs button:hover {
          color: #ffffff;
          background: #22272c;
        }

        .viewer-tabs-empty {
          padding: 0 8px;
          color: #596169;
          font-size: 12px;
        }

        .viewer-tabs button.on {
          color: #ffffff;

          background: #343a40;

          border-color: #596169;

          font-weight: 600;
        }


        /* ===================================================
           Viewer Content
        =================================================== */

        .viewer-content {
          flex: 1;

          min-width: 0;
          min-height: 0;

          overflow: hidden;
        }


        /* ===================================================
           일반 영상 Viewer
           
           맘모 / 초음파 / 병리
        =================================================== */

        .generic-viewer {
          width: 100%;
          height: 100%;

          min-width: 0;
          min-height: 0;

          display: flex;
          flex-direction: column;

          overflow: hidden;

          background: #0b0e10;
        }


        /* ===================================================
           이미지 영역
        =================================================== */

        .generic-image-area {
          position: relative;

          flex: 1;

          min-width: 0;
          min-height: 0;

          display: flex;

          align-items: center;
          justify-content: center;

          /* 확대(zoom>100%)하면 이미지가 박스보다 커지는데, 그때는
             스크롤로 이동(pan)할 수 있어야 한다 */
          overflow: auto;

          padding: 16px;

          background: #0b0e10;
        }


        /*
         * 원본 + Mask를 정확히 같은 위치에 겹치기 위한
         * 이미지 Stack
         */
        .generic-image-stack {
          position: relative;

          width: 100%;
          height: 100%;

          min-width: 0;
          min-height: 0;

          display: flex;

          align-items: center;
          justify-content: center;

          flex: none;
        }


        /* ===================================================
           원본 이미지
        =================================================== */

        .generic-image {
          display: block;

          max-width: 100%;
          max-height: 100%;

          width: auto;
          height: auto;

          object-fit: contain;

          user-select: none;

          -webkit-user-drag: none;

          transform-origin: center center;
          transition: transform 0.12s ease;
        }


        /*
         * AI Mask
         *
         * 현재 mask 파일이 없기 때문에 실제 화면에서는
         * 표시되지 않는다.
         *
         * 나중에 mask URL이 들어오면 바로 overlay 가능.
         */
        .generic-mask {
          position: absolute;

          max-width: 100%;
          max-height: 100%;

          width: auto;
          height: auto;

          object-fit: contain;

          pointer-events: none;

          transform-origin: center center;
          transition: opacity 0.1s ease, transform 0.12s ease;
        }


        /* ===================================================
           영상 좌상단 정보
        =================================================== */

        .image-label {
          position: absolute;

          top: 10px;
          left: 10px;

          z-index: 30;

          display: flex;
          align-items: center;

          gap: 7px;

          padding: 5px 8px;

          border: 1px solid #343a40;
          border-radius: 4px;

          background: rgba(17, 21, 24, 0.9);

          color: #ffffff;

          font-size: 11px;

          pointer-events: none;
        }

        .image-label-dot {
          width: 7px;
          height: 7px;

          flex: 0 0 7px;

          border-radius: 50%;

          background: #c9828c;
        }


        /* ===================================================
           이미지 우측 상단 상태
        =================================================== */

        .image-status {
          position: absolute;

          top: 10px;
          right: 10px;

          z-index: 30;

          padding: 4px 7px;

          border: 1px solid #343a40;
          border-radius: 4px;

          background: rgba(17, 21, 24, 0.9);

          color: #8e959c;

          font-size: 10px;
        }

        .image-status.active {
          color: #ffffff;
        }


        /* ===================================================
           하단 컨트롤
        =================================================== */

        .viewer-control {
          flex: 0 0 auto;

          min-height: 50px;

          display: flex;
          align-items: center;
          flex-wrap: wrap;

          gap: 10px 12px;

          padding: 7px 12px;

          background: #171b1f;

          border-top: 1px solid #343a40;
        }


        /* ===================================================
           Mask Toggle
        =================================================== */

        .mask-toggle {
          display: inline-flex;

          align-items: center;

          gap: 5px;

          color: #ffffff;

          font-size: 11px;

          white-space: nowrap;

          cursor: pointer;
        }

        .mask-toggle input {
          width: 13px;
          height: 13px;

          margin: 0;

          accent-color: #c9828c;

          cursor: pointer;
        }

        .mask-toggle.disabled {
          color: #596169;

          cursor: default;
        }


        /* ===================================================
           확대/축소
        =================================================== */

        .zoom-wrap {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .zoom-btn {
          width: 24px;
          height: 24px;

          padding: 0;

          border: 1px solid #343a40;
          border-radius: 4px;

          background: #1c2024;

          color: #ffffff;

          font-size: 14px;
          line-height: 1;

          cursor: pointer;
        }

        .zoom-btn:hover:not(:disabled) {
          background: #343a40;
        }

        .zoom-btn:disabled {
          color: #596169;
          cursor: default;
        }

        .zoom-value {
          min-width: 44px;

          height: 24px;

          padding: 0 4px;

          border: 1px solid transparent;
          border-radius: 4px;

          background: transparent;

          color: #aeb4ba;

          font-size: 11px;
          font-variant-numeric: tabular-nums;

          cursor: pointer;
        }

        .zoom-value:hover:not(:disabled) {
          color: #ffffff;
          border-color: #343a40;
        }

        .zoom-value:disabled {
          color: #596169;
          cursor: default;
        }


        /* ===================================================
           투명도
        =================================================== */

        .control-label {
          color: #8e959c;

          font-size: 10px;

          white-space: nowrap;
        }

        .opacity-wrap {
          display: flex;

          align-items: center;

          gap: 7px;

          flex: 1;

          min-width: 120px;
        }

        .opacity-wrap input[type="range"] {
          flex: 1;

          min-width: 0;

          cursor: pointer;

          accent-color: #c9828c;
        }

        .opacity-wrap input[type="range"]:disabled {
          opacity: 0.3;

          cursor: default;
        }

        .opacity-value {
          width: 38px;

          text-align: right;

          color: #ffffff;

          font-size: 10px;

          font-variant-numeric: tabular-nums;
        }


        /* ===================================================
           Slice
           
           여러 장의 이미지가 들어왔을 경우만 표시
        =================================================== */

        .slice-wrap {
          display: flex;

          align-items: center;

          gap: 7px;

          min-width: 180px;
          max-width: 300px;
        }

        .slice-wrap input[type="range"] {
          flex: 1;

          min-width: 0;

          cursor: pointer;

          accent-color: #c9828c;
        }

        .slice-count {
          min-width: 48px;

          text-align: right;

          color: #aeb4ba;

          font-size: 10px;

          font-variant-numeric: tabular-nums;
        }


        /* ===================================================
           이미지 없음
        =================================================== */

        .generic-empty {
          width: 100%;
          height: 100%;

          display: flex;
          flex-direction: column;

          align-items: center;
          justify-content: center;

          gap: 8px;

          color: #596169;

          font-size: 12px;
        }

        .generic-empty-icon {
          font-size: 28px;

          opacity: 0.5;
        }

        .generic-empty-sub {
          color: #464c52;

          font-size: 10px;
        }

      `}</style>
    </div>
  );
}


/* ===========================================================
   맘모 / 초음파 / 병리 Viewer
=========================================================== */

function GenericImageViewer({
  modality,
  study,
}) {
  /*
   * API에서 이미지가 내려오면 우선 사용한다.
   *
   * 아직 mock DB의 slices가 비어 있어도
   * 아래 SAMPLE_IMAGES를 fallback으로 사용한다.
   */
  const apiSlices = Array.isArray(study?.slices)
    ? study.slices.filter(Boolean)
    : [];

  const sampleImage =
    SAMPLE_IMAGES[modality];

  const slices =
    apiSlices.length > 0
      ? apiSlices
      : sampleImage
        ? [sampleImage]
        : [];


  /*
   * Mask 데이터
   *
   * 현재 public/samples에는 mask 파일이 없으므로
   * 빈 배열이다.
   *
   * 추후 API에서 mask_slices가 들어오면 바로 사용할 수 있다.
   */
  const maskSlices =
    Array.isArray(study?.mask_slices)
      ? study.mask_slices.filter(Boolean)
      : Array.isArray(study?.maskSlices)
        ? study.maskSlices.filter(Boolean)
        : Array.isArray(study?.masks)
          ? study.masks.filter(Boolean)
          : [];


  const [sliceIndex, setSliceIndex] =
    useState(0);

  const [maskVisible, setMaskVisible] =
    useState(true);

  const [maskOpacity, setMaskOpacity] =
    useState(0.45);

  /*
   * 확대/축소 — 100%는 "박스에 꽉 차게 맞춘 크기"다(원본 픽셀 1:1이
   * 아니다). 병리 원본처럼 실제 해상도가 큰 이미지를 그대로 100%=원본
   * 픽셀로 두면 박스 밖으로 넘쳐서 다른 모달리티/옆 패널과 높이가
   * 안 맞았다 — object-fit:contain으로 박스에 맞춘 크기를 기준(100%)
   * 삼고, 그 위에서 배율만 곱한다.
   */
  const [zoom, setZoom] = useState(100);
  const ZOOM_MIN = 50;
  const ZOOM_MAX = 300;
  const ZOOM_STEP = 25;
  const zoomIn = () => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP));
  const zoomOut = () => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP));
  const zoomReset = () => setZoom(100);


  /*
   * 검사 / modality 변경 시 초기화
   */
  useEffect(() => {
    setSliceIndex(0);
    setMaskVisible(true);
    setMaskOpacity(0.45);
    setZoom(100);
  }, [modality, study]);


  const imageSrc =
    slices[sliceIndex] ?? null;

  const maskSrc =
    maskSlices.length > 0
      ? maskSlices[sliceIndex] ?? null
      : null;

  const hasMask =
    Boolean(maskSrc);


  return (
    <div className="generic-viewer">

      {/* =================================================
          큰 이미지 Viewer
      ================================================= */}

      <div className="generic-image-area">

        {!imageSrc ? (
          <div className="generic-empty">

            <div className="generic-empty-icon">
              ◫
            </div>

            <div>
              표시할 {modality} 영상이 없습니다.
            </div>

            <div className="generic-empty-sub">
              검사 데이터 또는 샘플 이미지가
              등록되지 않았습니다.
            </div>

          </div>
        ) : (
          <>

            {/* 좌상단 modality */}
            <div className="image-label">

              <span className="image-label-dot" />

              <span>
                {modality}
              </span>

              {study?.device && (
                <span>
                  · {study.device}
                </span>
              )}

            </div>


            {/* 우상단 */}
            <div
              className={
                `image-status ${
                  hasMask ? "active" : ""
                }`
              }
            >
              {hasMask
                ? "AI Mask 사용 가능"
                : "AI Mask 데이터 없음"}
            </div>


            {/* 원본 + Mask — 확대해도 둘이 같이 움직이도록 같은
                transform을 준다 */}
            <div className="generic-image-stack">

              {/* 원본 */}
              <img
                className="generic-image"
                src={imageSrc}
                alt={`${modality} 검사 영상`}
                style={{ transform: `scale(${zoom / 100})` }}
              />


              {/* AI Mask */}
              {hasMask &&
                maskVisible && (
                  <img
                    className="generic-mask"
                    src={maskSrc}
                    alt=""
                    aria-hidden="true"
                    style={{
                      opacity: maskOpacity,
                      transform: `scale(${zoom / 100})`,
                    }}
                  />
                )}

            </div>

          </>
        )}

      </div>


      {/* =================================================
          하단 Control
      ================================================= */}

      <div className="viewer-control">

        {/* 확대/축소 — 맘모/초음파/병리도 기본적인 뷰어 기능이라 필요 */}
        <div className="zoom-wrap">
          <button
            type="button"
            className="zoom-btn"
            onClick={zoomOut}
            disabled={!imageSrc || zoom <= ZOOM_MIN}
            aria-label="축소"
          >
            −
          </button>
          <button
            type="button"
            className="zoom-value"
            onClick={zoomReset}
            disabled={!imageSrc}
            title="100%로 리셋"
          >
            {zoom}%
          </button>
          <button
            type="button"
            className="zoom-btn"
            onClick={zoomIn}
            disabled={!imageSrc || zoom >= ZOOM_MAX}
            aria-label="확대"
          >
            ＋
          </button>
        </div>

        {/* AI Mask */}
        <label
          className={
            `mask-toggle ${
              !hasMask
                ? "disabled"
                : ""
            }`
          }
        >

          <input
            type="checkbox"
            checked={
              hasMask
                ? maskVisible
                : false
            }
            onChange={(e) =>
              setMaskVisible(
                e.target.checked
              )
            }
            disabled={!hasMask}
          />

          <span>
            AI Mask
          </span>

        </label>


        {/* 투명도 */}
        <span className="control-label">
          투명도
        </span>

        <div className="opacity-wrap">

          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={maskOpacity}
            onChange={(e) =>
              setMaskOpacity(
                Number(e.target.value)
              )
            }
            disabled={!hasMask}
          />

          <span className="opacity-value">
            {Math.round(
              maskOpacity * 100
            )}%
          </span>

        </div>


        {/* Slice
            여러 장일 때만 표시 */}
        {slices.length > 1 && (
          <div className="slice-wrap">

            <span className="control-label">
              Slice
            </span>

            <input
              type="range"
              min="0"
              max={slices.length - 1}
              step="1"
              value={sliceIndex}
              onChange={(e) =>
                setSliceIndex(
                  Number(e.target.value)
                )
              }
            />

            <span className="slice-count">
              {sliceIndex + 1} /{" "}
              {slices.length}
            </span>

          </div>
        )}

      </div>

    </div>
  );
}