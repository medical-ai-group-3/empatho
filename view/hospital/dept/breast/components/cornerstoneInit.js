import * as cornerstone from "@cornerstonejs/core";
import * as cornerstoneTools from "@cornerstonejs/tools";
import dicomImageLoader from "@cornerstonejs/dicom-image-loader";

/* MPRViewer가 쓰는 cornerstone3D 초기화. 등록 로직을 한 곳에 모아 둬야
 * 나중에 손볼 자리가 하나가 된다(init()은 멱등이라 여러 번 불러도 안전). */
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
    })();
  }
  return initPromise;
}
