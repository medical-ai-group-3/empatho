import { useEffect, useState } from "react";
import * as nifti from "nifti-reader-js";

/*
 * NIfTI 볼륨을 한 번만 불러와서 axial/coronal/sagittal 세 뷰가 같이
 * 쓴다 — 뷰마다 따로 fetch/parse하면 64MB 파일을 3번 읽게 된다.
 * crosshair 동기화도 세 뷰가 같은 볼륨 배열을 봐야 좌표 계산이 어긋나지 않는다.
 */
export function useNiftiVolume(url) {
  const [state, setState] = useState({
    volume: null,
    loading: true,
    error: "",
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setState({
        volume: null,
        loading: true,
        error: "",
      });

      try {
        const response = await fetch(url);

        if (!response.ok) {
          throw new Error(
            `NIfTI 파일을 불러오지 못했습니다. HTTP ${response.status}`
          );
        }

        const buffer = await response.arrayBuffer();

        let data = buffer;

        if (nifti.isCompressed(data)) {
          data = nifti.decompress(data);
        }

        if (!nifti.isNIFTI(data)) {
          throw new Error("유효한 NIfTI 파일이 아닙니다.");
        }

        const header = nifti.readHeader(data);
        const image = nifti.readImage(header, data);

        const dims = [
          Number(header.dims[1]),
          Number(header.dims[2]),
          Number(header.dims[3]),
        ];

        const typed = makeTypedArray(
          header.datatypeCode,
          image
        );

        if (!cancelled) {
          setState({
            volume: {
              header,
              dims,
              data: typed,
            },
            loading: false,
            error: "",
          });
        }
      } catch (err) {
        console.error("NIfTI load error:", err);

        if (!cancelled) {
          setState({
            volume: null,
            loading: false,
            error:
              err?.message ||
              "MRI NIfTI를 불러오는 중 오류가 발생했습니다.",
          });
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [url]);

  return state;
}

function makeTypedArray(datatypeCode, image) {
  switch (datatypeCode) {
    case 2:
      return new Uint8Array(image);

    case 4:
      return new Int16Array(image);

    case 8:
      return new Int32Array(image);

    case 16:
      return new Float32Array(image);

    case 64:
      return new Float64Array(image);

    case 256:
      return new Int8Array(image);

    case 512:
      return new Uint16Array(image);

    case 768:
      return new Uint32Array(image);

    default:
      throw new Error(
        `지원하지 않는 NIfTI datatype code: ${datatypeCode}`
      );
  }
}