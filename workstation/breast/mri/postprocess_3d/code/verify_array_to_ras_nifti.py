#!/usr/bin/env python3
"""
NIfTI(MAMA-MIA)용 배열좌표 -> RAS 직접 변환 검증 스크립트.
DICOM 시리즈 대신 .nii.gz 파일 하나를 바로 읽는다는 것만 verify_array_to_ras.py와 다름.

사용법:
    python verify_array_to_ras_nifti.py \
        --nifti-path ISPY2_242370_0001.nii.gz \
        --points 69.6,82.3,73.8
"""

import argparse
import SimpleITK as sitk


def resample_get_transform(img, spacing=(1.0, 1.0, 1.0)):
    img = sitk.DICOMOrient(img, "LPS")
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
    resampler.SetInterpolator(sitk.sitkLinear)
    return resampler.Execute(img)


def array_zyx_to_ras(img_resampled, z, y, x):
    lps = img_resampled.TransformContinuousIndexToPhysicalPoint((float(x), float(y), float(z)))
    ras = (-lps[0], -lps[1], lps[2])
    return ras


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nifti-path", required=True)
    ap.add_argument("--points", nargs="+", required=True, help="z,y,x 형식")
    args = ap.parse_args()

    img = sitk.ReadImage(args.nifti_path)
    img_rs = resample_get_transform(img)
    print(f"리샘플링 결과 크기: {img_rs.GetSize()}  spacing: {img_rs.GetSpacing()}")
    print()

    for p in args.points:
        z, y, x = [float(v) for v in p.split(",")]
        ras = array_zyx_to_ras(img_rs, z, y, x)
        print(f"배열좌표 (z={z}, y={y}, x={x})  ->  RAS = ({ras[0]:.2f}, {ras[1]:.2f}, {ras[2]:.2f})")

    print()
    print("이 RAS 값을 Slicer 실측 RAS(병변: R=76.77, A=-21.42, S=-1.07)와 비교하세요.")


if __name__ == "__main__":
    main()
