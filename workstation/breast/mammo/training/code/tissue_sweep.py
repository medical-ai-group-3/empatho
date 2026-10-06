#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""조직 위에 없는 검출을 걸러낸다 — 얼마나 좋아지고 무엇을 잃는지 잰다.

여기까지 알아낸 것
  A 상자 방식은 사망. 두 번째로 큰 연결 요소의 면적비가 중앙 0.005 이고
    0.1 을 넘는 영상이 598장 중 14장뿐이다. 중간 크기 조각이 없으니
    '큰 요소 몇 개' 는 최대 하나만 남기는 것과 같고, 그건 병변을 자른다.
  B 타일 방식은 된다. 조직 20% 문턱에서 타일 51% 감소, 1FP 민감도
    석회 +0.029 · 종괴 +0.035, 그러면서 max 가 한 칸도 안 떨어졌다.
    = 지금 찾고 있던 병변은 하나도 안 잃었다.

그래서 이번에 더 보는 것
  B 를 0.5 까지 밀어 본다. 0.2 에서 아직 오르는 중이었다.
  C 검출 상자 안의 조직 비율로 거른다. 타일보다 날카롭다 — 공기 위에 뜬
    오탐을 직접 집는다. 이건 타일과 달리 추론을 안 건드리고 후처리로만 된다.
  D 정답 상자 안의 조직 비율을 재서 정답 자체를 검사한다.
    재현이 어긋난 원인(내 max 0.879 vs 참조 0.949)이 여기 있을 수 있다.
    정답 상자가 공기 위에 있으면 그건 좌표가 틀린 것이다.

재추론하지 않는다. 전부 지우기만 하는 규칙이라 저장된 검출에 씌우면
결과가 그대로 나온다. 읽기만 한다.

판정
  ① max 가 떨어지지 않는가   ← 이게 진짜 기준이다. 떨어지면 찾던 병변을 잃은 것
  ② 병변 손실 (재추론까지 갈 때만 문제가 된다. 후처리만 하면 해당 없음)
  ③ 작동점별 민감도 변화
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_mammo_det import CAT, load_gt                                # noqa: E402
from make_tiles import mask_box, norm8, positions, tissue_mask         # noqa: E402
from check_tissue_bbox import bbox_all, inside, n_tiles                # noqa: E402

FP = (0.25, 0.5, 1.0, 2.0, 4.0)
ALIAS = {"calcification": "calc", "calcifications": "calc", "calcs": "calc",
         "masses": "mass", "malignant_mass": "mass"}


def die(*msg):
    print("\n[중단]", *msg)
    sys.exit(2)


def to_cat(k):
    lo = k.lower()
    for c in (k, lo, ALIAS.get(lo, "")):
        if c in CAT:
            return c
    for c in CAT:
        if lo.startswith(c.lower()) or c.lower().startswith(lo):
            return c
    return None


def frac_in(mask, box):
    """상자 안 조직 비율. 영상 밖은 잘라 낸다."""
    H, W = mask.shape[:2]
    x1 = max(0, int(box[0])); y1 = max(0, int(box[1]))
    x2 = min(W, int(np.ceil(box[2]))); y2 = min(H, int(np.ceil(box[3])))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return float(np.mean(mask[y1:y2, x1:x2]))


def tiles_of(mask, box, tile, stride):
    """상자 위 타일 격자와 각 타일의 조직 비율. positions 규약은 make_tiles 와 같다."""
    x1, y1, x2, y2 = box
    out = []
    for oy in positions(y2 - y1, tile, stride):
        for ox in positions(x2 - x1, tile, stride):
            ty, tx = y1 + oy, x1 + ox
            sub = mask[ty:ty + tile, tx:tx + tile]
            out.append((tx, ty, tx + tile, ty + tile,
                        float(np.mean(sub)) if sub.size else 0.0))
    return out


def center(b):
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def in_any(box, tiles):
    cx, cy = center(box)
    for tx1, ty1, tx2, ty2, _f in tiles:
        if tx1 <= cx <= tx2 and ty1 <= cy <= ty2:
            return True
    return False


def center_in(box, o):
    cx, cy = center(box)
    return o[0] <= cx <= o[2] and o[1] <= cy <= o[3]


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def hit(box, g, mode, thr):
    if mode == "center":
        cx, cy = center(box)
        return g[0] <= cx <= g[2] and g[1] <= cy <= g[3]
    return iou(box, g) >= thr


def match(box, boxes, used, mode, thr):
    if mode == "center":
        for j, g in enumerate(boxes):
            if not used[j] and hit(box, g, mode, thr):
                return j
        return -1
    best, bj = thr, -1
    for j, g in enumerate(boxes):
        if used[j]:
            continue
        v = iou(box, g)
        if v >= best:
            best, bj = v, j
    return bj


def froc(dets_sorted, gtk, uids, mode, thr):
    us = set(uids)
    ngt = sum(len(gtk.get(u, ())) for u in us)
    if ngt == 0:
        return {p: float("nan") for p in FP + ("max",)}, 0
    used = {u: [False] * len(gtk.get(u, ())) for u in us}
    n, tp, fp = len(us), 0, 0
    res = {p: 0.0 for p in FP}
    for u, box, _s in dets_sorted:
        if u not in used:
            continue
        j = match(box, gtk.get(u, ()), used[u], mode, thr)
        if j >= 0:
            used[u][j] = True
            tp += 1
        else:
            fp += 1
        r = fp / n
        for p in FP:
            if r <= p:
                res[p] = tp / ngt
    res["max"] = tp / ngt
    return res, ngt


def header(delta):
    s = "    " + " " * 26
    for p in FP:
        s += f"{p:>7}" + ("      Δ" if delta else "")
    return s + "     max      Δmax"


def line(tag, res, base=None):
    s = "    " + str(tag)[:26].ljust(26)
    for p in FP:
        s += f"{res[p]:>7.3f}"
        if base is not None:
            s += f"{res[p]-base[p]:>+7.3f}"
    s += f"{res['max']:>8.3f}"
    if base is not None:
        s += f"{res['max']-base['max']:>+10.3f}"
    return s


# ────────────────────────────────────────────────────────────────── 본체

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=0, help="0 이면 전부")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--tile", type=int, default=1008)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--iou-hit", type=float, default=0.3)
    ap.add_argument("--tile-fracs", default="0.05,0.10,0.20,0.30,0.40,0.50")
    ap.add_argument("--det-fracs", default="0.02,0.05,0.10,0.20,0.30,0.50")
    ap.add_argument("--dets", default="archive/outputs/tile_dets_wbf03_tissue.json")
    ap.add_argument("--ref", default="docs/merge_tissue.json")
    a = ap.parse_args()
    stride = max(1, a.tile - a.overlap)
    tfr = [float(x) for x in a.tile_fracs.split(",") if x.strip()]
    dfr = [float(x) for x in a.det_fracs.split(",") if x.strip()]

    print("=" * 84)
    print("조직 걸러내기 — 재기만 한다. 아무것도 안 바꾼다")
    print("=" * 84)

    # ── 0 준비 ────────────────────────────────────────────────────────────
    print("\n── 0 준비")
    ents = load_gt(a.split)
    if not ents:
        die("load_gt 가 비었다.")
    raw = json.loads(Path(a.dets).read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    det_keys = {str(d["img"]) for k in kinds for d in raw[k]}
    pair = {k: to_cat(k) for k in kinds}
    if any(v is None for v in pair.values()) or len(set(pair.values())) != len(pair):
        die(f"검출 종류를 CAT {list(CAT)} 에 못 잇는다: {pair}")
    id2kind = {CAT[c]: k for k, c in pair.items()}
    print(f"  색인 {len(ents):,}장 · 검출 {sum(len(raw[k]) for k in kinds):,}건 "
          f"· 종류 {pair}")

    def cand(u):
        q = Path(str(ents[u]["dcm"]))
        return {"uid": str(u), "dcm.stem": q.stem, "dcm.name": q.name,
                "dcm 상위": q.parent.name}

    best_s, best_hit = None, -1
    for s in sorted(cand(next(iter(ents)))):
        h = sum(1 for u in ents if cand(u)[s] in det_keys)
        if h > best_hit:
            best_s, best_hit = s, h
    if best_hit < 0.9 * min(len(ents), len(det_keys)):
        die("영상 이름이 안 이어진다.\n"
            f"    검출 예시 {sorted(det_keys)[:3]}\n    색인 예시 {cand(next(iter(ents)))}")
    print(f"  이름 잇기 {best_s} ({best_hit}/{len(ents)})")
    kof = (lambda u: cand(u)[best_s])

    uids = sorted(u for u in ents if kof(u) in det_keys)
    if a.n:
        uids = uids[:a.n]
    print(f"  대상 {len(uids):,}장")

    # 검출을 점수 내림차순으로 굳히고, 영상별 위치를 색인해 둔다
    dets, pos_by, dfrac = {}, {}, {}
    for k in kinds:
        dets[k] = sorted(((str(d["img"]), tuple(map(float, d["box"])),
                           float(d["score"])) for d in raw[k]), key=lambda t: -t[2])
        pb = {}
        for i, x in enumerate(dets[k]):
            pb.setdefault(x[0], []).append(i)
        pos_by[k] = pb
        dfrac[k] = np.full(len(dets[k]), np.nan)

    # ── 1 화소 한 번 읽기 ─────────────────────────────────────────────────
    print("\n── 1 화소 읽는 중 (영상당 한 번)")
    gt = {k: {} for k in kinds}
    box0, keep_t = {}, {t: {} for t in tfr}
    n_box0, n_tile = 0, {t: 0 for t in tfr}
    lost_tile = {t: [] for t in tfr}
    gt_frac = {k: [] for k in kinds}
    lost_detail = {}
    tf_all = []
    outside = skipped = no_gt = 0

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
        H, W = arr.shape[:2]
        m = tissue_mask(norm8(arr, a.clip))
        b = bbox_all(m, a.pad)
        if b is None:
            skipped += 1
            continue
        k = kof(uid)
        box0[k] = b
        n_box0 += n_tiles(b, a.tile, stride)

        truth = []
        for cid, mp in e["masks"]:
            bb, shape = mask_box(mp)
            if bb is None:
                continue
            scaled = bool(shape and tuple(shape) != (H, W))
            if scaled:
                sy, sx = H / shape[0], W / shape[1]
                bb = (bb[0] * sx, bb[1] * sy, bb[2] * sx, bb[3] * sy)
            bb = tuple(map(float, bb))
            kind = id2kind.get(cid)
            truth.append((bb, kind, scaled, shape))
            if kind in gt:
                gt[kind].setdefault(k, []).append(bb)
                gt_frac[kind].append((frac_in(m, bb), scaled, k, bb, (H, W), shape))

        if not truth:
            no_gt += 1
        outside += sum(1 for bb, _k, _s, _sh in truth if not inside(b, bb))

        grid = tiles_of(m, b, a.tile, stride)
        tf_all.extend(g[4] for g in grid)
        for t in tfr:
            kept = [g for g in grid if g[4] >= t]
            keep_t[t][k] = kept
            n_tile[t] += len(kept)
            for bb, kind, _s, _sh in truth:
                if not in_any(bb, kept):
                    lost_tile[t].append((k, bb, kind))
                    lost_detail.setdefault((k, bb), frac_in(m, bb))

        for kk in kinds:                       # C 검출 상자 안 조직 비율
            for j in pos_by[kk].get(k, ()):
                dfrac[kk][j] = frac_in(m, dets[kk][j][1])

        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()

    done = sorted(box0)
    if not done:
        die("잰 영상이 없다.")
    if skipped:
        print(f"  못 읽어서 빠진 영상 {skipped}장")
    if no_gt:
        print(f"  정답 마스크를 못 읽은 영상 {no_gt}장")
    if outside:
        print(f"  ⚠ 현행 상자 밖에 있는 정답 {outside}건 — 상자는 거의 영상 전체인데도")
    for k in kinds:
        print(f"  정답 {k:<14} {sum(len(v) for v in gt[k].values()):,}건")

    tf = np.array(tf_all)
    print("\n  ── 타일의 조직 비율 (현행 상자 위 전체)")
    print("    " + " · ".join(f"{q}퍼 {np.percentile(tf, q):.3f}"
                              for q in (5, 25, 50, 75)))
    for k in kinds:
        d = dfrac[k][~np.isnan(dfrac[k])]
        print(f"  ── {k} 검출 상자 안 조직 비율 · "
              + " · ".join(f"{q}퍼 {np.percentile(d, q):.3f}" for q in (5, 25, 50))
              + f" · 0.05 미만 {100*(d < 0.05).mean():.0f}%")

    # ── D 정답 상자 검사 ─────────────────────────────────────────────────
    print("\n── D 정답 상자가 조직 위에 있는가 (여기가 재현 어긋남의 후보다)")
    for k in kinds:
        g = gt_frac[k]
        if not g:
            continue
        fr = np.array([x[0] for x in g])
        sc = np.array([x[1] for x in g])
        print(f"  {k:<14} {len(fr)}건 · 중앙 {np.median(fr):.3f} · "
              f"조직 5% 미만 {(fr < 0.05).sum()}건 · 크기보정된 것 {sc.sum()}건")
        bad = [x for x in g if x[0] < 0.05]
        if bad:
            print(f"    ↓ 조직 위에 없는 정답 {len(bad)}건 (앞 3건)")
            for f_, s_, kk, bb, hw, sh in bad[:3]:
                print(f"      {str(kk)[:38]} 정답 {tuple(int(v) for v in bb)} "
                      f"영상 {hw[1]}x{hw[0]} 마스크 {sh} 보정 {s_} 조직 {f_:.3f}")

    # ── 2 재현과 기준선 ──────────────────────────────────────────────────
    print("\n── 2 재현 (안 거른 상태)")
    print(header(False))
    for k in kinds:
        for mode in ("center", "iou"):
            res, ngt = froc(dets[k], gt[k], done, mode, a.iou_hit)
            print(line(f"{k} {mode} ({ngt})", res))
    rp = Path(a.ref)
    if rp.is_file():
        rj = json.loads(rp.read_text())
        node = next((rj[x] for x in rj if "wbf" in x and "0.3" in x), None)
        if node:
            print(f"  ── 대조 {a.ref} wbf@0.3")
            for k in kinds:
                for mode in ("center", "iou"):
                    d = node.get(k, {}).get(mode)
                    if d:
                        r = {p: d.get(str(p), float("nan")) for p in FP}
                        r["max"] = d.get("max", float("nan"))
                        print(line(f"{k} {mode}", r))

    def split_by(k, arr, t):
        keep, drop = [], []
        for i, x in enumerate(dets[k]):
            if x[0] not in box0 or np.isnan(arr[i]):
                continue
            (keep if arr[i] >= t else drop).append(x)
        return keep, drop

    def split_tiles(k, kt):
        keep, drop = [], []
        for x in dets[k]:
            if x[0] not in kt:
                continue
            (keep if in_any(x[1], kt[x[0]]) else drop).append(x)
        return keep, drop

    base, base_n = {}, {}
    print("\n── 3 기준선 (현행 상자 안 검출만) — 아래 증감은 전부 이 표 대비")
    print(header(False))
    for k in kinds:
        keep = [x for x in dets[k] if x[0] in box0 and center_in(x[1], box0[x[0]])]
        base_n[k] = len(keep)
        for mode in ("center", "iou"):
            res, _ = froc(keep, gt[k], done, mode, a.iou_hit)
            base[(k, mode)] = res
        print(line(f"{k} center ({len(keep):,})", base[(k, "center")]))
        print(line(f"{k} iou", base[(k, "iou")]))

    def report(tag, splitter, ntiles, lost):
        print(f"\n  {tag}")
        if ntiles is not None:
            print(f"    타일 {n_box0:,} → {ntiles:,} "
                  f"({100*(1-ntiles/max(1, n_box0)):+.0f}%) · 병변 손실 {len(lost)}건")
        print(header(True))
        for k in kinds:
            keep, drop = splitter(k)
            for mode in ("center", "iou"):
                res, _ = froc(keep, gt[k], done, mode, a.iou_hit)
                miss = sum(1 for x in drop
                           if any(hit(x[1], g, mode, a.iou_hit)
                                  for g in gt[k].get(x[0], ())))
                tail = f"  남은 {len(keep):,}/{base_n[k]:,} · 버린 것 중 맞는 것 {miss}"
                print(line(f"{k} {mode}", res, base[(k, mode)]) + tail)

    print("\n" + "=" * 84)
    print("B 타일 문턱 — 조직 비율이 낮은 타일을 버린다 (재추론하면 시간도 준다)")
    print("=" * 84)
    for t in tfr:
        report(f"타일 문턱 {t}", lambda k, t=t: split_tiles(k, keep_t[t]),
               n_tile[t], lost_tile[t])

    print("\n" + "=" * 84)
    print("C 검출 문턱 — 검출 상자 안 조직 비율로 거른다 (순수 후처리, 재추론 불필요)")
    print("=" * 84)
    for t in dfr:
        report(f"검출 문턱 {t}", lambda k, t=t: split_by(k, dfrac[k], t), None, [])

    # ── 4 갈무리 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 84)
    print("갈무리 — max 가 안 떨어지면 '지금 찾던 병변' 은 하나도 안 잃은 것이다")
    print("=" * 84)
    rows = []
    for t in tfr:
        for k in kinds:
            keep, _ = split_tiles(k, keep_t[t])
            r, _ = froc(keep, gt[k], done, "center", a.iou_hit)
            rows.append((f"B 타일 {t}", k, r[1.0], r["max"],
                         base[(k, "center")][1.0], base[(k, "center")]["max"],
                         100 * (1 - n_tile[t] / max(1, n_box0))))
    for t in dfr:
        for k in kinds:
            keep, _ = split_by(k, dfrac[k], t)
            r, _ = froc(keep, gt[k], done, "center", a.iou_hit)
            rows.append((f"C 검출 {t}", k, r[1.0], r["max"],
                         base[(k, "center")][1.0], base[(k, "center")]["max"], 0.0))
    print(f"    {'설정':<14}{'종류':<16}{'@1FP':>8}{'Δ':>8}{'max':>8}{'Δmax':>8}{'타일':>8}")
    for tag, k, v, mx, b, bm, tl in rows:
        flag = "" if mx >= bm - 1e-9 else "   ← max 하락"
        print(f"    {tag:<14}{k:<16}{v:>8.3f}{v-b:>+8.3f}{mx:>8.3f}{mx-bm:>+8.3f}"
              f"{tl:>7.0f}%{flag}")
    if lost_detail:
        print(f"\n  ── 타일에서 잘려 나간 정답 {len(lost_detail)}건과 그 자리의 조직 비율")
        print("     조직 비율이 0 에 가까우면 그 정답 상자는 공기 위에 있다 = 좌표가 틀렸다")
        for (kk, bb), fr in sorted(lost_detail.items(), key=lambda x: x[1])[:10]:
            print(f"      {str(kk)[:38]} {tuple(int(v) for v in bb)} 조직 {fr:.3f}")

    print("\n  C 는 순수 후처리다 — 지금 저장된 검출에 바로 적용할 수 있고 GPU 가 필요 없다.")
    print("  B 는 추론 단계에서 걸러야 시간이 주는데, 결과만 보려면 C 와 같이 후처리로도 된다.")
    print("=" * 84)


if __name__ == "__main__":
    main()
