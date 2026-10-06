#!/usr/bin/env python3
"""
배치 스모크테스트 — 여러 환자로 시트형 오탐필터 효과 + 정답개수 대비 검출개수 확인.

지금까지 검증(축방향, 시트형필터)이 전부 환자 1명(ISPY2_242370)에만 의존했던 걸
표본을 넓혀서 재확인한다. 정답(GT) 라벨과 예측 결과를 환자별로 나란히 비교한다.

사용법:
    # val split에서 무작위 N명 자동 선택 (기본값이 이제 실배포 임계값과 동일함)
    python3 batch_smoke_test.py --config ... --weights ... \
        --mama-mia-dir ... --coco-root ... --n-patients 10

    # 환자 직접 지정
    python3 batch_smoke_test.py --config ... --weights ... \
        --mama-mia-dir ... --coco-root ... --patients ISPY2_242370,DUKE_287,NACT_57

    # 실배포와 다른 조건으로 일부러 비교하고 싶을 때만 명시적으로 override
    python3 batch_smoke_test.py ... --score-threshold 0.7 --seg-score-threshold 0.7
"""

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from eval_mri_lora_v3 import load_config, import_medsam3, build_model  # noqa: E402
from build_3d_from_predictions_v9 import (  # noqa: E402
    volume_to_rgb_slices, find_patient_volume, run_pipeline_for_patient,
    check_val_membership,
)
from compute_stage1_metrics import summarize_lesions  # noqa: E402


def sample_val_patients(coco_root: Path, mama_mia_dir: Path, n: int, seed: int):
    """val split에 속하면서 실제 .npy가 있는 mamamia 환자 중 n명 무작위 선택."""
    val_json = coco_root / "val" / "_annotations.coco.json"
    with open(val_json) as f:
        coco = json.load(f)
    pids = set()
    for im in coco["images"]:
        fn = im["file_name"]
        if fn.startswith("mamamia_"):
            # mamamia_ISPY2_242370_z0070.png -> ISPY2_242370
            parts = fn[len("mamamia_"):].rsplit("_z", 1)
            pids.add(parts[0])
    available = [p for p in pids if (mama_mia_dir / "labels" / f"{p}.npy").exists()]
    rng = random.Random(seed)
    rng.shuffle(available)
    return available[:n]


def get_gt_lesion_count(mama_mia_dir: Path, pid: str) -> int:
    lbl_path = mama_mia_dir / "labels" / f"{pid}.npy"
    if not lbl_path.exists():
        return None
    lbl = np.load(lbl_path)
    _, n = summarize_lesions(lbl == 1, pid, "tumor")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--mama-mia-dir", required=True, type=Path)
    ap.add_argument("--duke-dir", required=True, type=Path)  # run_pipeline_for_patient가 요구, mamamia만 써도 인자는 필요
    ap.add_argument("--coco-root", required=True, type=Path)
    ap.add_argument("--n-patients", type=int, default=10)
    ap.add_argument("--patients", default=None, help="쉼표로 직접 지정하면 --n-patients 무시")
    ap.add_argument("--score-threshold", type=float, default=0.5,
                     help="⚠ 2026-09-04 수정 - 실배포 기본값(model_io.py DEFAULTS, "
                          "mri_lora.yaml에 inference: 섹션 없어 이 값이 그대로 적용됨)과 맞춤. "
                          "예전 기본값 0.7은 이 스크립트만의 관행값이었고 실서빙과 달랐음")
    ap.add_argument("--seg-score-threshold", type=float, default=0.5,
                     help="tumor 기준 실배포 값과 동일(0.5). breast는 실배포 0.8이지만 이 스크립트는 "
                          "mamamia(tumor)만 검증하므로 breast 값은 여기서 안 씀")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="results/batch_smoke_test.csv", type=Path)
    args = ap.parse_args()

    args.mama_mia_dir = args.mama_mia_dir.resolve()
    args.duke_dir = args.duke_dir.resolve()
    args.coco_root = args.coco_root.resolve()
    args.config = str(Path(args.config).resolve())
    args.weights = str(Path(args.weights).resolve())
    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.patients:
        patients = [p.strip() for p in args.patients.split(",")]
    else:
        patients = sample_val_patients(args.coco_root, args.mama_mia_dir, args.n_patients, args.seed)

    if not patients:
        sys.exit("대상 환자를 못 찾음 - --mama-mia-dir, --coco-root 경로 확인")

    print(f"대상 환자 {len(patients)}명: {patients}")
    print(f"임계값 — score_threshold={args.score_threshold}, "
          f"seg_score_threshold={args.seg_score_threshold} "
          f"({'실배포와 동일' if args.score_threshold == 0.5 and args.seg_score_threshold == 0.5 else '⚠ 실배포(0.5/0.5)와 다름 - 의도한 게 맞는지 확인'})")

    cfg = load_config(args.config)
    resolution = cfg["data"]["resolution"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("모델 로딩 중...")
    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, args.weights, M, device)
    print("로딩 완료.\n")

    rows = []
    for i, pid in enumerate(patients):
        print(f"\n{'='*60}\n[{i+1}/{len(patients)}] {pid}\n{'='*60}")

        split = check_val_membership(args.coco_root, pid)
        gt_n = get_gt_lesion_count(args.mama_mia_dir, pid)

        try:
            img, dataset_tag = find_patient_volume(args.mama_mia_dir, args.duke_dir, pid)
        except FileNotFoundError as e:
            print(f"  스킵: {e}")
            continue
        if dataset_tag != "mamamia":
            print(f"  스킵: mamamia 소스가 아님({dataset_tag})")
            continue

        rgb_slices = volume_to_rgb_slices(img, dataset_tag)

        # 필터 켠 것
        rows_on, _ = run_pipeline_for_patient(
            model, M, device, resolution, rgb_slices, pid, dataset_tag,
            args.score_threshold, args.seg_score_threshold, raw_img=img,
            apply_flat_filter=True,
        )
        n_on = len(rows_on)

        # 필터 끈 것 (비교용, 추론 다시 안 하려면 캐싱해야 하지만 단순화를 위해 재추론)
        rows_off, _ = run_pipeline_for_patient(
            model, M, device, resolution, rgb_slices, pid, dataset_tag,
            args.score_threshold, args.seg_score_threshold, raw_img=img,
            apply_flat_filter=False,
        )
        n_off = len(rows_off)

        rows.append({
            "patient_id": pid,
            "split": split,
            "gt_lesion_count": gt_n,
            "pred_count_filter_on": n_on,
            "pred_count_filter_off": n_off,
            "filter_removed": n_off - n_on,
            "diff_from_gt_filter_on": (n_on - gt_n) if gt_n is not None else None,
        })
        print(f"  GT={gt_n}  예측(필터ON)={n_on}  예측(필터OFF)={n_off}  "
              f"(필터가 {n_off-n_on}개 제거)")

    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)

    print(f"\n\n{'='*60}\n요약\n{'='*60}")
    print(df.to_string(index=False))
    print(f"\n저장: {args.out}")

    print(f"\n평균 GT 개수: {df['gt_lesion_count'].mean():.2f}")
    print(f"평균 예측(필터ON): {df['pred_count_filter_on'].mean():.2f}")
    print(f"평균 예측(필터OFF): {df['pred_count_filter_off'].mean():.2f}")
    print(f"필터가 평균 {df['filter_removed'].mean():.2f}개씩 제거함")
    print(f"필터ON 기준 GT와의 평균 차이: {df['diff_from_gt_filter_on'].mean():.2f}개 "
          f"(0에 가까울수록 좋음, 양수면 여전히 과다검출)")

    exact_match = (df["pred_count_filter_on"] == df["gt_lesion_count"]).sum()
    print(f"\n필터ON 상태로 GT 개수와 정확히 일치한 환자: {exact_match}/{len(df)}명")


if __name__ == "__main__":
    main()
