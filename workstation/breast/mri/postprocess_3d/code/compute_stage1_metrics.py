#!/usr/bin/env python3
"""
3D 후처리 1단계 지표 계산 - 부피 / 최대직경 / 병변개수 / 위치 / 밀도비율

지금은 우리가 이미 가진 "정답(GT) 3D 라벨"로 로직을 검증한다.
나중에 모델 예측 마스크로 입력만 바꿔 끼우면 그대로 재사용 가능
(입력 형식: (Z,Y,X) 또는 (2,Z,Y,X) numpy 배열, 학습 전처리 때 이미 1x1x1mm로
 리샘플링해뒀으므로 복셀 1개 = 1mm^3).

계단 경계에 "둔감"한 지표만 다룬다(1단계) - Marching Cubes/메시 불필요.
형태지표(구형도 등, 2단계)는 여기서 다루지 않는다.

사용법:
    python compute_stage1_metrics.py \
        --mama-mia-labels data/mri/mama_mia_processed/labels \
        --duke-labels data/mri/duke_density_processed/labels \
        --ambl-labels data/mri/ambl_processed/labels \
        --out stage1_metrics.csv
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.spatial import ConvexHull

VOXEL_MM3 = 1.0
MIN_VOXELS = 20  # 1차 필터: 순수 노이즈(1~10복셀대) 제거용
MAX_LESIONS_PER_PATIENT = 10  # 2차 필터: 20복셀 기준을 통과해도 남는 파편들이
                               # 환자당 수십~100개씩 나오는 문제 확인됨(최솟값이 항상
                               # MIN_VOXELS 경계에 몰려있어 파편 확정). 임상적으로 유방암은
                               # 다발성이어도 보통 5개 이내라, 부피 큰 순으로 최대 10개만 인정.


def find_instances(mask_3d, max_lesions=MAX_LESIONS_PER_PATIENT, return_stats=False):
    """[2026-09-29] max_lesions / return_stats 인자 추가 — 기본값이면 기존과 동일.
    return_stats=True면 (instances, {"dropped_below_min_voxels": a, "dropped_over_cap": b})를
    반환한다. 상한에 잘린 병변이 있었는지 서빙 응답(truncated)에 알려주기 위해.
    (서빙은 앞단 filter_false_positives가 30복셀로 먼저 거르므로 dropped_below_min_voxels는
    min_voxels를 20 미만으로 낮춘 경우에만 0이 아니다.)"""
    if mask_3d.sum() == 0:
        return ([], {"dropped_below_min_voxels": 0, "dropped_over_cap": 0}) if return_stats else []
    structure = np.ones((3, 3, 3), dtype=int)
    labeled, n = ndimage.label(mask_3d.astype(np.uint8), structure=structure)
    instances = []
    dropped_below_min = 0
    for lbl in range(1, n + 1):
        coords = np.argwhere(labeled == lbl)
        if coords.shape[0] < MIN_VOXELS:
            dropped_below_min += 1
            continue
        instances.append(coords)

    # 2차 필터: MIN_VOXELS 통과해도 남는 파편이 많으면(환자당 수십개) 부피 큰 순으로 상한만 남김
    dropped_over_cap = 0
    if len(instances) > max_lesions:
        dropped_over_cap = len(instances) - max_lesions
        instances = sorted(instances, key=lambda c: c.shape[0], reverse=True)[:max_lesions]

    if return_stats:
        return instances, {"dropped_below_min_voxels": dropped_below_min, "dropped_over_cap": dropped_over_cap}
    return instances


def max_diameter_mm(coords):
    if coords.shape[0] < 2:
        return 0.0
    if coords.shape[0] <= 4:
        pts = coords.astype(float)
    else:
        try:
            hull = ConvexHull(coords)
            pts = coords[hull.vertices].astype(float)
        except Exception:
            pts = coords.astype(float)

    diffs = pts[:, None, :] - pts[None, :, :]
    dists = np.sqrt((diffs ** 2).sum(axis=-1))
    return float(dists.max())


def find_breast_nipple_proxy(breast_mask: np.ndarray):
    """[근사치, 검증 필요] 유방 마스크에서 유두 위치를 근사한다.
    전처리 때 DICOMOrient(LPS)를 적용했으므로 배열 축 순서는 (Z,Y,X) = (Superior축, Posterior축, Left축).
    즉 Y가 작을수록(=덜 후방=더 전방) 유두에 가깝다고 가정 - anterior-most 지점을 유두로 근사.
    좌/우 유방이 한 볼륨에 같이 있는(양측) 경우를 대비해, X축 중앙을 기준으로 좌/우를 나눠
    각 절반에서 따로 유두 후보를 찾는다.
    ⚠ 이 방향 가정은 추론이며 실측 검증(3D Slicer로 눈으로 확인)이 필요하다.

    ⚠ [한계] 이 함수는 학습된 breast 모델의 예측 마스크를 입력으로 받는다.
    MAMA-MIA 소스에서는 이 모델이 불안정(22조각으로 쪼개짐)함이 확인됨 - Duke 소스
    (원래 breast 학습 도메인)에서만 상대적으로 신뢰 가능. MAMA-MIA에는
    find_body_silhouette_proxy()(명암 기반, 모델 불필요) 사용을 권장."""
    coords = np.argwhere(breast_mask)
    if coords.shape[0] == 0:
        return None

    x_mid = (coords[:, 2].min() + coords[:, 2].max()) / 2
    # [최종 확정] 검증 결과: 배열 x가 클수록 왼쪽(Left) - x=73.8일 때 R=77.35(오른쪽),
    # x=120.0일 때 R=31.15(더 왼쪽 방향). 즉 x 작음=오른쪽, x 큼=왼쪽.
    sides = {"right_half": coords[coords[:, 2] < x_mid], "left_half": coords[coords[:, 2] >= x_mid]}

    nipples = {}
    for side, pts in sides.items():
        if pts.shape[0] == 0:
            continue
        min_y = pts[:, 1].min()
        anterior_pts = pts[pts[:, 1] <= min_y + 2]  # 제일 전방인 지점 부근(±2복셀) 평균
        nipples[side] = anterior_pts.mean(axis=0)  # (z,y,x)
    return nipples


def find_body_silhouette_mask(pre_contrast_volume: np.ndarray, min_component_voxels: int = 5000):
    """[신규] 학습된 breast 모델에 의존하지 않는 대체 방법.
    MAMA-MIA에서 breast 모델이 불안정(22조각)했던 문제를 근본적으로 피하기 위해,
    AI 예측 대신 순수 명암 기반(threshold)으로 몸통 윤곽을 잡는다.
    소스(MAMA-MIA/Duke/AMBL)에 관계없이 항상 동일하게 작동 - 모델 성능과 무관.
    반환된 마스크는 기존 summarize_lesions(breast_mask=...)에 그대로 넣으면 됨
    (내부에서 find_breast_nipple_proxy가 알아서 유두 근사를 계산함).

    pre_contrast_volume: (Z,Y,X) z-score 정규화된 조영전 볼륨 (img[0] 형태로 넘기면 됨)
    한계: "유방"이 아니라 "몸통 전체" 윤곽이라 팔·목 등이 섞일 수 있어 breast 모델보다
          정밀도는 다소 떨어짐. 대신 항상 작동한다는 게 핵심 장점.
    """
    body_mask = pre_contrast_volume > 0  # z-score 정규화 기준 평균(0) 초과 = 몸(밝은 부분)
    structure = np.ones((3, 3, 3), dtype=int)
    labeled, n = ndimage.label(body_mask, structure=structure)
    if n == 0:
        return None
    sizes = ndimage.sum(body_mask, labeled, range(1, n + 1))
    largest_label = np.argmax(sizes) + 1
    if sizes[largest_label - 1] < min_component_voxels:
        return None
    return labeled == largest_label


def classify_quadrant(lesion_centroid, nipple_point, side: str):
    """유두 기준 상/하 · 내/외측 4분면. side는 lesion_centroid의 x가 nipple보다
    작은지 큰지로 이미 정해진 반쪽(left_half/right_half)을 그대로 물려받는다.
    내측(medial)/외측(lateral) 판정은 실제 좌/우 유방 여부를 모르므로 근사치다."""
    dz = lesion_centroid[0] - nipple_point[0]  # +면 아래(inferior), -면 위(superior)
    dx = lesion_centroid[2] - nipple_point[2]

    # [최종 확정] NIfTI 배열좌표->RAS 직접 변환으로 검증 완료 (2026-08-31).
    # z=69.6일 때 S=-8.47, z=100.0일 때 S=21.93 -> z가 클수록 S(위쪽)도 커짐.
    # 즉 "배열 z가 클수록 위(superior)" - 기존 가정(z 클수록 아래)이 반대였음.
    vertical = "상부(superior)" if dz > 0 else "하부(inferior)"
    # side 이름 규칙 변경(2026-08-31 검증)에 맞춰 조건도 반전:
    # left_half(실제 왼쪽)=array x 큼 -> 외측은 dx>0(더 왼쪽으로), right_half(실제 오른쪽)=array x 작음 -> 외측은 dx<0(더 오른쪽으로)
    horizontal = "외측(lateral)" if (side == "left_half" and dx > 0) or (side == "right_half" and dx < 0) else "내측(medial)"
    return f"{vertical}-{horizontal}"


def extract_duke_numeric_id(filename: str):
    """DUKE_043 / duke_043 / Breast_MRI_043 -> 43 (숫자만 추출해서 서로 매칭)."""
    import re
    m = re.search(r"(\d+)", filename)
    return int(m.group(1)) if m else None


def summarize_lesions(mask_3d, patient_id, class_name, breast_mask=None,
                      max_lesions=MAX_LESIONS_PER_PATIENT, return_stats=False):
    """[2026-09-29] max_lesions / return_stats 인자 추가 — 기본값이면 기존과 동일(rows, n).
    return_stats=True면 (rows, n, find_instances의 stats)를 반환한다."""
    instances, cap_stats = find_instances(mask_3d, max_lesions=max_lesions, return_stats=True)
    nipples = find_breast_nipple_proxy(breast_mask) if breast_mask is not None else None

    rows = []
    for i, coords in enumerate(instances):
        volume_mm3 = coords.shape[0] * VOXEL_MM3
        volume_cm3 = volume_mm3 / 1000.0
        diameter = max_diameter_mm(coords)
        centroid = coords.mean(axis=0)

        row = {
            "patient_id": patient_id,
            "class": class_name,
            "lesion_index": i,
            "volume_cm3": round(volume_cm3, 3),
            "max_diameter_mm": round(diameter, 1),
            "centroid_z": round(float(centroid[0]), 1),
            "centroid_y": round(float(centroid[1]), 1),
            "centroid_x": round(float(centroid[2]), 1),
            "nipple_distance_mm": None,
            "quadrant": None,
        }

        if nipples:
            # 병변 중심이 어느 절반(좌/우)에 속하는지로 어느 유두를 기준삼을지 결정
            # x 작음=오른쪽, x 큼=왼쪽 (위와 동일 규칙)
            side = "right_half" if centroid[2] < np.mean([p[2] for p in nipples.values()]) else "left_half"
            if side in nipples:
                nipple = nipples[side]
                dist = float(np.sqrt(((centroid - nipple) ** 2).sum()))
                row["nipple_distance_mm"] = round(dist, 1)
                row["quadrant"] = classify_quadrant(centroid, nipple, side)

        rows.append(row)
    if return_stats:
        return rows, len(instances), cap_stats
    return rows, len(instances)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mama-mia-labels", default=None)
    ap.add_argument("--duke-labels", default=None)
    ap.add_argument("--ambl-labels", default=None)
    ap.add_argument("--out", default="stage1_metrics.csv")
    args = ap.parse_args()

    lesion_rows = []
    summary_rows = []

    # Duke 밀도용 breast 마스크를 환자번호 기준으로 미리 인덱싱
    # (MAMA-MIA의 Duke 서브셋과 환자번호가 같으면 여기서 유방윤곽을 빌려옴 - 위치 근사용)
    duke_breast_by_numid = {}
    if args.duke_labels:
        for fp in sorted(Path(args.duke_labels).glob("*.npy")):
            numid = extract_duke_numeric_id(fp.stem)
            if numid is not None:
                duke_breast_by_numid[numid] = fp

    if args.mama_mia_labels:
        print("[처리 중] MAMA-MIA tumor ...")
        matched_n = 0
        for fp in sorted(Path(args.mama_mia_labels).glob("*.npy")):
            pid = fp.stem
            lbl = np.load(fp)

            breast_mask = None
            numid = extract_duke_numeric_id(pid)
            if numid is not None and numid in duke_breast_by_numid:
                duke_lbl = np.load(duke_breast_by_numid[numid])  # (2,Z,Y,X)
                if duke_lbl.ndim == 4 and duke_lbl.shape[1:] == lbl.shape:
                    breast_mask = duke_lbl[0] == 1
                    matched_n += 1
                # shape 다르면(리샘플링 결과가 서로 다를 수 있음) 매칭 포기 - None 유지

            rows, n = summarize_lesions(lbl == 1, pid, "tumor", breast_mask=breast_mask)
            lesion_rows.extend(rows)
            summary_rows.append({"patient_id": pid, "class": "tumor", "lesion_count": n})
        print(f"  위치(유두거리/사분면) 계산 가능 환자: {matched_n}명 (Duke 유방윤곽과 매칭된 경우만)")

    if args.ambl_labels:
        print("[처리 중] AMBL benign/malignant lesion ...")
        for fp in sorted(Path(args.ambl_labels).glob("*.npy")):
            pid = fp.stem
            lbl = np.load(fp)
            for cname, val in (("benign lesion", 1), ("malignant lesion", 2)):
                rows, n = summarize_lesions(lbl == val, pid, cname)
                lesion_rows.extend(rows)
                summary_rows.append({"patient_id": pid, "class": cname, "lesion_count": n})

    density_rows = []
    if args.duke_labels:
        print("[처리 중] Duke 밀도비율 ...")
        for fp in sorted(Path(args.duke_labels).glob("*.npy")):
            pid = fp.stem
            lbl = np.load(fp)
            if lbl.ndim != 4 or lbl.shape[0] < 2:
                continue
            breast_vox = int((lbl[0] == 1).sum())
            dense_vox = int((lbl[1] == 2).sum())
            vessels_vox = int((lbl[1] == 1).sum())
            if breast_vox == 0:
                continue
            density_pure = dense_vox / breast_vox * 100
            density_with_vessels = (dense_vox + vessels_vox) / breast_vox * 100
            density_rows.append({
                "patient_id": pid,
                "breast_volume_cm3": round(breast_vox * VOXEL_MM3 / 1000.0, 1),
                "dense_density_pct": round(density_pure, 2),
                "dense_plus_vessels_density_pct": round(density_with_vessels, 2),
            })

    out_root = Path(args.out).parent
    out_root.mkdir(parents=True, exist_ok=True)
    base = Path(args.out).stem

    if lesion_rows:
        df_lesions = pd.DataFrame(lesion_rows)
        df_lesions.to_csv(out_root / f"{base}_lesions.csv", index=False)
        print(f"\n병변별 상세(부피/최대직경/위치): {out_root / (base + '_lesions.csv')} ({len(df_lesions)}행)")

    if summary_rows:
        df_summary = pd.DataFrame(summary_rows)
        df_summary.to_csv(out_root / f"{base}_lesion_counts.csv", index=False)
        print(f"환자별 병변개수: {out_root / (base + '_lesion_counts.csv')} ({len(df_summary)}행)")

        print("\n클래스별 병변개수 분포:")
        for cname, grp in df_summary.groupby("class"):
            vals = grp["lesion_count"]
            print(f"  {cname:20s} 환자수={len(vals)}  "
                  f"평균 {vals.mean():.2f}개  중앙값 {vals.median():.0f}개  "
                  f"최대 {vals.max()}개  0개(병변없음) {int((vals==0).sum())}명")

    if density_rows:
        df_density = pd.DataFrame(density_rows)
        df_density.to_csv(out_root / (base + "_density.csv"), index=False)
        print(f"\n환자별 밀도비율: {out_root / (base + '_density.csv')} ({len(df_density)}행)")
        print(f"  dense_density_pct 평균 {df_density['dense_density_pct'].mean():.2f}%  "
              f"중앙값 {df_density['dense_density_pct'].median():.2f}%")

    if lesion_rows:
        print("\n부피/최대직경 분포 (클래스별):")
        for cname, grp in pd.DataFrame(lesion_rows).groupby("class"):
            print(f"  {cname:20s} 부피(cm3) 중앙값 {grp['volume_cm3'].median():.2f}  "
                  f"최대직경(mm) 중앙값 {grp['max_diameter_mm'].median():.1f}")


if __name__ == "__main__":
    main()