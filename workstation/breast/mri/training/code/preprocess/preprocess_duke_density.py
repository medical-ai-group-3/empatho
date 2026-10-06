"""
Duke 밀도(%) 계산용 전처리 스크립트
- 각 환자 폴더 안에서 DICOM SeriesDescription을 읽어 pre-contrast 시리즈 자동 탐지
- 3D Breast.seg.nrrd(이진) + Dense_and_Vessels.seg.nrrd(라벨1=Vessels,2=Dense) 결합
- 1x1x1mm 등방성 리샘플링(MAMA-MIA와 동일 스펙, 인코더 공유 위해 통일)
- 부피 기반 밀도 %(치밀조직=Dense+Vessels 기준, 순수 Dense 기준 둘 다) 계산

실행 전 설치: pip install SimpleITK pydicom pynrrd numpy pandas --break-system-packages

사용법:
    python preprocess_duke_density.py \
        --dicom-root /path/to/duke_breast_cancer_mri \
        --nrrd-root /path/to/Segmentation_Masks_NRRD \
        --out data/mri/duke_density
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pydicom
import SimpleITK as sitk
import nrrd


def find_pre_contrast_series(patient_dir: Path, debug_log: list):
    """환자 폴더 안 모든 시리즈 폴더를 훑어 pre-contrast 시리즈를 탐지.
    1단계: 'pre' 포함 + 'post' 미포함 (dyn 단어는 요구하지 않음 - 스캐너/시기별 표기가 제각각이라 완화)
    2단계: 1단계 실패 시, 'dyn' 계열 시리즈 중 SeriesNumber가 가장 낮은 것을 pre로 간주
           (조영 전 촬영이 항상 가장 먼저 = 가장 낮은 시리즈 번호라는 임상 관례 이용)
    3단계: 그래도 없으면 전체 시리즈 중 슬라이스 20장 이상, SeriesNumber 최저인 것(로컬라이저 제외 추정)
    """
    series_dirs = [p for p in patient_dir.rglob("*") if p.is_dir()]
    all_series = []  # (dir, desc, n_files, series_number)
    for sdir in series_dirs:
        dcm_files = list(sdir.glob("*.dcm"))
        if not dcm_files:
            continue
        try:
            ds = pydicom.dcmread(str(dcm_files[0]), stop_before_pixels=True)
            desc = str(getattr(ds, "SeriesDescription", "")).lower()
            series_num = int(getattr(ds, "SeriesNumber", 9999))
        except Exception:
            continue
        all_series.append((sdir, desc, len(dcm_files), series_num))

    debug_log.append({"patient": patient_dir.name, "all_series_desc": [s[1] for s in all_series]})

    # 1단계
    tier1 = [s for s in all_series if "pre" in s[1] and "post" not in s[1]]
    if tier1:
        tier1.sort(key=lambda x: -x[2])
        return tier1[0][0], tier1[0][1] + " [tier1]"

    # 2단계
    tier2 = [s for s in all_series if "dyn" in s[1]]
    if tier2:
        tier2.sort(key=lambda x: x[3])  # SeriesNumber 오름차순
        return tier2[0][0], tier2[0][1] + " [tier2:lowest-series-num-dyn]"

    # 3단계
    tier3 = [s for s in all_series if s[2] >= 20]
    if tier3:
        tier3.sort(key=lambda x: x[3])
        return tier3[0][0], tier3[0][1] + " [tier3:fallback-lowest-series-num]"

    return None, None


def resample_to_isotropic(img: sitk.Image, spacing=(1.0, 1.0, 1.0), is_label=False) -> sitk.Image:
    img = sitk.DICOMOrient(img, "LPS")  # 데이터셋 간 축 방향 통일 (AMBL/Duke가 MAMA-MIA와 acquisition plane 다를 수 있음)
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


def resample_to_reference(img: sitk.Image, reference: sitk.Image, is_label=False) -> sitk.Image:
    """마스크를 이미지(reference)의 정확한 그리드(size/spacing/origin/direction)에 강제로 맞춤.
    Breast·Dense_and_Vessels 마스크가 서로 다른 물리범위로 크롭 저장된 경우에도
    항상 동일 shape가 나오도록 보장 - shape mismatch 원천 차단."""
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference)
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(0)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor if is_label else sitk.sitkLinear)
    return resampler.Execute(img)


def load_nrrd_as_sitk(path: Path) -> sitk.Image:
    """pynrrd 수동 파싱 대신 SimpleITK 내장 NRRD 리더 사용
    - 좌표축/방향 처리를 SimpleITK가 알아서 정확히 해줌 (수동 transpose로 인한 axes 에러 방지)"""
    return sitk.ReadImage(str(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dicom-root", required=True, help="Breast_MRI_XXX 폴더들이 있는 위치")
    ap.add_argument("--nrrd-root", required=True, help="Segmentation_Masks_NRRD 위치")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    dicom_root = Path(args.dicom_root)
    nrrd_root = Path(args.nrrd_root)
    out_root = Path(args.out)
    out_images = out_root / "images"
    out_labels = out_root / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    patient_dirs = sorted([p for p in nrrd_root.iterdir() if p.is_dir()])
    print(f"NRRD 마스크 보유 환자: {len(patient_dirs)}명")

    density_rows = []
    skipped = []
    debug_log = []

    for i, pnrrd_dir in enumerate(patient_dirs):
        pid = pnrrd_dir.name  # Breast_MRI_XXX
        breast_fp = pnrrd_dir / f"Segmentation_{pid}_Breast.seg.nrrd"
        dense_fp = pnrrd_dir / f"Segmentation_{pid}_Dense_and_Vessels.seg.nrrd"
        if not breast_fp.exists():
            cands = list(pnrrd_dir.glob("*Breast.seg.nrrd"))
            breast_fp = cands[0] if cands else None
        if not dense_fp.exists():
            cands = list(pnrrd_dir.glob("*Dense_and_Vessels.seg.nrrd"))
            dense_fp = cands[0] if cands else None

        pdicom_dir = dicom_root / pid
        if not pdicom_dir.exists() or breast_fp is None or dense_fp is None:
            skipped.append((pid, "파일 누락(dicom 또는 nrrd)"))
            continue

        series_dir, desc = find_pre_contrast_series(pdicom_dir, debug_log)
        if series_dir is None:
            skipped.append((pid, "pre-contrast 시리즈 탐지 실패"))
            continue

        try:
            reader = sitk.ImageSeriesReader()
            dcm_names = reader.GetGDCMSeriesFileNames(str(series_dir))
            reader.SetFileNames(dcm_names)
            img = reader.Execute()

            breast_img = load_nrrd_as_sitk(breast_fp)
            dense_img = load_nrrd_as_sitk(dense_fp)

            img_rs = resample_to_isotropic(img, is_label=False)
            breast_rs = resample_to_reference(breast_img, img_rs, is_label=True)
            dense_rs = resample_to_reference(dense_img, img_rs, is_label=True)

            img_arr = sitk.GetArrayFromImage(img_rs).astype(np.float32)
            mean, std = img_arr.mean(), img_arr.std()
            std = std if std > 1e-6 else 1.0
            img_norm = (img_arr - mean) / std

            breast_arr = sitk.GetArrayFromImage(breast_rs).astype(np.uint8)
            dense_arr = sitk.GetArrayFromImage(dense_rs).astype(np.uint8)  # 1=Vessels, 2=Dense

            # shape 불일치 체크 (마스크가 이미지랑 다른 그리드일 수 있음 - 주의 필요)
            if img_norm.shape != breast_arr.shape:
                skipped.append((pid, f"shape 불일치: img{img_norm.shape} vs mask{breast_arr.shape}"))
                continue

            np.save(out_images / f"{pid}.npy", img_norm[None].astype(np.float32))  # (1,Z,Y,X)
            label_combined = np.stack([breast_arr, dense_arr], axis=0)  # (2,Z,Y,X): breast, dense_vessels
            np.save(out_labels / f"{pid}.npy", label_combined)

            breast_vox = int((breast_arr == 1).sum())
            vessels_vox = int((dense_arr == 1).sum())
            dense_vox = int((dense_arr == 2).sum())
            density_with_vessels = (vessels_vox + dense_vox) / breast_vox * 100 if breast_vox else None
            density_pure = dense_vox / breast_vox * 100 if breast_vox else None

            density_rows.append({
                "patient_id": pid,
                "series_desc": desc,
                "breast_voxels": breast_vox,
                "vessels_voxels": vessels_vox,
                "dense_voxels": dense_vox,
                "density_with_vessels_pct": density_with_vessels,
                "density_pure_dense_pct": density_pure,
            })

        except Exception as e:
            skipped.append((pid, str(e)))
            continue

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(patient_dirs)} 처리, 성공 {len(density_rows)}, 스킵 {len(skipped)}")

    print(f"\n완료: 성공 {len(density_rows)}명, 스킵 {len(skipped)}명")
    if skipped:
        print("스킵 사유:")
        for pid, reason in skipped:
            print(f"  {pid}: {reason}")

    df = pd.DataFrame(density_rows)
    df.to_csv(out_root / "density_summary.csv", index=False)
    with open(out_root / "skipped.json", "w") as f:
        json.dump(skipped, f, indent=1)
    with open(out_root / "series_debug_log.json", "w") as f:
        json.dump(debug_log, f, indent=1, ensure_ascii=False)

    print(f"\n밀도 요약 CSV: {out_root / 'density_summary.csv'}")
    print(f"출력 위치: {out_root}")


if __name__ == "__main__":
    main()
