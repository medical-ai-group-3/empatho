#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""문턱을 올리면 정상에서 얼마나 조용해지나 — 맞바꿈 곡선의 절반.

무엇을 알아냈나
  VinDr 정상 검사 75건에서 **75건 전부 재소환** 이 나왔다.
  영상당 검출 2.30건이고, 작동점이 「종류당 영상당 오탐 2개」이므로
  **예산 안이다.** 검출기는 시킨 대로 했고, 틀린 것은 작동점이다.

      사진 한 장이 조용할 확률   5.3%
      네 장 다 조용할 확률       0.053⁴ ≈ 0.0008%

  0/75 는 우연이 아니라 산수다.

이 스크립트가 하는 것
  문턱을 올려 가며 **정상 쪽이 얼마나 조용해지는지**를 센다.
  점수가 이미 저장돼 있어 GPU 도 영상도 필요 없다. 몇 초면 된다.

  ⚠ 이것은 맞바꿈의 **절반**이다. 문턱을 올리면 민감도를 잃는데,
    그 손해는 CBIS 쪽에서 재야 한다. 이 표만 보고 문턱을 정하면
    「아무것도 안 찾는 조용한 모델」이 제일 좋아 보인다.

  ⚠ 문턱은 **올리기만** 할 수 있다. 저장된 검출이 이미 0.448 · 0.462 로
    걸러진 것이라 그보다 낮은 값은 계산할 수 없다.

사용
  python3 training/code/sweep_normals.py
  python3 training/code/sweep_normals.py --target 10    # 재소환 10% 목표
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "archive" / "outputs"
DOCS = REPO / "docs"

# 지금 운영 문턱 (infer_mammo.DEFAULTS)
NOW = {"calcification": 0.448, "mass": 0.462}


def load(jl):
    if not jl.is_file():
        sys.exit(f"[중단] 결과가 없다: {jl}")
    last = {}
    for line in jl.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:                                   # noqa: BLE001
            continue
        last[r["image_id"]] = r
    return [r for r in last.values() if "error" not in r]


def at(recs, t):
    """문턱 t 에서 사진·검사 단위 값. t 는 두 종류에 같이 건다."""
    img_fire = img_biop = 0
    n_les = 0
    st_fire = defaultdict(bool)
    st_biop = defaultdict(bool)
    for r in recs:
        keep = [l for l in r["lesions"] if l["score"] >= t]
        n_les += len(keep)
        b = any(l["biopsy"] for l in keep)
        if keep:
            img_fire += 1
            st_fire[r["study_id"]] = True
        else:
            st_fire.setdefault(r["study_id"], False)
        if b:
            img_biop += 1
            st_biop[r["study_id"]] = True
        else:
            st_biop.setdefault(r["study_id"], False)
    n = len(recs)
    ns = len(st_fire)
    return {
        "t": t, "n": n, "ns": ns,
        "img_fire": img_fire / n * 100,
        "img_biop": img_biop / n * 100,
        "per_img": n_les / n,
        "st_fire": sum(st_fire.values()) / ns * 100,
        "st_biop": sum(st_biop.values()) / ns * 100,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=str(OUT / "normal_dets.jsonl"))
    ap.add_argument("--target", type=float, default=10.0,
                    help="검사 단위 재소환 목표 %%")
    a = ap.parse_args()

    recs = load(Path(a.jsonl))
    les = [l for r in recs for l in r["lesions"]]
    if not les:
        sys.exit("[중단] 검출이 하나도 없다.")

    print("=" * 78)
    print(f"문턱을 올리면 정상에서 얼마나 조용해지나 — 영상 {len(recs)}장")
    print("=" * 78)

    # 저장된 점수의 범위부터. 여기 밖은 계산이 안 된다.
    lo = min(l["score"] for l in les)
    hi = max(l["score"] for l in les)
    print(f"\n  저장된 검출 {len(les)}건 · 점수 {lo:.3f} ~ {hi:.3f}")
    print(f"  지금 문턱  석회 {NOW['calcification']:.3f} · 종괴 {NOW['mass']:.3f}")
    print("  ⚠ 문턱은 **올리기만** 볼 수 있다 — 더 낮은 값의 검출은 저장돼 있지 않다.")

    grid = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    rows = [at(recs, t) for t in grid]

    print(f"\n  {'문턱':>6}{'사진 울림':>11}{'사진 조직검사':>14}"
          f"{'영상당':>9}{'검사 재소환':>13}{'검사 조직검사':>14}")
    for r in rows:
        mark = "  ← 지금" if abs(r["t"] - 0.45) < 1e-9 else ""
        print(f"  {r['t']:>6.2f}{r['img_fire']:>10.1f}%{r['img_biop']:>13.1f}%"
              f"{r['per_img']:>9.2f}{r['st_fire']:>12.1f}%"
              f"{r['st_biop']:>13.1f}%{mark}")

    # 목표 재소환율에 닿는 문턱
    ok = [r for r in rows if r["st_fire"] <= a.target]
    print()
    if ok:
        r = ok[0]
        print(f"  ▶ 검사 재소환 {a.target:.0f}% 이하가 되는 첫 문턱은 "
              f"**{r['t']:.2f}** 이다 (재소환 {r['st_fire']:.1f}%).")
        print(f"     지금 문턱보다 {r['t'] - NOW['mass']:+.2f} 다.")
    else:
        best = min(rows, key=lambda r: r["st_fire"])
        print(f"  ▶ **격자 안에 목표 {a.target:.0f}% 를 만족하는 문턱이 없다.**")
        print(f"     가장 조용한 {best['t']:.2f} 에서도 재소환 "
              f"{best['st_fire']:.1f}% 다.")
        print("""
     이것이 뜻하는 것 — 점수를 올리는 것만으로는 검진에 못 간다.
     검출기가 정상 유방에서 내는 점수와 병변에서 내는 점수가
     **충분히 안 갈라진다.** 문턱은 그 둘을 가르는 선일 뿐이고,
     선을 옮겨서 해결되지 않는 문제는 선의 문제가 아니다.""")

    # 검사 단위가 왜 이렇게 나쁜지 — 사진 넷을 곱한 결과다
    print("\n" + "-" * 78)
    print("사진 단위와 검사 단위가 왜 이렇게 벌어지나")
    print("-" * 78)
    print(f"\n  {'문턱':>6}{'사진 조용':>11}{'그것의 4제곱':>14}"
          f"{'실제 검사 조용':>15}")
    for r in rows[:7]:
        q = (100 - r["img_fire"]) / 100
        print(f"  {r['t']:>6.2f}{100-r['img_fire']:>10.1f}%"
              f"{q**4*100:>13.2f}%{100-r['st_fire']:>14.1f}%")
    print("""
  4제곱과 실제가 비슷하면 **네 장이 서로 독립**이라는 뜻이다.
  실제가 더 낮으면 같은 여성의 네 장이 함께 울린다는 뜻이고,
  그건 유방 조직 자체의 특성(치밀도 등)이 원인일 수 있다.""")

    # 종류별로 나눠 본다 — 어느 쪽이 시끄러운가
    print("\n" + "-" * 78)
    print("어느 종류가 시끄러운가")
    print("-" * 78)
    for kind in ("mass", "calcification"):
        ks = sorted(l["score"] for l in les if l["kind"] == kind)
        if not ks:
            continue
        n = len(ks)

        def p(q):
            return ks[min(n - 1, int(q * (n - 1)))]
        print(f"\n  {kind:14s} {n:4d}건 · 영상당 {n/len(recs):.2f}")
        print(f"    점수 중앙 {p(.5):.3f} · 90퍼 {p(.9):.3f} · "
              f"99퍼 {p(.99):.3f} · 최대 {ks[-1]:.3f}")
        print(f"    0.70 이상 {sum(1 for s in ks if s >= .70):4d}건 · "
              f"0.80 이상 {sum(1 for s in ks if s >= .80):4d}건 · "
              f"0.90 이상 {sum(1 for s in ks if s >= .90):4d}건")

    # 짝이 되는 CBIS 쪽 자료가 있는지 본다
    print("\n" + "=" * 78)
    print("다음에 필요한 것 — 잃는 쪽")
    print("=" * 78)
    sd = DOCS / "score_dets.json"
    if sd.is_file():
        try:
            d = json.load(sd.open(encoding="utf-8"))
        except Exception as e:                              # noqa: BLE001
            print(f"  score_dets.json 을 못 읽었다: {e}")
        else:
            def shape(x, d0=0):
                if isinstance(x, dict):
                    ks = list(x)[:8]
                    return "{" + ", ".join(str(k) for k in ks) + \
                           (", …}" if len(x) > 8 else "}")
                if isinstance(x, list):
                    return f"[{len(x)}개]"
                return type(x).__name__
            print(f"\n  docs/score_dets.json 이 있다. 최상위 {shape(d)}")
            if isinstance(d, dict):
                for k in list(d)[:6]:
                    print(f"    {k:24s} {shape(d[k])}")
            print("""
  ▶ 이 안에 «문턱 → 민감도» 가 들어 있으면 위 표와 바로 이을 수 있다.
    위 구조를 알려 주면 두 표를 합쳐 맞바꿈 곡선을 만들겠다.""")
    else:
        print("""
  docs/score_dets.json 이 없다. 문턱을 올렸을 때 **CBIS 에서 얼마나
  놓치는지**를 따로 재야 맞바꿈이 완성된다.

    python3 training/code/score_dets.py --help""")

    print("""
⚠ 이 표만 보고 문턱을 정하면 안 된다
  여기서는 문턱이 높을수록 좋아 보인다. 아무것도 안 찾는 모델이 제일
  조용하기 때문이다. **잃는 쪽을 같이 놓아야 판단이 된다.**""")


if __name__ == "__main__":
    main()
