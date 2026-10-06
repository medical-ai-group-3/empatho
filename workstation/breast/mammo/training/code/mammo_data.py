#!/usr/bin/env python
"""
CBIS-DDSM ROI 데이터셋 — 서술어 헤드 학습용.

입력  build_roi_index.py 가 만든 roi_index_{kind}_{split}.csv
출력  (이미지 3xSxS, 라벨 다중핫)

전처리 — check_preproc.py 로 실측한 결과에 근거한다.

  확인된 것 (조치 불필요)
    PhotometricInterpretation  400/400 MONOCHROME2  -> 반전 불필요
    VOILUTSequence / WindowCenter  없음             -> LUT 적용 불필요
    RescaleSlope / Intercept       없음             -> 애초에 min-max 가 흡수
    BitsStored 16, unsigned

  확인된 문제 (조치함)
    종횡비  중앙 1.13 · 75퍼 1.25 · 90퍼 1.47 · 최대 5.93
            정사각 리사이즈는 4장 중 1장을 1.25배 이상 찌그러뜨린다.
            OVAL 과 ROUND 를 가르는 정보가 바로 그 비율이므로 치명적이다.
            -> pad_square: 긴 변을 size 에 맞추고 짧은 변은 가운데 정렬 후 0 패딩.
               0 은 정규화 후 이미지 최솟값이라 배경과 이어진다.

    이상점  (최대-최소)/(99.9백분위-최소) 중앙 1.066 · 31.7% 가 1.10 이상
            밝은 화소 몇 개가 값 범위를 지배해 조직 대비를 압축한다.
            -> clip_pct: [100-p, p] 백분위로 자른 뒤 정규화.

  두 조치 모두 끌 수 있게 두었다. 고쳤다고 반드시 좋아지는 것은 아니다.
  패딩은 비율을 살리는 대신 화면 일부를 빈 영역으로 만들고, 그것이 격자
  풀링에는 불리할 수 있다. 켜고 끄고 재서 판단할 문제다.

라벨
  label_schema.json 의 축 순서를 그대로 따른다.
    mass  shape(3) + margin(5) + finding(4)  = 12
    calc  calctype(9) + calcdist(4)          = 13
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pydicom
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset

AXES = {"mass": ["shape", "margin", "finding"],
        "calc": ["calctype", "calcdist"]}


def load_schema(schema_path):
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)


def label_columns(schema, kind):
    """스키마의 축 순서대로 컬럼 이름을 만든다. 헤드 출력 순서와 일치한다."""
    cols = []
    for ax in AXES[kind]:
        for cls in schema["axes"][ax]:
            cols.append(f"{ax}__{cls}")
    return cols


def axis_slices(schema, kind):
    """축별 출력 구간. 축 단위 지표를 낼 때 쓴다.  {'shape': (0,3), ...}"""
    out, start = {}, 0
    for ax in AXES[kind]:
        n = len(schema["axes"][ax])
        out[ax] = (start, start + n)
        start += n
    return out


class MammoROIDataset(Dataset):
    def __init__(self, index_csv, schema_path, kind, size=1008,
                 augment=False, skip_binary=True,
                 pad_square=True, clip_pct=99.9):
        self.df = pd.read_csv(index_csv)
        self.schema = load_schema(schema_path)
        self.kind = kind
        self.cols = label_columns(self.schema, kind)
        self.size = size
        self.augment = augment
        self.skip_binary = skip_binary
        self.pad_square = pad_square
        self.clip_pct = clip_pct

        missing = [c for c in self.cols if c not in self.df.columns]
        if missing:
            raise ValueError(f"인덱스에 없는 라벨 컬럼: {missing}")

        big = self.df[(self.df.roi_h > 2000) | (self.df.roi_w > 2000)]
        if len(big):
            print(f"  ! ROI 가 비정상적으로 큰 행 {len(big)}건 "
                  f"(마스크 오인 가능) — 로드 시 이진이면 건너뛴다")

    def __len__(self):
        return len(self.df)

    def _read_roi(self, path):
        arr = pydicom.dcmread(str(path)).pixel_array.astype(np.float32)
        if self.skip_binary and len(np.unique(arr)) <= 2:
            return None

        if self.clip_pct and self.clip_pct < 100:
            lo = float(np.percentile(arr, 100.0 - self.clip_pct))
            hi = float(np.percentile(arr, self.clip_pct))
            if hi <= lo:                      # 거의 균일한 영상 — 절단 포기
                lo, hi = float(arr.min()), float(arr.max())
            arr = np.clip(arr, lo, hi)
        else:
            lo, hi = float(arr.min()), float(arr.max())

        return (arr - lo) / (hi - lo + 1e-8)

    def _resize(self, img):
        """img (1,1,H,W) in [0,1] -> (1,1,S,S)."""
        s = self.size
        if not self.pad_square:
            return F.interpolate(img, size=(s, s), mode="bilinear",
                                 align_corners=False)
        h, w = img.shape[-2:]
        scale = s / max(h, w)
        nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
        img = F.interpolate(img, size=(nh, nw), mode="bilinear",
                            align_corners=False)
        ph, pw = s - nh, s - nw
        top, left = ph // 2, pw // 2
        # 0 = 정규화 후 최솟값. 배경과 이어지므로 인위적 경계가 안 생긴다.
        return F.pad(img, (left, pw - left, top, ph - top), value=0.0)

    def __getitem__(self, i):
        row = self.df.iloc[i]
        arr = self._read_roi(row["roi_file"])

        # 이진(마스크 오인)이면 다음 행으로 대체 — 배치 형태를 깨지 않는다
        tries = 0
        while arr is None and tries < 10:
            i = (i + 1) % len(self.df)
            row = self.df.iloc[i]
            arr = self._read_roi(row["roi_file"])
            tries += 1
        if arr is None:
            arr = np.zeros((self.size, self.size), dtype=np.float32)

        img = self._resize(torch.from_numpy(arr)[None, None])
        img = img[0].repeat(3, 1, 1)                               # 3,S,S

        if self.augment:
            if torch.rand(1).item() < 0.5:
                img = torch.flip(img, dims=[2])                    # 좌우
            if torch.rand(1).item() < 0.5:
                img = torch.flip(img, dims=[1])                    # 상하

        img = (img - 0.5) / 0.5        # inference_lora.py:91 과 동일

        y = torch.tensor([float(row[c]) for c in self.cols], dtype=torch.float32)
        return img, y


def make_datasets(index_dir, schema_path, kind, size=1008,
                  pad_square=True, clip_pct=99.9):
    index_dir = Path(index_dir)
    kw = dict(size=size, pad_square=pad_square, clip_pct=clip_pct)
    tr = MammoROIDataset(index_dir / f"roi_index_{kind}_train.csv",
                         schema_path, kind, augment=True, **kw)
    te = MammoROIDataset(index_dir / f"roi_index_{kind}_test.csv",
                         schema_path, kind, augment=False, **kw)
    return tr, te
