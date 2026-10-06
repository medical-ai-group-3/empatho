#!/usr/bin/env python
"""
검출 결과 둘을 같은 영상 집합에서 비교한다 — 추론을 다시 하지 않는다.

왜 필요한가
  에폭 5 는 598장, 에폭 0 은 200장으로 쟀다. 표본이 다르면 "올랐다" 를
  말하기 전에 "같은 사람들인가" 부터 따져야 한다.
  두 결과에 공통으로 들어 있는 영상만 남겨 양쪽을 다시 계산한다.

왜 정답을 다시 만드나
  검출 좌표는 유방 영역을 잘라낸 기준이라, 같은 잘라내기를 재현해야
  정답 박스가 맞는다. 그 함수들을 eval_mammo_det 에서 그대로 가져온다 —
  복사하면 한쪽만 고쳐졌을 때 조용히 어긋난다.
  DICOM 을 읽으므로 영상당 1~2초 걸린다. GPU 는 안 쓴다.

사용
  python3 compare_froc.py --a ../../archive/outputs/tile_dets_last.json \
                          --b ../../archive/outputs/tile_dets_ep0.json
  python3 compare_froc.py --a ... --b ... --label-a "에폭 5" --label-b "에폭 0"
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from eval_det import at_fp, center_in, froc, iou            # noqa: E402
from eval_mammo_det import PROMPTS, load_gt                 # noqa: E402
from make_tiles import CAT, mask_box, norm8, tissue_bbox, tissue_mask  # noqa: E402

FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)


def load_dets(p):
    d = json.loads(Path(p).read_text())
    out = {}
    for name, lst in d.items():
        out[name] = [dict(img=x["img"], box=tuple(x["box"]),
                          score=float(x["score"])) for x in lst]
    return out


def build_gt(uids, split, clip, pad):
    """
    유방 영역 기준 정답 박스. 평가기와 같은 잘라내기를 재현한다.
    """
    import pydicom
    ents = load_gt(split)
    name_of = {v: k for k, v in CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}
    gts = {n: defaultdict(list) for n in PROMPTS}
    ok = 0
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
        cx0, cy0 = tb[0], tb[1]
        for cid, b in boxes:
            gts[alias[name_of[cid]]][uid].append(
                (b[0] - cx0, b[1] - cy0, b[2] - cx0, b[3] - cy0))
        ok += 1
        if i % 20 == 0:
            print(f"\r  정답 재구성 {i}/{len(uids)}   ", end="", flush=True)
    print(f"\r  정답 재구성 {ok}/{len(uids)} 완료      ")
    return gts


def table(rows, labels):
    """rows[label][name][fp] = 민감도"""
    for name in PROMPTS:
        print(f"\n{'='*70}\n{name}\n{'='*70}")
        print(f"  {'영상당 오탐':>12s}  " + "".join(f"{l:>12s}" for l in labels)
              + f"{'차이':>10s}")
        print("  " + "-" * (14 + 12 * len(labels) + 10))
        for t in FP_POINTS:
            vs = [rows[l][name].get(t, 0.0) for l in labels]
            d = vs[1] - vs[0] if len(vs) > 1 else 0.0
            print(f"  {t:12.2f}  " + "".join(f"{v:11.1%} " for v in vs)
                  + f"{d:+9.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou", type=float, default=0.3)
    a = ap.parse_args()

    print("=" * 70)
    print("같은 영상 집합에서 두 결과 비교")
    print("=" * 70)

    A, B = load_dets(a.a), load_dets(a.b)
    ua = {d["img"] for n in A for d in A[n]}
    ub = {d["img"] for n in B for d in B[n]}
    common = ua & ub
    print(f"  {a.label_a}: 영상 {len(ua)}   {a.label_b}: 영상 {len(ub)}")
    print(f"  공통 {len(common)}장 으로 양쪽을 다시 계산한다")
    if not common:
        sys.exit("  공통 영상이 없다")

    gts = build_gt(common, a.split, a.clip, a.pad)

    labels = [a.label_a, a.label_b]
    res = {l: {n: {} for n in PROMPTS} for l in labels}
    for lab, D in ((a.label_a, A), (a.label_b, B)):
        for name in PROMPTS:
            g = {u: v for u, v in gts[name].items() if v and u in common}
            n_gt = sum(len(v) for v in g.values())
            if not n_gt:
                continue
            dets = [d for d in D[name] if d["img"] in common]
            curve = froc(dets, n_gt, len(common),
                         lambda p, q: 1.0 if center_in(p, q) else 0.0, g)
            for t in FP_POINTS:
                res[lab][name][t] = at_fp(curve, t)[0]
            if lab == labels[0]:
                print(f"  {name:14s} 정답 {n_gt}건 / 영상 {len(g)}장")

    print("\n■ 중심 명중 기준")
    table(res, labels)

    print("\n" + "=" * 70)
    print("읽는 법")
    print("=" * 70)
    print("  같은 영상, 같은 정답, 같은 지표다. 차이는 가중치뿐이다.")
    print("  검증 손실이 낮은 쪽이 검출도 나은지 여기서 갈린다 —")
    print("  손실에는 박스·분류·존재 여부가 섞여 있고 FROC 은 순위만 본다.")
    print()
    print("  기준선 (1008 축소 · 전체 미세조정 838M · 에폭 20 · 598장)")
    print("    종괴 57.3%   석회 18.6%     오탐 1개/영상")
    print("    종괴 61.3%   석회 37.3%     오탐 4개/영상")
    print("  ! 기준선은 598장이라 이 표와 표본이 다르다. 참고로만 봐라.")


if __name__ == "__main__":
    main()
