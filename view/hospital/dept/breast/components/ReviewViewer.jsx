import { useEffect, useState } from "react";
import { breast as api, rad } from "../../../api";
import { radStage } from "../../radiology";
import { useApi } from "../../../lib/useApi";
import { useFile } from "../../../lib/files";
import { Body } from "../../../lib/Body";
import MRIReviewGrid from "../../../lib/dicom/MRIReviewGrid";
import { MODALITY, label, modality as asModality } from "../../../codes";
import DicomStackViewer from "../../../lib/dicom/DicomStackViewer";
import Stage from "../../../lib/Stage";

/* 탭에 쓰는 값은 **서버 코드**다 (mammo · us · mri).
 *
 * 전에는 한글 라벨(["맘모","초음파","MRI","병리"])을 그대로 들고
 * study.modality 와 비교했다. 목업이 한글을 돌려주어 화면에서는 멀쩡해
 * 보였지만, 진짜 서버는 mammo·us·mri 를 보내므로 **비교가 하나도 안 맞아
 * 탭이 통째로 사라진다.** 게다가 그 한글이 onModalityChange 를 타고
 * 리포트 저장 본문(saveReport 의 modality)까지 들어가고 있었다.
 *
 * 코드표와 라벨은 codes.js 한 곳에서 온다. 비교는 늘 asModality() 를
 * 거친다 — 목업 일부가 아직 "ultrasound" 로 주는데 서버는 "us" 다.
 *
 * ⚠ 「병리」가 빠진 것은 서버 MODALITY 에 그 값이 없어서다. 병리는 study
 *   가 아니라 specimen 으로 다룬다. 넣어 둬도 study.modality 와 영영 안
 *   맞아 탭이 뜨지 않는다 — 안 뜨는 탭을 목록에 두면 「왜 안 나오지」가
 *   된다. 병리를 이 뷰어에 붙이려면 specimen 을 따로 받아 와야 한다.
 */

export default function ReviewViewer({
  patientId,
  lesions = [],
  onModalityChange,
  /* 검사 이력에서 고른 검사. 주면 그 검사를 연다 — 모달리티가 같은 검사가
     여러 건일 때 탭만으로는 「어느 것」을 못 고른다(늘 첫 건이 열렸다). */
  studyId = null,
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
   * 코드표를 항상 다 보여주면 안 찍은 검사까지 탭이 떠서
   * "표시할 영상이 없습니다" 빈 화면만 늘어난다.
   */
  const availableModalities = Array.isArray(studies)
    ? Object.keys(MODALITY).filter((code) =>
        studies.some(
          (item) =>
            asModality(item.modality) === code &&
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
  /* 고른 검사가 바뀌면 그 검사의 모달리티로 탭을 옮긴다. 탭만 옮기고
     끝나는 것이 아니라 아래 study 도 그 검사를 집는다. */
  const chosen = Array.isArray(studies) && studyId != null
    ? studies.find((item) => String(item.study_id ?? item.id) === String(studyId))
    : null;

  useEffect(() => {
    if (!chosen) return;
    const code = asModality(chosen.modality);
    setTab(code);
    onModalityChange?.(code);
  }, [chosen?.study_id ?? chosen?.id, onModalityChange]);

  useEffect(() => {
    if (tab !== null) return;
    if (!Array.isArray(studies) || availableModalities.length === 0) return;

    const completed = studies.filter(
      (study) =>
        study?.performed_at &&
        asModality(study.modality) in MODALITY
    );

    const latest = [...completed].sort(
      (a, b) => new Date(b.performed_at) - new Date(a.performed_at)
    )[0];

    const next = asModality(latest?.modality) ?? availableModalities[0];
    setTab(next);
    onModalityChange?.(next);
  }, [tab, studies, availableModalities.join(","), onModalityChange]);

  /*
   * API에서 해당 modality 검사 결과를 찾는다.
   */
  /* 고른 검사가 지금 탭과 같은 모달리티면 그것을 쓴다. 탭을 손으로 다른
     모달리티로 옮기면 고른 것을 놓고 그 모달리티의 첫 검사로 돌아간다. */
  const study =
    chosen && asModality(chosen.modality) === tab
      ? chosen
      : (Array.isArray(studies)
          ? studies.find((item) => asModality(item.modality) === tab)
          : null);

  return (
    <div className="viewer-shell">

      {/* =====================================================
          상단 모달리티 탭
      ===================================================== */}

      <div className="viewer-tabs">
        {availableModalities.length === 0 && !loading ? (
          <span className="viewer-tabs-empty">촬영한 검사가 없습니다</span>
        ) : (
          availableModalities.map((code) => (
            <button
              key={code}
              type="button"
              className={
                tab === code ? "on" : ""
              }
              onClick={() => {
                setTab(code);
                onModalityChange?.(code);
              }}
            >
              {label(MODALITY, code)}
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
          {tab === null ? null : study ? (
            <StudyView study={study} lesions={lesions} />
          ) : null}
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
           PNG 오버레이 Viewer — 맘모 / 초음파 / 병리

           ⚠ 공통 영상 Viewer 설계(2026-09-17) 2단계 — 여기 예전엔
           인라인으로 새로 짠 GenericImageViewer(자체 zoom·마스크 상태)를
           썼다. 영상의학과·병리과 판독 화면(screens/Read.jsx)이 쓰는
           lib/Stage.jsx와 완전히 다른 구현이라 같은 화면인데 조작 방식이
           서로 달랐다 — 이제 Stage를 mode="review"로 그대로 가져다 쓴다.
           확대·이동·전체화면은 Stage 자체 Toolbar(.vtools)가 이미 하고,
           여기는 모달리티 라벨 · 마스크 투명도 슬라이더 · Slice 이동만
           얹는다(Stage가 모르는, 이 화면만의 것들).
        =================================================== */

        .png-overlay-viewer {
          width: 100%;
          height: 100%;

          min-width: 0;
          min-height: 0;

          display: flex;
          flex-direction: column;

          overflow: hidden;

          background: #0b0e10;
        }

        .png-overlay-stage {
          position: relative;

          flex: 1;

          min-width: 0;
          min-height: 0;

          display: flex;
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
           투명도 — review 모드는 마스크 투명도 슬라이더만 준다
           (설계 문서 §2 PNG 오버레이 엔진 review 규칙). zoom·마스크
           on/off 체크박스는 Stage 자체 Toolbar와 역할이 겹쳐 뺐다.
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
   검사 한 건을 연다 — **판독 화면과 같은 경로로 받는다.**

   전에는 `GET /patients/{id}/studies` 가 준 행을 그대로 뷰어에 넘기고
   study.slices · study.mask_slices 를 읽으려 했다. 그런 칸은 서버에
   없다(StudySerializer 는 Study 모델 그대로다) — 목업 시절 모양이라
   초음파는 늘 「이 검사에 등록된 영상이 없습니다」였다.

   파일은 `GET /radiology/studies/{id}/read` 가 알고, 바이트는 Go 관문이
   티켓을 받고 준다. 판독 화면이 하는 그대로다 — 모달리티마다 어느
   뷰어인지는 radStage() 한 곳에만 적혀 있다.

   ⚠ 여기는 **보기만 한다.** 도형을 누르거나 그리는 도구를 붙이지 않는다
     — 유방외과는 판독을 고치는 자리가 아니다.
=========================================================== */

function StudyView({ study, lesions }) {
  const id = study?.study_id ?? study?.id ?? null;
  const read = useApi(() => (id == null ? Promise.resolve(null) : rad.read(id)), [id]);
  const d = read.data;
  const view = d ? radStage(d, 0) : {};
  /* 티켓이 여는 범위 — 영상은 검사 단위다(lib/files.js) */
  const img = useFile(view.image, rad.ticket, { kind: "study", id });

  return (
    <Body loading={read.loading} error={read.error} onRetry={read.reload}>
      {!d ? null : view.volumeManifest ? (
        <MRIReviewGrid lesions={lesions} study={d} mode="review" />
      ) : view.stackManifest ? (
        <DicomStackViewer manifestUrl={view.stackManifest}
                          baseUrl={view.stackBase} mode="review" />
      ) : (
        <Stage src={img.src} w={view.w} h={view.h} alt={view.alt}
               loading={img.loading} loadError={img.error}
               shapes={view.shapes ?? []} opacity={45} mode="review" />
      )}
    </Body>
  );
}


/* ===========================================================
   PNG 오버레이 Viewer — 목업 시절 모양(study.slices)을 읽던 자리다.
   지금은 StudyView 가 대신한다. 아직 지우지 않은 것은 mock 화면
   (mock/hospital.json)이 이 모양을 쓰기 때문이다.
=========================================================== */

function PngOverlayViewer({ modality, study }) {
  /*
   * 서버가 준 것만 그린다.
   *
   * ⚠ slices 가 비면 예전엔 고정된 샘플 사진(/samples/…)을 대신
   *   띄웠다 — 판독 화면에서 그건 **남의 영상을 이 환자 것처럼
   *   보여주는 일**이라 없앴다(origin 쪽 수정, 2026-09-17). 화면만
   *   봐서는 진짜인지 샘플인지 구분할 수 없었다. 비면 아래
   *   「영상이 없습니다」가 뜬다 — 그게 맞는 상태다.
   */
  const slices = Array.isArray(study?.slices) ? study.slices.filter(Boolean) : [];

  const maskSlices = Array.isArray(study?.mask_slices) ? study.mask_slices.filter(Boolean)
    : Array.isArray(study?.maskSlices) ? study.maskSlices.filter(Boolean)
    : Array.isArray(study?.masks) ? study.masks.filter(Boolean) : [];

  const [sliceIndex, setSliceIndex] = useState(0);
  const [opacity, setOpacity] = useState(45);   /* Stage와 같은 0~100 스케일 */
  const [pick, setPick] = useState(null);
  const [full, setFull] = useState(false);

  useEffect(() => {
    setSliceIndex(0);
    setOpacity(45);
    setPick(null);
  }, [modality, study]);

  const src = slices[sliceIndex] ?? null;
  const maskSrc = maskSlices.length > 0 ? (maskSlices[sliceIndex] ?? null) : null;
  const hasMask = Boolean(maskSrc);

  /* Stage는 AI 좌표(shapes)를 원본 픽셀 크기(w·h) 기준으로 그리는데,
     이 화면은 shapes를 안 그린다(GenericImageViewer도 늘 그랬다) —
     그래도 Stage의 fit/zoom이 픽셀 크기를 요구하니 이미지 자연 크기를
     직접 재서 넘긴다. */
  const size = useImageSize(src);

  if (!src) {
    return (
      <div className="png-overlay-viewer">
        <div className="generic-empty">
          <div className="generic-empty-icon">◫</div>
          <div>표시할 {label(MODALITY, modality)} 영상이 없습니다.</div>
          <div className="generic-empty-sub">이 검사에 등록된 영상이 없습니다.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="png-overlay-viewer">
      <div className="png-overlay-stage">
        <div className="image-label">
          <span className="image-label-dot" />
          <span>{label(MODALITY, modality)}</span>
          {study?.device && <span> · {study.device}</span>}
        </div>

        <Stage
          src={src} w={size.w} h={size.h} alt={`${label(MODALITY, modality)} 검사 영상`}
          loading={!size.w && !size.error} loadError={size.error}
          mask={maskSrc} shapes={[]}
          opacity={opacity}
          pick={pick} onPick={setPick}
          full={full} onFull={() => setFull((v) => !v)}
          mode="review"
        />
      </div>

      <div className="viewer-control">
        <span className="control-label">마스크 투명도</span>
        <div className="opacity-wrap">
          <input
            type="range" min="0" max="100" step="5"
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            disabled={!hasMask}
          />
          <span className="opacity-value">{opacity}%</span>
        </div>

        {slices.length > 1 && (
          <div className="slice-wrap">
            <span className="control-label">Slice</span>
            <input
              type="range" min="0" max={slices.length - 1} step="1"
              value={sliceIndex}
              onChange={(e) => setSliceIndex(Number(e.target.value))}
            />
            <span className="slice-count">{sliceIndex + 1} / {slices.length}</span>
          </div>
        )}
      </div>
    </div>
  );
}

/* 서버가 픽셀 크기를 안 주므로(GenericImageViewer 시절부터 그랬다)
   화면에서 직접 잰다 — Stage가 fit()·SVG viewBox에 원본 크기를 쓴다.
   ⚠ onerror도 반드시 잡는다 — 안 잡으면 깨진 이미지 주소(샘플 이미지가
   아직 없는 모달리티 등)에서 size가 영원히 {0,0}으로 남아 Stage가
   "불러오는 중…"에 멈춰 버린다. */
function useImageSize(src) {
  const [state, setState] = useState({ w: 0, h: 0, error: null });
  useEffect(() => {
    if (!src) { setState({ w: 0, h: 0, error: null }); return; }
    setState({ w: 0, h: 0, error: null });
    let cancelled = false;
    const img = new Image();
    img.onload = () => { if (!cancelled) setState({ w: img.naturalWidth, h: img.naturalHeight, error: null }); };
    img.onerror = () => { if (!cancelled) setState({ w: 0, h: 0, error: { status: "불러오기 실패" } }); };
    img.src = src;
    return () => { cancelled = true; };
  }, [src]);
  return state;
}