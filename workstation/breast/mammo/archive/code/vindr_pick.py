#!/usr/bin/env python
"""
VinDr-Mammo 에서 받을 영상을 고른다 — 전체를 받지 않는다.

왜 고르나
  전체 20,486장은 수백 GB 다. 우리에게 필요한 것은 두 묶음뿐이다.
    양성  석회(또는 종괴) 박스가 있는 영상
    음성  정상 영상 — CBIS 에 없던 재료다

  정상을 18,082장 다 받으면 학습이 '아무것도 없다' 로 기울고 디스크만 먹는다.
  양성과 비슷한 규모로 맞추는 것이 낫다.

왜 음성이 필요한가
  지금 검출기는 CBIS 로만 학습해서 '이 영상 어딘가에 반드시 병변이 있다' 를
  전제로 배운다. 2,220장 전부에 병변이 있으니 그럴 수밖에 없다.
  정상 영상이 있어야 '없을 때는 없다' 를 배우고, FROC(영상당 오탐 개수별 민감도)
  를 잴 수 있다. 그게 맘모 CAD 의 표준 지표다.

촬영 방식 함정
  CBIS 는 필름 스캔, VinDr 은 디지털이다.
  CBIS(전부 양성) + VinDr(전부 음성) 로 섞으면 검출기가 병변이 아니라
  촬영 방식을 구분하는 법을 배운다.
  VinDr 의 양성도 함께 넣으면 그 지름길이 막힌다 — 그래서 양쪽을 다 고른다.

무엇을 만드나
  vindr_urls.txt      wget -i 로 넘길 URL 목록
  vindr_manifest.csv  받은 뒤 COCO 로 변환할 때 쓸 명세
                      (study_id, image_id, split, 양성 여부, 박스, 소견 종류)

사용
  python3 vindr_pick.py                       # 석회, 음성 1500장
  python3 vindr_pick.py --kind mass
  python3 vindr_pick.py --kind both --n-neg 2000
  python3 vindr_pick.py --check-url           # URL 형식만 확인
"""

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

HOME = Path.home()
LAB = HOME / "workspace/breast/labels"
FIND = LAB / "finding_annotations.csv"
BRST = LAB / "breast-level_annotations.csv"

TPL = ("https://physionet.org/files/vindr-mammo/1.0.0/"
       "images/{study_id}/{image_id}.dicom")

# finding_categories 문자열에서 찾을 말
KEY = {
    "calc": ("Suspicious Calcification",),
    "mass": ("Mass",),
    "both": ("Suspicious Calcification", "Mass"),
}

BOX = ["xmin", "ymin", "xmax", "ymax"]
NORMAL_BIRADS = ("BI-RADS 1", "BI-RADS 2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=list(KEY), default="calc")
    ap.add_argument("--n-neg", type=int, default=1500,
                    help="받을 정상 영상 수 (0 이면 양성만)")
    ap.add_argument("--tpl", default=TPL, help="URL 형식")
    ap.add_argument("--out", default="vindr_urls.txt")
    ap.add_argument("--manifest", default="vindr_manifest.csv")
    ap.add_argument("--mb-per-image", type=float, default=15.0,
                    help="용량 추정용 장당 크기(MB)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check-url", action="store_true",
                    help="URL 형식만 보고 끝낸다")
    a = ap.parse_args()

    for p in (FIND, BRST):
        if not p.is_file():
            sys.exit(f"라벨이 없다: {p}")

    f = pd.read_csv(FIND)
    b = pd.read_csv(BRST)

    need = {"study_id", "image_id", "finding_categories", "split"} | set(BOX)
    miss = need - set(f.columns)
    if miss:
        sys.exit(f"finding_annotations 에 없는 컬럼: {sorted(miss)}")

    print("=" * 74)
    print(f"VinDr 선별 — {a.kind}")
    print("=" * 74)
    print(f"  소견 라벨 {len(f):,}행   유방단위 {len(b):,}행")

    # ── 양성: 목표 소견이 있고 박스가 온전한 행 ────────────────────────
    keys = KEY[a.kind]
    hasbox = f[BOX].notna().all(axis=1)
    ismine = f["finding_categories"].astype(str).apply(
        lambda s: any(k in s for k in keys))
    pos = f[hasbox & ismine].copy()

    print(f"\n■ 양성")
    print(f"  '{' / '.join(keys)}' + 박스   병변 {len(pos):,}건")
    pos_imgs = pos[["study_id", "image_id", "split"]].drop_duplicates()
    print(f"  영상 {len(pos_imgs):,}장  (한 영상에 병변이 여럿일 수 있다)")
    for s, n in pos_imgs["split"].value_counts().items():
        print(f"    {s}: {n:,}장")

    # ── 음성: 소견이 하나도 없고 BI-RADS 1·2 인 영상 ──────────────────
    neg_imgs = pd.DataFrame(columns=["study_id", "image_id", "split"])
    if a.n_neg > 0:
        bcol = next((c for c in b.columns if "birads" in c.lower()), None)
        if bcol is None:
            sys.exit("유방단위 라벨에서 BI-RADS 컬럼을 못 찾았다")

        # 박스가 있는 영상은 어떤 소견이든 제외한다
        with_any = set(map(tuple, f[hasbox][["study_id", "image_id"]].values))
        cand = b[b[bcol].astype(str).isin(NORMAL_BIRADS)].copy()
        cand["_k"] = list(zip(cand["study_id"], cand["image_id"]))
        cand = cand[~cand["_k"].isin(with_any)]

        print(f"\n■ 음성 후보")
        print(f"  BI-RADS 1·2 이고 소견 없음   {len(cand):,}장")

        # 분할 비율을 양성과 맞춘다 — 검증셋이 한쪽으로 쏠리면 안 된다
        rng = np.random.default_rng(a.seed)
        want = {}
        tot_pos = max(1, len(pos_imgs))
        for s, n in pos_imgs["split"].value_counts().items():
            want[s] = int(round(a.n_neg * n / tot_pos))
        picked = []
        scol = "split" if "split" in cand.columns else None
        for s, k in want.items():
            sub = cand[cand[scol] == s] if scol else cand
            if len(sub) == 0:
                print(f"    ! {s} 분할에 후보가 없다")
                continue
            k = min(k, len(sub))
            idx = rng.choice(len(sub), size=k, replace=False)
            picked.append(sub.iloc[idx])
            print(f"    {s}: {k:,}장 선택 (후보 {len(sub):,})")
        if picked:
            neg_imgs = pd.concat(picked)[["study_id", "image_id"] +
                                         ([scol] if scol else [])]
            if scol is None:
                neg_imgs["split"] = "train"

    # ── URL ────────────────────────────────────────────────────────────
    allimg = pd.concat([pos_imgs.assign(positive=1),
                        neg_imgs.assign(positive=0)], ignore_index=True)
    allimg = allimg.drop_duplicates(subset=["study_id", "image_id"])

    urls = [a.tpl.format(study_id=r.study_id, image_id=r.image_id)
            for r in allimg.itertuples()]

    print(f"\n■ 합계")
    print(f"  영상 {len(allimg):,}장  "
          f"(양성 {int(allimg.positive.sum()):,} · 음성 {int((1-allimg.positive).sum()):,})")
    print(f"  예상 용량 약 {len(allimg) * a.mb_per_image / 1024:.0f}GB "
          f"(장당 {a.mb_per_image:.0f}MB 가정)")

    print(f"\n■ URL 표본 — 브라우저에 넣어 받아지는지 먼저 확인해라")
    for u in urls[:3]:
        print(f"  {u}")

    if a.check_url:
        print("\n  --check-url 이라 여기서 끝낸다.")
        return

    Path(a.out).write_text("\n".join(urls) + "\n", encoding="utf-8")

    # 명세 — 받은 뒤 COCO 변환에 쓴다.
    #   영상 목록을 왼쪽에 두어야 음성 행도 split 을 갖는다.
    #   양성은 병변 수만큼 행이 늘어난다 (한 영상에 병변이 여럿일 수 있다).
    man = allimg[["study_id", "image_id", "split", "positive"]].merge(
        pos[["study_id", "image_id", "finding_categories"] + BOX],
        on=["study_id", "image_id"], how="left")
    man.to_csv(a.manifest, index=False)

    nsp = man["split"].isna().sum()
    if nsp:
        print(f"  ! split 이 빈 행 {nsp}건 — 확인이 필요하다")

    print(f"\n  -> {a.out}          {len(urls):,}줄")
    print(f"  -> {a.manifest}   {len(man):,}행 (병변 단위, 음성은 박스가 비어 있다)")

    print("\n" + "=" * 74)
    print("받는 법")
    print("=" * 74)
    print("  PhysioNet 자격증명이 필요하다. 라벨을 받을 때 쓴 계정 그대로다.")
    print()
    print("    mkdir -p ~/workspace/breast/data/vindr")
    print("    cd ~/workspace/breast/data/vindr")
    print(f"    wget -c -nc -x -nH --cut-dirs=4 \\")
    print(f"         --user=<아이디> --ask-password \\")
    print(f"         -i ~/workspace/breast/mammo/{a.out}")
    print()
    print("  -c  끊겨도 이어받기   -nc  이미 받은 건 건너뜀")
    print("  -x -nH --cut-dirs=4  study_id/image_id.dicom 구조로 저장")
    print()
    print("  ! 오래 걸린다. nohup 으로 걸어두는 편이 낫다.")


if __name__ == "__main__":
    main()
