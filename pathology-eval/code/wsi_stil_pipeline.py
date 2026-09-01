"""
WSI 단위 sTIL 파이프라인 (TIGER WSITILS 검증용).

stil_inference_pipeline.py 의 타일 단위 로직(조직분할 socket1 + 세포검출/분류 socket2
+ 공간 게이팅)을 그대로 재사용하고, WSI 를 512px 타일로 순회해 슬라이드 단위로 면적 집계:

  slide_stil = nc_ratio * Σ_tiles(간질 내 면역세포 핵면적 px²) / Σ_tiles(간질 면적 px²) * 100

- 조직(전경) 타일만 대상 (thumbnail Otsu + 채도). 그중 --n_tiles 개를 무작위 서브샘플.
  Σnum/Σden 비율은 균일 무작위 부분집합에서 불편추정 (분자·분모가 동일 배율로 스케일→상쇄).
- 배율(mpp): 비율이라 상쇄되므로 리샘플 안 함. level-0 native 타일 사용
  (socket2 가 학습된 TIGER crop 해상도와 동일 조건).
"""
import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import openslide
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.expanduser("~/models/cellvitpp")
sys.path.insert(0, REPO_ROOT)

from stil_inference_pipeline import (
    load_tissue_model, load_cell_classifier, tissue_stroma_mask,
    detect_and_classify, STROMA_CLASS_IDX,
)
from extract_socket2_tokens import load_model as load_cellvit_sam, NR_TYPES
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy

TILE = 512


def foreground_mask(slide, thumb_max=2048):
    """thumbnail 에서 조직(전경) 마스크. Otsu(어두움) ∧ 채도 ∧ 극단값 제외."""
    thumb = slide.get_thumbnail((thumb_max, thumb_max)).convert("RGB")
    arr = np.array(thumb)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    fg = (otsu > 0) & (hsv[:, :, 1] > 15) & (g > 20) & (g < 235)
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return fg, thumb.size  # fg (H,W), (thumb_w, thumb_h)


def tissue_tiles(fg, thumb_wh, W0, H0, min_fg=0.25):
    tw, th = thumb_wh
    sx, sy = tw / W0, th / H0
    out = []
    for y in range(0, H0 - TILE, TILE):
        for x in range(0, W0 - TILE, TILE):
            a, b = int(x * sx), int(y * sy)
            c, d = int((x + TILE) * sx) + 1, int((y + TILE) * sy) + 1
            p = fg[b:d, a:c]
            if p.size and p.mean() >= min_fg:
                out.append((x, y))
    return out


def process_slide(path, models, args, device):
    tissue_model, cellvit, postproc, head, mean, std, image_size = models
    s = openslide.OpenSlide(str(path))
    W0, H0 = s.level_dimensions[0]
    mpp = float(s.properties.get("openslide.mpp-x", args.mpp))

    fg, twh = foreground_mask(s)
    tiles = tissue_tiles(fg, twh, W0, H0, args.min_fg)
    rng = random.Random(int(hashlib.md5(path.stem.encode()).hexdigest()[:8], 16))
    rng.shuffle(tiles)
    sample = tiles[: args.n_tiles]

    sum_imm_nuc, sum_stroma = 0.0, 0
    n_stroma_tiles = n_immune = 0
    for (x, y) in sample:
        tile = np.array(s.read_region((x, y), 0, (TILE, TILE)).convert("RGB")).astype(np.uint8)
        mask, _ = tissue_stroma_mask(tissue_model, Image.fromarray(tile), mean, std,
                                     image_size, device, TILE, TILE)
        st = int((mask == STROMA_CLASS_IDX).sum())
        if st == 0:
            continue
        n_stroma_tiles += 1
        sum_stroma += st
        cells = detect_and_classify(tile, cellvit, postproc, head, device, args.batch_size)
        immune = [c for c in cells if c["p_til"] >= args.til_threshold]
        intra = [c for c in immune
                 if mask[min(int(c["cy"]), TILE - 1), min(int(c["cx"]), TILE - 1)] == STROMA_CLASS_IDX]
        n_immune += len(intra)
        sum_imm_nuc += sum(c["area_px"] for c in intra)

    s.close()
    slide_stil_nuc = (sum_imm_nuc / sum_stroma * 100) if sum_stroma > 0 else None
    slide_stil = slide_stil_nuc * args.nc_ratio if slide_stil_nuc is not None else None
    return {
        "stem": path.stem,
        "level0_wh": [W0, H0],
        "mpp": round(mpp, 4),
        "n_tissue_tiles": len(tiles),
        "n_sampled": len(sample),
        "n_stroma_tiles": n_stroma_tiles,
        "n_intra_stromal_immune": n_immune,
        "sum_stroma_px": sum_stroma,
        "sum_immune_nucleus_px": round(sum_imm_nuc, 1),
        "slide_stil_nucleus": round(slide_stil_nuc, 3) if slide_stil_nuc is not None else None,
        "slide_stil": round(slide_stil, 3) if slide_stil is not None else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images_dir", default=os.path.expanduser("~/data/tiger/wsitils/images"))
    ap.add_argument("--gt_csv", default=os.path.expanduser("~/data/tiger/wsitils/tiger-til-scores-wsitils.csv"))
    ap.add_argument("--tissue_checkpoint",
                    default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand/best_head.pth"))
    ap.add_argument("--cell_head",
                    default=os.path.expanduser("~/pathology-eval/candidates/socket2/model_best.pth"))
    ap.add_argument("--cellvit_path", default=os.path.join(REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"))
    ap.add_argument("--til_threshold", type=float, default=0.5)
    ap.add_argument("--nc_ratio", type=float, default=1.5)
    ap.add_argument("--mpp", type=float, default=0.5, help="slide 메타데이터 없을 때 fallback")
    ap.add_argument("--n_tiles", type=int, default=600, help="슬라이드당 서브샘플 조직타일 수")
    ap.add_argument("--min_fg", type=float, default=0.25, help="타일이 조직으로 간주되는 최소 전경 비율")
    ap.add_argument("--batch_size", type=int, default=4)
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "stil_results"))
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--slides", nargs="*", default=None, help="특정 stem 만 (기본: images_dir 전체)")
    ap.add_argument("--append", action="store_true", help="기존 결과 JSON 유지, 미처리 슬라이드만 추가")
    ap.add_argument("--fp16", type=int, default=1, help="1이면 모델 가중치 fp16 (공유 GPU 저VRAM)")
    args = ap.parse_args()

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    os.makedirs(args.outdir, exist_ok=True)

    print(f"모델 로딩... (fp16={bool(args.fp16)})")
    tissue_model, mean, std, image_size = load_tissue_model(args.tissue_checkpoint, device, fp16=bool(args.fp16))
    cellvit, _ = load_cellvit_sam(args.cellvit_path, args.gpu)
    if args.fp16:
        cellvit.half()
    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=NR_TYPES)
    head = load_cell_classifier(args.cell_head, device)
    models = (tissue_model, cellvit, postproc, head, mean, std, image_size)

    gt = {}
    with open(args.gt_csv) as f:
        for row in csv.DictReader(f):
            gt[row["image-id"]] = int(row["tils-score"])

    out = Path(args.outdir) / "wsi_stil_results.json"
    results = []
    done = set()
    if args.append and out.exists():
        results = json.load(open(out))
        done = {r["stem"] for r in results}
        print(f"기존 결과 {len(done)}장 유지, 미처리분만 추가")

    paths = sorted(Path(args.images_dir).glob("*.tif"))
    if args.slides:
        paths = [p for p in paths if p.stem in set(args.slides)]
    paths = [p for p in paths if p.stem not in done]
    print(f"WSI {len(paths)}장, 슬라이드당 최대 {args.n_tiles} 타일, "
          f"til_thr {args.til_threshold}, nc_ratio {args.nc_ratio}")

    for i, p in enumerate(paths):
        t0 = time.time()
        r = process_slide(p, models, args, device)
        r["gt_tils_score"] = gt.get(p.stem)
        results.append(r)
        print(f"  [{i+1}/{len(paths)}] {p.stem:9s} GT={r['gt_tils_score']:>3}  "
              f"slide_stil={r['slide_stil']}  (조직타일 {r['n_tissue_tiles']}, 간질타일 "
              f"{r['n_stroma_tiles']}/{r['n_sampled']}, 면역세포 {r['n_intra_stromal_immune']}, "
              f"{time.time()-t0:.0f}s)")
        json.dump(results, open(out, "w"), ensure_ascii=False, indent=2)  # incremental

    results.sort(key=lambda r: (r.get("gt_tils_score") if r.get("gt_tils_score") is not None else -1, r["stem"]))
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out}  (총 {len(results)}장)")


if __name__ == "__main__":
    main()
