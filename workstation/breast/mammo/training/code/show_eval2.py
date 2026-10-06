#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""화면에 뜨는 표시를 기준으로 잰다 — 자르고 → 묶고 → 잰다.

1차 실험(show_eval.py)이 틀린 이유
  점수로 자르기 **전에** 군집을 만들었다. 24,000개를 통째로 묶으니 진짜
  검출 하나가 주변 오탐 열 개와 합쳐지고, 합집합 상자의 중심이 밀려나
  병변을 맞히던 표시가 사라졌다. 상한이 94.9% -> 50.8% 로 무너진 게 그것이다.

  화면에는 임계값을 넘은 것만 뜬다. 그러니 **임계값을 먼저 걸고 남은 것끼리**
  묶어야 한다. 임계값마다 표시가 달라지므로 임계값을 훑으면서 매번 다시
  만들어야 한다. 이 스크립트가 그렇게 한다.

무엇을 재나
  임계값 t 마다
    ① t 이상인 검출만 남긴다        ← 화면에 뜨는 것
    ② 방식대로 표시를 만든다
    ③ 표시가 정답을 맞혔는지 센다   ← 한 병변은 한 표시만 정탐
    ④ 못 맞힌 표시 수 / 영상 수     ← 영상당 헛표시
  그러면 (영상당 헛표시, 재현율) 곡선이 나온다. 이게 화면 기준 FROC 다.

표시 방식
  box            상자 그대로
  cluster<gap>   남은 표시끼리 빈 거리 gap 이하면 묶어 합집합 상자
  marker<pct>    **크기를 주장하지 않는다.** 검출 중심에 고정 크기 정사각형.
                 한 변은 조직 상자 넓이의 pct% 가 되게 잡는다.

왜 marker 인가
  미세석회 상자는 정답의 절반 크기이고(가로 0.58 · 세로 0.53) 편차가 크다
  (25퍼 0.07 · 75퍼 1.17). 중심이 완벽해도 크기가 절반이면 IoU 는 0.25 라
  0.3 문턱에 못 미친다. 일률적으로 키우면 작은 건 여전히 모자라고 이미
  맞던 건 망가진다 — 1차 실험의 grow 가 그것을 보여줬다.

  상자는 "병변이 이만큼 크다" 는 주장이다. 석회에서 우리는 그 주장을 할
  근거가 없다. 크기를 말하지 않고 "여기를 보라" 만 하는 표시가 정직하다.

  marker 는 크기가 고정이라 IoU 로 재는 것이 의미 없다. **중심 명중으로
  잰다** — 표식 중심이 정답 안에 들어가면 화면에서 병변을 가리킨 것이다.
  대신 표식이 얼마나 큰지를 ③ 표시 부담이 말해 준다.

사용
  python3 training/code/show_eval2.py \\
      archive/outputs/tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json

  show_eval.py 가 만든 정답 캐시를 그대로 쓴다.
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
import eval_mammo_det as E                                    # noqa: E402
import score_dets as S                                        # noqa: E402
from show_eval import get_gt, clusterize, area                # noqa: E402

PROMPTS = S.PROMPTS


def marker(dets, pct, origin):
    """검출 중심에 고정 크기 정사각형. 크기를 주장하지 않는 표시."""
    out = []
    for d in dets:
        o = origin.get(str(d["img"]))
        if not o:
            continue
        side = math.sqrt(float(o[2]) * float(o[3]) * pct / 100.0)
        x0, y0, x1, y1 = map(float, d["box"])
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        h = side / 2.0
        out.append({"img": str(d["img"]), "box": [cx - h, cy - h, cx + h, cy + h],
                    "score": float(d["score"])})
    return out


def make(mode, dets, origin):
    if mode == "box":
        return [{"img": str(d["img"]), "box": list(map(float, d["box"])),
                 "score": float(d["score"])} for d in dets]
    if mode.startswith("cluster"):
        return clusterize(dets, float(mode[7:]))
    if mode.startswith("marker"):
        return marker(dets, float(mode[6:]), origin)
    raise ValueError(mode)


def measure(marks, g, n_gt, n_img, hit, origin):
    """표시를 정답에 붙인다. 한 병변은 가장 높은 점수의 표시 하나만 정탐."""
    by_img = defaultdict(list)
    for m in marks:
        by_img[str(m["img"])].append(m)
    tp = fp = 0
    burden = []
    for uid, lst in by_img.items():
        lst.sort(key=lambda m: -m["score"])
        claimed = set()
        gs = g.get(uid, ())
        o = origin.get(uid)
        crop = float(o[2]) * float(o[3]) if o else 0.0
        for m in lst:
            b = tuple(m["box"])
            if crop > 0:
                burden.append(area(b) / crop)
            got = None
            for i, q in enumerate(gs):
                if i in claimed or not hit(b, q):
                    continue
                got = i
                break
            if got is None:
                fp += 1
            else:
                claimed.add(got)
                tp += 1
    return (tp / n_gt if n_gt else 0.0,
            fp / n_img if n_img else 0.0,
            float(np.median(burden)) * 100.0 if burden else float("nan"),
            len(marks))


def curve_at(pts, targets):
    """(헛표시/영상, 재현율, 임계값, 부담, 표시수) 목록에서 목표 지점을 읽는다."""
    pts = sorted(pts, key=lambda r: r[0])
    out = {}
    for t in targets:
        best = None
        for r in pts:
            if r[0] <= t:
                best = r          # 그 지점 이하에서 가장 오른쪽(=재현율 최대)
        out[t] = best
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dets")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--cache", default="docs/show_gt_cache.json")
    ap.add_argument("--modes",
                    default="box,cluster40,cluster120,marker0.5,marker1,marker2")
    ap.add_argument("--steps", type=int, default=60)
    a = ap.parse_args()

    fp_targets = list(getattr(E, "FP_POINTS", [0.25, 0.5, 1.0, 2.0, 4.0]))
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]

    print("=" * 100)
    print("화면에 뜨는 표시 기준 — 자르고 → 묶고 → 잰다")
    print("=" * 100)
    gts, origin, done = get_gt(a.split, a.clip, a.pad, a.n, a.cache)
    raw = json.loads(Path(a.dets).read_text())
    keep = set(origin)
    print(f"  검출 파일 {Path(a.dets).name}")
    print(f"  임계값 {a.steps}단계 · 방식 {len(modes)}가지")

    for kind in PROMPTS:
        g = {u: v for u, v in gts[kind].items() if v}
        n_gt = sum(len(v) for v in g.values())
        dets = [d for d in raw.get(kind, []) if str(d["img"]) in keep]
        if not n_gt or not dets:
            continue
        scores = np.array([float(d["score"]) for d in dets])
        # 점수 분위로 임계값 격자를 잡는다. 균등 격자는 위쪽이 텅 빈다.
        # 작동점은 점수 상위쪽에 몰려 있다. 오탐 0.25개/영상이면
        # 598장에서 150개, 곧 상위 0.6% 다. 균등 분위로 잡으면
        # 그 구간에 격자가 몇 개 안 들어가 재현율이 낮게 나온다.
        # 그래서 '상위 k개를 남긴다' 로 격자를 잡는다.
        srt = np.sort(scores)[::-1]
        ks = np.unique(np.round(np.geomspace(
            20, min(len(srt), 12 * done), a.steps)).astype(int))
        grid = np.unique(srt[np.clip(ks - 1, 0, len(srt) - 1)])

        print("\n" + "=" * 100)
        print(f"▪ {kind}   정답 {n_gt:,}건 · 검출 {len(dets):,}개 · 영상 {done}장")
        print("=" * 100)

        head = "".join(f"{t:>8g}" for t in fp_targets)

        def sweep(mode, hit):
            """임계값을 훑으며 (헛표시/영상, 재현율, 임계값, 부담, 표시수)."""
            pts = []
            for t in grid:
                sub = [d for d in dets if float(d["score"]) >= t]
                if not sub:
                    continue
                marks = make(mode, sub, origin)
                if not marks:
                    continue
                rec, fppi, bur, n = measure(marks, g, n_gt, done, hit, origin)
                pts.append((fppi, rec, float(t), bur, n))
            return pts

        def table(title, res, pick, scale=1.0, p=1):
            print(f"\n   {title}")
            print(f"   {'방식':<12}{head}")
            for mode, pts in res.items():
                if not pts:
                    continue
                at = curve_at(pts, fp_targets)
                cells = ""
                for t in fp_targets:
                    r = at[t]
                    cells += f"{scale*pick(r):>8.{p}f}" if r else f"{'-':>8}"
                print(f"   {mode:<12}{cells}")

        for label, hit in (("center", lambda p, q: E.center_in(p, q)),
                           ("iou", lambda p, q, t=a.iou: E.iou(p, q) >= t)):
            use = [m for m in modes
                   if not (label == "iou" and m.startswith("marker"))]
            res = {m: sweep(m, hit) for m in use}

            print(f"\n  ── {label} 기준 · 영상당 헛표시별 재현율(%) ──")
            if label == "iou" and len(use) < len(modes):
                print("   ※ marker 는 크기를 주장하지 않는 표시라 IoU 로 재지 않는다")
            print(f"   {'방식':<12}{head}{'최대':>8}")
            for mode, pts in res.items():
                if not pts:
                    continue
                at = curve_at(pts, fp_targets)
                cells = ""
                for t in fp_targets:
                    r = at[t]
                    cells += f"{100*r[1]:>8.1f}" if r else f"{'-':>8}"
                print(f"   {mode:<12}{cells}{100*max(r[1] for r in pts):>8.1f}")

            if label == "center":
                table("표시 하나의 넓이 / 조직 넓이 (중앙값 %)", res,
                      lambda r: r[3], p=2)
                table("영상당 표시 개수 (정탐 포함, 사람이 실제로 보는 수)", res,
                      lambda r: r[4] / done, p=2)
                table("그때의 점수 임계값", res, lambda r: r[2], p=3)

    print("\n" + "=" * 100)
    print("읽는 법")
    print("=" * 100)
    print("""  · '영상당 헛표시' 는 정답을 못 맞힌 표시 수다. 화면에 뜨는 헛것이다.
    '영상당 표시 개수' 는 정탐까지 포함한 전체다 — 사람이 실제로 보는 수.

  · marker 는 IoU 로 재지 않는다. 크기를 주장하지 않기 때문이다.
    대신 '표시 부담' 을 보면 그 표식이 얼마나 큰지 알 수 있다.
    조직 넓이의 1% 면 한 변이 조직 폭의 10% 쯤 되는 정사각형이다.

  · cluster 가 box 보다 나으려면 **같은 헛표시 수에서 재현율이 높아야** 한다.
    표시 수가 줄어드는 것 자체는 이득이 아니다 — 이미 헛표시 축에 반영돼 있다.

  · 상한(최대)이 방식마다 다르면 그 방식이 병변을 잃고 있다는 뜻이다.
    box 의 상한이 기준이고, 거기서 떨어지면 그만큼 표현이 병변을 못 담은 것이다.""")


if __name__ == "__main__":
    main()
