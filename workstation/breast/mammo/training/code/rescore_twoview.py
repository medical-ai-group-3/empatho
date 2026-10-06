#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""파트너 시야로 검출 순위를 다시 매긴다 — 미리 정한 규칙대로 재기만 한다.

왜 만드는가
  어제 「실질차이 3%p 또는 AUC 이득 0.02 초과면 만든다」고 미리 적었고
  종괴가 +3.6%(절대 100화소), AUC 이득이 +0.073/+0.080 으로 넘겼다.
  결과가 시원찮아 보인다고 미리 정한 규칙을 무르면, 잘 나왔을 때 규칙을
  지킨 것도 의미가 없어진다.

  게다가 **GPU 를 한 번도 안 쓴다.** 거리와 점수가 캐시에 다 있어서
  몇 초면 파일이 나온다. 논쟁할 것 없이 그냥 잰다.

기대치 — 미리 적어 둔다
  **FROC 에서 오를 것 같지 않다.** 근거 둘.

  ① 좁은 허용오차, 곧 「두 시야에서 **같은 자리**에 보이는가」라는 원래
     착상 쪽에서는 신호가 없거나 음수였다(상대 0.02: 석회 +0.2% ·
     종괴 −4.4%). 상대 0.05 에서 정탐 88.4% 대 **오탐 85.5%** 다.
     **헛것도 두 시야에 같이 나타난다.** 조직이 겹쳐 생긴 오탐은 그 유방의
     실제 조직 구조라 각도를 바꿔도 따라온다.

  ② 문턱을 넘긴 것은 넓은 허용오차 쪽인데, 거기서는 짝보유율이 97~99%라
     사실상 전부 걸린다. 그러면 이 값은 「같은 자리에 있나」가 아니라
     **「파트너 사진의 최고 검출 점수」** — 위치와 무관한 증례 난이도 값이다.

  그리고 판정에 실제로 쓰이는 칸(검출점수와 곱한 AUC)은 +0.007/+0.013 이다.
  이진 분류기는 그 칸이 +0.051 이었고 FROC 에서 졌다. 이건 4~7배 작다.

  → 그래도 잰다. 오르면 그건 **두 시야 일치가 아니라 증례 난이도**가
    먹힌 것이니, 문서에도 그렇게 적어야 한다.

무엇을 곱하나
      새 점수 = 검출 점수 × (1 − λ + λ·z)

  z 는 파트너 시야에서 허용오차 안에 있는 검출의 최고 점수(없으면 0).
  깊이 재점수와 같은 꼴이다. **절대 점수를 안 버린다** — 최저 (1−λ)배까지만
  누른다. 영상별 정규화와 교차 질의가 실패한 원인이 절대 점수를 버린 것이었다.

  λ=0 이면 원본과 **완전히 같다.** 내장 대조군이다.

짝이 없는 영상 (16%)
  버리지 않는다. 버리면 최대 재현율이 떨어져 비교가 깨진다. 그 종류 z 의
  **중앙값**을 똑같이 먹여 눈금만 맞춘다. 1 을 먹이면 짝 없는 영상이 통째로
  위로 올라가 버린다 — 이건 재점수가 아니라 사고다.

사용
  python3 training/code/rescore_twoview.py
  python3 training/code/rescore_twoview.py --tols 0.10,0.15 --lambdas 0,0.2,0.35,0.5
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

ROOT = Path(__file__).resolve().parents[2]


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402
import check_twoview as TV                                    # noqa: E402

PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets",
                    default="archive/outputs/"
                            "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json")
    ap.add_argument("--split", default="test")
    ap.add_argument("--cache", default="docs/twoview_cache.json")
    ap.add_argument("--out-dir", default="archive/outputs")
    ap.add_argument("--topk", type=int, default=20,
                    help="파트너에서 이만큼만 본다 — 잰 것과 같게 맞춘다")
    ap.add_argument("--tols", default="0.10,0.15",
                    help="상대 허용오차. 잴 때 이득이 난 값들")
    ap.add_argument("--lambdas", default="0,0.2,0.35,0.5")
    a = ap.parse_args()

    src = rp(a.dets)
    if not src.is_file():
        die(f"없는 파일: {src}")
    raw = json.loads(src.read_text())

    print("=" * 84)
    print("파트너 시야 재점수 — GPU 안 쓴다")
    print("=" * 84)

    cp = rp(a.cache)
    if not cp.is_file():
        die(f"캐시가 없다: {cp}\n  check_twoview.py 를 먼저 돌릴 것.")
    cj = json.loads(cp.read_text())
    if cj.get("ver") != TV.CACHE_VER:
        die("캐시가 옛 판이다. check_twoview.py --recache 를 먼저 돌릴 것.")
    img = cj["img"]

    meta, _ = TV.read_index(a.split)
    breast = defaultdict(dict)
    for u in img:
        if u in meta:
            p, s, v = meta[u]
            breast[(p, s)][v] = u
    partner = {}
    for _b, vs in breast.items():
        if "CC" in vs and "MLO" in vs:
            partner[vs["CC"]] = vs["MLO"]
            partner[vs["MLO"]] = vs["CC"]
    print(f"  검출 {src.name}")
    print(f"  짝이 있는 영상 {len(partner):,}장")

    # 파트너에서 볼 상위 k개 — 잴 때와 같은 방식이어야 한다
    pinfo = {k: defaultdict(list) for k in PROMPTS}
    byimg = {k: defaultdict(list) for k in PROMPTS}
    for k in PROMPTS:
        for d in raw.get(k, []):
            byimg[k][str(d["img"])].append(d)
        for u, ds in byimg[k].items():
            if u not in img:
                continue
            nip, rc = img[u]["nipple"], img[u]["reach"]
            for d in sorted(ds, key=lambda x: -float(x["score"]))[:a.topk]:
                r = TV.dist(nip, d["box"])
                pinfo[k][u].append((r, r / rc, float(d["score"])))

    tols = [float(x) for x in a.tols.split(",") if x.strip()]
    lams = [float(x) for x in a.lambdas.split(",") if x.strip()]

    # ── z 값 계산 (허용오차마다) ─────────────────────────────────
    #    검출 전부에 대해 낸다. 상위 k개만 내면 나머지가 중립값으로 밀려
    #    최대 재현율이 흔들린다.
    Z = {}
    print(f"\n  {'허용오차':>8}{'종류':<16}{'짝 있는 검출':>13}{'z 중앙값':>10}"
          f"{'짝 없는 영상':>13}")
    for t in tols:
        Z[t] = {}
        for k in PROMPTS:
            z, nopart = {}, 0
            for j, d in enumerate(raw.get(k, [])):
                u = str(d["img"])
                if u not in partner or u not in img:
                    nopart += 1
                    continue
                pl = pinfo[k].get(partner[u], [])
                r = TV.dist(img[u]["nipple"], d["box"]) / img[u]["reach"]
                z[j] = TV.hit(r, pl, t, True)
            if not z:
                die(f"{k} 에서 z 를 하나도 못 냈다.")
            v = np.array(list(z.values()), float)
            Z[t][k] = (z, float(np.median(v)))
            print(f"  {t:>8.2f}{k:<16}{int((v > 0).sum()):>13,}"
                  f"{np.median(v):>10.3f}{nopart:>13,}")

    # ── 파일 만들기 ─────────────────────────────────────────────
    made, seen0 = [], False
    print(f"\n■ 파일 만들기 — score × (1 − λ + λ·z)")
    for t in tols:
        for L in lams:
            if L == 0:
                if seen0:
                    continue
                seen0 = True
            obj = {k: v for k, v in raw.items() if k not in PROMPTS}
            for k in PROMPTS:
                z, nb = Z[t][k]
                obj[k] = [dict(d, score=float(d["score"])
                               * (1.0 - L + L * float(z.get(j, nb))))
                          for j, d in enumerate(raw.get(k, []))]
            tag = (f"tvL{int(round(L*100)):03d}" if L == 0 else
                   f"tv{int(round(t*100)):03d}_L{int(round(L*100)):03d}")
            dst = rp(a.out_dir) / f"{src.stem}_{tag}.json"
            if dst.resolve() == src.resolve():
                die("출력이 원본과 같다.")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
            note = "  ← 대조군. 원본과 같아야 한다" if L == 0 else ""
            print(f"  허용 {t:.2f} · λ={L:<5g} {dst.name}{note}")
            made.append(str(dst))

    print("\n다음 — 채점한다 (GPU 안 쓴다)")
    print("  python3 training/code/score_dets.py \\\n      " + str(src)
          + " \\\n      " + " \\\n      ".join(made)
          + " \\\n      --save docs/score_dets_twoview.json")
    print("""
  읽는 법 — 분류기 때와 같다
    ① λ=0 줄이 원본 줄과 **한 자리도 다르지 않아야 한다.**
    ② 판정은 center 기준 종류당 오탐 2개 칸. 지금 값은
         미세석회 77.5 · 종괴 76.7
       둘 다 오르면 붙인다. 하나만 오르면 그 종류에만. 둘 다 안 오르면 닫는다.
    ③ 만약 오르면 **이름을 바로 붙일 것.** 이득이 나는 허용오차(0.10~0.15)
       에서는 짝보유율이 97~99%라 이 값은 「두 시야에서 같은 자리」가 아니라
       «파트너 사진의 최고 검출 점수» — 증례 난이도 값이다. 두 시야 일치가
       통했다고 적으면 틀린 말이 된다.""")


if __name__ == "__main__":
    main()
