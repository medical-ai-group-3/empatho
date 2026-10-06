#!/usr/bin/env python3
"""
mri/ 폴더를 초음파 소켓 구조(archive/docs/serving/training/postprocess_3d)에 맞춰
한 번에 재정리하는 스크립트.

사용법
------
1. 이 스크립트를 mri 폴더의 "부모 디렉터리"에 둔다.
   예: ~/workspace/breast/mri/ 가 있다면, ~/workspace/breast/organize_mri.py 로 둘 것.
   (즉 스크립트와 같은 위치에서 './mri' 가 보여야 함)
2. VS Code 터미널에서:  python organize_mri.py
   - 기본은 DRY RUN(실제로 옮기지 않고 계획만 출력)이다.
   - 결과가 맘에 들면 아래처럼 실제 실행:  python organize_mri.py --apply

주의
----
- 원본을 덮어쓰는 게 아니라 mri/ "내부"에서 폴더만 재배치한다. 그래도 무서우면
  실행 전에 mri 폴더를 통째로 복사해두고 사본에 돌리는 걸 권장한다.
- __pycache__ 와 .cache_cleared_for_3rd 마커 파일은 그냥 삭제한다 (운영에 의미 없는 쓰레기).
- ckpt 4개 중 '_4th_backup'이 안 붙은 best/last를 최신(3차 결과물)으로 간주해서
  training/ckpt로, backup 붙은 건 archive/ckpt로 보낸다. 이름 붙이신 본인 기준과
  다르면 아래 MOVES 딕셔너리에서 직접 고치면 됨.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT_NAME = "mri"

# ------------------------------------------------------------------
# 명시적 이동 매핑: {기존 상대경로: 새 상대경로}
# ------------------------------------------------------------------
MOVES = {
    # --- training: 현재 진행 중인 학습 관련 코드/설정/체크포인트 ---
    "check_negative_balance.py": "training/code/check_negative_balance.py",
    "test_negative_sampling.py": "training/code/test_negative_sampling.py",
    "train_mri_lora.py": "training/code/train_mri_lora.py",
    "run_3rd_training.sh": "training/code/run_3rd_training.sh",
    "schedule_3rd_training.sh": "training/code/schedule_3rd_training.sh",
    "configs/mri_lora.yaml": "training/configs/mri_lora.yaml",
    "ckpt/mri_lora_best.pt": "training/ckpt/mri_lora_best.pt",
    "ckpt/mri_lora_last.pt": "training/ckpt/mri_lora_last.pt",
    "preprocess/preprocess_ambl.py": "training/code/preprocess/preprocess_ambl.py",
    "preprocess/preprocess_duke_density.py": "training/code/preprocess/preprocess_duke_density.py",
    "preprocess/preprocess_mamamia.py": "training/code/preprocess/preprocess_mamamia.py",

    # --- archive: 과거 체크포인트/구버전 코드/전체 로그 ---
    "ckpt/mri_lora_best_4th_backup.pt": "archive/ckpt/mri_lora_best_4th_backup.pt",
    "ckpt/mri_lora_last_4th_backup.pt": "archive/ckpt/mri_lora_last_4th_backup.pt",
    "postprocess_3d/build_3d_from_predictions_v7.py": "archive/code/postprocess_3d/build_3d_from_predictions_v7.py",
    "postprocess_3d/build_3d_from_predictions_v8.py": "archive/code/postprocess_3d/build_3d_from_predictions_v8.py",
    "etc/ambl_patients_filtered.csv": "archive/data/ambl_patients_filtered.csv",
    "etc/BreastDCEDL_AMBL_paitents.csv": "archive/data/BreastDCEDL_AMBL_paitents.csv",

    # --- postprocess_3d: 소켓3 전용 3D 후처리 (초음파엔 없는 파트) ---
    "postprocess_3d/build_3d_from_predictions_v9.py": "postprocess_3d/code/build_3d_from_predictions_v9.py",
    "postprocess_3d/build_coco_from_npy.py": "postprocess_3d/code/build_coco_from_npy.py",
    "postprocess_3d/check_lesion_thickness.py": "postprocess_3d/code/check_lesion_thickness.py",
    "postprocess_3d/compute_stage1_metrics.py": "postprocess_3d/code/compute_stage1_metrics.py",
    "postprocess_3d/eval_mri_lora_v3.py": "postprocess_3d/code/eval_mri_lora_v3.py",
    "postprocess_3d/verify_array_to_ras.py": "postprocess_3d/code/verify_array_to_ras.py",
    "postprocess_3d/verify_array_to_ras_nifti.py": "postprocess_3d/code/verify_array_to_ras_nifti.py",
    "postprocess_3d/verify_coco.py": "postprocess_3d/code/verify_coco.py",
    "visualize_gt_vs_pred.py": "postprocess_3d/code/visualize_gt_vs_pred.py",
    "eval_sample_list.json": "postprocess_3d/eval_sample_list.json",
    "postprocess_3d/stage1_metrics_density.csv": "postprocess_3d/verify_out/stage1_metrics_density.csv",
    "postprocess_3d/stage1_metrics_lesions.csv": "postprocess_3d/verify_out/stage1_metrics_lesions.csv",
    "postprocess_3d/stage1_metrics_lesion_counts.csv": "postprocess_3d/verify_out/stage1_metrics_lesion_counts.csv",
}

# 폴더 전체(glob) 단위로 옮기는 것들: {기존 상대 디렉터리: 새 상대 디렉터리}
DIR_MOVES = {
    "logs": "archive/logs",                                   # 학습 로그 전부
    "postprocess_3d/results": "archive/eval_out/postprocess_3d_results",  # smoke test 결과
}

# 통째로 삭제할 디렉터리 (검증용으로 찍어낸 시각화 이미지 - 기록 가치 없음, 재생성 가능)
DELETE_DIR_CONTENTS = ["verify_out"]

# 빈 채로라도 만들어둘 스캐폴드 (초음파 구조 대칭 맞추기용)
EMPTY_DIRS = [
    "archive/eval_out",
    "docs",
    "serving/ckpt",
    "serving/code",
    "serving/configs",
]

# 그냥 삭제할 것들 (운영에 의미 없는 캐시/마커)
DELETE_DIRS = ["postprocess_3d/__pycache__", "preprocess/__pycache__"]
DELETE_FILES = [".cache_cleared_for_3rd"]

# 재정리 끝난 뒤 비어있으면 지울 원래 폴더들
CLEANUP_IF_EMPTY = ["ckpt", "configs", "etc", "logs", "preprocess",
                     "postprocess_3d/results", "postprocess_3d"]


def find_root(start: Path) -> Path:
    candidate = start / ROOT_NAME
    if candidate.is_dir():
        return candidate
    print(f"[오류] '{ROOT_NAME}' 폴더를 {start} 밑에서 찾을 수 없습니다. "
          f"스크립트를 mri의 부모 디렉터리에 두고 실행하십시오.")
    sys.exit(1)


def plan_actions(root: Path):
    actions = []  # (kind, src, dst)

    for src_rel, dst_rel in MOVES.items():
        src = root / src_rel
        dst = root / dst_rel
        if src.exists():
            actions.append(("move_file", src, dst))
        else:
            actions.append(("skip_missing", src, dst))

    for src_rel, dst_rel in DIR_MOVES.items():
        src_dir = root / src_rel
        dst_dir = root / dst_rel
        if src_dir.is_dir():
            for f in sorted(src_dir.iterdir()):
                if f.is_file():
                    actions.append(("move_file", f, dst_dir / f.name))
        else:
            actions.append(("skip_missing", src_dir, dst_dir))

    for d in EMPTY_DIRS:
        actions.append(("mkdir", root / d, None))

    for d in DELETE_DIRS:
        p = root / d
        if p.exists():
            actions.append(("rmtree", p, None))

    for d in DELETE_DIR_CONTENTS:
        p = root / d
        if p.is_dir():
            actions.append(("rmtree", p, None))

    for f in DELETE_FILES:
        p = root / f
        if p.exists():
            actions.append(("rmfile", p, None))

    return actions


def execute(actions, apply: bool):
    for kind, src, dst in actions:
        if kind == "move_file":
            print(f"  [이동] {src.relative_to(src.anchor)} -> {dst}")
            if apply:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        elif kind == "skip_missing":
            print(f"  [건너뜀-원본없음] {src}")
        elif kind == "mkdir":
            print(f"  [폴더생성] {src}")
            if apply:
                src.mkdir(parents=True, exist_ok=True)
        elif kind == "rmtree":
            print(f"  [삭제-디렉터리] {src}")
            if apply:
                shutil.rmtree(src, ignore_errors=True)
        elif kind == "rmfile":
            print(f"  [삭제-파일] {src}")
            if apply:
                src.unlink(missing_ok=True)


def cleanup_empty(root: Path, apply: bool):
    for d in CLEANUP_IF_EMPTY:
        p = root / d
        if p.is_dir():
            is_empty = not any(p.rglob("*"))
            if is_empty:
                print(f"  [정리-빈폴더삭제] {p}")
                if apply:
                    shutil.rmtree(p, ignore_errors=True)
            else:
                remaining = list(p.rglob("*"))
                print(f"  [주의] {p} 안에 아직 파일이 남아있어 그대로 둡니다: "
                      f"{[str(x.relative_to(p)) for x in remaining]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                         help="실제로 파일을 이동/삭제한다. 없으면 dry-run(계획만 출력).")
    parser.add_argument("--base", default=".",
                         help="mri 폴더의 부모 디렉터리 (기본값: 현재 디렉터리)")
    args = parser.parse_args()

    base = Path(args.base).resolve()
    root = find_root(base)

    mode = "실제 적용" if args.apply else "DRY RUN (미리보기만, --apply 붙이면 실행)"
    print(f"대상: {root}")
    print(f"모드: {mode}\n")

    actions = plan_actions(root)
    execute(actions, apply=args.apply)

    print("\n-- 빈 폴더 정리 --")
    cleanup_empty(root, apply=args.apply)

    if not args.apply:
        print("\n계획만 출력했습니다. 실제로 옮기려면:\n"
              "    python organize_mri.py --apply")
    else:
        print("\n정리 완료. 결과는 mri/ 밑에서 확인하십시오.")


if __name__ == "__main__":
    main()