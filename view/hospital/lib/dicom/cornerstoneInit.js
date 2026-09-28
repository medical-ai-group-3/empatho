import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import dicomImageLoader from "@cornerstonejs/dicom-image-loader";

/* DicomMprPanel이 쓰는 cornerstone3D 초기화. 등록 로직을 한 곳에 모아 둬야
 * 나중에 손볼 자리가 하나가 된다(init()은 멱등이라 여러 번 불러도 안전).
 *
 * 유방외과·영상의학과 둘 다 이 파일을 쓴다 — 과 하나에 묶인 초기화가
 * 아니라서 hospital/lib/ 로 옮겨 왔다(원래 dept/breast/components/에
 * 있었다). */
let initPromise = null;

/* ⚠ VOI LUT 함수 바로잡기 (09-28)
 *   dicom-image-loader 5.x 의 createImage 가 VOILUTFunction(0028,1056)을
 *   배열로 여기고 [0] 을 꺼낸다. 그런데 wadouri 메타데이터는 문자열이라
 *   "SIGMOID" 가 "S" 가 된다. StackViewport 는 「Invalid VOI LUT function」을
 *   던지고 그 장을 안 그린다 — 오류는 IMAGE_LOAD_ERROR 이벤트로만 나가
 *   화면에는 아무 표시가 없다. 맘모 장비(GE · Hologic)는 SIGMOID 를 흔히
 *   적는다(CMMD 샘플도 그렇다). 그래서 맘모 네 장 중 **첫 장만 뜨고 ‹ › ·
 *   휠로 넘겨도 「뷰 1 / 4」에서 안 움직였다.**
 *   불러온 직후(IMAGE_LOADED — 뷰포트가 쓰기 전에 먼저 불린다) 원래 값으로
 *   되돌린다. 모르는 값이면 LINEAR. 캐시에 든 image 를 고치므로 한 번이면 된다 */
function fixVoiLutFunction(evt) {
  const image = evt?.detail?.image;
  const T = cornerstone.Enums.VOILUTFunctionType;
  const valid = Object.values(T);
  if (!image || image.voiLUTFunction == null || valid.includes(image.voiLUTFunction)) return;
  let v = null;
  try { v = cornerstone.metaData.get("voiLutModule", image.imageId)?.voiLUTFunction; }
  catch { /* 메타데이터가 없으면 LINEAR */ }
  v = String((Array.isArray(v) ? v[0] : v) ?? "").trim().toUpperCase();
  image.voiLUTFunction = valid.includes(v) ? v : T.LINEAR;
}

export function ensureCornerstoneInit() {
  if (!initPromise) {
    initPromise = (async () => {
      await cornerstone.init();
      dicomImageLoader.init();
      cornerstoneTools.init();
      cornerstone.eventTarget.addEventListener(cornerstone.Enums.Events.IMAGE_LOADED, fixVoiLutFunction);
      cornerstone.volumeLoader.registerVolumeLoader(
        "cornerstoneStreamingImageVolume",
        cornerstone.cornerstoneStreamingImageVolumeLoader
      );
      cornerstoneTools.addTool(cornerstoneTools.TrackballRotateTool);
      cornerstoneTools.addTool(cornerstoneTools.StackScrollTool);
      cornerstoneTools.addTool(cornerstoneTools.CrosshairsTool);

      /* 맘모(DicomStackViewer)가 쓰는 2D 탐색 도구 — MRI MPR 쪽은
       * Crosshairs로 세 단면을 같이 움직이니 따로 안 썼지만, 맘모는
       * 단면이 하나뿐이라 창값·이동·확대가 곧 "탐색"이다. */
      cornerstoneTools.addTool(cornerstoneTools.PanTool);
      cornerstoneTools.addTool(cornerstoneTools.ZoomTool);
      cornerstoneTools.addTool(cornerstoneTools.WindowLevelTool);

      /* 판독 도구 — 영상의학과가 직접 재는·그리는 것들.
           길이 측정   LengthTool. DICOM에 pixel spacing이 있어 실제 mm로 나온다
           사각형 ROI  RectangleROITool. 바운딩박스 + 안쪽 평균/표준편차
           마스크      BrushTool. 실제 세그멘테이션(라벨맵)에 칠한다 —
                       윤곽선만 그리는 것과 달리 픽셀 단위로 남는다 */
      cornerstoneTools.addTool(cornerstoneTools.LengthTool);
      cornerstoneTools.addTool(cornerstoneTools.RectangleROITool);
      cornerstoneTools.addTool(cornerstoneTools.BrushTool);
    })();
  }
  return initPromise;
}
