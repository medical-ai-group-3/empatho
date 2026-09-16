import { useEffect, useRef } from "react";

/* 축상/시상/관상 색 배정 — MPRViewer(cornerstone3D 쪽)와 통일해서
 * 같은 앱 안에서 "이 색 = 이 단면" 규칙이 흔들리지 않게 한다. */
const AXIS_COLOR = {
  axial: "rgb(255, 86, 86)",
  coronal: "rgb(90, 150, 255)",
  sagittal: "rgb(70, 210, 120)",
};

/* 단면(axis)별로 화면 가로/세로가 볼륨의 어느 축인지, 그리고 나머지
 * 한 축(고정되는 slice 축)이 무엇인지 정의한다. cursor{x,y,z}는 항상
 * 볼륨 복셀 좌표계 기준 — 세 패널이 이 좌표 하나를 공유해서 crosshair가
 * 어긋나지 않는다. */
const AXIS_DEF = {
  axial: { widthAxis: "x", heightAxis: "y", sliceAxis: "z" },
  coronal: { widthAxis: "x", heightAxis: "z", sliceAxis: "y" },
  sagittal: { widthAxis: "y", heightAxis: "z", sliceAxis: "x" },
};

/**
 * NIfTI volume의 한 단면(axis)을 그리고, 나머지 두 단면과 공유하는
 * cursor(볼륨 복셀 좌표)를 crosshair로 표시한다. 이미지를 클릭·드래그하면
 * 이 단면의 "가로/세로" 두 좌표만 바뀌고(자기 slice 축은 그대로) — 그
 * 결과가 부모의 공유 cursor를 통해 나머지 두 패널에도 즉시 반영된다.
 */
export default function NiftiSliceViewer({
  title,
  axis,
  volume,
  maskVolume = null,
  loading,
  maskLoading = false,
  error,
  maskError = "",
  cursor,
  showMask = true,
  maskOpacity = 0.45,
  selectedLesion = null,
  onCursorChange,
}) {
  const canvasRef = useRef(null);
  const dragRef = useRef(false);

  const def = AXIS_DEF[axis];
  const dims = volume?.dims;
  const sliceIndex = dims ? cursor[def.sliceAxis] : 0;
  const maxSlice = dims ? axisSize(dims, def.sliceAxis) - 1 : 0;

  useEffect(() => {
    if (!volume) return;
    drawSlice({ canvas: canvasRef.current, volume, maskVolume, axis, slice: sliceIndex, cursor, showMask, maskOpacity, selectedLesion });
  }, [volume, maskVolume, axis, sliceIndex, cursor, showMask, maskOpacity, selectedLesion]);

  function pickFromEvent(e) {
    const canvas = canvasRef.current;
    if (!canvas || !dims) return;
    const rect = canvas.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * canvas.width;
    const py = ((e.clientY - rect.top) / rect.height) * canvas.height;
    const w = axisSize(dims, def.widthAxis);
    const h = axisSize(dims, def.heightAxis);
    const wCoord = clamp(Math.round(px), 0, w - 1);
    const hCoord = clamp(Math.round(py), 0, h - 1);
    onCursorChange?.({ [def.widthAxis]: wCoord, [def.heightAxis]: hCoord });
  }

  function handlePointerDown(e) {
    dragRef.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    pickFromEvent(e);
  }
  function handlePointerMove(e) {
    if (!dragRef.current) return;
    pickFromEvent(e);
  }
  function handlePointerUp() {
    dragRef.current = false;
  }

  function changeSlice(value) {
    onCursorChange?.({ [def.sliceAxis]: Number(value) });
  }

  return (
    <div className="nifti-viewer">
      <div className="nifti-title">
        {title}
        <span className="nifti-axis-dot" style={{ background: AXIS_COLOR[axis] }} />
        {showMask && maskVolume && <span className="nifti-mask-badge">MASK</span>}
      </div>

      <div className="nifti-canvas-wrap">
        {loading && <div className="nifti-message">MRI 불러오는 중...</div>}
        {!loading && error && <div className="nifti-message nifti-error">{error}</div>}
        {!loading && !error && (
          <canvas
            ref={canvasRef}
            className="nifti-canvas"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
          />
        )}
        {maskLoading && <div className="nifti-mask-loading">AI MASK 불러오는 중...</div>}
      </div>

      <div className="nifti-slice-control">
        <span>Slice</span>
        <input
          type="range"
          min="0"
          max={maxSlice}
          step="1"
          value={Math.min(sliceIndex, maxSlice)}
          onChange={(e) => changeSlice(e.target.value)}
          disabled={loading || Boolean(error) || maxSlice === 0}
        />
        <span className="nifti-count">
          {sliceIndex + 1} / {maxSlice + 1}
        </span>
      </div>
    </div>
  );
}

function clamp(v, lo, hi) {
  return Math.min(Math.max(v, lo), hi);
}

function axisSize(dims, axisName) {
  const [nx, ny, nz] = dims;
  if (axisName === "x") return nx;
  if (axisName === "y") return ny;
  return nz;
}

function drawSlice({ canvas, volume, maskVolume, axis, slice, cursor, showMask, maskOpacity, selectedLesion }) {
  if (!canvas || !volume) return;

  const { dims, data } = volume;
  const [nx, ny, nz] = dims;

  let width;
  let height;

  if (axis === "axial") {
    width = nx;
    height = ny;
  } else if (axis === "coronal") {
    width = nx;
    height = nz;
  } else {
    width = ny;
    height = nz;
  }

  const values = new Float32Array(width * height);

  let p = 0;
  for (let j = 0; j < height; j++) {
    for (let i = 0; i < width; i++) {
      let index;

      if (axis === "axial") {
        const x = i, y = j, z = slice;
        index = x + nx * (y + ny * z);
      } else if (axis === "coronal") {
        const x = i, y = slice, z = j;
        index = x + nx * (y + ny * z);
      } else {
        const x = slice, y = i, z = j;
        index = x + nx * (y + ny * z);
      }

      values[p++] = Number(data[index]) || 0;
    }
  }

  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    min = 0;
    max = 1;
  }

  const sorted = Array.from(values).filter(Number.isFinite).sort((a, b) => a - b);
  const low = sorted[Math.floor(sorted.length * 0.01)] ?? min;
  const high = sorted[Math.floor(sorted.length * 0.99)] ?? max;
  const windowMin = low === high ? min : low;
  const windowMax = low === high ? max : high;

  canvas.width = width;
  canvas.height = height;

  const ctx = canvas.getContext("2d");
  const imageData = ctx.createImageData(width, height);

  for (let i = 0; i < values.length; i++) {
    const normalized = (values[i] - windowMin) / (windowMax - windowMin);
    const gray = Math.max(0, Math.min(255, Math.round(normalized * 255)));
    const dst = i * 4;
    imageData.data[dst] = gray;
    imageData.data[dst + 1] = gray;
    imageData.data[dst + 2] = gray;
    imageData.data[dst + 3] = 255;
  }

  ctx.putImageData(imageData, 0, 0);

  if (showMask && maskVolume?.data && sameDims(maskVolume.dims, dims)) {
    drawMaskOverlay(ctx, maskVolume, axis, slice, width, height, maskOpacity, selectedLesion);
  }

  // ── crosshair — 나머지 두 단면이 이 단면을 어디서 가로지르는지 표시 ──
  const def = AXIS_DEF[axis];
  const wCoord = cursor[def.widthAxis];
  const hCoord = cursor[def.heightAxis];
  const otherAxisForWidth = axisForCoord(def.widthAxis);
  const otherAxisForHeight = axisForCoord(def.heightAxis);

  ctx.save();
  ctx.lineWidth = 1;

  ctx.strokeStyle = AXIS_COLOR[otherAxisForWidth];
  ctx.beginPath();
  ctx.moveTo(wCoord + 0.5, 0);
  ctx.lineTo(wCoord + 0.5, height);
  ctx.stroke();

  ctx.strokeStyle = AXIS_COLOR[otherAxisForHeight];
  ctx.beginPath();
  ctx.moveTo(0, hCoord + 0.5);
  ctx.lineTo(width, hCoord + 0.5);
  ctx.stroke();

  ctx.restore();
}

/* 볼륨 축 이름(x/y/z)이 "고정되면" 어느 단면(axial/coronal/sagittal)이
 * 되는지 — crosshair 선 색을 "이 선이 대표하는 단면"에 맞추기 위한
 * 역방향 매핑이다(AXIS_DEF의 sliceAxis를 뒤집은 것). */
function voxelIndex(x, y, z, dims) {
  const [nx, ny] = dims;
  return x + nx * (y + ny * z);
}

function sameDims(a, b) {
  return Array.isArray(a) && Array.isArray(b) && a.length === 3 && b.length === 3 && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

function drawMaskOverlay(ctx, maskVolume, axis, slice, width, height, opacity, selectedLesion) {
  const dims = maskVolume.dims;
  const data = maskVolume.data;
  const rgba = new ImageData(width, height);
  const palette = ["#C9828C", "#8FA8C2", "#B59A6A", "#9B8FB5"];
  const selectedIndex = typeof selectedLesion === "number" ? selectedLesion : null;

  for (let j = 0; j < height; j++) {
    for (let i = 0; i < width; i++) {
      let x, y, z;
      if (axis === "axial") { x = i; y = j; z = slice; }
      else if (axis === "coronal") { x = i; y = slice; z = j; }
      else { x = slice; y = i; z = j; }

      const label = Number(data[voxelIndex(x, y, z, dims)]) || 0;
      if (label <= 0) continue;

      const colorIndex = label === 1 && selectedIndex !== null ? selectedIndex : Math.max(0, Math.round(label) - 1);
      const [r, g, b] = hexToRgb(palette[colorIndex % palette.length]);
      const dst = (j * width + i) * 4;
      rgba.data[dst] = r;
      rgba.data[dst + 1] = g;
      rgba.data[dst + 2] = b;
      rgba.data[dst + 3] = Math.round(255 * clamp(opacity, 0, 1));
    }
  }

  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = width;
  maskCanvas.height = height;
  maskCanvas.getContext("2d").putImageData(rgba, 0, 0);
  ctx.drawImage(maskCanvas, 0, 0);
}

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)];
}

function axisForCoord(coordAxis) {
  if (coordAxis === "z") return "axial";
  if (coordAxis === "y") return "coronal";
  return "sagittal";
}
