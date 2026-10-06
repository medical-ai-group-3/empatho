#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VinDr 외부검증 — 조직 타일 필터와 깊이 가중을 씌워 채점한다.

CBIS 에서 확인된 것 (오탐 1개/영상 · 중심 명중)
                현행     +조직타일30%   +깊이가중
    미세석회     57.9%      62.1%        63.7%
    종괴         56.4%      60.5%        66.0%
  max 는 세 줄 모두 동일 — 병변을 하나도 안 잃고 순위만 바꿨다.

  깊이 가중의 λ 는 손으로 고른 값이 아니다. [1]에서 잰 분리도에 1.8 을
  곱해 나온다. 석회 0.082x1.8=0.15 · 종괴 0.193x1.8=0.35 이고, 두 종류의
  실측 최적과 각각 일치했다.

여기서 답할 것
  ① 같은 후처리가 다른 병원 · 다른 장비에서도 듣는가
  ② **CBIS 에서 나온 λ 를 재조정 없이 그대로 걸어도 듣는가**
     ②가 되면 "시험 집합에 맞춘 것 아니냐" 가 원천적으로 사라진다.
  ③ VinDr 자체 분리도로 λ 를 다시 잡으면 얼마나 더 오르는가 (참고용)

eval_vindr.main() 에서 그대로 옮긴 것 — 하나라도 다르면 좌표가 어긋난다
  · read_dicom 으로 읽는다. MONOCHROME1 441장 중 73장을 뒤집어야 한다.
    안 뒤집으면 조직 마스크가 공기를 조직으로 잡아 필터가 거꾸로 돈다.
  · norm8 을 **먼저** 하고 배율을 건다. 백분위는 원본 화소 분포에서 잡는다.
  · sc = mm / target_mm. 배율이 1 에 가까우면 영상은 안 키우지만 정답
    좌표에는 sc 를 그대로 곱한다 (eval_vindr 가 그렇게 한다).
  · 조직 상자로 자르고, 정답과 검출을 **자른 영상 기준 좌표**로 둔다.
  · 타일 격자는 자른 영상 위 (0,0) 부터. 가장자리는 0 으로 채우므로
    조직 비율의 분모는 타일 전체 넓이다.

FROC 은 eval_det 의 froc · at_fp 를 그대로 쓴다. CBIS 쪽과 같은 코드다.

분모 주의
  영상당 오탐의 분모는 **검출 파일에 들어 있는 영상 수**다. 추론에서
  건너뛴 영상(깨진 화소 · OOM)은 파일에 없고 그게 eval_vindr 의 done 이다.

사용
  python3 training/code/score_vindr.py archive/outputs/vindr_dets.json
  python3 training/code/score_vindr.py archive/outputs/vindr_dets_scaled.json \
      --target-mm 0.0599
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_vindr as V                                        # noqa: E402
from eval_det import at_fp, center_in, froc, iou              # noqa: E402

NEED = ("read_dicom", "load_gt", "RAW_VINDR", "LABELS", "PROMPTS",
        "norm8", "tissue_mask", "tissue_bbox", "positions")
_miss = [n for n in NEED if not hasattr(V, n)]
if _miss:
    sys.exit(f"[중단] eval_vindr 에 {_miss} 가 없다. 이름이 바뀌었으면 알려 달라.")

FP_PTS = (0.25, 0.5, 1.0, 2.0, 4.0)
# CBIS 에서 분리도 x 1.8 로 나온 값. 여기서 다시 조정하지 않는다.
CBIS_LAMBDA = {"calcification": 0.15, "mass": 0.35}
K_SEP = 1.8


def grid_of(mask_crop, tile, stride):
    """자른 영상 위 타일 격자와 조직 비율. eval_vindr 의 두 겹 반복과 같다."""
    H, W = mask_crop.shape[:2]
    area = float(tile * tile)
    out = []
    for ty in V.positions(H, tile, stride):
        for tx in V.positions(W, tile, stride):
            sub = mask_crop[ty:ty + tile, tx:tx + tile]
            out.append((tx, ty, tx + tile, ty + tile, float(np.sum(sub)) / area))
    return out


def in_any(box, tiles):
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    for tx1, ty1, tx2, ty2, _f in tiles:
        if tx1 <= cx <= tx2 and ty1 <= cy <= ty2:
            return True
    return False


def depth_at(depth, box):
    H, W = depth.shape[:2]
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    x, y = int(round(cx)), int(round(cy))
    if x < 0 or y < 0 or x >= W or y >= H:
        return 0.0
    return float(depth[y, x])


def hit(b, g, thr):
    cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    return (g[0] <= cx <= g[2] and g[1] <= cy <= g[3]) or iou(b, g) >= thr


def curve_at(dets, n_gt, done, mode, thr, g):
    fn = ((lambda p, q: 1.0 if center_in(p, q) else 0.0) if mode == "center"
          else (lambda p, q: 1.0 if iou(p, q) >= thr else 0.0))
    c = froc(dets, n_gt, done, fn, g)
    r = {t: at_fp(c, t)[0] for t in FP_PTS}
    r["max"] = max((s for _, s, _ in c), default=0.0)
    return r


def pct(v, qs=(5, 25, 50, 75)):
    return " · ".join(f"{q}퍼 {np.percentile(v, q):.3f}" for q in qs) if len(v) else "없음"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--csv", default="")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--tile", type=int, default=1008)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--target-mm", type=float, default=0.0,
                    help="검출 파일을 만들 때 쓴 값과 **반드시 같아야** 한다")
    ap.add_argument("--tile-fracs", default="0.3")
    ap.add_argument("--save", default="docs/score_vindr.json")
    a = ap.parse_args()
    stride = max(1, a.tile - a.overlap)
    tfr = [0.0] + [float(x) for x in a.tile_fracs.split(",") if x.strip()]
    csv = a.csv or str(V.LABELS / "finding_annotations.csv")

    print("=" * 100)
    print("VinDr 외부검증 — 조직 타일 필터 + 깊이 가중")
    print("=" * 100)
    print("  배율  " + (f"화소 간격을 {a.target_mm:.4f}mm 로 맞춘 것으로 본다"
                       if a.target_mm > 0 else "원본 그대로 (--target-mm 0)"))
    print(f"  CBIS 에서 가져온 λ  {CBIS_LAMBDA}  (여기서 다시 조정하지 않는다)")

    imgs = {}
    for ext in ("*.dicom", "*.dcm", "*.DCM"):
        for f in V.RAW_VINDR.rglob(ext):
            imgs[f.stem] = f
    print(f"  DICOM {len(imgs):,}개")
    if not imgs:
        sys.exit("받은 영상이 없다")
    gt = V.load_gt(csv, set(imgs))

    raws, used = {}, set()
    for f in a.files:
        raws[f] = json.loads(Path(f).read_text())
        for n in V.PROMPTS:
            used |= {str(x["img"]) for x in raws[f].get(n, [])}
    uids = sorted(u for u in gt if u in used and u in imgs)
    print(f"  검출 파일의 영상 {len(used):,}장 · 정답과 이어지는 것 {len(uids):,}장")
    if len(uids) < 0.9 * len(used):
        sys.exit(f"[중단] 이어지는 영상이 너무 적다. 정답 예시 {sorted(gt)[:2]} · "
                 f"검출 예시 {sorted(used)[:2]}")

    # 검출을 영상별로 색인해 둔다 (화소를 한 번만 읽기 위해)
    pos = {f: {n: defaultdict(list) for n in V.PROMPTS} for f in a.files}
    dep = {f: {n: None for n in V.PROMPTS} for f in a.files}
    tpf = {f: {n: None for n in V.PROMPTS} for f in a.files}
    for f in a.files:
        for n in V.PROMPTS:
            lst = raws[f].get(n, [])
            for i, d in enumerate(lst):
                pos[f][n][str(d["img"])].append(i)
            dep[f][n] = np.full(len(lst), np.nan)
            tpf[f][n] = np.zeros(len(lst), bool)

    print("\n화소 읽는 중 (영상당 한 번)")
    gts = {n: defaultdict(list) for n in V.PROMPTS}
    keep = {t: {} for t in tfr}
    gt_depth = {n: [] for n in V.PROMPTS}
    done, skipped, scaled = 0, [], 0
    for i, iid in enumerate(uids, 1):
        arr, mm, photo = V.read_dicom(imgs[iid])
        if arr is None:
            skipped.append(iid)
            continue
        u8 = V.norm8(arr, a.clip)
        sc = 1.0
        if a.target_mm > 0 and mm:
            sc = mm / a.target_mm
            if abs(sc - 1.0) > 0.01:
                u8 = cv2.resize(u8, None, fx=sc, fy=sc,
                                interpolation=cv2.INTER_CUBIC)
                scaled += 1
        tmask = V.tissue_mask(u8)
        tb = V.tissue_bbox(tmask, a.pad)
        if tb is None:
            skipped.append(iid)
            continue
        cx0, cy0, cx1, cy1 = tb
        tsub = tmask[cy0:cy1, cx0:cx1] > 0
        dist = cv2.distanceTransform(tsub.astype(np.uint8), cv2.DIST_L2, 5)
        mx = float(dist.max())
        depth = dist / mx if mx > 0 else dist

        truth = {n: [] for n in V.PROMPTS}
        for name, b in gt[iid]:
            bb = (b[0] * sc - cx0, b[1] * sc - cy0, b[2] * sc - cx0, b[3] * sc - cy0)
            gts[name][iid].append(bb)
            truth[name].append(bb)
            gt_depth[name].append(depth_at(depth, bb))

        g = grid_of(tsub, a.tile, stride)
        for t in tfr:
            keep[t][iid] = [x for x in g if x[4] >= t]

        for f in a.files:
            for n in V.PROMPTS:
                for j in pos[f][n].get(iid, ()):
                    b = raws[f][n][j]["box"]
                    dep[f][n][j] = depth_at(depth, b)
                    tpf[f][n][j] = any(hit(b, q, a.iou) for q in truth[n])
        done += 1
        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()
    print(f"  채점 대상 {done}장"
          + (f" · 못 읽은 영상 {len(skipped)}장" if skipped else "")
          + (f" · 배율 적용 {scaled}장" if scaled else ""))
    for n in V.PROMPTS:
        print(f"  정답 {n:<14} {sum(len(v) for v in gts[n].values()):,}건")
    ok = set(keep[0.0])

    # ── VinDr 자체 분리도 ────────────────────────────────────────────────
    print("\n── 깊이 분리도 (첫 번째 검출 파일 기준)")
    f0 = a.files[0]
    vin_lam = {}
    for n in V.PROMPTS:
        d, t = dep[f0][n], tpf[f0][n]
        okm = ~np.isnan(d)
        d_tp, d_fp = d[okm & t], d[okm & ~t]
        print(f"  {n}")
        print(f"    맞은 검출 {len(d_tp):>6,}건  {pct(d_tp)}")
        print(f"    틀린 검출 {len(d_fp):>6,}건  {pct(d_fp)}")
        if len(d_tp) and len(d_fp):
            lo = float(np.percentile(d_tp, 5))
            s = float((d_fp < lo).mean()) - float((d_tp < lo).mean())
            vin_lam[n] = round(K_SEP * s, 4)
            print(f"    분리도 {s:+.1%}  →  VinDr 자체 λ = {s:.3f}x{K_SEP} = {vin_lam[n]}"
                  f"   (CBIS λ = {CBIS_LAMBDA.get(n)})")
        else:
            vin_lam[n] = 0.0

    # ── 채점 ─────────────────────────────────────────────────────────────
    modes_lam = [("깊이없음", None),
                 ("CBIS λ", CBIS_LAMBDA),
                 ("VinDr λ", vin_lam)]
    hdr = (f"{'파일':<24}{'타일':<7}{'깊이':<10}{'종류':<14}{'검출':>9}"
           + "".join(f"{t:>8}" for t in FP_PTS) + f"{'max':>8}")
    out = {}
    for mode in ("center", "iou"):
        print(f"\n{'='*100}\n{mode} 기준 · 영상당 오탐별 민감도\n{'='*100}")
        print(hdr)
        for f in a.files:
            for t in tfr:
                for dname, lam in modes_lam:
                    for n in V.PROMPTS:
                        g = {u: v for u, v in gts[n].items() if v and u in ok}
                        n_gt = sum(len(v) for v in g.values())
                        if not n_gt:
                            continue
                        L = 0.0 if lam is None else float(lam.get(n, 0.0))
                        d = []
                        for j, x in enumerate(raws[f].get(n, [])):
                            iid = str(x["img"])
                            if iid not in ok:
                                continue
                            if t > 0 and not in_any(x["box"], keep[t][iid]):
                                continue
                            z = dep[f][n][j]
                            if L > 0 and not np.isnan(z):
                                x = dict(x)
                                x["score"] = float(x["score"]) * (1.0 - L + L * float(z))
                            d.append(x)
                        r = curve_at(d, n_gt, done, mode, a.iou, g)
                        out.setdefault(Path(f).name, {}).setdefault(
                            f"t{int(round(t*100)):02d}", {}).setdefault(
                            dname, {}).setdefault(n, {})[mode] = r
                        print(f"{Path(f).name[:24]:<24}"
                              f"{('없음' if t == 0 else f'{t:.0%}'):<7}{dname:<10}"
                              f"{n[:14]:<14}{len(d):>9,}"
                              + "".join(f"{r[x]:>8.3f}" for x in FP_PTS)
                              + f"{r['max']:>8.3f}")

    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, default=float, indent=1))
        print(f"\n저장 -> {p}")
    print("\n※ '타일 없음 · 깊이없음' 줄이 기존에 보고한 VinDr 수치와 같아야 한다.")
    print("  다르면 --target-mm 이 검출 파일을 만들 때 쓴 값과 다른 것이다.")
    print("※ 'CBIS λ' 줄이 오르면 규칙이 재조정 없이 옮겨간 것이다 — 이게 핵심이다.")


if __name__ == "__main__":
    main()
