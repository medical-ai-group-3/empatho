#!/usr/bin/env python
"""
CBIS-DDSM ROI 인덱스 생성.

라벨 CSV 의 roi_path 는 TCIA 공식 디렉터리 구조를 가정하지만
실제 다운로드는 SeriesUID 한 단계로 평탄하다. 게다가 한 시리즈 안에
ROI(크롭 영상)와 MASK(이진 마스크)가 같이 들어 있고 파일명 순서가 제각각이다.

  [0] 1-1=MASK 1-2=ROI      [1] 1-1=ROI 1-2=MASK

파일명으로는 구분할 수 없으므로 DICOM 헤더의 Rows/Columns 로 판별한다.
MASK 는 원본 전체 크기(4800x3024 등), ROI 는 작다(168~812).
헤더만 읽으므로 픽셀을 로드하지 않아 빠르다.

출력: roi_index_{mass,calc}_{train,test}.csv
      원본 라벨 컬럼 + roi_file / mask_file(절대경로) + roi_h / roi_w
"""

import sys
from pathlib import Path

try:
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}  ->  pip install pandas pydicom")

RAW = Path.home() / "workspace/breast/data/cbis/raw"
LAB = Path.home() / "workspace/breast/labels/labels"
OUT = Path.home() / "workspace/breast/labels/index"


def pick_roi_and_mask(series_uid):
    """
    시리즈 디렉터리에서 (ROI, MASK) 를 크기로 골라낸다.
    반환: (roi_path, mask_path, h, w)  또는  None
    """
    d = RAW / series_uid
    if not d.exists():
        return None
    files = sorted(d.glob("*.dcm"))
    if not files:
        return None

    sized = []
    for f in files:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True)
            sized.append((int(ds.Rows) * int(ds.Columns), int(ds.Rows), int(ds.Columns), f))
        except Exception:
            continue
    if not sized:
        return None

    sized.sort(key=lambda t: t[0])          # 면적 오름차순
    _, h, w, roi = sized[0]                 # 가장 작은 것 = ROI
    mask = sized[-1][3] if len(sized) > 1 else None
    if mask is roi:
        mask = None
    return roi, mask, h, w


def build(kind, split):
    src = LAB / f"labels_{kind}_{split}.csv"
    if not src.exists():
        print(f"  건너뜀 (없음): {src.name}")
        return
    df = pd.read_csv(src)

    rows, dropped = [], {"디렉터리없음": 0, "파일없음": 0}
    for rec in df.to_dict("records"):
        uid = str(rec["roi_path"]).strip().split("/")[-2]
        got = pick_roi_and_mask(uid)
        if got is None:
            dropped["디렉터리없음"] += 1
            continue
        roi, mask, h, w = got
        rec["roi_file"] = str(roi)
        rec["mask_file"] = str(mask) if mask else ""
        rec["roi_h"], rec["roi_w"] = h, w
        rows.append(rec)

    out_df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"roi_index_{kind}_{split}.csv"
    out_df.to_csv(dst, index=False)

    has_mask = (out_df["mask_file"] != "").sum() if len(out_df) else 0
    print(f"  {kind}/{split}: {len(out_df)}/{len(df)} 건  "
          f"(마스크 있음 {has_mask})  제외 {sum(dropped.values())}")
    if len(out_df):
        print(f"      ROI 크기  h {out_df['roi_h'].min()}~{out_df['roi_h'].max()} "
              f"(중앙 {int(out_df['roi_h'].median())}) · "
              f"w {out_df['roi_w'].min()}~{out_df['roi_w'].max()} "
              f"(중앙 {int(out_df['roi_w'].median())})")
    return out_df


def main():
    print(f"원본 라벨: {LAB}")
    print(f"DICOM   : {RAW}")
    print(f"출력    : {OUT}\n")
    for kind in ("mass", "calc"):
        for split in ("train", "test"):
            build(kind, split)
    print("\n완료 — 학습 코드는 이 인덱스만 읽으면 된다.")


if __name__ == "__main__":
    main()
