"""
MAMA-MIA 전처리 스크립트
- pre-contrast(0000) + first post-contrast(0001) 2-phase 고정
- 1x1x1mm 등방성 리샘플링
- phase 전체 mean/std로 z-score 정규화 (원 논문 방식과 동일)
- 환자 단위 5-fold split 생성

실행 전 설치: pip install SimpleITK nibabel numpy scikit-learn --break-system-packages

사용법:
    python preprocess_mamamia.py --root /path/to/MAMA-MIA --out data/mri/mama_mia
"""

import argparse
import json
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from sklearn.model_selection import KFold


def resample_to_isotropic(img: sitk.Image, spacing=(1.0, 1.0, 1.0), is_label=False) -> sitk.Image:
    img = sitk.DICOMOrient(img, "LPS")  # Duke/AMBL과 축 방향 완전 통일
    orig_spacing = img.GetSpacing()
    orig_size = img.GetSize()
    new_size = [
        int(round(orig_size[i] * orig_spacing[i] / spacing[i])) for i in range(3)
    ]
    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(spacing)
    resampler.SetSize(new_size)
    resampler.SetOutputDirection(img.GetDirection())
    resampler.SetOutputOrigin(img.GetOrigin())
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(0)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor if is_label else sitk.sitkLinear)
    return resampler.Execute(img)


def zscore_two_phases(pre: sitk.Image, post: sitk.Image):
    pre_arr = sitk.GetArrayFromImage(pre).astype(np.float32)
    post_arr = sitk.GetArrayFromImage(post).astype(np.float32)
    combined = np.concatenate([pre_arr.ravel(), post_arr.ravel()])
    mean, std = combined.mean(), combined.std()
    std = std if std > 1e-6 else 1.0
    pre_norm = (pre_arr - mean) / std
    post_norm = (post_arr - mean) / std
    return pre_norm, post_norm, float(mean), float(std)


def find_patient_dirs(images_root: Path):
    return sorted([p for p in images_root.iterdir() if p.is_dir()])


def find_phase_files(patient_dir: Path):
    """{dataset}_{id}_0000.nii.gz(pre), _0001.nii.gz(first post) 탐색.
    파일이 폴더로 잡히는 경우(사용자 스크린샷처럼 압축이 폴더로 보이는 케이스)도 처리."""
    candidates = sorted(patient_dir.glob("*_0000.nii*"))
    pre = candidates[0] if candidates else None
    candidates1 = sorted(patient_dir.glob("*_0001.nii*"))
    post = candidates1[0] if candidates1 else None
    return pre, post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="MAMA-MIA 최상위 폴더 (images/, segmentations/ 있는 곳)")
    ap.add_argument("--out", required=True, help="출력 폴더 (예: data/mri/mama_mia)")
    ap.add_argument("--n-splits", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    root = Path(args.root)
    images_root = root / "images"
    seg_root = root / "segmentations" / "expert"
    out_root = Path(args.out)
    out_images = out_root / "images"
    out_labels = out_root / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    norm_stats = {}
    ok_patients = []
    skipped = []

    patient_dirs = find_patient_dirs(images_root)
    print(f"총 {len(patient_dirs)}명 발견")

    for i, pdir in enumerate(patient_dirs):
        pid = pdir.name  # 예: duke_043, ispy1_1060
        pre_fp, post_fp = find_phase_files(pdir)
        seg_fp = seg_root / f"{pid}.nii.gz"
        if not seg_fp.exists():
            # 대소문자 불일치 대응 (images=DUKE_001, segmentations=duke_001 케이스)
            seg_fp = seg_root / f"{pid.lower()}.nii.gz"
        if pre_fp is None or post_fp is None:
            skipped.append((pid, "phase 파일 누락"))
            continue
        if not seg_fp.exists():
            skipped.append((pid, "segmentation 없음"))
            continue

        try:
            pre_img = sitk.ReadImage(str(pre_fp))
            post_img = sitk.ReadImage(str(post_fp))
            seg_img = sitk.ReadImage(str(seg_fp))

            pre_rs = resample_to_isotropic(pre_img, is_label=False)
            post_rs = resample_to_isotropic(post_img, is_label=False)
            seg_rs = resample_to_isotropic(seg_img, is_label=True)

            pre_norm, post_norm, mean, std = zscore_two_phases(pre_rs, post_rs)

            # 2-channel(pre, post) npy로 저장 - 학습 스크립트에서 바로 로드하기 쉽게
            stacked = np.stack([pre_norm, post_norm], axis=0)  # (2, Z, Y, X)
            np.save(out_images / f"{pid}.npy", stacked.astype(np.float32))

            seg_arr = sitk.GetArrayFromImage(seg_rs).astype(np.uint8)
            np.save(out_labels / f"{pid}.npy", seg_arr)

            norm_stats[pid] = {"mean": mean, "std": std}
            ok_patients.append(pid)

        except Exception as e:
            skipped.append((pid, str(e)))
            continue

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(patient_dirs)} 처리, 성공 {len(ok_patients)}, 스킵 {len(skipped)}")

    print(f"\n완료: 성공 {len(ok_patients)}명, 스킵 {len(skipped)}명")
    if skipped:
        print("스킵 사유 상위 10개:")
        for pid, reason in skipped[:10]:
            print(f"  {pid}: {reason}")

    with open(out_root / "normalize_out.json", "w") as f:
        json.dump(norm_stats, f, indent=1)

    with open(out_root / "skipped.json", "w") as f:
        json.dump(skipped, f, indent=1)

    # 환자 단위 5-fold split (seed 고정 - 재현성)
    kf = KFold(n_splits=args.n_splits, shuffle=True, random_state=args.seed)
    ok_patients_arr = np.array(ok_patients)
    for fold, (train_idx, val_idx) in enumerate(kf.split(ok_patients_arr)):
        with open(out_root / f"train_fold{fold}.txt", "w") as f:
            f.write("\n".join(ok_patients_arr[train_idx]))
        with open(out_root / f"val_fold{fold}.txt", "w") as f:
            f.write("\n".join(ok_patients_arr[val_idx]))

    print(f"\n{args.n_splits}-fold split 파일 생성 완료 (train_fold{{0..{args.n_splits-1}}}.txt / val_fold{{0..{args.n_splits-1}}}.txt)")
    print(f"출력 위치: {out_root}")


if __name__ == "__main__":
    main()