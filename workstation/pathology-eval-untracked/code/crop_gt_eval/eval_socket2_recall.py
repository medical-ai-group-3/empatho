#!/usr/bin/env python3
"""분석 2: 림프구 검출(socket2) recall — 크롭 단위 GT 점.

CellViT-SAM-H + 세포분류 헤드만 로드하고 sip.detect_and_classify() 를 그대로 쓴다.
  GT 점 = tiger-coco.json bbox 중심
  AI 점 = p_til >= 0.5 인 세포 중심
매칭 (반경 15px):
  1:1 (기본)  — 거리 오름차순 그리디, GT·AI 각각 최대 1번
  반경 (비교) — recall = 반경 안에 AI 점이 하나라도 있는 GT 비율,
                precision = 반경 안에 GT 점이 하나라도 있는 AI 비율
1:1 에서 놓친 GT 는 원인별로 나눈다 (핵 병합 가설 확인용):
  miss_taken  : 반경 안에 TIL 점은 있으나 이미 다른 GT 에 배정됨 (한 검출 = 여러 GT → 병합 신호)
  miss_nontil : 반경 안 TIL 점 없음, 검출 세포는 있으나 p_til < 0.5 (분류 탈락)
  miss_nodet  : 반경 안에 검출 세포 자체가 없음 (검출 실패)
밀도 = GT 점 수 / GT 간질 면적(mm², mpp 0.5) — GT 간질 0 인 크롭은 밀도 구간에서 제외.

출력: results/socket2_crop_gt.csv, results/socket2_points/{id}.json

실행: ~/miniconda3/envs/cellvitpp/bin/python code/crop_gt_eval/eval_socket2_recall.py [--fp16]
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import common as C
import extract_socket2_tokens as e2   # noqa: E402
import stil_inference_pipeline as sip  # noqa: E402
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy  # noqa: E402


def greedy_match(gt: np.ndarray, ai: np.ndarray, r: float) -> list[tuple[int, int, float]]:
    if len(gt) == 0 or len(ai) == 0:
        return []
    pairs = cKDTree(gt).sparse_distance_matrix(cKDTree(ai), r, output_type="ndarray")
    pairs = pairs[np.argsort(pairs["v"], kind="stable")]
    used_g, used_a, out = set(), set(), []
    for i, j, d in zip(pairs["i"], pairs["j"], pairs["v"]):
        if i in used_g or j in used_a:
            continue
        used_g.add(int(i)); used_a.add(int(j))
        out.append((int(i), int(j), float(d)))
    return out


def any_within(src: np.ndarray, dst: np.ndarray, r: float) -> np.ndarray:
    """src 각 점에 대해 dst 점이 반경 r 안에 있는지 (bool (len(src),))."""
    if len(src) == 0:
        return np.zeros(0, bool)
    if len(dst) == 0:
        return np.zeros(len(src), bool)
    d, _ = cKDTree(dst).query(src, k=1, distance_upper_bound=r)
    return np.isfinite(d) & (d <= r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=4)
    a = ap.parse_args()

    val, s2 = C.check_split()
    ids = C.crop_ids(val)
    gt_pts = C.load_gt_points()
    out_pts = C.RESULTS / "socket2_points"
    out_pts.mkdir(parents=True, exist_ok=True)

    C.gpu_guard(6.0 if a.fp16 else 10.0, a.fp16, a.gpu)
    device = f"cuda:{a.gpu}"
    t0 = time.time()
    cellvit, _ = e2.load_model(C.CELLVIT_CKPT, a.gpu)
    if a.fp16:
        cellvit.half()
    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=e2.NR_TYPES)
    head = sip.load_cell_classifier(C.CELL_HEAD, device)
    print(f"[load] CellViT-SAM-H + cell head {time.time() - t0:.1f}s "
          f"(DEDUP_RADIUS={e2.DEDUP_RADIUS}, OVERLAP={e2.OVERLAP})")

    R = C.MATCH_RADIUS
    px_mm2 = (C.MPP / 1000.0) ** 2
    rows = []
    t0 = time.time()
    for n, stem in enumerate(val):
        cid = ids[stem]
        img = np.array(C.load_image(stem))
        H, W = img.shape[:2]
        gt = C.load_gt_mask(stem)
        g = gt_pts[stem]
        cells = sip.detect_and_classify(img, cellvit, postproc, head, device, a.batch_size)
        allc = np.array([[c["cx"], c["cy"]] for c in cells], float).reshape(-1, 2)
        ptil = np.array([c["p_til"] for c in cells], float)
        ai = allc[ptil >= C.TIL_THR]

        m = greedy_match(g, ai, R)
        tp = len(m)
        matched_g = np.zeros(len(g), bool)
        matched_g[[i for i, _, _ in m]] = True
        g_hit = any_within(g, ai, R)          # 반경 방식 recall
        a_hit = any_within(ai, g, R)          # 반경 방식 precision
        g_anycell = any_within(g, allc, R)
        miss = ~matched_g
        miss_taken = int((miss & g_hit).sum())
        miss_nontil = int((miss & ~g_hit & g_anycell).sum())
        miss_nodet = int((miss & ~g_anycell).sum())
        # 반경 안 GT 가 2개 이상인 AI 점 수 (한 검출이 여러 GT 를 덮음)
        multi_ai = 0
        if len(ai) and len(g):
            cnt = np.array([len(x) for x in cKDTree(g).query_ball_point(ai, R)])
            multi_ai = int((cnt >= 2).sum())

        gt_s_px = int((gt == 2).sum())
        # 참고: GT 점 중 GT 간질 위에 있는 것 (밀도 분자는 스펙대로 전체 GT 점)
        gx = np.clip(g[:, 0].astype(int), 0, W - 1)
        gy = np.clip(g[:, 1].astype(int), 0, H - 1)
        stroma_gt_pts = int((gt[gy, gx] == 2).sum())
        r = {
            "crop_id": cid, "stem": stem, "W": W, "H": H,
            "in_socket2_train": stem in s2,
            "n_gt": len(g), "n_ai": len(ai), "n_cells_all": len(allc),
            "tp_1to1": tp,
            "recall_1to1": tp / len(g) if len(g) else np.nan,
            "precision_1to1": tp / len(ai) if len(ai) else np.nan,
            "gt_hit_radius": int(g_hit.sum()), "ai_hit_radius": int(a_hit.sum()),
            "recall_radius": g_hit.mean() if len(g) else np.nan,
            "precision_radius": a_hit.mean() if len(ai) else np.nan,
            "miss_taken": miss_taken, "miss_nontil": miss_nontil, "miss_nodet": miss_nodet,
            "ai_multi_gt": multi_ai,
            "n_gt_in_gt_stroma": stroma_gt_pts,
            "gt_stroma_px": gt_s_px,
            "gt_stroma_mm2": gt_s_px * px_mm2,
            "density_per_mm2": len(g) / (gt_s_px * px_mm2) if gt_s_px else np.nan,
            "mean_match_dist": float(np.mean([d for *_, d in m])) if m else np.nan,
            "median_til_area_px": float(np.median([c["area_px"] for c in cells if c["p_til"] >= C.TIL_THR]))
                                  if len(ai) else np.nan,
        }
        rows.append(r)
        (out_pts / f"{cid}.json").write_text(json.dumps({
            "crop_id": cid, "stem": stem, "W": W, "H": H, "radius": R, "til_thr": C.TIL_THR,
            "gt_points": g.round(2).tolist(),
            "cells": [{k: round(v, 4) for k, v in c.items()} for c in cells],
            "matches_1to1": [[i, j, round(d, 3)] for i, j, d in m],  # (gt 인덱스, ai 인덱스=p_til>=thr 필터 후 순서, 거리)
        }))
        if (n + 1) % 20 == 0 or n + 1 == len(val):
            print(f"  {n + 1}/{len(val)}  {time.time() - t0:.0f}s", flush=True)

    df = pd.DataFrame(rows)
    # 밀도 3분위 (GT 간질 > 0 이고 GT 점 >= 1 인 크롭 기준으로 경계 산정, 전체 281 기준)
    ok = df["density_per_mm2"].notna() & (df["n_gt"] > 0)
    q1, q2 = df.loc[ok, "density_per_mm2"].quantile([1 / 3, 2 / 3]).tolist()
    df["density_bin"] = np.where(~ok, "NA",
                         np.where(df["density_per_mm2"] <= q1, "low",
                         np.where(df["density_per_mm2"] <= q2, "mid", "high")))
    df.to_csv(C.RESULTS / "socket2_crop_gt.csv", index=False)
    (C.RESULTS / "socket2_meta.json").write_text(json.dumps({
        "density_cutoffs_per_mm2": [q1, q2], "radius_px": R, "til_thr": C.TIL_THR, "mpp": C.MPP,
        "fp16": a.fp16, "batch_size": a.batch_size, "cell_head": C.CELL_HEAD, "cellvit": C.CELLVIT_CKPT,
        "dedup_radius": e2.DEDUP_RADIUS, "tile_overlap": e2.OVERLAP,
    }, indent=2))
    print(f"density cutoffs (/mm²): {q1:.0f}, {q2:.0f}")
    tot = df[["n_gt", "n_ai", "tp_1to1", "gt_hit_radius", "ai_hit_radius"]].sum()
    print(f"ALL recall 1:1={tot.tp_1to1 / tot.n_gt:.3f} prec 1:1={tot.tp_1to1 / tot.n_ai:.3f} | "
          f"radius recall={tot.gt_hit_radius / tot.n_gt:.3f} prec={tot.ai_hit_radius / tot.n_ai:.3f}")
    print(f"saved -> {C.RESULTS / 'socket2_crop_gt.csv'}")


if __name__ == "__main__":
    main()
