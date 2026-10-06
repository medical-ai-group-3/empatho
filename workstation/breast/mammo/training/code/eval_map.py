#!/usr/bin/env python
"""
검출 결과에서 COCO mAP 를 낸다 — FROC 과 같은 결과에서, 다시 추론하지 않는다.

왜 필요한가
  맘모그래피 CAD 의 표준 지표는 FROC 이다. 영상당 오탐 개수별 민감도를 보는
  것이 임상 사용 방식에 맞기 때문이다.

  그러나 물체 검출의 공통 언어는 mAP 다. 다른 분야 사람이 성능을 물을 때
  기대하는 숫자이고, 없으면 비교 자체가 안 된다. 둘 다 내는 것이 맞다.

두 지표가 보는 것이 다르다
  mAP    IoU 0.5~0.95 평균. 박스가 얼마나 딱 맞는지를 강하게 본다
  FROC   병변을 찾았는지와 영상당 오탐 개수. 경계 정확도는 덜 본다

  미세석회는 군집이라 박스 경계가 원래 애매하다. 판독의가 그린 경계와
  정확히 겹치는지는 임상적 의미가 적다. 그래서 mAP 가 FROC 보다 낮게
  나오는 것이 정상이고, 낮다고 검출이 실패한 것은 아니다.

크기 구간 주의
  COCO 의 small/medium/large 기준(32²·96² 화소)은 자연 영상에 맞춰진 값이다.
  1024 화면의 석회 박스는 한 변 50px 안팎이라 거의 전부 small 로 분류된다.
  APs 만 보고 판단하면 안 된다.

사용
  python3 eval_map.py                                   # 기준선
  python3 eval_map.py --dets tile_dets.json --ann det_tile1008/annotations/val.json
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
except ImportError:
    sys.exit("pycocotools 가 없다 -> pip install pycocotools")

from paths import ARCHIVE, DATA  # noqa: E402


def to_coco_dets(raw):
    """
    eval_det.py 가 저장한 형식을 COCO 검출 형식으로 옮긴다.

      저장 형식  {"1": [{"img": id, "box": [x0,y0,x1,y1], "score": s}, ...], ...}
      COCO       [{"image_id":, "category_id":, "bbox":[x,y,w,h], "score":}, ...]
    """
    out = []
    for cid, lst in raw.items():
        c = int(cid)
        for d in lst:
            x0, y0, x1, y1 = [float(v) for v in d["box"]]
            w, h = x1 - x0, y1 - y0
            if w <= 0 or h <= 0:
                continue
            out.append(dict(image_id=int(d["img"]), category_id=c,
                            bbox=[x0, y0, w, h], score=float(d["score"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", default=str(DATA / "det/annotations/val.json"))
    ap.add_argument("--dets", default=str(ARCHIVE / "outputs/base_dets.json"))
    ap.add_argument("--out", default="", help="요약을 저장할 경로")
    a = ap.parse_args()

    for p in (a.ann, a.dets):
        if not Path(p).is_file():
            sys.exit(f"없다: {p}")

    print("=" * 74)
    print("COCO mAP — FROC 과 같은 검출 결과에서")
    print("=" * 74)
    print(f"  정답  {a.ann}")
    print(f"  검출  {a.dets}")

    gt = COCO(a.ann)
    cats = {c["id"]: c["name"] for c in gt.loadCats(gt.getCatIds())}
    raw = json.loads(Path(a.dets).read_text())
    dets = to_coco_dets(raw)
    if not dets:
        sys.exit("  검출이 하나도 없다")

    img_ids = sorted({d["image_id"] for d in dets})
    print(f"  범주  {cats}")
    print(f"  검출 {len(dets):,}건 · 영상 {len(img_ids):,}장")

    dt = gt.loadRes(dets)
    summary = {}

    def run(cat_ids, label):
        E = COCOeval(gt, dt, "bbox")
        E.params.imgIds = img_ids
        if cat_ids is not None:
            E.params.catIds = cat_ids
        E.evaluate()
        E.accumulate()
        print(f"\n── {label} ──")
        E.summarize()
        s = E.stats
        summary[label] = dict(mAP=float(s[0]), AP50=float(s[1]), AP75=float(s[2]),
                              APs=float(s[3]), APm=float(s[4]), APl=float(s[5]),
                              AR100=float(s[8]))
        return s

    run(None, "전체")
    for cid, name in cats.items():
        if any(d["category_id"] == cid for d in dets):
            run([cid], name)

    # ── 표 ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("요약")
    print("=" * 74)
    print(f"  {'':12s} {'mAP':>8s} {'AP50':>8s} {'AP75':>8s} {'AR100':>8s}")
    print("  " + "-" * 48)
    for k, v in summary.items():
        print(f"  {k:12s} {v['mAP']:8.3f} {v['AP50']:8.3f} "
              f"{v['AP75']:8.3f} {v['AR100']:8.3f}")

    print("\n" + "=" * 74)
    print("읽는 법")
    print("=" * 74)
    print("  mAP    IoU 0.5~0.95 평균. 박스가 얼마나 딱 맞는지까지 본다")
    print("  AP50   IoU 0.5 하나만. '찾았는가' 에 가까워 임상 감각과 더 맞는다")
    print("  AR100  영상당 100개까지 허용했을 때의 재현율 상한")
    print()
    print("  AP50 은 높은데 mAP 가 낮으면 -> 위치는 찾는데 경계가 헐겁다는 뜻이다.")
    print("  미세석회 군집은 경계가 원래 애매해서 이 모양이 나오는 것이 자연스럽다.")
    print()
    print("  ! COCO 의 small/medium/large 기준(32²·96²)은 자연 영상용이다.")
    print("    맘모 병변은 대부분 small 로 분류되므로 APs 만 보고 판단하지 마라.")
    print()
    print("  ! FROC 의 민감도와 mAP 를 나란히 놓고 비교하지 마라. 다른 값이다.")

    if a.out:
        Path(a.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
