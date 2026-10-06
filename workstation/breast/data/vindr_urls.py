#!/usr/bin/env python
"""
VinDr-Mammo 에서 '병변이 있는 영상'만 골라 다운로드 URL 목록을 만든다.

전체 20,000장 중 89% 는 No Finding 이다. 우리 용도는 병변을 잘라내
파이프라인에 통과시키는 것이므로 소견이 있는 영상만 있으면 된다.
받을 용량이 대략 10분의 1 로 준다.

주의: 사이트의 디렉터리 구조를 눈으로 확인한 뒤 받아라.
      --template 으로 바꿀 수 있게 해두었고, 실행하면 표본 URL 을 찍어준다.
      브라우저 주소창에 그 URL 을 붙여넣어 DICOM 이 받아지면 맞는 것이다.
"""

import argparse, sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas 필요")

DEF_CSV = Path.home() / "workspace/breast/labels/finding_annotations.csv"
DEF_TPL = ("https://physionet.org/files/vindr-mammo/1.0.0/"
           "images/{study_id}/{image_id}.dicom")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEF_CSV))
    ap.add_argument("--out", default="vindr_urls.txt")
    ap.add_argument("--template", default=DEF_TPL)
    ap.add_argument("--all", action="store_true",
                    help="No Finding 까지 전부. 기본은 병변 있는 것만")
    a = ap.parse_args()

    df = pd.read_csv(a.csv)
    need = {"study_id", "image_id"}
    if not need <= set(df.columns):
        sys.exit(f"컬럼 부족: {need} / 실제 {list(df.columns)}")

    print(f"전체 {len(df):,}행")

    if a.all:
        sel = df
        print("  --all : 전부 받는다")
    else:
        box = [c for c in ("xmin", "ymin", "xmax", "ymax") if c in df.columns]
        if len(box) == 4:
            sel = df.dropna(subset=box)
            print(f"  바운딩 박스 있는 행 {len(sel):,}")
        else:
            sel = df[df["finding_birads"].notna()]
            print(f"  등급 있는 행 {len(sel):,}  (박스 컬럼이 없어 등급으로 걸렀다)")

    pairs = sel[["study_id", "image_id"]].drop_duplicates()
    print(f"  고유 영상 {len(pairs):,}장  (전체 {df['image_id'].nunique():,}장 중 "
          f"{100*len(pairs)/max(df['image_id'].nunique(),1):.1f}%)")

    urls = [a.template.format(study_id=s, image_id=i)
            for s, i in pairs.itertuples(index=False)]
    Path(a.out).write_text("\n".join(urls) + "\n", encoding="utf-8")

    print(f"\n목록 저장: {a.out}  ({len(urls):,}줄)")
    print("\n표본 URL — 브라우저에 붙여넣어 받아지는지 먼저 확인하라:")
    for u in urls[:3]:
        print(f"  {u}")
    print("\n받아지지 않으면 사이트의 Files 목록을 보고 --template 을 고쳐라.")
    print("  예: --template 'https://physionet.org/files/vindr-mammo/1.0.0/"
          "images/{study_id}/{image_id}.dicom'")


if __name__ == "__main__":
    main()
