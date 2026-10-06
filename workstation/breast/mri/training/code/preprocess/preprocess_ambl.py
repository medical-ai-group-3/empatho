"""
AMBL 전처리 스크립트
- pid + 'acq*' DCE 이미지 중 앞 2개 phase(pre + 1st post 추정) 사용
- sus.nii.gz(병변별 instance 라벨) + tum.nii.gz(이진, 악성) 조합
  -> connected component + 환자별 상대 크기 필터링(CSV n_tum개만큼 큰 것부터 채택)
     으로 노이즈 제거한 뒤, sus 병변마다 악성 영역과 겹치면 2(악성)/안 겹치면 1(양성)로 라벨링
- 이미지 그리드에 맞춰 마스크 강제 리샘플링(Duke에서 썼던 방식과 동일, shape mismatch 방지)
- z-score 정규화, 1x1x1mm 등방성 리샘플링

실행 전 설치: pip install SimpleITK nibabel numpy pandas scipy --break-system-packages

사용법:
    python preprocess_ambl.py \
        --images-dir /path/to/ambl/images \
        --labels-dir /path/to/ambl/labels \
        --patient-csv /path/to/BreastDCEDL_AMBL_paitents.csv \
        --out data/mri/ambl_processed
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import SimpleITK as sitk
from scipy import ndimage


def resample_to_isotropic(img, spacing=(1.0, 1.0, 1.0), is_label=False):
    img = sitk.DICOMOrient(img, "LPS")  # 데이터셋 간 축 방향 통일
    orig_spacing = img.GetSpacing()
    orig_size = img.GetSize()
    new_size = [int(round(orig_size[i] * orig_spacing[i] / spacing[i])) for i in range(3)]
    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(spacing)
    resampler.SetSize(new_size)
    resampler.SetOutputDirection(img.GetDirection())
    resampler.SetOutputOrigin(img.GetOrigin())
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(0)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor if is_label else sitk.sitkLinear)
    return resampler.Execute(img)


def resample_to_reference(img, reference, is_label=False):
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference)
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(0)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor if is_label else sitk.sitkLinear)
    return resampler.Execute(img)


def find_acq_phases(images_dir: Path, pid: str, n_phases=2):
    files = sorted(images_dir.glob(f"{pid}acq*.nii*"))
    def acq_num(fp):
        m = re.search(r"acq(\d+)", fp.name)
        return int(m.group(1)) if m else 999
    files.sort(key=acq_num)
    return files[:n_phases]


def build_malignancy_label(sus_arr: np.ndarray, tum_arr: np.ndarray, n_tum_expected: int):
    """sus(instance) + tum(binary, 노이즈 섞임) -> 0=배경,1=양성,2=악성 라벨 생성"""
    tum_bin = (tum_arr > 0).astype(np.uint8)
    labeled, n_components = ndimage.label(tum_bin)
    if n_components == 0:
        malignant_mask = np.zeros_like(tum_bin)
    else:
        sizes = ndimage.sum(tum_bin, labeled, range(1, n_components + 1))
        order = np.argsort(sizes)[::-1]  # 큰 순
        keep_labels = set((order[:n_tum_expected] + 1).tolist()) if n_tum_expected > 0 else set()
        malignant_mask = np.isin(labeled, list(keep_labels)).astype(np.uint8)

    out = np.zeros_like(sus_arr, dtype=np.uint8)
    sus_labels = [v for v in np.unique(sus_arr) if v != 0]
    for lbl in sus_labels:
        region = sus_arr == lbl
        overlap = (region & (malignant_mask > 0)).sum()
        if overlap > 0:
            out[region] = 2  # 악성
        else:
            out[region] = 1  # 양성
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--labels-dir", required=True)
    ap.add_argument("--patient-csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    images_dir = Path(args.images_dir)
    labels_dir = Path(args.labels_dir)
    out_root = Path(args.out)
    out_images = out_root / "images"
    out_labels = out_root / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.patient_csv)

    ok_patients = []
    skipped = []

    for _, row in df.iterrows():
        pid = row["pid"]
        n_tum = int(row["n_tum"])

        phase_files = find_acq_phases(images_dir, pid, n_phases=2)
        sus_fp = labels_dir / f"{pid}_sus.nii.gz"
        tum_fp = labels_dir / f"{pid}_tum.nii.gz"

        if len(phase_files) < 2:
            skipped.append((pid, f"DCE phase 부족({len(phase_files)}개)"))
            continue
        if not sus_fp.exists() or not tum_fp.exists():
            skipped.append((pid, "마스크 파일 없음"))
            continue

        try:
            img0 = sitk.ReadImage(str(phase_files[0]))
            img1 = sitk.ReadImage(str(phase_files[1]))
            sus_img = sitk.ReadImage(str(sus_fp))
            tum_img = sitk.ReadImage(str(tum_fp))

            img0_rs = resample_to_isotropic(img0, is_label=False)
            img1_rs = resample_to_reference(img1, img0_rs, is_label=False)  # phase간 그리드 통일
            sus_rs = resample_to_reference(sus_img, img0_rs, is_label=True)
            tum_rs = resample_to_reference(tum_img, img0_rs, is_label=True)

            arr0 = sitk.GetArrayFromImage(img0_rs).astype(np.float32)
            arr1 = sitk.GetArrayFromImage(img1_rs).astype(np.float32)
            combined = np.concatenate([arr0.ravel(), arr1.ravel()])
            mean, std = combined.mean(), combined.std()
            std = std if std > 1e-6 else 1.0
            arr0n = (arr0 - mean) / std
            arr1n = (arr1 - mean) / std

            sus_arr = sitk.GetArrayFromImage(sus_rs).astype(np.int32)
            tum_arr = sitk.GetArrayFromImage(tum_rs).astype(np.int32)

            label_arr = build_malignancy_label(sus_arr, tum_arr, n_tum)

            if arr0n.shape != label_arr.shape:
                skipped.append((pid, f"shape 불일치 img{arr0n.shape} vs label{label_arr.shape}"))
                continue

            stacked = np.stack([arr0n, arr1n], axis=0).astype(np.float32)
            np.save(out_images / f"{pid}.npy", stacked)
            np.save(out_labels / f"{pid}.npy", label_arr)

            ok_patients.append(pid)

        except Exception as e:
            skipped.append((pid, str(e)))
            continue

    print(f"완료: 성공 {len(ok_patients)}명, 스킵 {len(skipped)}명")
    if skipped:
        print("스킵 사유:")
        for pid, reason in skipped:
            print(f"  {pid}: {reason}")

    with open(out_root / "skipped.json", "w") as f:
        json.dump(skipped, f, indent=1)
    with open(out_root / "ok_patients.txt", "w") as f:
        f.write("\n".join(ok_patients))

    print(f"\n출력 위치: {out_root}")


if __name__ == "__main__":
    main()
