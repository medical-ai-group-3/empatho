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
export function ensureCornerstoneInit() {
  if (!initPromise) {
    initPromise = (async () => {
      await cornerstone.init();
      dicomImageLoader.init();
      cornerstoneTools.init();
      cornerstone.volumeLoader.registerVolumeLoader(
        "cornerstoneStreamingImageVolume",
        cornerstone.cornerstoneStreamingImageVolumeLoader
      );
      cornerstoneTools.addTool(cornerstoneTools.TrackballRotateTool);
      cornerstoneTools.addTool(cornerstoneTools.StackScrollTool);
      cornerstoneTools.addTool(cornerstoneTools.CrosshairsTool);

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
