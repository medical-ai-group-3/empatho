#!/usr/bin/env python3
"""
저장된 원본 예측(npz)에 서빙 predict()의 후처리를 "그대로" 적용해서 병변 단위로 평가 (CPU).

2026-10-01 신규 — 서빙 설정 후보(모델 × 임계값 × z_gap_fill × min_lesion_score_mean)를
서빙과 같은 함수·같은 순서로 평가한다. 후처리 순서는 infer_mri.predict()와 동일:
  score>=t → _gap_fill_z → filter_false_positives → filter_flat_artifacts
  → _filter_low_score_components(평균은 원래 예측 복셀만) → find_instances(max_lesions)

사용법:
    python3 eval_serving_config.py --in results/raw_predictions_v6_last --threshold 0.45 --gap 1 --score-min 0.55
    python3 eval_serving_config.py --in DIR                       # 서빙 DEFAULTS 그대로
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "serving" / "code")]

from analyze_lesion_fp import quiet, gt_components, match, dice  # noqa: E402
from build_3d_from_predictions_v9 import filter_false_positives, filter_flat_artifacts  # noqa: E402
from compute_stage1_metrics import find_instances  # noqa: E402
from infer_mri import _gap_fill_z, _filter_low_score_components  # noqa: E402
from model_io import DEFAULTS  # noqa: E402


def serving_postprocess(score, P):
    tumor_mask = (score >= P["tumor_score_threshold"]).astype(np.uint8)
    m = _gap_fill_z(tumor_mask, P["z_gap_fill"])
    m = quiet(filter_false_positives, m, min_voxels=P["min_voxels"],
              min_contiguous_slices=P["min_contiguous_slices"])
    m = quiet(filter_flat_artifacts, m, min_aspect_ratio=P["flat_min_aspect_ratio"],
              min_thin_axis_mm=P["flat_min_thin_axis_mm"])
    m, _ = _filter_low_score_components(m, score, P["min_lesion_score_mean"], score_voxels=tumor_mask)
    inst = find_instances(m, max_lesions=P["max_lesions"])
    lab = np.zeros(m.shape, np.int32)
    for k, c in enumerate(inst, 1):
        lab[tuple(c.T)] = k
    return lab, len(inst)


def evaluate_dir(inp: Path, P: dict, verbose=False):
    tot = {"pts": 0, "fp": 0, "prim": 0, "n_prim": 0, "tp": 0, "n_gt": 0, "dice": 0.0}
    per = []
    for fp in sorted(inp.glob("*.npz")):
        d = np.load(fp)
        pid = json.loads(str(d["meta"]))["pid"]
        if "gt" not in d:
            continue
        score = d["tumor_score"].astype(np.float32)
        gt = d["gt"].astype(bool)
        lab, n = serving_postprocess(score, P)
        gl, gids = gt_components(gt)
        st, cg = match(lab, n, gl, gids)
        hit_prim = None
        if gids:
            prim = gids[int(np.argmax(ndimage.sum(gt, gl, gids)))]
            hit_prim = any(prim in ov for ov in cg)
            tot["n_prim"] += 1
            tot["prim"] += int(hit_prim)
        tot["pts"] += 1
        tot["fp"] += st["pure_fp"]
        tot["tp"] += st["tp_gt"]
        tot["n_gt"] += st["n_gt"]
        tot["dice"] += dice(lab > 0, gt)
        per.append({"pid": pid, **st, "primary_hit": hit_prim})
        if verbose and hit_prim is False:
            print(f"  주 병변 놓침: {pid}")
    n = max(tot["pts"], 1)
    return {"patients": tot["pts"], "fp_per_pt": round(tot["fp"] / n, 3),
            "primary": f"{tot['prim']}/{tot['n_prim']}",
            "lesion_sens": round(tot["tp"] / max(tot["n_gt"], 1), 3),
            "dice": round(tot["dice"] / n, 3)}, per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--gap", type=int, default=None)
    ap.add_argument("--score-min", type=float, default=None)
    a = ap.parse_args()
    P = dict(DEFAULTS)
    if a.threshold is not None:
        P["tumor_score_threshold"] = a.threshold
    if a.gap is not None:
        P["z_gap_fill"] = a.gap
    if a.score_min is not None:
        P["min_lesion_score_mean"] = a.score_min
    s, _ = evaluate_dir(a.inp, P, verbose=True)
    print(json.dumps({"config": {k: P[k] for k in ("tumor_score_threshold", "z_gap_fill", "min_lesion_score_mean")},
                      **s}, ensure_ascii=False))


if __name__ == "__main__":
    main()
