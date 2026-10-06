#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""유방 경계로부터의 깊이로 순위를 다시 매긴다 — 먼저 재고, 되면 쓴다.

여기까지의 원칙
  순위를 건드린 시도가 전부 실패했다 — 덩어리 크기, 박스 좁기, 점수 평균,
  영상별 정규화, 교차 질의(여섯 설정 전부, 강하게 쓸수록 단조롭게 악화).
  공통점은 **검출기가 이미 본 정보를 재배열한 것**이라는 데 있다.

  유일하게 성공한 조직 타일 필터는 검출기가 안 보는 정보를 들여왔다 —
  별도 알고리즘이 만든 조직 마스크. 석회 57.9->62.1 · 종괴 56.4->60.5.

  → 순위를 올리려면 검출기가 갖고 있지 않은 정보를 넣어야 한다.

그래서 깊이
  오탐이 공기가 아니라 **유방 경계선**(피부선 · 대흉근 가장자리)에 몰린다는
  것을 확인했다. 조직 필터는 그것을 타일(1008px) 단위로만 걸렀다.
  거리변환으로 화소 단위로 보면 훨씬 날카롭다.

  깊이 = 조직 마스크의 거리변환. 그 영상의 최댓값으로 나눠 0~1 로 만든다.
  영상마다 유방 두께가 다르므로 절대 화소로 비교하면 안 된다.

순서가 중요하다 — 재고 나서 쓴다
  [1] 정답 병변과 오탐의 깊이 분포를 **먼저 찍는다.**
      겹치면 이 방향은 무용이고 거기서 끝난다. 변환을 먼저 만들어 놓고
      숫자를 맞추면 안 된다.
  [2] 분포가 갈리면 그 갈리는 지점으로 설정을 만든다.

원본은 안 건드린다. GPU 는 안 쓴다. DICOM 을 영상당 한 번 읽는다.

사용
  python3 training/code/depth_rescore.py            # [1] 재기만
  python3 training/code/depth_rescore.py --write    # [1] + [2] 파일 만들기
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import cv2
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402


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


def at(depth, box):
    """상자 중심의 정규화 깊이. 영상 밖이면 0."""
    H, W = depth.shape[:2]
    cx, cy = center(box)
    x, y = int(round(cx)), int(round(cy))
    if x < 0 or y < 0 or x >= W or y >= H:
        return 0.0
    return float(depth[y, x])


def pct(v, qs=(5, 10, 25, 50, 75, 90)):
    if not len(v):
        return "없음"
    return " · ".join(f"{q}퍼 {np.percentile(v, q):.3f}" for q in qs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", default="archive/outputs/tile_dets_wbf03_tissue_t30.json")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou-hit", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--write", action="store_true",
                    help="[2] 설정 파일까지 만든다. 없으면 [1] 재기만 한다")
    ap.add_argument("--gates", default="0.02,0.05,0.10,0.20")
    ap.add_argument("--lambdas", default="0.25,0.5")
    ap.add_argument("--mix", default="",
                    help="종류마다 다른 λ 로 한 파일을 만든다. "
                         "예: calcification=0.15,mass=0.35")
    ap.add_argument("--k-sep", type=float, default=0.0,
                    help="λ 를 직접 주는 대신 [1]에서 잰 분리도 × 이 상수로 정한다. "
                         "실측 최적이 두 종류 모두 1.8 근처였다")
    ap.add_argument("--out-dir", default="archive/outputs")
    a = ap.parse_args()

    src = Path(a.dets)
    raw = json.loads(src.read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    print("=" * 84)
    print("깊이로 순위 다시 매기기 — [1] 재고 [2] 되면 쓴다")
    print("=" * 84)
    print(f"원본 {src}")
    print(f"  " + " · ".join(f"{k} {len(raw[k]):,}건" for k in kinds))

    ents = E.load_gt(a.split)
    if not ents:
        die("load_gt 가 비었다.")
    name_of = {v: k for k, v in E.CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}

    by = {k: defaultdict(list) for k in kinds}
    for k in kinds:
        for i, d in enumerate(raw[k]):
            by[k][str(d["img"])].append(i)
    det_keys = set().union(*[set(by[k]) for k in kinds])

    uids = sorted(u for u in ents if str(u) in det_keys)
    if a.n:
        uids = uids[:a.n]
    print(f"  대상 {len(uids):,}장")

    # 결과를 담을 곳
    dep = {k: np.full(len(raw[k]), np.nan) for k in kinds}   # 검출의 깊이
    tp = {k: np.zeros(len(raw[k]), bool) for k in kinds}     # 정답과 맞는가
    gt_dep = {k: [] for k in kinds}                          # 정답 병변의 깊이
    skipped = 0

    print("\n── [1] 화소 읽는 중 (영상당 한 번)")
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            skipped += 1
            continue
        if arr.ndim != 2:
            skipped += 1
            continue
        u8 = E.norm8(arr, a.clip)
        m = E.tissue_mask(u8)
        tb = E.tissue_bbox(m, a.pad)
        if tb is None:
            skipped += 1
            continue
        cx0, cy0, cx1, cy1 = tb
        mc = (m[cy0:cy1, cx0:cx1] > 0).astype(np.uint8)
        # 거리변환 — 경계에서 멀어질수록 큰 값. 영상마다 두께가 다르므로
        # 그 영상의 최댓값으로 나눠 0~1 로 맞춘다.
        dist = cv2.distanceTransform(mc, cv2.DIST_L2, 5)
        mx = float(dist.max())
        depth = dist / mx if mx > 0 else dist

        key = str(uid)
        truth = {k: [] for k in kinds}
        for cid, mp in e["masks"]:
            bb, shape = E.mask_box(mp)
            if bb is None or shape != arr.shape[:2]:   # eval 과 같게 — 다르면 버린다
                continue
            bb = (bb[0] - cx0, bb[1] - cy0, bb[2] - cx0, bb[3] - cy0)
            kind = alias.get(name_of.get(cid))
            if kind in kinds:
                truth[kind].append(bb)
                gt_dep[kind].append(at(depth, bb))

        for k in kinds:
            for j in by[k].get(key, ()):
                b = raw[k][j]["box"]
                dep[k][j] = at(depth, b)
                cx, cy = center(b)
                for g in truth[k]:
                    if (g[0] <= cx <= g[2] and g[1] <= cy <= g[3]) \
                            or iou(b, g) >= a.iou_hit:
                        tp[k][j] = True
                        break
        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()
    if skipped:
        print(f"  못 읽어서 빠진 영상 {skipped}장")

    print("\n── [1] 결과 — 정답 병변과 오탐의 깊이가 갈리는가")
    print("   (0 = 유방 경계 · 1 = 가장 깊은 곳. 영상별 최댓값으로 정규화)")
    usable = True
    sep = {}
    for k in kinds:
        ok = ~np.isnan(dep[k])
        d_tp = dep[k][ok & tp[k]]
        d_fp = dep[k][ok & ~tp[k]]
        g = np.array(gt_dep[k])
        print(f"\n  {k}")
        print(f"    정답 병변  {len(g):>6,}건   {pct(g)}")
        print(f"    맞은 검출  {len(d_tp):>6,}건   {pct(d_tp)}")
        print(f"    틀린 검출  {len(d_fp):>6,}건   {pct(d_fp)}")
        if len(d_tp) and len(d_fp):
            lo = float(np.percentile(d_tp, 5))
            below_tp = float((d_tp < lo).mean())
            below_fp = float((d_fp < lo).mean())
            print(f"    → 맞은 검출의 5퍼 지점({lo:.3f}) 아래에 있는 비율 — "
                  f"맞은 것 {below_tp:.1%} · 틀린 것 {below_fp:.1%}")
            gainish = below_fp - below_tp
            sep[k] = gainish
            print(f"      차이 {gainish:+.1%}  "
                  + ("갈린다. 쓸 여지가 있다" if gainish > 0.03
                     else "거의 안 갈린다. 이 방향은 무용이다"))
            if gainish <= 0.03:
                usable = False
        else:
            usable = False

    if not usable:
        print("\n판단 — 깊이로는 정답과 오탐이 갈리지 않는다. 여기서 접는다.")
        print("       (--write 를 줘도 만들 값어치가 없다)")
    if not a.write:
        print("\n[2] 는 --write 를 줘야 만든다. 위 분포를 보고 결정할 것.")
        return

    print("\n── [2] 설정 파일 만들기")
    gates = [float(x) for x in a.gates.split(",") if x.strip()]
    lams = [float(x) for x in a.lambdas.split(",") if x.strip()]
    made = []

    def emit(tag, keepfn, scorefn):
        obj = {k: v for k, v in raw.items() if k not in kinds}
        cnt = {}
        for k in kinds:
            out = []
            for j, d in enumerate(raw[k]):
                z = dep[k][j]
                if np.isnan(z):            # 못 읽은 영상은 손대지 않는다
                    out.append(d)
                    continue
                if not keepfn(z):
                    continue
                e2 = dict(d)
                e2["score"] = scorefn(float(d["score"]), float(z))
                out.append(e2)
            obj[k] = out
            cnt[k] = len(out)
        dst = Path(a.out_dir) / f"{src.stem}_{tag}.json"
        if dst.resolve() == src.resolve():
            die("출력이 원본과 같다.")
        dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
        print(f"  {dst.name:<52}" + "".join(f"{cnt[k]:>12,}" for k in kinds))
        made.append(str(dst))

    print(f"  {'파일':<52}" + "".join(f"{k[:11]:>12}" for k in kinds))
    for gt_ in gates:
        emit(f"pg{int(round(gt_*100)):03d}", lambda z, t=gt_: z >= t,
             lambda s, z: s)
    for L in lams:
        # 깊을수록 올린다. 최저 (1-L) 배까지만 눌러서 절대 점수를 안 버린다 —
        # 영상별 정규화와 교차 질의가 실패한 원인이 절대 점수를 버린 것이었다.
        emit(f"pw{int(round(L*100)):03d}", lambda z: True,
             lambda s, z, L=L: s * (1.0 - L + L * z))

    # 종류마다 다른 λ 로 한 파일. --k-sep 를 주면 [1]에서 잰 분리도에서 정한다.
    mix = {}
    if a.k_sep > 0:
        mix = {k: round(a.k_sep * sep.get(k, 0.0), 4) for k in kinds}
        print(f"\n  λ 를 분리도 × {a.k_sep} 로 정했다 — "
              + " · ".join(f"{k} {sep.get(k, 0):.3f}→{mix[k]}" for k in kinds))
    elif a.mix:
        for part in a.mix.split(","):
            if "=" not in part:
                die(f"--mix 형식이 틀렸다: {part}  (예: mass=0.35)")
            kk, vv = part.split("=", 1)
            kk = kk.strip()
            if kk not in kinds:
                die(f"--mix 의 {kk} 가 종류 {kinds} 에 없다")
            mix[kk] = float(vv)
    if mix:
        missing = [k for k in kinds if k not in mix]
        if missing:
            die(f"--mix 에 {missing} 가 빠졌다. 종류를 전부 적어야 한다")
        obj = {k: v for k, v in raw.items() if k not in kinds}
        for k in kinds:
            L = mix[k]
            out = []
            for j, d in enumerate(raw[k]):
                z = dep[k][j]
                e2 = dict(d)
                if not np.isnan(z):
                    e2["score"] = float(d["score"]) * (1.0 - L + L * float(z))
                out.append(e2)
            obj[k] = out
        tag = "pwmix" + "".join(f"_{k[:4]}{int(round(mix[k]*100)):03d}" for k in kinds)
        dst = Path(a.out_dir) / f"{src.stem}_{tag}.json"
        if dst.resolve() == src.resolve():
            die("출력이 원본과 같다.")
        dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
        print(f"  {dst.name:<52}"
              + "".join(f"{len(obj[k]):>12,}" for k in kinds))
        made.append(str(dst))

    print("\n다음 — 채점한다")
    print("  python3 training/code/score_dets.py \\\n      " + str(src)
          + " \\\n      " + " \\\n      ".join(made))


if __name__ == "__main__":
    main()
