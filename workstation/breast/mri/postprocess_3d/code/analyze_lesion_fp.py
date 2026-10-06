#!/usr/bin/env python3
"""
dump_raw_predictions.py가 저장한 npz로 병변 단위 오탐 분석 (CPU만 사용).

2026-09-29 신규 — MRI 병변 오탐 검토 3단계.

1) 임계값 스윕 (3D, 병변 단위) — 서빙 후처리(크기·연속성·시트형·상한) 그대로 적용 후
   환자당 순수 오탐 / 조각 / 병변 민감도 / Dice. 기존 기록(2D 슬라이스 0.5·0.8 두 점)을 대체.
2) 필터 비교 (서빙 임계값) — 필터 없음 / 크기·연속성만 / +시트형(서빙) / 시트형 기준 격자.
   시트형 필터가 지운 "정답과 겹치는" 성분(DUKE_399류)은 치수까지 따로 기록.
3) 오탐 위치 (서빙 설정) — 순수 오탐 성분마다 정답 z범위에서 몇 슬라이스 떨어졌는지,
   breast 마스크·몸통 윤곽 안 비율. "종양 없는 슬라이스에서 헛짚는다"는 가설(학습 데이터에
   종양 없는 슬라이스가 거의 없음 — build_coco_from_npy.py:109)을 직접 확인하는 용도.

매칭 규칙: 예측 성분이 정답 복셀과 1개라도 겹치면 그 정답 병변에 매칭(느슨한 기준).
  - 정답과 안 겹치는 예측 성분 = 순수 오탐(pure_fp)
  - 한 정답에 예측 성분이 2개 이상 매칭 = 초과분이 조각(fragment)
  - 정답 성분은 26-연결, GT_MIN_VOXELS 이상만(라벨 잡티 제외), 개수 상한 없음

사용법:
    python3 analyze_lesion_fp.py                       # results/raw_predictions/*.npz
    python3 analyze_lesion_fp.py --in DIR --out DIR
"""

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_3d_from_predictions_v9 import filter_false_positives, filter_flat_artifacts  # noqa: E402
from compute_stage1_metrics import find_instances  # noqa: E402

STRUCT = np.ones((3, 3, 3), dtype=int)  # 26-connectivity, 서빙과 동일
GT_MIN_VOXELS = 20                       # compute_stage1_metrics.MIN_VOXELS와 동일
SWEEP = [round(0.30 + 0.05 * i, 2) for i in range(11)]   # 0.30 ~ 0.80
ROI_DILATE_MM = [0, 5, 10]
ROI_MIN_FRAC = [0.1, 0.3]
FLAT_GRID = [(2.0, 0.2), (3.0, 0.2), (3.0, 0.3), (4.0, 0.3), (5.0, 0.3), (4.0, 0.4)]


def quiet(fn, *a, **k):
    """필터 함수들의 진행 print 억제 (환자×설정 수백 번 호출됨)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def postprocess(mask, P, stage="serving"):
    """서빙 predict()의 후처리를 재현. stage로 어디까지 적용할지 고른다.
    반환: 최종 성분 라벨 배열, 성분 수, 시트형 필터 직전 마스크, 상한 직전 마스크(분석용)."""
    m = mask.astype(np.uint8)
    if stage != "none":
        m = quiet(filter_false_positives, m, min_voxels=P["min_voxels"],
                  min_contiguous_slices=P["min_contiguous_slices"])
    pre_flat = m
    if stage == "serving":
        m = quiet(filter_flat_artifacts, m, min_aspect_ratio=P["flat_min_aspect_ratio"],
                  min_thin_axis_mm=P["flat_min_thin_axis_mm"])
    pre_cap = m
    # 상한(max_lesions)은 서빙과 똑같이 부피 큰 순으로 자른다
    inst = find_instances(m, max_lesions=P.get("max_lesions", 10)) if stage == "serving" \
        else find_instances(m, max_lesions=10 ** 9)
    lab = np.zeros(m.shape, np.int32)
    for k, coords in enumerate(inst, 1):
        lab[tuple(coords.T)] = k
    return lab, len(inst), pre_flat, pre_cap


def gt_components(gt):
    lab, n = ndimage.label(gt, structure=STRUCT)
    if n == 0:
        return lab, []
    sizes = ndimage.sum(gt, lab, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= GT_MIN_VOXELS]
    return lab, keep


def match(pred_lab, n_pred, gt_lab, gt_ids):
    """예측 성분 → 겹치는 정답 id 집합. 반환: 통계 dict, 성분별 매칭 목록."""
    hits_per_gt = {g: 0 for g in gt_ids}
    comp_gt = []
    for k in range(1, n_pred + 1):
        ov = np.unique(gt_lab[pred_lab == k])
        ov = [int(g) for g in ov if g in hits_per_gt]
        comp_gt.append(ov)
        for g in ov:
            hits_per_gt[g] += 1
    pure_fp = sum(1 for ov in comp_gt if not ov)
    fragments = sum(max(0, c - 1) for c in hits_per_gt.values())
    tp_gt = sum(1 for c in hits_per_gt.values() if c > 0)
    return {"n_pred": n_pred, "n_gt": len(gt_ids), "tp_gt": tp_gt, "pure_fp": pure_fp,
            "fragments": fragments, "fn_gt": len(gt_ids) - tp_gt}, comp_gt


def dice(a, b):
    s = a.sum() + b.sum()
    return float(2 * np.logical_and(a, b).sum() / s) if s else 1.0


def bbox_dims(coords):
    return (coords.max(0) - coords.min(0) + 1).tolist()


def analyze_patient(fp, P, serving_t):
    d = np.load(fp)
    meta = json.loads(str(d["meta"]))
    pid = meta["pid"]
    if "gt" not in d:
        print(f"  {pid}: gt 없음 — 건너뜀 ({meta.get('gt_shape_mismatch')})")
        return [], [], [], [], []
    score = d["tumor_score"].astype(np.float32)
    gt = d["gt"].astype(bool)
    breast = d["breast_score"].astype(np.float32) >= P["breast_score_threshold"]
    body = d["body_mask"].astype(bool)
    gt_lab, gt_ids = gt_components(gt)
    primary_gt = None
    if gt_ids:
        sizes = ndimage.sum(gt, gt_lab, gt_ids)
        primary_gt = gt_ids[int(np.argmax(sizes))]  # 가장 큰 정답 병변 = 주 병변
    gt_rows = []
    gt_z = np.where(gt.any(axis=(1, 2)))[0]
    zmin, zmax = (int(gt_z.min()), int(gt_z.max())) if gt_z.size else (None, None)
    if meta["dump_threshold"] > min(SWEEP):
        raise SystemExit(f"{pid}: dump_threshold {meta['dump_threshold']} > 스윕 최솟값 {min(SWEEP)}")

    sweep_rows, filter_rows, fp_rows, flat_tp_rows = [], [], [], []

    def match_p(lab, n):
        st, comp_gt = match(lab, n, gt_lab, gt_ids)
        st["primary_hit"] = None if primary_gt is None else int(any(primary_gt in ov for ov in comp_gt))
        return st, comp_gt

    # 1) 임계값 스윕 — 서빙 후처리 그대로
    for t in SWEEP:
        lab, n, _, _ = postprocess(score >= t, P, "serving")
        st, _ = match_p(lab, n)
        sweep_rows.append({"pid": pid, "threshold": t, **st, "dice": dice(lab > 0, gt)})

    # 2) 필터 비교 — 서빙 임계값
    raw = score >= serving_t
    for stage in ("none", "size_span", "serving"):
        lab, n, pre_flat, pre_cap = postprocess(raw, P, stage)
        st, comp_gt = match_p(lab, n)
        filter_rows.append({"pid": pid, "variant": stage, **st, "dice": dice(lab > 0, gt)})
        if stage == "serving":
            serving_lab, serving_n, serving_comp_gt = lab, n, comp_gt
            pre_flat_mask, pre_cap_mask = pre_flat, pre_cap
    for thin, ar in FLAT_GRID:
        Q = {**P, "flat_min_thin_axis_mm": thin, "flat_min_aspect_ratio": ar}
        lab, n, _, _ = postprocess(raw, Q, "serving")
        st, _ = match_p(lab, n)
        filter_rows.append({"pid": pid, "variant": f"flat_thin{thin}_ar{ar}", **st, "dice": dice(lab > 0, gt)})
    Q = {**P, "max_lesions": 10 ** 9}
    lab, n, _, _ = postprocess(raw, Q, "serving")
    st, _ = match_p(lab, n)
    filter_rows.append({"pid": pid, "variant": "serving_no_cap", **st, "dice": dice(lab > 0, gt)})

    # 유방 영역 필터 시뮬레이션 — 서빙 결과에서 breast 마스크(서빙 임계값) 안 비율이 기준 미만인 성분 제거.
    # 마스크를 dil mm 넓혀서도 본다(가슴벽에 붙은 병변 보호용).
    for dil in ROI_DILATE_MM:
        bm = ndimage.binary_dilation(breast, structure=STRUCT, iterations=dil) if dil else breast
        for frac in ROI_MIN_FRAC:
            keep = np.zeros_like(serving_lab)
            j = 0
            for k in range(1, serving_n + 1):
                comp = serving_lab == k
                if bm[comp].mean() >= frac:
                    j += 1
                    keep[comp] = j
            st, _ = match_p(keep, j)
            filter_rows.append({"pid": pid, "variant": f"roi_dil{dil}_frac{frac}", **st,
                                "dice": dice(keep > 0, gt)})
    for g in gt_ids:
        comp = gt_lab == g
        gt_rows.append({"pid": pid, "gt_id": g, "voxels": int(comp.sum()),
                        "is_primary": g == primary_gt,
                        "in_breast_frac": round(float(breast[comp].mean()), 3),
                        "in_body_frac": round(float(body[comp].mean()), 3)})

    # 시트형 필터(서빙 기준)가 지운 성분 중 정답과 겹치는 것 = 실제 병변을 지웠을 가능성
    pf_lab, pf_n = ndimage.label(pre_flat_mask, structure=STRUCT)
    for k in range(1, pf_n + 1):
        comp = pf_lab == k
        if pre_cap_mask[comp].any():
            continue  # 시트형 필터는 통과한 성분(최종에서 빠졌다면 상한 때문)
        if not gt[comp].any():
            continue  # 정답과 무관한 성분(원래 의도대로 지운 오탐)
        coords = np.argwhere(comp)
        dz, dy, dx = bbox_dims(coords)
        flat_tp_rows.append({"pid": pid, "voxels": int(comp.sum()), "bbox_z": dz, "bbox_y": dy, "bbox_x": dx,
                             "min_mm": min(dz, dy, dx), "aspect": round(min(dz, dy, dx) / max(dz, dy, dx), 3),
                             "gt_overlap_frac": round(float(gt[comp].mean()), 3)})

    # 3) 오탐 위치 — 서빙 설정의 순수 오탐 성분
    for k, ov in enumerate(serving_comp_gt, 1):
        if ov:
            continue
        comp = serving_lab == k
        coords = np.argwhere(comp)
        z0, z1 = int(coords[:, 0].min()), int(coords[:, 0].max())
        if zmin is None:
            zdist = None
        else:
            zdist = 0 if (z1 >= zmin and z0 <= zmax) else min(abs(z0 - zmax), abs(zmin - z1))
        dz, dy, dx = bbox_dims(coords)
        fp_rows.append({"pid": pid, "voxels": int(comp.sum()), "z_dist_from_gt": zdist,
                        "in_breast_frac": round(float(breast[comp].mean()), 3),
                        "in_body_frac": round(float(body[comp].mean()), 3),
                        "score_max": round(float(score[comp].max()), 3),
                        "score_mean": round(float(score[comp].mean()), 3),
                        "bbox_z": dz, "bbox_y": dy, "bbox_x": dx})
    return sweep_rows, filter_rows, fp_rows, flat_tp_rows, gt_rows


def summarize(df, key):
    g = df.groupby(key)
    out = pd.DataFrame({
        "patients": g["pid"].nunique(),
        "pure_fp_per_pt": g["pure_fp"].mean().round(2),
        "fragments_per_pt": g["fragments"].mean().round(2),
        "lesion_sens": (g["tp_gt"].sum() / g["n_gt"].sum()).round(3),
        "primary_hit_rate": g["primary_hit"].mean().round(3),
        "pts_with_miss": g.apply(lambda x: int((x["fn_gt"] > 0).sum()), include_groups=False),
        "dice_mean": g["dice"].mean().round(3),
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, default=HERE / "results" / "raw_predictions")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "lesion_fp_analysis")
    args = ap.parse_args()

    sys.path.insert(0, str(HERE.parents[1] / "serving" / "code"))
    from model_io import DEFAULTS
    P = dict(DEFAULTS)
    serving_t = P["tumor_score_threshold"]

    files = sorted(args.inp.glob("*.npz"))
    if not files:
        sys.exit(f"npz 없음: {args.inp} — dump_raw_predictions.py 먼저 실행")
    args.out.mkdir(parents=True, exist_ok=True)

    acc = [[], [], [], [], []]
    for i, fp in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {fp.stem}")
        for a, rows in zip(acc, analyze_patient(fp, P, serving_t)):
            a.extend(rows)
    sweep, filt, fps, flat_tp, gts = (pd.DataFrame(a) for a in acc)
    if sweep.empty:
        sys.exit("분석 가능한 환자 없음(gt 전부 없음/불일치)")

    sweep.to_csv(args.out / "sweep_per_patient.csv", index=False)
    filt.to_csv(args.out / "filters_per_patient.csv", index=False)
    fps.to_csv(args.out / "pure_fp_components.csv", index=False)
    flat_tp.to_csv(args.out / "flat_filter_removed_gt_overlap.csv", index=False)
    gts.to_csv(args.out / "gt_lesions.csv", index=False)

    s1, s2 = summarize(sweep, "threshold"), summarize(filt, "variant")
    s1.to_csv(args.out / "sweep_summary.csv")
    s2.to_csv(args.out / "filters_summary.csv")

    print(f"\n{'='*70}\n1) 임계값 스윕 (3D 병변 단위, 서빙 후처리 적용) — 환자 {sweep['pid'].nunique()}명\n{'='*70}")
    print(s1.to_string())
    print(f"\n{'='*70}\n2) 필터 비교 (임계값 {serving_t})\n{'='*70}")
    print(s2.to_string())
    print(f"\n시트형 필터(서빙 기준)가 지운 성분 중 정답과 겹친 것: {len(flat_tp)}개")
    if not flat_tp.empty:
        print(flat_tp.to_string(index=False))

    print(f"\n{'='*70}\n3) 순수 오탐 위치 (서빙 설정) — 총 {len(fps)}개\n{'='*70}")
    if not fps.empty:
        zd = fps["z_dist_from_gt"].dropna()
        bins = {"정답 z범위 안(같은 슬라이스대)": int((zd == 0).sum()),
                "1~10슬라이스 밖": int(((zd > 0) & (zd <= 10)).sum()),
                "10슬라이스 넘게 밖(종양 없는 슬라이스)": int((zd > 10).sum())}
        for k, v in bins.items():
            print(f"  {k:40s} {v:4d}  ({v / max(len(zd), 1):.0%})")
        print(f"  breast 마스크 안 비율 중앙값 {fps['in_breast_frac'].median():.2f}, "
              f"몸통 윤곽 안 비율 중앙값 {fps['in_body_frac'].median():.2f}")
        print(f"  breast 마스크와 거의 안 겹침(<10%): {int((fps['in_breast_frac'] < 0.1).sum())}개")
    print(f"\n{'='*70}\n4) 정답 병변 위치 — 유방 영역 필터를 켰을 때 지워질 위험\n{'='*70}")
    prim = gts[gts["is_primary"]]
    print(f"  정답 병변 {len(gts)}개(주 병변 {len(prim)}개). breast 마스크 안 비율 <0.3인 것: "
          f"전체 {int((gts['in_breast_frac'] < 0.3).sum())}개, 주 병변 {int((prim['in_breast_frac'] < 0.3).sum())}개")
    print(f"\nCSV 저장: {args.out}")


if __name__ == "__main__":
    main()
