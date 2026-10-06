#!/usr/bin/env python3
"""
서빙 경로 그대로 추론해서 "필터 전" 원본 결과를 환자별 npz로 저장한다 (GPU 1회).

2026-09-29 신규 — MRI 병변 오탐 검토 2단계. 저장한 걸로 analyze_lesion_fp.py가
임계값 스윕·필터 비교·오탐 위치 분석을 CPU로 몇 번이고 돌린다.

왜 batch_smoke_test.py를 안 쓰나:
  - 그건 오프라인 경로(전처리 끝난 npy + dataset_tag)라 서빙(원본 nii → preprocess_raw_to_volume)과 다르다
  - 필터 켠/끈 비교를 위해 추론을 두 번 돌리고, 병변 "개수"만 남긴다

핵심 — 낮은 임계값(기본 0.3)에서 점수 맵(return_score_map)을 저장한다. 점수 맵은
"각 픽셀을 덮는 쿼리 중 최대 점수"라서, (score_map >= t)가 임계값 t로 추론한 마스크와
정확히 같다(t >= dump 임계값, mask_pixel_threshold 동일 조건). 그래서 스윕에 GPU가 다시 필요 없다.

저장 내용 (npz, 전부 서빙과 같은 1mm 리샘플링 격자, (Z,Y,X)):
  tumor_score   float32  tumor 쿼리 점수 맵 (dump_threshold 미만은 0)
  breast_score  float32  breast 쿼리 점수 맵 (density 경로, 1-phase — 서빙과 동일)
  body_mask     uint8    find_body_silhouette_mask (사분면·유두거리에 쓰는 몸통 윤곽)
  gt            uint8    MAMA-MIA expert 라벨 (mama_mia_processed/labels, 격자 불일치면 저장 안 함)
  meta          json 문자열

사용법:
    python3 dump_raw_predictions.py --n-patients 40               # val에서 무작위 40명
    python3 dump_raw_predictions.py --patients DUKE_399,ISPY2_242370
    python3 dump_raw_predictions.py --n-patients 40 --dry-run     # 모델 안 올리고 대상·파일만 확인
    python3 dump_raw_predictions.py --n-patients 40 --exclude-from results/raw_predictions \
        --out results/raw_predictions_holdout                     # 독립 검증용 새 환자
이미 저장된 환자는 건너뛴다(중단 후 재실행하면 이어서 진행).
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MRI_ROOT = HERE.parents[1]                       # mri/
BREAST_ROOT = MRI_ROOT.parent                    # breast/
SERVING_CODE = MRI_ROOT / "serving" / "code"
for _p in (HERE, SERVING_CODE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DEFAULT_RAW = BREAST_ROOT / "data" / "mri" / "mama_mia" / "images"
DEFAULT_LABELS = BREAST_ROOT / "data" / "mri" / "mama_mia_processed" / "labels"
DEFAULT_COCO = BREAST_ROOT / "data" / "mri" / "coco_2d"
DEFAULT_OUT = HERE / "results" / "raw_predictions"


def val_patients(coco_root: Path):
    """coco val split에 들어간 mamamia 환자 id (batch_smoke_test.sample_val_patients와 같은 규칙)."""
    with open(coco_root / "val" / "_annotations.coco.json") as f:
        coco = json.load(f)
    pids = set()
    for im in coco["images"]:
        fn = im["file_name"]
        if fn.startswith("mamamia_"):
            pids.add(fn[len("mamamia_"):].rsplit("_z", 1)[0])
    return sorted(pids)


def find_raw_dir(raw_root: Path, pid: str):
    for cand in (raw_root / pid, raw_root / pid.upper(), raw_root / pid.lower()):
        if cand.is_dir():
            return cand
    return None


def find_label(labels_dir: Path, pid: str):
    for cand in (labels_dir / f"{pid}.npy", labels_dir / f"{pid.upper()}.npy", labels_dir / f"{pid.lower()}.npy"):
        if cand.exists():
            return cand
    return None


def phase_files(pdir: Path):
    """_0000(pre), _0001(first post) — preprocess_mamamia.find_phase_files와 같은 규칙."""
    pre = sorted(pdir.glob("*_0000.nii*"))
    post = sorted(pdir.glob("*_0001.nii*"))
    return (pre[0] if pre else None), (post[0] if post else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(MRI_ROOT / "serving" / "configs" / "mri_lora.yaml"))
    ap.add_argument("--weights", default=None, help="생략하면 서빙과 같은 mri_lora_best.pt")
    ap.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--coco-root", type=Path, default=DEFAULT_COCO)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--n-patients", type=int, default=40)
    ap.add_argument("--patients", default=None, help="쉼표로 직접 지정하면 --n-patients 무시")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--exclude-from", type=Path, action="append", default=[],
                    help="(2026-10-01) 이 폴더에 npz가 있는 환자는 후보에서 뺀다 — 기준 고를 때 쓴 환자와 겹치지 않는 "
                         "독립 검증용. 여러 번 줄 수 있음")
    ap.add_argument("--dump-threshold", type=float, default=0.3,
                    help="이 값 이상 임계값만 나중에 재현 가능. 서빙은 0.5")
    ap.add_argument("--dry-run", action="store_true", help="모델 안 올리고 대상 환자·파일 존재만 확인")
    args = ap.parse_args()

    if args.patients:
        patients = [p.strip() for p in args.patients.split(",") if p.strip()]
    else:
        excluded = {f.stem for d in args.exclude_from for f in d.glob("*.npz")}
        pool = [p for p in val_patients(args.coco_root)
                if find_raw_dir(args.raw_root, p) and p not in excluded]
        if excluded:
            print(f"제외 {len(excluded)}명(--exclude-from), 남은 후보 {len(pool)}명")
        random.Random(args.seed).shuffle(pool)
        patients = pool[:args.n_patients]

    todo = []
    for pid in patients:
        pdir = find_raw_dir(args.raw_root, pid)
        pre, post = phase_files(pdir) if pdir else (None, None)
        lbl = find_label(args.labels_dir, pid)
        status = "OK" if (pre and post) else "원본 phase 누락"
        print(f"  {pid:20s} {status}  label={'있음' if lbl else '없음'}")
        if pre and post:
            todo.append((pid, pre, post, lbl))
    print(f"대상 {len(todo)}명 (요청 {len(patients)}명)")
    if args.dry_run or not todo:
        return

    import torch
    from model_io import load_model, DEFAULTS
    from infer_mri import preprocess_raw_to_volume
    from build_3d_from_predictions_v9 import volume_to_rgb_slices, rgb_array_to_tensor, infer_slice_mask
    from compute_stage1_metrics import find_body_silhouette_mask

    args.out.mkdir(parents=True, exist_ok=True)
    print("모델 로딩 중...")
    bundle = load_model(args.config, args.weights)
    M, model, dev, R = bundle["M"], bundle["model"], bundle["device"], bundle["resolution"]
    mpt = bundle["params"]["mask_pixel_threshold"]
    print(f"로딩 완료 (device={dev}). dump_threshold={args.dump_threshold}, mask_pixel_threshold={mpt}\n")

    for i, (pid, pre_fp, post_fp, lbl_fp) in enumerate(todo, 1):
        out_fp = args.out / f"{pid}.npz"
        if out_fp.exists():
            print(f"[{i}/{len(todo)}] {pid} — 이미 있음, 건너뜀")
            continue
        t0 = time.time()
        tumor_volume, density_volume = preprocess_raw_to_volume(pre_fp, post_fp)

        def score_volume(rgb_slices, cname):
            maps = []
            with torch.no_grad():
                for rgb in rgb_slices:
                    image_tensor, orig_size = rgb_array_to_tensor(rgb, R)
                    _, sm = infer_slice_mask(model, M, image_tensor, R, orig_size, cname, dev,
                                             args.dump_threshold, mask_pixel_threshold=mpt,
                                             return_score_map=True)
                    maps.append(sm)  # float32 유지 — float16이면 0.45→0.44995처럼 경계값이 틀어져 재현이 깨짐
            return np.stack(maps, axis=0)

        # 서빙 predict()와 같은 입력 — tumor는 2-phase("mamamia"), breast는 density 1-phase("duke")
        tumor_score = score_volume(volume_to_rgb_slices(tumor_volume, "mamamia"), "tumor")
        breast_score = score_volume(volume_to_rgb_slices(density_volume, "duke"), "breast")
        body = find_body_silhouette_mask(tumor_volume[0])
        body = body.astype(np.uint8) if body is not None else np.zeros(tumor_score.shape, np.uint8)

        meta = {"pid": pid, "pre": str(pre_fp), "post": str(post_fp), "shape": list(tumor_score.shape),
                "dump_threshold": args.dump_threshold, "mask_pixel_threshold": mpt,
                "serving_defaults": DEFAULTS, "weights": args.weights or "mri_lora_best.pt",
                "gt": None}
        arrays = {"tumor_score": tumor_score, "breast_score": breast_score, "body_mask": body}
        if lbl_fp is not None:
            gt = np.load(lbl_fp)
            if gt.shape == tumor_score.shape:
                arrays["gt"] = (gt > 0).astype(np.uint8)
                meta["gt"] = str(lbl_fp)
            else:
                # 격자가 다르면 비교 자체가 무의미 — 조용히 넘기지 않고 기록한다
                meta["gt_shape_mismatch"] = [list(gt.shape), list(tumor_score.shape)]
                print(f"  ⚠ GT 격자 불일치 {gt.shape} vs {tumor_score.shape} — gt 저장 안 함")

        np.savez_compressed(out_fp, meta=json.dumps(meta, ensure_ascii=False), **arrays)
        n_hot = int((tumor_score >= bundle["params"]["tumor_score_threshold"]).sum())
        print(f"[{i}/{len(todo)}] {pid} shape={tumor_score.shape} "
              f"tumor>=서빙임계 {n_hot}복셀  {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
