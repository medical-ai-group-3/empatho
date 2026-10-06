#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""2겹 교차적합 — 후처리 설정을 고른 자료로 채점하지 않는다.

무엇이 문제였나
  조직 타일 문턱 0.30, 깊이 λ(0.15 · 0.35), 점수 임계값을 **전부 시험 집합에서
  골랐다.** 매번 규칙으로 방어했지만(max 가 안 떨어지는 마지막 지점 · 분리도x1.8)
  발표에서 지적당할 여지가 있다. 검증 인덱스(roi_index_*_val.csv)가 없어서
  따로 뺄 자료가 없다.

무엇을 하나
  환자 단위로 반 가른다. 겹 A 에서 셋을 정해 **겹 B 에서 재고**, 뒤바꿔 한 번 더.
  모든 영상이 자기가 관여하지 않은 파라미터로 채점된다.

  환자 단위로 가르는 이유 — 같은 유방의 CC/MLO 가 서로 다른 겹에 들어가면
  한쪽에서 정한 것이 다른 쪽에 새어 든다.

무엇을 고르는 것으로 보나
  ① 깊이 λ (종류별) = K_SEP x 분리도.  분리도는 그 겹에서 잰다
  ② 타일 문턱      = 그 겹에서 max 가 안 떨어지는 가장 높은 값
  ③ 점수 임계값    = 그 겹의 1 FP/영상 지점
  ③ 은 FROC 곡선 자체에는 안 쓰이지만(곡선이 문턱을 훑는다) 운영에 넣는 값이라
  같이 낸다 — 겹마다 얼마나 흔들리는지가 그 값의 신뢰도다.

덤으로 나오는 것
  두 겹이 **독립적으로 같은 값을 고르는가.** 같으면 그 선택이 잡음이 아니라는
  증거이고, 규칙으로 설명하는 것보다 강하다.

화소는 한 번만 읽는다
  검출마다 두 값을 미리 뽑아 캐시에 둔다 —
    tfrac_max  그 검출의 중심을 품는 타일들의 조직 비율 중 최댓값.
               타일 문턱 t 로 거르는 것은 tfrac_max >= t 와 **정확히 같다.**
               그래서 문턱을 아무리 훑어도 DICOM 을 다시 안 읽는다.
    depth      유방 경계로부터의 거리(영상별 최댓값으로 나눈 값)
  캐시가 있으면 그다음부터는 몇 초면 끝난다.

사용
  python3 training/code/crossfit.py                    # 처음엔 화소를 읽는다
  python3 training/code/crossfit.py --folds 5          # 5겹으로
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import cv2
    import numpy as np
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402

K_SEP = 1.8


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


def sep5(tp, fp):
    """정탐 5퍼 지점 아래의 오탐 초과분. 깊이에서 쓴 것과 같은 정의다."""
    if len(tp) == 0 or len(fp) == 0:
        return 0.0
    lo = float(np.percentile(tp, 5))
    return float((fp < lo).mean()) - float((tp < lo).mean())


# ────────────────────────────────────────────────────── 화소 한 번 읽기

def build_cache(a, kinds, raw):
    ents = E.load_gt(a.split)
    name_of = {v: k for k, v in E.CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}

    # uid -> 환자. roi_index CSV 가 유일한 출처다.
    pat = {}
    for f in sorted(glob.glob(f"{E.ROI_INDEX}/roi_index_*_{a.split}.csv")):
        d = pd.read_csv(f)
        for r in d.to_dict("records"):
            uid = str(r["image_path"]).strip().split("/")[-2]
            pat[uid] = str(r["patient_id"])

    by = {k: defaultdict(list) for k in kinds}
    for k in kinds:
        for i, d in enumerate(raw[k]):
            by[k][str(d["img"])].append(i)
    det_keys = set().union(*[set(by[k]) for k in kinds])
    uids = sorted(u for u in ents if str(u) in det_keys)
    if a.n:
        uids = uids[:a.n]
    miss = [u for u in uids if str(u) not in pat]
    if miss:
        die(f"환자를 못 찾은 영상 {len(miss)}장 — 예: {miss[:2]}")

    tf = {k: np.full(len(raw[k]), np.nan) for k in kinds}
    dp = {k: np.full(len(raw[k]), np.nan) for k in kinds}
    tp = {k: np.zeros(len(raw[k]), bool) for k in kinds}
    gt = {k: defaultdict(list) for k in kinds}
    ok_imgs, stride = [], max(1, a.tile - a.overlap)

    print(f"\n── 화소 읽는 중 {len(uids):,}장 (영상당 한 번)")
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            continue
        if arr.ndim != 2:
            continue
        u8 = E.norm8(arr, a.clip)
        m = E.tissue_mask(u8)
        tb = E.tissue_bbox(m, a.pad)
        if tb is None:
            continue
        cx0, cy0, cx1, cy1 = tb
        tsub = m[cy0:cy1, cx0:cx1] > 0
        H, W = tsub.shape[:2]
        area = float(a.tile * a.tile)
        tiles = []
        for ty in E.positions(H, a.tile, stride):
            for tx in E.positions(W, a.tile, stride):
                s = tsub[ty:ty + a.tile, tx:tx + a.tile]
                tiles.append((tx, ty, tx + a.tile, ty + a.tile,
                              float(np.sum(s)) / area))
        dist = cv2.distanceTransform(tsub.astype(np.uint8), cv2.DIST_L2, 5)
        mx = float(dist.max())
        depth = dist / mx if mx > 0 else dist

        key = str(uid)
        ok_imgs.append(key)
        truth = {k: [] for k in kinds}
        for cid, mp in e["masks"]:
            bb, shape = E.mask_box(mp)
            if bb is None or shape != arr.shape[:2]:
                continue
            kind = alias.get(name_of.get(cid))
            if kind in kinds:
                b = (bb[0] - cx0, bb[1] - cy0, bb[2] - cx0, bb[3] - cy0)
                truth[kind].append(b)
                gt[kind][key].append(b)

        for k in kinds:
            for j in by[k].get(key, ()):
                b = raw[k][j]["box"]
                cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
                # 중심을 품는 타일들의 조직 비율 중 최댓값.
                # 문턱 t 로 거르기 == tfrac_max >= t
                best = 0.0
                for tx1, ty1, tx2, ty2, f in tiles:
                    if tx1 <= cx <= tx2 and ty1 <= cy <= ty2 and f > best:
                        best = f
                tf[k][j] = best
                x = int(round(cx)); y = int(round(cy))
                dp[k][j] = (float(depth[y, x]) if 0 <= x < W and 0 <= y < H
                            else 0.0)
                for g in truth[k]:
                    if (g[0] <= cx <= g[2] and g[1] <= cy <= g[3]) \
                            or iou(b, g) >= a.iou_hit:
                        tp[k][j] = True
                        break
        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()
    return dict(tf=tf, dp=dp, tp=tp, gt=gt, imgs=ok_imgs, pat=pat)


def save_cache(path, C, kinds):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    arrs = {}
    for k in kinds:
        arrs[f"tf_{k}"] = C["tf"][k]
        arrs[f"dp_{k}"] = C["dp"][k]
        arrs[f"tp_{k}"] = C["tp"][k]
    np.savez_compressed(p, **arrs)
    side = p.with_suffix(".json")
    side.write_text(json.dumps({
        "imgs": C["imgs"],
        "pat": {u: C["pat"][u] for u in C["imgs"]},
        "gt": {k: {u: [list(map(float, b)) for b in v]
                   for u, v in C["gt"][k].items()} for k in kinds},
    }, ensure_ascii=False))
    print(f"  캐시 저장 -> {p} · {side.name}")


def load_cache(path, kinds):
    p = Path(path)
    side = p.with_suffix(".json")
    if not (p.is_file() and side.is_file()):
        return None
    z = np.load(p)
    j = json.loads(side.read_text())
    return dict(
        tf={k: z[f"tf_{k}"] for k in kinds},
        dp={k: z[f"dp_{k}"] for k in kinds},
        tp={k: z[f"tp_{k}"] for k in kinds},
        gt={k: {u: [tuple(b) for b in v] for u, v in j["gt"][k].items()}
            for k in kinds},
        imgs=j["imgs"], pat=j["pat"])


# ────────────────────────────────────────────────────────────── 채점

def froc_on(dets, gtk, imgs, iou_hit, mode="center"):
    """eval_mammo_det 의 froc · at_fp 를 그대로 쓴다."""
    g = {u: v for u, v in gtk.items() if v and u in imgs}
    n_gt = sum(len(v) for v in g.values())
    if not n_gt:
        return None
    fn = ((lambda p, q: 1.0 if E.center_in(p, q) else 0.0) if mode == "center"
          else (lambda p, q: 1.0 if E.iou(p, q) >= iou_hit else 0.0))
    curve = E.froc(dets, n_gt, len(imgs), fn, g)
    s1, thr = E.at_fp(curve, 1.0)
    return dict(at1=s1, thr=thr, n_gt=n_gt,
                mx=max((s for _, s, _ in curve), default=0.0))


def apply_and_score(raw, C, k, imgs, tfrac, lam, iou_hit, mode="center"):
    keep = []
    for j, d in enumerate(raw[k]):
        u = str(d["img"])
        if u not in imgs:
            continue
        t, z = C["tf"][k][j], C["dp"][k][j]
        if np.isnan(t) or t < tfrac:
            continue
        s = float(d["score"])
        if lam > 0 and not np.isnan(z):
            s *= (1.0 - lam + lam * float(z))
        keep.append(dict(img=u, box=d["box"], score=s))
    keep.sort(key=lambda x: -x["score"])
    return froc_on(keep, C["gt"][k], imgs, iou_hit, mode)


def fit_on(raw, C, k, imgs, fracs, iou_hit, fixed=None):
    """이 겹에서 λ 와 타일 문턱을 고른다. 정답을 쓰지만 이 겹 것만 쓴다.

    fixed 가 주어지면 λ 는 고르지 않는다 — 미리 정해 둔 값으로 보고
    타일 문턱만 고른다. 타일 이득과 깊이 이득을 갈라 보려는 것이다.
    """
    if fixed is not None:
        lam = float(fixed)
    else:
        idx = [j for j, d in enumerate(raw[k]) if str(d["img"]) in imgs
               and not np.isnan(C["dp"][k][j])]
        z = C["dp"][k][idx]
        t = C["tp"][k][idx]
        lam = round(K_SEP * max(0.0, sep5(z[t], z[~t])), 4)

    base = apply_and_score(raw, C, k, imgs, 0.0, lam, iou_hit)
    if base is None:
        return lam, 0.0, None
    best_t, best_at1 = 0.0, base["at1"]
    for f in fracs:
        if f <= 0:
            continue
        r = apply_and_score(raw, C, k, imgs, f, lam, iou_hit)
        if r is None:
            continue
        # max 가 안 떨어지는 가장 높은 문턱. 같으면 @1FP 가 높은 쪽.
        if r["mx"] >= base["mx"] - 1e-9 and (
                f > best_t or (abs(f - best_t) < 1e-9 and r["at1"] > best_at1)):
            best_t, best_at1 = f, r["at1"]
    return lam, best_t, base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", default="archive/outputs/tile_dets_wbf03_tissue.json")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--tile", type=int, default=1008)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--iou-hit", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--folds", type=int, default=2)
    ap.add_argument("--tile-fracs", default="0.05,0.10,0.20,0.25,0.30,0.35,0.40")
    ap.add_argument("--lam", default="fit",
                    help="깊이 λ. 'fit' 이면 겹마다 분리도로 정한다(기본). "
                         "'0' 이면 깊이 가중 없이 타일 필터만. "
                         "'0.15,0.35' 처럼 주면 그 값으로 고정한다 — "
                         "λ 를 미리 정해 둔 것으로 보고 타일 문턱만 고르는 경우")
    ap.add_argument("--cache", default="docs/crossfit_cache.npz")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    fracs = [float(x) for x in a.tile_fracs.split(",") if x.strip()]
    fixed = None
    if a.lam != "fit":
        vals = [float(x) for x in a.lam.split(",") if x.strip()]
        fixed = vals            # 종류 순서대로. 하나만 주면 전부 그 값

    raw = json.loads(Path(a.dets).read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    print("=" * 88)
    print(f"{a.folds}겹 교차적합 — 고른 자료로 채점하지 않는다")
    print("=" * 88)
    print(f"원본 {a.dets}")
    print("  " + " · ".join(f"{k} {len(raw[k]):,}건" for k in kinds))

    C = None if a.rebuild else load_cache(a.cache, kinds)
    if C is None:
        C = build_cache(a, kinds, raw)
        save_cache(a.cache, C, kinds)
    else:
        print(f"  캐시 사용 {a.cache}")
    for k in kinds:
        if len(C["tf"][k]) != len(raw[k]):
            die(f"캐시와 검출 파일의 길이가 다르다 ({k}). --rebuild 로 다시 만들 것.")

    imgs = list(C["imgs"])
    pat = C["pat"]
    pats = sorted({pat[u] for u in imgs})
    print(f"  영상 {len(imgs):,}장 · 환자 {len(pats):,}명")
    print("  깊이 λ  " + ("겹마다 분리도로 정함" if fixed is None
                        else f"고정 {a.lam}"))

    # 환자를 번갈아 배정한다. 환자 단위라 같은 유방의 두 방향이 안 갈린다.
    fold_of = {p: i % a.folds for i, p in enumerate(pats)}
    folds = [set(u for u in imgs if fold_of[pat[u]] == i) for i in range(a.folds)]
    print("  겹 크기 " + " · ".join(f"{len(f)}장" for f in folds))

    hdr = (f"    {'겹':<4}{'λ':>7}{'타일문턱':>10}{'임계값':>9}"
           f"{'자기 겹':>10}{'상대 겹':>10}{'차이':>9}")
    picks = {}
    for k in kinds:
        print(f"\n  {k}")
        print(hdr)
        picks[k] = []
        for i in range(a.folds):
            tr = folds[i]
            te = set().union(*[folds[j] for j in range(a.folds) if j != i])
            fx = (None if fixed is None
                  else (fixed[kinds.index(k)] if len(fixed) == len(kinds)
                        else fixed[0]))
            lam, tfr, _ = fit_on(raw, C, k, tr, fracs, a.iou_hit, fx)
            r_in = apply_and_score(raw, C, k, tr, tfr, lam, a.iou_hit)
            r_out = apply_and_score(raw, C, k, te, tfr, lam, a.iou_hit)
            picks[k].append((lam, tfr))
            thr = r_in["thr"] if r_in and r_in["thr"] is not None else float("nan")
            print(f"    {chr(65+i):<4}{lam:>7.3f}{tfr:>10.2f}{thr:>9.3f}"
                  f"{r_in['at1']:>10.3f}{r_out['at1']:>10.3f}"
                  f"{r_out['at1']-r_in['at1']:>+9.3f}")

        # 겹 밖 채점 — 각 영상을 '그 영상이 없는 겹' 에서 고른 값으로 거른다
        merged = []
        for i in range(a.folds):
            src = i  # 겹 i 에서 고른 값을, 겹 i 에 **없는** 영상에 쓴다
            lam, tfr = picks[k][src]
            for j, d in enumerate(raw[k]):
                u = str(d["img"])
                if u not in imgs or u in folds[src]:
                    continue
                if a.folds > 2:
                    continue     # 2겹일 때만 이 방식이 딱 떨어진다
                t, z = C["tf"][k][j], C["dp"][k][j]
                if np.isnan(t) or t < tfr:
                    continue
                s = float(d["score"])
                if lam > 0 and not np.isnan(z):
                    s *= (1.0 - lam + lam * float(z))
                merged.append(dict(img=u, box=d["box"], score=s))
        if a.folds == 2 and merged:
            merged.sort(key=lambda x: -x["score"])
            oof = froc_on(merged, C["gt"][k], set(imgs), a.iou_hit)
            # 비교 대상 — 전체에서 고르고 전체에서 잰 값(지금 보고 중인 것)
            lam_all, tfr_all, _ = fit_on(raw, C, k, set(imgs), fracs,
                                         a.iou_hit, fx)
            r_all = apply_and_score(raw, C, k, set(imgs), tfr_all, lam_all,
                                    a.iou_hit)
            r_none = apply_and_score(raw, C, k, set(imgs), 0.0, 0.0, a.iou_hit)
            print(f"    {'─'*58}")
            print(f"    후처리 없음                        @1FP {r_none['at1']:.3f}")
            print(f"    전체에서 고르고 전체에서 잼        @1FP {r_all['at1']:.3f}"
                  f"   (λ {lam_all} · 문턱 {tfr_all})   ← 지금 보고 중")
            print(f"    **겹 밖**                          @1FP {oof['at1']:.3f}"
                  f"   ({oof['at1']-r_all['at1']:+.3f})")

    print("\n" + "=" * 88)
    print("읽는 법")
    print("=" * 88)
    print("  · 두 겹이 **같은 타일 문턱과 비슷한 λ** 를 고르면 그 선택은 잡음이 아니다.")
    print("    규칙으로 설명하는 것보다 이쪽이 강한 근거다.")
    print("  · '겹 밖' 이 정직한 값이다. '전체에서 고르고 전체에서 잼' 과의 차이가")
    print("    시험 집합에 맞춘 만큼이고, 그 차이가 작으면 지금 수치를 그대로 써도 된다.")
    print("  · 임계값은 겹마다 다르게 나온다. 그 흔들림이 운영값의 불확실성이다.")


if __name__ == "__main__":
    main()
