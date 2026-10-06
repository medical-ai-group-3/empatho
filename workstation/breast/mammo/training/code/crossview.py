#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""다른 방향(CC/MLO)에서도 잡혔는가로 순위를 다시 매긴다 — 먼저 재고, 되면 쓴다.

왜 이걸 하나
  한 유방을 CC 와 MLO 두 방향에서 찍는다. 실제 병변은 두 영상 모두에
  나타나고, 조직이 겹쳐 생긴 허상은 한쪽에만 나타난다. 상용 CAD 가 전부
  쓰는 방법인데 우리는 안 쓰고 있다.

  이건 검출기가 원리적으로 볼 수 없는 정보다 — 다른 각도의 두 번째 투영.
  지금까지 먹힌 두 조치(조직 타일 필터 · 깊이 가중)와 같은 성격이고,
  실패한 여섯 가지(전부 검출기가 이미 본 것의 재배열)와 다르다.

어떻게 맞추나
  CC 와 MLO 는 서로 다른 투영이라 정확한 대응을 계산하려면 3차원 위치가
  필요하다. 대신 판독의가 실제로 쓰는 규칙을 쓴다 —
  **유두로부터의 거리는 두 방향에서 대체로 보존된다.**

  유두 = 조직 마스크에서 흉벽으로부터 가장 먼 지점.
  흉벽 = 유방이 붙어 있는 세로 가장자리 (좌우 중 조직이 많은 쪽).

  검출 하나마다 유두 거리를 재고, 반대편 영상에서 그 거리 ±띠폭 안에 있는
  같은 종류 검출의 최고 점수를 짝으로 삼는다.

대조군을 반드시 같이 잰다
  띠폭 1.0 은 사실상 무한대다 — "이 유방의 다른 영상 어딘가에 높은 점수가
  있는가" 가 되고, 그건 훨씬 약한 정보다. 좁은 띠와 성능이 같으면 띠 맞추기가
  아무 일도 안 하는 것이므로 그 사실을 알아야 한다.

거리 재는 법도 둘 다 잰다
  px    유두로부터 화소 거리. 두 영상이 같은 배율로 스캔됐다면 이쪽이 맞다.
  norm  유방 크기로 나눈 상대 거리. 배율이 다르면 이쪽이 맞다.
  CBIS 는 필름 스캔이라 PixelSpacing 이 없어 어느 쪽인지 미리 알 수 없다.
  그래서 재서 고른다.

순서
  [1] 짝짓기가 되는가 · 짝 점수가 정답과 오탐을 가르는가를 **먼저** 잰다.
      안 갈리면 거기서 끝이다.
  [2] 갈리면 깊이와 같은 규칙으로 설정을 만든다 — λ = 1.8 x 분리도.

원본은 안 건드린다. GPU 는 안 쓴다. DICOM 을 영상당 한 번 읽는다.

사용
  python3 training/code/crossview.py            # [1] 재기만
  python3 training/code/crossview.py --write    # [1] + [2] 파일 만들기
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

K_SEP = 1.8          # λ = K_SEP x 분리도. 깊이에서 두 종류 모두 이 값이었다.


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


def nipple_of(mask):
    """흉벽 반대쪽 끝 = 유두. (x, y, 흉벽쪽, 유방 깊이) 를 돌려준다.

    유방은 세로 가장자리 하나에 붙어 있다. 좌우 끝 5% 띠의 조직 양을 비교해
    많은 쪽을 흉벽으로 본다. 유두는 거기서 가장 먼 조직 화소들의 중앙이다.
    """
    H, W = mask.shape[:2]
    band = max(1, W // 20)
    left = int(mask[:, :band].sum())
    right = int(mask[:, -band:].sum())
    wall_left = left >= right
    xs = np.arange(W)
    dx = xs if wall_left else (W - 1 - xs)          # 흉벽에서의 가로 거리
    cols = mask.any(axis=0)
    if not cols.any():
        return None
    far = int(dx[cols].max())
    if far <= 0:
        return None
    # 가장 먼 곳에서 1% 안쪽까지를 유두 근처로 본다. 한 화소만 쓰면
    # 스캔 잡음 하나에 유두가 끌려간다.
    tol = max(1, int(round(far * 0.01)))
    sel = cols & (dx >= far - tol)
    ys, xs2 = np.nonzero(mask[:, sel])
    if ys.size == 0:
        return None
    cx = float(np.mean(np.nonzero(sel)[0]))
    cy = float(np.median(ys))
    return cx, cy, ("왼쪽" if wall_left else "오른쪽"), float(far)


def auc(pos, neg):
    """Mann-Whitney AUC. 0.5 면 전혀 안 갈린다."""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    v = np.concatenate([pos, neg])
    r = pd.Series(v).rank().to_numpy()
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def sep5(tp, fp):
    """깊이에서 쓴 것과 같은 분리도 — 정탐 5퍼 지점 아래의 오탐 초과분."""
    if len(tp) == 0 or len(fp) == 0:
        return 0.0, 0.0
    lo = float(np.percentile(tp, 5))
    return lo, float((fp < lo).mean()) - float((tp < lo).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets",
                    default="archive/outputs/tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou-hit", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--tols", default="0.05,0.10,0.20,1.00",
                    help="유두 거리 띠폭(유방 깊이 대비). 1.00 은 사실상 무한대 = 대조군")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out-dir", default="archive/outputs")
    a = ap.parse_args()
    tols = [float(x) for x in a.tols.split(",") if x.strip()]

    src = Path(a.dets)
    raw = json.loads(src.read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    print("=" * 88)
    print("다시점 일치 — [1] 재고 [2] 되면 쓴다")
    print("=" * 88)
    print(f"원본 {src}")
    print("  " + " · ".join(f"{k} {len(raw[k]):,}건" for k in kinds))

    # ── 0 짝짓기 ─────────────────────────────────────────────────────────
    print("\n── 0 짝짓기 (roi_index CSV 의 patient_id · side · view)")
    meta = {}
    for f in sorted(glob.glob(f"{E.ROI_INDEX}/roi_index_*_{a.split}.csv")):
        d = pd.read_csv(f)
        need = ["patient_id", "side", "view", "image_path"]
        if any(c not in d.columns for c in need):
            die(f"{f} 에 {need} 중 일부가 없다: {list(d.columns)}")
        for r in d.to_dict("records"):
            # load_gt 과 **똑같이** uid 를 뽑는다. 다르면 검출과 안 이어진다.
            uid = str(r["image_path"]).strip().split("/")[-2]
            key = (str(r["patient_id"]), str(r["side"]))
            prev = meta.get(uid)
            cur = (key, str(r["view"]))
            if prev is not None and prev != cur:
                print(f"  ! uid {uid[:24]} 가 두 곳을 가리킨다: {prev} vs {cur}")
            meta[uid] = cur
    print(f"  CSV 에서 uid {len(meta):,}개")

    det_keys = set()
    for k in kinds:
        det_keys |= {str(d["img"]) for d in raw[k]}
    hit = len(det_keys & set(meta))
    print(f"  검출 영상 {len(det_keys):,}장 중 {hit:,}장이 CSV 와 이어진다")
    if hit < 0.9 * len(det_keys):
        die("이어지는 영상이 너무 적다. uid 뽑는 방식이 load_gt 와 다른지 볼 것.\n"
            f"    검출 예시 {sorted(det_keys)[:2]}\n    CSV 예시 {sorted(meta)[:2]}")

    breast = defaultdict(dict)              # (환자, 좌우) -> {방향: uid}
    for uid, (key, view) in meta.items():
        if uid in det_keys:
            breast[key][view] = uid
    both = {k: v for k, v in breast.items() if len(v) >= 2}
    partner = {}
    for k, v in both.items():
        vs = list(v.items())
        for i, (vi, ui) in enumerate(vs):
            others = [uj for j, (vj, uj) in enumerate(vs) if j != i]
            partner[ui] = others
    n_paired = sum(1 for u in det_keys if u in partner)
    print(f"  유방 {len(breast):,}개 중 두 방향이 다 있는 것 {len(both):,}개")
    print(f"  → 짝이 있는 영상 {n_paired:,}/{len(det_keys):,}장 "
          f"({100*n_paired/max(1,len(det_keys)):.0f}%)")
    if n_paired == 0:
        die("짝이 있는 영상이 없다. 이 방향은 쓸 수 없다.")
    vcnt = defaultdict(int)
    for _uid, (_k, view) in meta.items():
        vcnt[view] += 1
    print(f"  방향 분포 {dict(vcnt)}")

    # ── 1 화소 한 번 읽기 — 유두와 거리 ──────────────────────────────────
    ents = E.load_gt(a.split)
    name_of = {v: k for k, v in E.CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}
    by = {k: defaultdict(list) for k in kinds}
    for k in kinds:
        for i, d in enumerate(raw[k]):
            by[k][str(d["img"])].append(i)

    uids = sorted(u for u in ents if str(u) in det_keys)
    if a.n:
        uids = uids[:a.n]
    print(f"\n── 1 화소 읽는 중 {len(uids):,}장 (영상당 한 번)")

    rpx = {k: np.full(len(raw[k]), np.nan) for k in kinds}   # 유두 거리 (화소)
    rnm = {k: np.full(len(raw[k]), np.nan) for k in kinds}   # 유두 거리 (상대)
    tpf = {k: np.zeros(len(raw[k]), bool) for k in kinds}
    walls = defaultdict(int)
    has_gt = {k: set() for k in kinds}      # 그 종류의 정답이 실제로 있는 영상
    fars, skipped = [], 0
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
        mc = m[cy0:cy1, cx0:cx1] > 0
        nip = nipple_of(mc)
        if nip is None:
            skipped += 1
            continue
        nx, ny, wall, far = nip
        walls[wall] += 1
        fars.append(far)

        key = str(uid)
        truth = {k: [] for k in kinds}
        for cid, mp in e["masks"]:
            bb, shape = E.mask_box(mp)
            if bb is None or shape != arr.shape[:2]:
                continue
            kind = alias.get(name_of.get(cid))
            if kind in kinds:
                truth[kind].append((bb[0] - cx0, bb[1] - cy0,
                                    bb[2] - cx0, bb[3] - cy0))
        for k in kinds:
            if truth[k]:
                has_gt[k].add(key)
            for j in by[k].get(key, ()):
                b = raw[k][j]["box"]
                bx, byy = center(b)
                d = float(np.hypot(bx - nx, byy - ny))
                rpx[k][j] = d
                rnm[k][j] = d / far if far > 0 else 0.0
                cx, cy = bx, byy
                for g in truth[k]:
                    if (g[0] <= cx <= g[2] and g[1] <= cy <= g[3]) \
                            or iou(b, g) >= a.iou_hit:
                        tpf[k][j] = True
                        break
        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()
    if skipped:
        print(f"  못 읽어서 빠진 영상 {skipped}장")
    print(f"  흉벽 쪽 분포 {dict(walls)}")
    # px 로 띠를 잡을 때의 기준 길이. 영상마다 유방 깊이가 다르므로
    # 전체 중앙값 하나를 쓴다 — 정답을 안 보고 정할 수 있는 값이다.
    far_med = float(np.median(fars)) if fars else 1.0
    print(f"  유방 깊이 중앙 {far_med:,.0f}px "
          f"(5퍼 {np.percentile(fars,5):,.0f} · 95퍼 {np.percentile(fars,95):,.0f})")

    # ── 짝 점수 계산 ─────────────────────────────────────────────────────
    def partner_scores(k, rr, tol, scale):
        """검출마다 반대편 영상의 같은 띠 안 최고 점수. 짝이 없으면 nan."""
        out = np.full(len(raw[k]), np.nan)
        pos = by[k]
        for img, idxs in pos.items():
            others = partner.get(img)
            if not others:
                continue
            cand = []
            for o in others:
                for j in pos.get(o, ()):
                    if not np.isnan(rr[k][j]):
                        cand.append((rr[k][j], float(raw[k][j]["score"])))
            if not cand:
                for j in idxs:
                    out[j] = 0.0
                continue
            cr = np.array([c[0] for c in cand])
            cs = np.array([c[1] for c in cand])
            for j in idxs:
                r = rr[k][j]
                if np.isnan(r):
                    continue
                near = np.abs(cr - r) <= tol * scale
                out[j] = float(cs[near].max()) if near.any() else 0.0
        return out

    print("\n── 1 결과 — 짝 점수가 정답과 오탐을 가르는가")
    print("   (띠폭 1.00 은 사실상 무한대 = 대조군. 좁은 띠와 같으면 띠가 무의미하다)")
    best = {}
    for k in kinds:
        print(f"\n  {k}")
        okm = ~np.isnan(rpx[k])
        havep = np.array([str(d["img"]) in partner for d in raw[k]])
        base = okm & havep
        print(f"    짝이 있는 검출 {int(base.sum()):,}/{len(raw[k]):,}"
              f" · 그중 정답과 맞는 것 {int((base & tpf[k]).sum()):,}")
        # 정답이 있는 영상으로만 한정한 AUC 를 같이 낸다.
        # CBIS 는 석회 사례와 종괴 사례의 영상 집합이 겹치지 않는다. 그래서
        # 짝 점수가 '이 유방이 어느 사례인가' 를 맞히고 있을 수 있는데, 그건
        # 자료 구성이 만든 지름길이지 임상 정보가 아니다 — 실제 배포에서는
        # 그 영상이 어느 사례인지 모른다. 한정했을 때 AUC 가 0.5 로 무너지면
        # 그 지름길을 타고 있었던 것이다.
        ing = np.array([str(d["img"]) in has_gt[k] for d in raw[k]])
        print(f"    정답이 있는 영상의 검출 {int((base & ing).sum()):,} "
              f"/ 전체 {int(base.sum()):,}")
        print(f"    {'거리':<6}{'띠폭':<8}{'AUC':>8}{'분리도':>10}{'λ':>8}"
              f"{'짝 있음':>10}{'정답영상만 AUC':>16}")
        # norm 은 영상별 유방 깊이로 이미 나눠 놓았으므로 띠폭이 그대로 쓰인다.
        # px 는 원 화소 거리라 띠폭을 길이로 환산해야 한다 — 유방 깊이 중앙값을
        # 쓴다. 정답을 안 보고 정할 수 있는 값이라야 한다.
        for mname, rr, scale in (("px", rpx, far_med), ("norm", rnm, 1.0)):
            for tol in tols:
                ps = partner_scores(k, rr, tol, scale)
                sel = base & ~np.isnan(ps)
                p_tp, p_fp = ps[sel & tpf[k]], ps[sel & ~tpf[k]]
                A = auc(p_tp, p_fp)
                lo, s = sep5(p_tp, p_fp)
                lam = round(K_SEP * max(0.0, s), 4)
                w = sel & ing
                Aw = auc(ps[w & tpf[k]], ps[w & ~tpf[k]])
                print(f"    {mname:<6}{tol:<8.2f}{A:>8.3f}{s:>+10.1%}{lam:>8.3f}"
                      f"{100*float((ps[base] > 0).mean()):>9.0f}%{Aw:>16.3f}")
                # 채택 후보는 '정답이 있는 영상만' 에서도 살아남는 것으로 한정한다
                if Aw == Aw and Aw > best.get(k, (0.55, None, None, 0.0))[0]:
                    best[k] = (Aw, mname, tol, lam)
    print()
    for k in kinds:
        if k in best:
            A, mn, tol, lam = best[k]
            print(f"  {k:<14} 채택 후보 — 거리 {mn} · 띠폭 {tol} · "
                  f"정답영상만 AUC {A:.3f} · λ {lam}")
        else:
            print(f"  {k:<14} 정답이 있는 영상만 보면 가르지 못한다 (AUC ≤ 0.55)")

    ok = [k for k in kinds if k in best and best[k][3] > 0]
    if not ok:
        print("\n판단 — 정답이 있는 영상만 보면 짝 점수가 정답과 오탐을 못 가른다.")
        print("       전체에서 갈리던 것은 '이 유방이 어느 사례인가' 를 맞힌 것이고,")
        print("       그건 자료 구성이 만든 지름길이라 실제 배포에서는 쓸 수 없다.")
        print("       여기서 접는다.")
    if not a.write:
        print("\n[2] 는 --write 를 줘야 만든다. 위 표를 보고 결정할 것.")
        print("    특히 좁은 띠와 띠폭 1.00 의 AUC 차이를 볼 것 — 차이가 없으면")
        print("    유두 거리 맞추기가 아무 일도 안 하고 있다는 뜻이다.")
        return

    print("\n── [2] 설정 파일 만들기")
    obj = {k: v for k, v in raw.items() if k not in kinds}
    tag = []
    for k in kinds:
        if k not in best:
            obj[k] = list(raw[k])
            continue
        _A, mn, tol, lam = best[k]
        rr = rpx if mn == "px" else rnm
        ps = partner_scores(k, rr, tol, far_med if mn == "px" else 1.0)
        out = []
        for j, d in enumerate(raw[k]):
            e2 = dict(d)
            p = ps[j]
            if not np.isnan(p):        # 짝이 없는 영상은 점수를 안 건드린다
                e2["score"] = float(d["score"]) * (1.0 - lam + lam * float(p))
            out.append(e2)
        obj[k] = out
        tag.append(f"{k[:4]}{mn}{int(round(tol*100)):03d}l{int(round(lam*100)):03d}")
    dst = Path(a.out_dir) / f"{src.stem}_xv_{'_'.join(tag)}.json"
    if dst.resolve() == src.resolve():
        die("출력이 원본과 같다.")
    dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
    print(f"  {dst.name}")
    print("\n다음 — 채점한다")
    print(f"  python3 training/code/score_dets.py \\\n      {src} \\\n      {dst}")


if __name__ == "__main__":
    main()
