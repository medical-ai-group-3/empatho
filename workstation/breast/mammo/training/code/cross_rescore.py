#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""같은 자리에 있는 다른 질의의 점수로 순위를 다시 매긴다.

왜 이걸 하나
  운영점 @1FP 62% 인데 오탐 무제한에서는 95% 다. 병변은 후보에 들어 있고
  막혀 있는 것은 순위다. VinDr 확대판 종괴는 더 심하다 — max 99.1% 인데
  운영점 40.4% 로, 58.7%p 가 순위 때문에 버려진다.

왜 이 방식인가
  이미 실패한 7가지(덩어리 크기 · 박스 좁기 · 점수 평균 · 영상별 정규화)는
  전부 **박스의 모양**만 봤다. 안에 무엇이 있는지는 안 봤다.

  발표 문서 6-3절 ② — 종괴 영상 3장 전부에서 미세석회 질의가 종괴 위에
  높은 점수를 냈다. 위치는 맞히고 종류를 틀린다.

  그런데 지금은 두 질의를 완전히 따로 줄 세운다. '같은 자리에 다른 질의가
  더 확신하고 있다' 는 정보가 파일 안에 있는데 쓰지 않는다. 이건 모양이
  아니라 **내용**에 관한 정보다.

방식 네 가지
  gate    같은 자리 다른 질의 점수가 더 높으면 버린다 (가장 단순)
  d25/50/100   s / (1 + λ·other)   — 눌러 내리되 버리지는 않는다
  ratio   s / (s + other)          — 상대적 확신만 남긴다

  d 계열은 점수가 항상 양수로 남아 순서만 바뀐다. gate 만 검출을 지운다.

같은 자리인가
  한쪽 중심이 다른 쪽 상자 안에 있거나 IoU 가 문턱을 넘으면 같은 자리로 본다.
  석회는 알갱이, 종괴는 덩어리라 상자 크기가 크게 다르므로 IoU 만으로는
  같은 병변을 놓친다. 그래서 중심 포함을 함께 쓴다.

원본은 안 건드린다. GPU 도 DICOM 도 필요 없다.

사용
  python3 training/code/cross_rescore.py \
      --dets archive/outputs/tile_dets_wbf03_tissue_t30.json
"""

import argparse
import json
import sys
from pathlib import Path


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def center(b):
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def same_spot(a, b, thr):
    ax, ay = center(a)
    if b[0] <= ax <= b[2] and b[1] <= ay <= b[3]:
        return True
    bx, by = center(b)
    if a[0] <= bx <= a[2] and a[1] <= by <= a[3]:
        return True
    return iou(a, b) >= thr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", default="archive/outputs/tile_dets_wbf03_tissue_t30.json")
    ap.add_argument("--overlap-iou", type=float, default=0.3)
    ap.add_argument("--lambdas", default="0.25,0.5,1.0")
    ap.add_argument("--out-dir", default="archive/outputs")
    a = ap.parse_args()

    src = Path(a.dets)
    raw = json.loads(src.read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    if len(kinds) != 2:
        die(f"종류가 두 개여야 한다: {kinds}")
    k1, k2 = kinds
    print(f"원본 {src}")
    print(f"  {k1} {len(raw[k1]):,}건 · {k2} {len(raw[k2]):,}건")

    # 영상별로 모아 둔다
    by = {k: {} for k in kinds}
    for k in kinds:
        for d in raw[k]:
            by[k].setdefault(str(d["img"]), []).append(d)

    # 각 검출에 대해 '같은 자리 다른 질의의 최고 점수' 를 구한다
    other = {k: [] for k in kinds}
    for k, o in ((k1, k2), (k2, k1)):
        n_hit = 0
        for d in raw[k]:
            img = str(d["img"])
            best = 0.0
            for e in by[o].get(img, ()):
                if float(e["score"]) > best and same_spot(d["box"], e["box"],
                                                          a.overlap_iou):
                    best = float(e["score"])
            other[k].append(best)
            if best > 0:
                n_hit += 1
        hi = sum(1 for d, b in zip(raw[k], other[k]) if b > float(d["score"]))
        print(f"  {k:<14} 같은 자리에 다른 질의가 있는 검출 {n_hit:,}/{len(raw[k]):,}"
              f" · 그중 저쪽이 더 높은 것 {hi:,}")

    lam = [float(x) for x in a.lambdas.split(",") if x.strip()]

    def make(tag, fn, drop):
        obj = {}
        for k in raw:
            if k not in kinds:
                obj[k] = raw[k]
        kept = {}
        for k in kinds:
            out = []
            for d, o in zip(raw[k], other[k]):
                s = float(d["score"])
                if drop and o > s:
                    continue
                e = dict(d)
                e["score"] = fn(s, o)
                out.append(e)
            obj[k] = out
            kept[k] = len(out)
        dst = Path(a.out_dir) / f"{src.stem}_{tag}.json"
        if dst.resolve() == src.resolve():
            die("출력이 원본과 같다.")
        dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
        print(f"{dst.name:<48}" + "".join(f"{kept[k]:>12,}" for k in kinds))
        return str(dst)

    print(f"\n{'파일':<48}" + "".join(f"{k[:11]:>12}" for k in kinds))
    made = [make("xgate", lambda s, o: s, True)]
    for L in lam:
        made.append(make(f"xd{int(round(L*100)):03d}",
                         lambda s, o, L=L: s / (1.0 + L * o), False))
    made.append(make("xratio", lambda s, o: s / (s + o) if (s + o) > 0 else 0.0,
                     False))

    print("\n다음 — 채점한다")
    print("  python3 training/code/score_dets.py \\\n      " + str(src)
          + " \\\n      " + " \\\n      ".join(made))


if __name__ == "__main__":
    main()
