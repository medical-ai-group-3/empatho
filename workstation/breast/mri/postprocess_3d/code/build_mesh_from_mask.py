#!/usr/bin/env python3
"""
3D 시각화 메시 생성 — 예측된 병변/유방 마스크를 Marching Cubes로 입체 도형(메시)으로 변환.

1단계 지표(부피·직경·개수·밀도)는 메시 없이 계산 가능했지만(compute_stage1_metrics.py),
화면에 입체로 "보여주는" 것은 표면(메시)이 있어야 한다. 이 스크립트가 그 마지막 단계.

파이프라인 전체 흐름:
    infer_mri.predict() → 3D 이진 마스크(오탐필터까지 끝난 것)
    → 이 스크립트 → STL(범용 3D포맷) + JSON(정점/삼각형, 프론트엔드가 바로 쓰기 쉬움)
    → Cornerstone3D가 읽어서 화면에 렌더링

사용법:
    python3 build_mesh_from_mask.py \
        --config ../../serving/configs/mri_lora.yaml \
        --weights ../../serving/ckpt/mri_lora_best.pt \
        --mama-mia-dir ... --duke-dir ... --coco-root ... \
        --pid ISPY2_242370 --class-name tumor \
        --out results/ISPY2_242370_tumor_mesh

설치 필요: pip install scikit-image --break-system-packages
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from eval_mri_lora_v3 import load_config, import_medsam3, build_model  # noqa: E402
from build_3d_from_predictions_v9 import (  # noqa: E402
    volume_to_rgb_slices, rgb_array_to_tensor, infer_slice_mask,
    filter_false_positives, filter_flat_artifacts, find_patient_volume,
    FLAT_FILTER_ELIGIBLE_CLASSES, MIN_ASPECT_RATIO, MIN_THIN_AXIS_MM,
)

try:
    from skimage import measure
except ImportError:
    sys.exit("scikit-image 필요: pip install scikit-image --break-system-packages")

import torch


def mask_to_mesh(mask_3d: np.ndarray, voxel_spacing=(1.0, 1.0, 1.0), smooth_iters: int = 0):
    """3D 이진 마스크 -> (정점, 삼각형면, 법선벡터). Marching Cubes.
    voxel_spacing: (Z,Y,X) 방향 복셀 크기(mm) - 1x1x1mm 리샘플링이므로 기본값 그대로 두면 됨.
    smooth_iters: 0이면 매끈화 안 함. 계단 무늬가 신경쓰이면 라플라시안 스무딩 반복 횟수(간단 구현)."""
    if mask_3d.sum() == 0:
        return None

    padded = np.pad(mask_3d, 1, mode="constant", constant_values=0)  # 경계에서 표면이 안 끊기게
    verts, faces, normals, _ = measure.marching_cubes(
        padded.astype(np.float32), level=0.5, spacing=voxel_spacing
    )
    verts -= np.array(voxel_spacing)  # 패딩 1칸만큼 좌표 보정

    if smooth_iters > 0:
        verts = _laplacian_smooth(verts, faces, iters=smooth_iters)

    return verts, faces, normals


def _laplacian_smooth(verts, faces, iters=1, lam=0.5):
    """아주 단순한 라플라시안 스무딩 - 계단 무늬를 부드럽게. 과하게 하면 형태가 뭉개지므로
    smooth_iters는 1~3 정도로만 쓸 것(1단계 지표에는 이미 스무딩 전 값을 썼으니 지표 재사용 금지)."""
    n = verts.shape[0]
    neighbors = [set() for _ in range(n)]
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            neighbors[a].add(b)
            neighbors[b].add(a)

    v = verts.copy()
    for _ in range(iters):
        new_v = v.copy()
        for i, nbrs in enumerate(neighbors):
            if nbrs:
                new_v[i] = v[i] + lam * (np.mean([v[j] for j in nbrs], axis=0) - v[i])
        v = new_v
    return v


def save_stl(path: Path, verts, faces):
    """의존성 없는 최소 바이너리 STL writer."""
    import struct
    with open(path, "wb") as f:
        f.write(b"\x00" * 80)  # 헤더
        f.write(struct.pack("<I", len(faces)))
        for tri in faces:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            n = np.cross(v1 - v0, v2 - v0)
            norm = np.linalg.norm(n)
            n = n / norm if norm > 0 else np.zeros(3)
            f.write(struct.pack("<3f", *n))
            for v in (v0, v1, v2):
                f.write(struct.pack("<3f", *v))
            f.write(struct.pack("<H", 0))


def save_web_json(path: Path, verts, faces, meta: dict):
    """Cornerstone3D/three.js가 바로 쓰기 쉬운 형태 - flat array."""
    data = {
        "positions": verts.flatten().round(3).tolist(),   # [x0,y0,z0,x1,y1,z1,...]
        "indices": faces.flatten().tolist(),                # [i0,i1,i2, i3,i4,i5, ...]
        "vertex_count": int(verts.shape[0]),
        "triangle_count": int(faces.shape[0]),
        "unit": "mm",
        **meta,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--mama-mia-dir", required=True, type=Path)
    ap.add_argument("--duke-dir", required=True, type=Path)
    ap.add_argument("--pid", required=True)
    ap.add_argument("--class-name", required=True, choices=["tumor", "breast", "dense tissue"])
    ap.add_argument("--score-threshold", type=float, default=0.7)
    ap.add_argument("--smooth-iters", type=int, default=1,
                     help="0=원본 계단무늬 그대로, 1~3=적당히 매끈, 그 이상은 형태 왜곡 위험")
    ap.add_argument("--skip-flat-filter", action="store_true",
                     help="디버깅용 - 시트형 오탐 필터를 끄고 원본 그대로 메시 생성")
    ap.add_argument("--force-flat-filter", action="store_true",
                     help="위험: breast/dense tissue처럼 원래 필터 대상이 아닌 클래스에도 "
                          "억지로 필터를 건다. 유방은 원래 납작한 구조라 정상 조직이 잘려나갈 "
                          "수 있음 - 육안 검증 없이 쓰지 말 것")
    ap.add_argument("--min-aspect-ratio", type=float, default=MIN_ASPECT_RATIO,
                     help="시트형 오탐 필터: bbox 최소축/최대축 비율 임계값")
    ap.add_argument("--min-thin-axis-mm", type=float, default=MIN_THIN_AXIS_MM,
                     help="시트형 오탐 필터: 이보다 얇은 축이 있으면 무조건 제거(mm)")
    ap.add_argument("--out", required=True, type=Path, help="확장자 없이 - .stl/.json 둘 다 붙여 저장")
    args = ap.parse_args()

    args.mama_mia_dir = args.mama_mia_dir.resolve()
    args.duke_dir = args.duke_dir.resolve()
    args.config = str(Path(args.config).resolve())
    args.weights = str(Path(args.weights).resolve())
    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    cfg = load_config(args.config)
    resolution = cfg["data"]["resolution"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, args.weights, M, device)

    img, dataset_tag = find_patient_volume(args.mama_mia_dir, args.duke_dir, args.pid)
    rgb_slices = volume_to_rgb_slices(img, dataset_tag)

    print(f"[{args.pid}] {args.class_name} 추론 중 (threshold={args.score_threshold})...")
    mask_slices = []
    with torch.no_grad():
        for rgb in rgb_slices:
            image_tensor, orig_size = rgb_array_to_tensor(rgb, resolution)
            mask_2d = infer_slice_mask(model, M, image_tensor, resolution, orig_size,
                                        args.class_name, device, args.score_threshold)
            mask_slices.append(mask_2d)
    mask_3d = np.stack(mask_slices, axis=0).astype(np.uint8)

    print("오탐 필터링 (복셀 수 + 슬라이스 연속성)...")
    min_contig = 1 if args.class_name != "tumor" else 2
    filtered = filter_false_positives(mask_3d, min_voxels=30, min_contiguous_slices=min_contig)

    eligible = args.class_name in FLAT_FILTER_ELIGIBLE_CLASSES
    if args.skip_flat_filter:
        pass
    elif eligible or args.force_flat_filter:
        if not eligible:
            print(f"  ⚠ '{args.class_name}'는 원래 시트형 필터 대상이 아님(--force-flat-filter로 "
                  f"강제 적용됨) - 결과 메시를 반드시 육안 확인할 것")
        print("오탐 필터링 (납작한 시트형 성분 추가 제거)...")
        filtered = filter_flat_artifacts(
            filtered,
            min_aspect_ratio=args.min_aspect_ratio,
            min_thin_axis_mm=args.min_thin_axis_mm,
        )
    else:
        print(f"  [납작형오탐필터] '{args.class_name}'는 대상 클래스가 아니라 건너뜀 "
              f"(대상: {sorted(FLAT_FILTER_ELIGIBLE_CLASSES)})")

    if filtered.sum() == 0:
        sys.exit(f"[{args.pid}] {args.class_name} 마스크가 비어있음 - 메시 생성 불가")

    print(f"메시 생성 중 (스무딩 {args.smooth_iters}회)...")
    verts, faces, normals = mask_to_mesh(filtered, smooth_iters=args.smooth_iters)
    print(f"  정점 {len(verts)}개, 삼각형 {len(faces)}개")

    stl_path = args.out.with_suffix(".stl")
    json_path = args.out.with_suffix(".json")
    save_stl(stl_path, verts, faces)
    flat_filter_applied = (not args.skip_flat_filter) and (eligible or args.force_flat_filter)
    save_web_json(json_path, verts, faces, meta={
        "patient_id": args.pid, "class_name": args.class_name,
        "score_threshold": args.score_threshold, "smooth_iters": args.smooth_iters,
        "flat_filter_applied": flat_filter_applied,
    })

    print(f"저장 완료:")
    print(f"  {stl_path}   (범용 3D 뷰어 확인용)")
    print(f"  {json_path}  (프론트엔드 렌더링용)")


if __name__ == "__main__":
    main()
