#!/usr/bin/env python3
"""
병변이 Z축(슬라이스 방향)으로 몇 mm 두께로 나타나는지 분포를 확인한다.
전처리 시 1x1x1mm로 리샘플링했으므로, "슬라이스 개수 = mm 두께"로 바로 환산 가능.

목적: 인접 슬라이스 간격 샘플링(2~3mm씩 건너뛰기)을 적용해도 되는지 판단.
      두께가 얇은 병변이 많으면(예: 2mm 미만이 흔하면) 간격 샘플링 시
      그 병변이 통째로 슬라이스에서 빠질 위험이 있음.

대상:
  - tumor            : MAMA-MIA labels (Z,Y,X), 값==1
  - dense tissue      : Duke labels (2,Z,Y,X) 중 채널1==2
  - benign lesion     : AMBL labels (Z,Y,X), 값==1
  - malignant lesion  : AMBL labels (Z,Y,X), 값==2

사용법:
    python check_lesion_thickness.py \
        --mama-mia-labels data/mri/mama_mia_processed/labels \
        --duke-labels data/mri/duke_density_processed/labels \
        --ambl-labels data/mri/ambl_processed/labels
"""

import argparse
from pathlib import Path

import numpy as np
from scipy import ndimage


def instance_thicknesses(mask_3d: np.ndarray) -> list:
    """3D 이진 마스크 -> 연결된 병변(instance)마다 Z축 두께(슬라이스 수) 리스트.
    26-connectivity(대각선 포함)로 라벨링 - 노이즈로 인한 인위적 분절 완화."""
    if mask_3d.sum() == 0:
        return []
    structure = np.ones((3, 3, 3), dtype=int)
    labeled, n = ndimage.label(mask_3d.astype(np.uint8), structure=structure)
    thicknesses = []
    for lbl in range(1, n + 1):
        zs = np.where(labeled == lbl)[0]  # axis 0 = Z
        if zs.size == 0:
            continue
        thickness = int(zs.max() - zs.min() + 1)
        voxel_count = int((labeled == lbl).sum())
        if voxel_count < 5:  # 노이즈 파편 제외 (5복셀 미만)
            continue
        thicknesses.append(thickness)
    return thicknesses


def summarize(name: str, thicknesses: list):
    print(f"\n{'=' * 60}")
    print(f"{name}  (병변 인스턴스 {len(thicknesses)}개)")
    print("=" * 60)
    if not thicknesses:
        print("  데이터 없음")
        return
    arr = np.array(thicknesses)
    print(f"  min={arr.min()}mm  p10={np.percentile(arr,10):.1f}mm  "
          f"median={np.median(arr):.1f}mm  mean={arr.mean():.1f}mm  "
          f"p90={np.percentile(arr,90):.1f}mm  max={arr.max()}mm")
    print()
    print("  간격 샘플링 위험도 (이 두께 미만이면 해당 간격에서 병변이 통째로 빠질 수 있음)")
    for th in (2, 3, 4, 5):
        cnt = int((arr < th).sum())
        pct = cnt / len(arr) * 100
        print(f"    두께 < {th}mm : {cnt}/{len(arr)}개  ({pct:.1f}%)")
    print()
    print("  두께 히스토그램 (1mm 단위, 최대 15mm까지)")
    for th in range(1, 16):
        cnt = int((arr == th).sum())
        bar = "#" * min(cnt, 50)
        print(f"    {th:2d}mm: {cnt:4d} {bar}")
    over15 = int((arr > 15).sum())
    if over15:
        print(f"    >15mm: {over15}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mama-mia-labels", default=None)
    ap.add_argument("--duke-labels", default=None)
    ap.add_argument("--ambl-labels", default=None)
    args = ap.parse_args()

    if args.mama_mia_labels:
        print("\n[처리 중] MAMA-MIA tumor ...")
        all_th = []
        for fp in sorted(Path(args.mama_mia_labels).glob("*.npy")):
            lbl = np.load(fp)  # (Z,Y,X)
            mask = (lbl == 1)
            all_th.extend(instance_thicknesses(mask))
        summarize("tumor (MAMA-MIA)", all_th)

    if args.duke_labels:
        print("\n[처리 중] Duke dense tissue ...")
        all_th = []
        for fp in sorted(Path(args.duke_labels).glob("*.npy")):
            lbl = np.load(fp)  # (2,Z,Y,X)
            if lbl.ndim != 4 or lbl.shape[0] < 2:
                continue
            mask = (lbl[1] == 2)  # dense tissue
            all_th.extend(instance_thicknesses(mask))
        summarize("dense tissue (Duke)", all_th)

    if args.ambl_labels:
        print("\n[처리 중] AMBL benign/malignant lesion ...")
        benign_th, malignant_th = [], []
        for fp in sorted(Path(args.ambl_labels).glob("*.npy")):
            lbl = np.load(fp)  # (Z,Y,X)
            benign_th.extend(instance_thicknesses(lbl == 1))
            malignant_th.extend(instance_thicknesses(lbl == 2))
        summarize("benign lesion (AMBL)", benign_th)
        summarize("malignant lesion (AMBL)", malignant_th)

    print("\n" + "=" * 60)
    print("결론 가이드")
    print("=" * 60)
    print("  '두께 < 3mm' 비율이 높은 클래스가 있으면, 그 클래스는")
    print("  2~3mm 간격 샘플링 시 병변이 슬라이스에서 완전히 누락될 위험이 큽니다.")
    print("  특히 benign/malignant lesion은 이미 정량 성능이 낮으므로,")
    print("  여기서 위험도가 높게 나오면 간격 샘플링은 이번 2차 학습에서 보류하는 게 안전합니다.")


if __name__ == "__main__":
    main()
