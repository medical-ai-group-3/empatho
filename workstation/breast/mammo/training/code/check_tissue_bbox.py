#!/usr/bin/env python
"""
조직 상자가 얼마나 헛돌고 있는지 잰다 — **아무것도 안 바꾼다.**

무엇이 문제인가
  make_tiles.tissue_bbox 는 마스크 전체의 min/max 를 쓴다.

      ys, xs = np.nonzero(mask)
      return (xs.min()-pad, ys.min()-pad, xs.max()+pad, ys.max()+pad)

  연결 요소 분석이 없다. 필름 스캔 구석의 밝은 점 하나, 각인 글자,
  먼지가 마스크에 남으면 상자가 영상 전체로 늘어난다.

  시연에서 실제로 그랬다 — 3826x6601 영상의 조직 상자가 [0,0,3826,6601],
  즉 영상 전체였다. 타일 45장 중 상당수가 공기만 훑었다.

고칠 방법
  가장 큰 연결 요소만 남기고 상자를 잡는다. 유방은 큰 덩어리 하나이고
  테두리·각인·먼지는 따로 잡힌다.

왜 지금 안 고치나
  조직 상자를 바꾸면 훑는 영역이 바뀌고, 그러면 **지금까지의 검출 수치가
  전부 무효가 된다** (FROC · mAP · 끝단 61.7%). 발표 32일 전이다.
  그래서 먼저 '얼마나 흔한 문제인가' 와 '고쳐도 병변을 안 자르는가' 를
  재고, 그 값을 보고 결정한다.

무엇을 재나
  ① 지금 상자가 영상의 몇 %인가  vs  최대 연결 요소 상자는 몇 %인가
  ② 타일 수가 몇 장에서 몇 장으로 주는가
  ③ **새 상자가 정답 병변을 자르지 않는가**  ← 이게 통과 못 하면 고치면 안 된다

  ③ 이 가장 중요하다. 상자를 줄여서 빨라져도 병변이 밖으로 나가면
  민감도가 떨어진다. 한 건이라도 잘리면 그 방식은 못 쓴다.

GPU 를 안 쓴다. 영상당 화소를 한 번 읽는다.

사용
  python3 check_tissue_bbox.py --n 60
  python3 check_tissue_bbox.py --n 0        # 전부 (598장 · 15분쯤)
"""

import argparse
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_mammo_det import load_gt                       # noqa: E402
from make_tiles import mask_box, norm8, positions, tissue_mask   # noqa: E402


def bbox_all(mask, pad):
    """현행 — 마스크 전체의 min/max. make_tiles.tissue_bbox 와 같다."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    H, W = mask.shape[:2]
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
            min(W, int(xs.max()) + 1 + pad), min(H, int(ys.max()) + 1 + pad))


def bbox_largest(mask, pad):
    """고친 안 — 가장 큰 연결 요소만 보고 상자를 잡는다."""
    m = (mask > 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(stats[k, cv2.CC_STAT_LEFT]), int(stats[k, cv2.CC_STAT_TOP]),
                  int(stats[k, cv2.CC_STAT_WIDTH]), int(stats[k, cv2.CC_STAT_HEIGHT]))
    H, W = mask.shape[:2]
    return (max(0, x - pad), max(0, y - pad),
            min(W, x + w + pad), min(H, y + h + pad))


def n_tiles(box, tile, stride):
    if box is None:
        return 0
    w, h = box[2] - box[0], box[3] - box[1]
    return len(positions(h, tile, stride)) * len(positions(w, tile, stride))


def inside(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=60, help="0 이면 전부")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--tile", type=int, default=1008)
    ap.add_argument("--overlap", type=int, default=256)
    a = ap.parse_args()
    stride = max(1, a.tile - a.overlap)

    print("=" * 76)
    print("조직 상자 점검 — 재기만 한다. 아무것도 안 바꾼다")
    print("=" * 76)

    ents = load_gt(a.split)
    uids = sorted(ents)
    if a.n:
        uids = uids[:a.n]
    print(f"  영상 {len(uids)}장 · 타일 {a.tile}px · 겹침 {a.overlap}px\n")

    rows, cut, no_gt = [], [], 0
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            continue
        if arr.ndim != 2:
            continue
        H, W = arr.shape[:2]
        m = tissue_mask(norm8(arr, a.clip))
        b_now, b_new = bbox_all(m, a.pad), bbox_largest(m, a.pad)
        if b_now is None or b_new is None:
            continue
        area = float(H) * W
        f_now = (b_now[2] - b_now[0]) * (b_now[3] - b_now[1]) / area
        f_new = (b_new[2] - b_new[0]) * (b_new[3] - b_new[1]) / area
        t_now, t_new = n_tiles(b_now, a.tile, stride), n_tiles(b_new, a.tile, stride)

        # ③ 새 상자가 정답 병변을 자르는가 — 원본 좌표계에서 본다
        gts, lost = [], 0
        for _, mp in e["masks"]:
            bb, shape = mask_box(mp)
            if bb is None:
                continue
            if shape and shape != (H, W):        # 마스크 크기가 다르면 비율로 맞춘다
                sy, sx = H / shape[0], W / shape[1]
                bb = (bb[0] * sx, bb[1] * sy, bb[2] * sx, bb[3] * sy)
            gts.append(bb)
            if not inside(b_new, bb):
                lost += 1
        if not gts:
            no_gt += 1
        if lost:
            cut.append((uid, lost, len(gts)))

        rows.append((f_now, f_new, t_now, t_new))
        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()

    if not rows:
        sys.exit("  잰 영상이 없다.")
    fn = np.array([r[0] for r in rows])
    fw = np.array([r[1] for r in rows])
    tn = np.array([r[2] for r in rows])
    tw = np.array([r[3] for r in rows])

    print(f"\n  ── 상자가 영상에서 차지하는 비율")
    print(f"    현행        중앙 {np.median(fn):.1%} · 90퍼 {np.percentile(fn,90):.1%}")
    print(f"    최대요소만  중앙 {np.median(fw):.1%} · 90퍼 {np.percentile(fw,90):.1%}")
    big = float((fn > 0.9).mean())
    print(f"    현행 상자가 영상의 90% 를 넘는 경우  {big:.0%}  ({int(big*len(fn))}장)")

    print(f"\n  ── 타일 수")
    print(f"    현행 {tn.sum():,}장  →  최대요소만 {tw.sum():,}장  "
          f"({(1 - tw.sum()/max(tn.sum(),1)):.0%} 감소)")
    print(f"    영상당 중앙  {int(np.median(tn))} → {int(np.median(tw))}")

    print(f"\n  ── ★ 새 상자가 정답 병변을 자르는가")
    if no_gt:
        print(f"    정답 마스크를 못 읽은 영상 {no_gt}장은 이 검사에서 빠졌다")
    if cut:
        tot = sum(c[1] for c in cut)
        print(f"    ✗ {len(cut)}장에서 병변 {tot}건이 새 상자 밖으로 나간다")
        for uid, k, n in cut[:8]:
            print(f"        {uid[:44]}  {k}/{n}건")
        print("    → 이 방식은 그대로 쓰면 안 된다. 최대 요소만 남기는 대신")
        print("      '큰 요소 몇 개' 를 합치거나 여백을 더 주는 쪽을 봐야 한다.")
    else:
        print(f"    ✓ 잘리는 병변 없음 — 잰 영상 전부에서 정답이 새 상자 안에 있다")

    print("\n  " + "─" * 72)
    gain = 1 - tw.sum() / max(tn.sum(), 1)
    if cut:
        print("  판단 — 병변이 잘린다. 이 형태로는 채택 불가.")
    elif gain < 0.1:
        print(f"  판단 — 타일이 {gain:.0%} 밖에 안 준다. 고칠 값어치가 작다.")
        print("         시연에서 본 그 영상이 예외였을 가능성이 크다.")
    else:
        print(f"  판단 — 병변을 안 자르면서 타일이 {gain:.0%} 준다.")
        print("         속도가 그만큼 빨라지고, 공기에서 나오던 오탐이 줄어")
        print("         같은 오탐 예산에서 민감도가 오를 여지가 있다.")
        print("\n  ⚠ 다만 채택하면 **지금까지의 검출 수치가 전부 무효**다.")
        print("    FROC · mAP · 끝단 61.7% 를 다시 재야 한다 (GPU 83분 + 후속).")
        print("    발표까지 남은 기간과 견줘 결정할 것.")
    print("=" * 76)


if __name__ == "__main__":
    main()
