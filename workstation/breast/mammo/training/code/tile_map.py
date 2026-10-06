#!/usr/bin/env python
"""
타일 검출 결과의 COCO mAP — 추론을 다시 하지 않는다. GPU 를 안 쓴다.

왜 별도 스크립트인가
  eval_map.py 는 COCO 형식(정수 image_id, 축소 영상 좌표)을 기대한다.
  타일 평가 결과는 유방 영역 좌표계에 UID 로 묶여 있어 그대로 못 넣는다.
  같은 좌표계의 정답을 만들어 붙여야 한다.

정답을 다시 만드는 이유
  검출 좌표가 '유방 영역을 잘라낸' 기준이라, 같은 잘라내기를 재현해야
  정답 박스가 맞는다. 그 함수들을 eval_mammo_det 에서 그대로 가져온다 —
  복사하면 한쪽만 고쳐졌을 때 조용히 어긋난다.
  DICOM 을 읽으므로 영상당 1~2초 걸린다.

읽을 때 주의
  mAP 는 IoU 0.5~0.95 평균이라 박스가 얼마나 딱 맞는지를 강하게 본다.
  미세석회 정답 박스는 흩어진 석회를 감싼 영역이고 판독의마다 다르게 그린다.
  AP50 이 임상 감각에 더 가깝다.

  COCO 의 small/medium/large 기준(32²·96²)은 자연 영상용이다.
  맘모 병변은 대부분 small 로 분류되므로 APs 만 보고 판단하지 마라.

사용
  python3 tile_map.py --dets ../../archive/outputs/tile_dets_last.json
  python3 tile_map.py --dets ... --out ../../docs/tile_map.json
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from eval_mammo_det import PROMPTS, load_gt                       # noqa: E402
from make_tiles import CAT, mask_box, norm8, tissue_bbox, tissue_mask  # noqa: E402

NAME_OF = {v: k for k, v in CAT.items()}
ALIAS = {"calc": "calcification", "mass": "mass"}
CAT_ID = {"mass": 1, "calcification": 2}      # 기존 det/ 와 같은 번호


def build(uids, split, clip, pad):
    """
    (COCO 정답 dict, uid->image_id) 를 만든다.
    좌표계는 유방 영역 기준 — 검출 결과와 같아야 한다.
    """
    import pydicom
    ents = load_gt(split)
    images, anns = [], []
    idmap = {}
    aid = 1
    for i, uid in enumerate(sorted(uids), 1):
        e = ents.get(uid)
        if e is None:
            continue
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            continue
        if arr.ndim != 2:
            continue
        boxes = []
        for cid, mp in e["masks"]:
            b, shp = mask_box(mp)
            if b is not None and shp == arr.shape[:2]:
                boxes.append((cid, b))
        if not boxes:
            continue
        tb = tissue_bbox(tissue_mask(norm8(arr, clip)), pad)
        if tb is None:
            continue
        cx0, cy0, cx1, cy1 = tb
        iid = len(images) + 1
        idmap[uid] = iid
        images.append(dict(id=iid, file_name=f"{uid}.dcm",
                           width=int(cx1 - cx0), height=int(cy1 - cy0)))
        for cid, b in boxes:
            x0, y0 = b[0] - cx0, b[1] - cy0
            w, h = b[2] - b[0], b[3] - b[1]
            anns.append(dict(id=aid, image_id=iid,
                             category_id=CAT_ID[ALIAS[NAME_OF[cid]]],
                             bbox=[float(x0), float(y0), float(w), float(h)],
                             area=float(w * h), iscrowd=0))
            aid += 1
        if i % 20 == 0:
            print(f"\r  정답 재구성 {i}/{len(uids)}   ", end="", flush=True)
    print(f"\r  정답 재구성 {len(images)}장 · 병변 {len(anns)}건        ")
    gt = dict(images=images, annotations=anns,
              categories=[dict(id=v, name=k) for k, v in CAT_ID.items()])
    return gt, idmap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    print("=" * 72)
    print("타일 검출 결과의 COCO mAP")
    print("=" * 72)
    print(f"  검출 {a.dets}")

    raw = json.loads(Path(a.dets).read_text())
    uids = {d["img"] for n in raw for d in raw[n]}
    print(f"  영상 {len(uids)}장")

    gt_dict, idmap = build(uids, a.split, a.clip, a.pad)
    if not gt_dict["annotations"]:
        sys.exit("  정답이 없다")

    dets = []
    dropped = 0
    for name, lst in raw.items():
        cid = CAT_ID.get(name)
        if cid is None:
            continue
        for d in lst:
            iid = idmap.get(d["img"])
            if iid is None:
                dropped += 1
                continue
            x0, y0, x1, y1 = [float(v) for v in d["box"]]
            w, h = x1 - x0, y1 - y0
            if w <= 0 or h <= 0:
                continue
            dets.append(dict(image_id=iid, category_id=cid,
                             bbox=[x0, y0, w, h], score=float(d["score"])))
    print(f"  검출 {len(dets):,}건"
          + (f"   (정답 없는 영상의 검출 {dropped:,}건 제외)" if dropped else ""))

    tmp = Path(a.dets).with_suffix(".gt.json")
    tmp.write_text(json.dumps(gt_dict))
    gt = COCO(str(tmp))
    dt = gt.loadRes(dets)

    summary = {}

    def run(cat_ids, label):
        E = COCOeval(gt, dt, "bbox")
        E.params.imgIds = sorted(idmap.values())
        if cat_ids is not None:
            E.params.catIds = cat_ids
        E.evaluate(); E.accumulate()
        print(f"\n── {label} ──")
        E.summarize()
        s = E.stats
        summary[label] = dict(mAP=float(s[0]), AP50=float(s[1]),
                              AP75=float(s[2]), AR100=float(s[8]))

    run(None, "전체")
    for name, cid in CAT_ID.items():
        if any(d["category_id"] == cid for d in dets):
            run([cid], name)

    print("\n" + "=" * 72)
    print("요약")
    print("=" * 72)
    print(f"  {'':14s} {'mAP':>8s} {'AP50':>8s} {'AP75':>8s} {'AR100':>8s}")
    print("  " + "-" * 50)
    for k, v in summary.items():
        print(f"  {k:14s} {v['mAP']:8.3f} {v['AP50']:8.3f} "
              f"{v['AP75']:8.3f} {v['AR100']:8.3f}")

    print("\n  기준선 (1008 축소 · 전체 미세조정 838M · 에폭 20)")
    print(f"  {'종괴':14s} {0.157:8.3f} {0.370:8.3f} {0.088:8.3f} {0.337:8.3f}")
    print(f"  {'미세석회':14s} {0.002:8.3f} {0.008:8.3f} {0.000:8.3f} {0.162:8.3f}")
    print("\n  ! 기준선은 축소 영상 좌표계에서 쟀다. 좌표계가 다르므로")
    print("    AP50 의 방향(올랐나 내렸나)까지만 읽고, 소수점 비교는 하지 마라.")

    if a.out:
        Path(a.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\n  -> {a.out}")
    tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
