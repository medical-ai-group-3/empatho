#!/usr/bin/env python
"""
타일 간 점수 비교 문제를 고쳐 본다 — 재학습 없이, 저장된 박스 위에서.

무엇이 문제인가
  검출기는 못 보는 게 아니다. 오탐을 무제한 허용하면 미세석회 99.4% ·
  종괴 99.7% 를 찾는다. 오탐 1개/영상에서는 57.9% · 56.4% 다.
  **후보 안에는 있는데 오탐보다 위로 못 올린다.**

  의심 지점 — 타일마다 점수를 독립적으로 매긴다. 한산한 타일의 약한 검출이
  복잡한 타일의 강한 검출보다 높은 점수를 받을 수 있다. 영상 하나의 검출을
  한 줄로 세울 때 그 순서가 뒤섞인다.

실측으로 밝혀진 것 (2026-08-31 · CBIS 598장)
  ① 덩어리 크기를 점수에 더하면 **크게 나빠진다.**
       agree α=0.15   석회 -2.9%p · 종괴 -19.5%p
       agree α=0.30   석회 -8.0%p · 종괴 -27.9%p
       agree α=0.50   석회 -10.3%p · 종괴 -34.3%p
     α 에 따라 단조롭게 나빠진다 — 우연이 아니라 방향이 반대다.

     왜인지가 분포에 있다. 덩어리 최대 크기가 60~67개다. 타일 겹침으로는
     한 지점을 많아야 4장이 덮는다. **60개는 타일 합의가 아니라 한 자리에
     질의 200개가 무더기로 쏟아진 것**이고, 그건 조직이 복잡한 곳에서 생긴다.
     즉 덩어리 크기는 '여러 증거' 가 아니라 **'애매함'** 의 지표였다.
     종괴가 훨씬 심한 것도 맞아떨어진다 — 크니까 겹치는 질의가 더 많다.

  ※ 처음 이 파일을 쓸 때 "합의 신호가 더 유망하다" 고 적었다. 틀렸다.
    측정이 반대로 나왔으므로 그 문장을 지우고 이 기록으로 대체한다.

무엇을 시험하나  (위 결과가 가리키는 방향으로)

  ① 덩어리 크기를 **깎는다**  [agree · 음수 α]
     "크면 나쁘다" 의 직접적 역방향.

  ② 위치 일치도  [tight]
     덩어리 안 박스들이 합쳐진 상자와 얼마나 겹치는지의 평균 IoU.
     **개수가 아니라 합의의 질이다.** 진짜 병변이면 여러 박스가 같은 자리에
     딱 겹치고, 밀집 조직의 무더기는 넓게 흩어진다. 원래 하려던 '합의' 를
     올바른 형태로 다시 쓴 것.

  ③ 최대값 대신 평균  [meanscore]
     덩어리 안 점수의 평균. 넓게 퍼진 덩어리는 낮은 점수 구성원이 많아
     평균이 내려간다. 운 좋은 한 개의 높은 점수를 깎는 효과.

  ④ 타일별 정규화  [PRE · zscore · maxnorm · subq]
     ⚠ 이쪽은 오히려 나빠질 수 있다. 공기만 있는 타일의 잡음 최고값이
     "그 타일 안에서는 1등" 이라 위로 올라온다. 타일 좌표가 있을 때만 돈다.

무엇을 안 바꾸나
  좌표 합치기는 wbf@0.3 고정이다(확정 운영점). 조직 필터 0.5 도 그대로.
  **바꾸는 것은 점수 하나뿐**이라 차이가 나오면 원인이 하나다.

정직성 장치
  전략 'none' 이 현행 수치(석회 57.9% · 종괴 56.4% @1FP 중심명중)를
  재현하는지 먼저 찍는다. 재현이 안 되면 비교의 바닥이 다른 것이므로
  아래 차이값도 못 믿는다 — 그 경우 크게 경고한다.

사용
  python3 rerank.py --raw ../../archive/outputs/tile_raw_ep6.json
  python3 rerank.py --raw ... --alpha-sweep 0.1,0.2,0.3,0.5
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mammo_io import PROMPTS, cluster, iou, m_wbf             # noqa: E402
from merge_boxes import (apply_tissue, froc_gt_from, get_gt,  # noqa: E402
                         get_tissue, score_one)

FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)
# 현행 확정 수치. 'none' 이 이걸 재현해야 비교의 바닥이 같다.
CURRENT = {"calcification": 0.579, "mass": 0.564}      # @1FP · 중심 명중

PRE = ("none", "zscore", "maxnorm", "subq")
POST = ("none", "agree", "ntile")


# ─────────────────────── 점수 손보기 ───────────────────────
def pre_transform(boxes, how, q):
    """타일 안에서 점수를 상대화한다. 박스는 (x0,y0,x1,y1,s,tx,ty)."""
    if how == "none":
        return boxes
    bytile = defaultdict(list)
    for b in boxes:
        bytile[(b[5], b[6]) if len(b) > 6 else None].append(b)
    out = []
    for lst in bytile.values():
        s = np.array([b[4] for b in lst], float)
        if how == "zscore":
            sd = float(s.std())
            t = (s - s.mean()) / sd if sd > 1e-6 else s - s.mean()
        elif how == "maxnorm":
            m = float(s.max())
            t = s / m if m > 1e-6 else s
        elif how == "subq":
            t = s - float(np.quantile(s, q))
        else:
            raise ValueError(how)
        out.extend((b[0], b[1], b[2], b[3], float(v)) + tuple(b[5:])
                   for b, v in zip(lst, t))
    return out


def merge_with(boxes, thr, post, alpha):
    """
    덩어리로 묶어 wbf 로 합친다. post 가 'none' 이 아니면 점수에 합의를 반영한다.

    agree — 덩어리 안 박스 수
    ntile — 덩어리에 걸린 서로 다른 타일 수.
            같은 타일에서 나온 중복 박스는 새 증거가 아니므로 안 센다.
            agree 보다 이쪽이 '타일 간 합의' 라는 원래 뜻에 맞다.
    """
    out = []
    for grp in cluster(boxes, thr):
        b = m_wbf(grp)                       # 좌표는 항상 wbf — 운영점 고정
        s = b[4]
        if post == "agree":
            # α 가 음수면 큰 덩어리를 깎는다
            s *= 1.0 + alpha * math.log(len(grp))
        elif post == "ntile":
            k = len({(g[5], g[6]) for g in grp if len(g) > 6}) or 1
            s *= 1.0 + alpha * math.log(k)
        elif post == "tight":
            # 합쳐진 상자와 구성원들의 평균 IoU. 1에 가까울수록 같은 자리다.
            # 크기 1인 덩어리는 1.0 이라 안 깎인다 — 의도한 것이다.
            t = sum(iou(g[:4], b[:4]) for g in grp) / len(grp)
            s *= max(t, 1e-6) ** alpha
        elif post == "meanscore":
            s = sum(g[4] for g in grp) / len(grp)
        out.append((b[0], b[1], b[2], b[3], s))
    out.sort(key=lambda x: -x[4])
    return out


def run(by, gtf, uids, thr, pre, post, alpha, q, iou_hit):
    """한 전략을 끝까지 돌려 FROC 을 낸다."""
    res = {}
    for n in PROMPTS:
        dets = []
        for uid in uids:
            bs = by[n].get(uid) or []
            if not bs:
                continue
            for b in merge_with(pre_transform(bs, pre, q), thr, post, alpha):
                dets.append(dict(img=uid, box=list(b[:4]), score=float(b[4])))
        r = score_one(dets, gtf[n], len(uids), iou_hit)
        if r:
            res[n] = r
    return res


def at1(res, n):
    """
    오탐 1개/영상 · 중심 명중.

    score_one 의 반환은  res[종류]["center"][1.0]  형태다.
    ("at_fp" 같은 중간 키가 없다 — merge_boxes.score_one 을 직접 확인했다.
     여기를 추측으로 쓰면 조용히 None 이 되어 전 전략이 빠진다.)
    """
    return ((res.get(n) or {}).get("center") or {}).get(1.0)


def curve(res, n):
    d = (res.get(n) or {}).get("center") or {}
    return {fp: d[fp] for fp in FP_POINTS if fp in d}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--nms", type=float, default=0.3, help="덩어리 IoU (운영점)")
    ap.add_argument("--tissue-frac", type=float, default=0.5, help="운영점")
    ap.add_argument("--iou-hit", type=float, default=0.3)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--gt-cache", default="merge_gt_cache.json")
    ap.add_argument("--tissue-cache", default="merge_tissue_cache.json")
    ap.add_argument("--alpha-sweep", default="0.15,0.3,0.5",
                    help="agree/ntile 의 양수 α (덩어리가 크면 올린다)")
    ap.add_argument("--neg-sweep", default="-0.15,-0.3,-0.5",
                    help="agree 의 음수 α (덩어리가 크면 깎는다). "
                         "실측에서 양수가 크게 나빴으므로 이쪽을 본다")
    ap.add_argument("--tight-sweep", default="0.5,1.0,2.0",
                    help="tight 의 지수. 클수록 흩어진 덩어리를 세게 깎는다")
    ap.add_argument("--q", type=float, default=0.9, help="subq 의 분위수")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    print("=" * 78)
    print("타일 간 점수 순위 실험 — 재학습 없이, CPU 로")
    print("=" * 78)

    raw = json.loads(Path(a.raw).expanduser().resolve().read_text())
    by = {n: defaultdict(list) for n in PROMPTS}
    n_tile, n_all = 0, 0
    for name, lst in raw.items():
        if name not in by:
            continue
        for d in lst:
            b = [float(v) for v in d["box"]]
            t = d.get("tile")
            n_all += 1
            rec = (b[0], b[1], b[2], b[3], float(d["score"]))
            if t:
                rec = rec + (float(t[0]), float(t[1]))
                n_tile += 1
            by[name][d["img"]].append(rec)

    print(f"  박스 {n_all:,}개 · 타일 좌표 있음 {n_tile:,}개 "
          f"({n_tile/max(n_all,1):.0%})")
    has_tile = n_tile >= n_all * 0.99
    if not has_tile:
        print("\n  ! 타일 좌표가 없다 — 이 파일은 좌표를 저장하기 전 버전으로")
        print("    뽑혔다. 타일 정보가 필요한 전략은 건너뛴다.")
        print("      건너뜀   ntile · zscore · maxnorm · subq")
        print("      돌아감   agree (덩어리 크기 — 타일 정보 불필요)")
        print("    전부 보려면 추론을 다시 해야 한다 (GPU 약 83분):")
        print("      eval_mammo_det.py --save-raw <파일> --raw-topk 300")

    uids = sorted({u for n in by for u in by[n]})
    if a.limit:
        uids = uids[:a.limit]
        for n in by:
            by[n] = {u: v for u, v in by[n].items() if u in set(uids)}
    print(f"  영상 {len(uids)}장")
    print("  ! 영상·종류당 상위 300개까지 담긴 파일이다. 오탐 4개/영상 구간은")
    print("    온전하지만 곡선 끝(최대 재현율)은 잘려 있다.")

    # ── 조직 필터 (운영점) — 합치기 전. 박스 순서를 유지해야 캐시가 맞는다
    if a.tissue_frac > 0:
        frac = get_tissue(by, uids, a.clip, a.pad, a.tissue_cache)
        drop = apply_tissue(by, frac, a.tissue_frac)
        print(f"  조직 필터 {a.tissue_frac:.0%} — 제외 "
              + " · ".join(f"{n} {drop[n]:,}" for n in PROMPTS))

    # 덩어리 크기가 다양해야 '합의' 가 순위를 가를 수 있다.
    # 전부 크기 1이면 이 실험은 시작부터 성립하지 않는다.
    print("\n  덩어리 크기 분포 (IoU %.2f 로 묶었을 때)" % a.nms)
    for n in PROMPTS:
        sizes = [len(g) for u in uids for g in cluster(by[n].get(u) or [], a.nms)]
        if not sizes:
            continue
        v = np.array(sizes)
        one = float((v == 1).mean())
        print(f"    {n:14s} 덩어리 {len(v):,}개 · 중앙 {int(np.median(v))} · "
              f"크기1 {one:.0%} · 최대 {v.max()}")
        if one > 0.9:
            print("      ★ 90% 이상이 크기 1이다. 합의 신호가 거의 없다 —")
            print("        agree/ntile 로 순위가 바뀔 여지가 작다.")

    gt, idmap = get_gt(uids, a.split, a.clip, a.pad, a.gt_cache)
    gtf = froc_gt_from(gt, idmap)

    # ── 바닥 확인: 'none' 이 현행 수치를 재현하는가 ──────────────────
    print("\n" + "─" * 78)
    print("바닥 확인 — 'none' 이 현행 확정 수치를 재현해야 한다")
    print("─" * 78)
    base = run(by, gtf, uids, a.nms, "none", "none", 0.0, a.q, a.iou_hit)
    ok = True
    for n in PROMPTS:
        got, want = at1(base, n), CURRENT[n]
        if got is None:
            print(f"  {n:14s} 측정 실패"); ok = False; continue
        d = (got - want) * 100
        mark = "✓" if abs(d) <= 1.0 else "✗"
        print(f"  {n:14s} {got:.1%}   현행 {want:.1%}   차이 {d:+.1f}%p   {mark}")
        if abs(d) > 1.0:
            ok = False
    if not ok:
        print("\n  ✗ 바닥이 현행과 다르다. 아래 차이값은 못 믿는다.")
        print("    원인 후보 — 원본 파일이 다른 실행의 것 / 조직 캐시 불일치 /")
        print("    상위 300개 절단의 영향. 확인하기 전에는 결론 내지 말 것.")
    else:
        print("\n  ✓ 바닥이 같다. 아래 차이는 점수 전략만의 효과다.")

    # ── 전략 비교 ────────────────────────────────────────────────
    alphas = [float(x) for x in a.alpha_sweep.split(",") if x.strip()]
    negs = [float(x) for x in a.neg_sweep.split(",") if x.strip()]
    tights = [float(x) for x in a.tight_sweep.split(",") if x.strip()]

    trials = [("none", "none", 0.0)]
    trials += [("none", "agree", al) for al in alphas]     # 양수 — 실측 재확인
    trials += [("none", "agree", al) for al in negs]       # 음수 — 역방향
    trials += [("none", "tight", t) for t in tights]       # 위치 일치도
    trials.append(("none", "meanscore", 0.0))              # 최대 대신 평균
    if has_tile:
        trials += [("none", "ntile", al) for al in alphas]
        for pre in ("zscore", "maxnorm", "subq"):          # ② 타일별 정규화
            trials.append((pre, "none", 0.0))
        trials.append(("subq", "ntile", alphas[len(alphas) // 2]))

    print("\n" + "─" * 78)
    print("전략별 — 오탐 1개/영상 · 중심 명중")
    print("─" * 78)
    print(f"  {'전략':30s}{'미세석회':>12s}{'차이':>9s}{'종괴':>10s}{'차이':>9s}")
    print("  " + "-" * 74)

    b_calc, b_mass = at1(base, "calcification"), at1(base, "mass")
    rows, best = [], None
    for pre, post, al in trials:
        res = base if (pre, post) == ("none", "none") else \
            run(by, gtf, uids, a.nms, pre, post, al, a.q, a.iou_hit)
        c, m = at1(res, "calcification"), at1(res, "mass")
        if c is None or m is None:
            continue
        label = ("현행 (none)" if (pre, post) == ("none", "none")
                 else f"{pre} + {post}" + (f" α={al}" if post != "none" else ""))
        dc, dm = (c - b_calc) * 100, (m - b_mass) * 100
        print(f"  {label:30s}{c:11.1%}{dc:+8.1f}{m:10.1%}{dm:+8.1f}")
        rows.append(dict(pre=pre, post=post, alpha=al, calc=c, mass=m,
                         d_calc=dc, d_mass=dm, curve_calc=curve(res, "calcification"),
                         curve_mass=curve(res, "mass")))
        if (pre, post) != ("none", "none") and (best is None or
                                                dc + dm > best["d_calc"] + best["d_mass"]):
            best = rows[-1]

    # ── 읽는 법 ──────────────────────────────────────────────────
    print("\n" + "─" * 78)
    if best is None:
        print("  비교할 전략이 없다.")
    else:
        tot = best["d_calc"] + best["d_mass"]
        lab = f"{best['pre']} + {best['post']} α={best['alpha']}"
        print(f"  가장 나은 것  {lab}   석회 {best['d_calc']:+.1f}%p · "
              f"종괴 {best['d_mass']:+.1f}%p")
        if tot < 1.0:
            print("\n  → 의미 있는 개선이 아니다.")
            # 양방향이 다 나쁜지 본다. 한 방향만 나쁘면 부호를 뒤집으면 되지만,
            # 양쪽 다 나쁘면 원래 점수가 이미 그 특징에 대해 최적에 가깝다는 뜻이다.
            pos = [r for r in rows if r["post"] == "agree" and r["alpha"] > 0]
            neg = [r for r in rows if r["post"] == "agree" and r["alpha"] < 0]
            worse = (pos and neg
                     and max(r["d_calc"] + r["d_mass"] for r in pos) < 0
                     and max(r["d_calc"] + r["d_mass"] for r in neg) < 0)
            if worse:
                print("     ★ 덩어리 크기를 올려도 내려도 나빠졌다. 원래 점수가")
                print("       이미 이 특징에 대해 최적에 가깝게 정렬돼 있다는 뜻이다.")
                print("       '타일마다 독립 채점이라 순위가 뒤섞인다' 는 전제가")
                print("       근거를 잃었다 — 덩어리에서 뽑는 특징으로는 그렇다.")
            if not has_tile:
                ran = sorted({r["post"] for r in rows if r["post"] != "none"})
                print(f"     이번에 돌린 전략: {', '.join(ran)}")
                print("     타일 좌표가 필요한 ntile·정규화 3종은 안 돌았다.")
            print("     다음 후보는 조직 상자 개선(공기 타일 제거)이다 —")
            print("     시연에서 3826x6601 영상의 조직 상자가 전체로 잡혔다.")
        else:
            print(f"\n  → 개선이 있다. 다만 이 값은 **CBIS 시험 분할에서 고른 것**이다.")
            print("     같은 분할에서 여러 전략을 재고 최선을 고르면 그만큼 낙관적이다.")
            print("     채택하려면 VinDr 에서도 같은 방향인지 확인할 것.")

    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(baseline_ok=ok, rows=rows),
                                ensure_ascii=False, indent=2, default=float))
        print(f"\n  -> {p}")
    print("=" * 78)


if __name__ == "__main__":
    main()
