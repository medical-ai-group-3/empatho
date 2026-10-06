#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""topk 를 몇으로 둘지 — 결정에 필요한 숫자를 뽑는다.

무엇이 걸려 있나
  서빙은 topk=0(제한 없음, 임계값만으로 자른다)이고 predict.py·eval_end2end 는
  영상·종류당 상위 2개만 넘긴다. 그래서 발표 자료의 끝단 수치와
  「영상당 조직검사 권고 2.34개」는 **상위 2개 설정의 값이고 서빙 동작이 아니다.**

  둘 중 하나로 맞춰야 하는데 이건 팀 결정이다. 여기서는 결정에 필요한 숫자만
  낸다. 문서의 근거(1개 46.6% vs 2개 67.2%)는 순위가 나쁘던 때 값이라
  지금은 다를 수 있다.

무엇을 재나 (영상·종류당)
  ① 임계값을 넘는 검출이 몇 개나 되는가 — 제한이 실제로 걸리기는 하는가
  ② topk 로 자르면 **정탐을 몇 개 잃는가** — 그게 민감도 손실이다
  ③ topk 로 자르면 오탐이 몇 개 주는가 — 그게 불필요한 조직검사 권고 감소다

  ②와 ③의 교환비가 결정 근거다. 암을 놓치는 비용이 추가 검사보다 크므로
  ②가 크면 제한을 두면 안 된다.

crossfit 캐시를 쓴다 — 검출마다 타일 조직 비율 · 깊이 · 정탐 여부가 들어 있어
DICOM 을 다시 안 읽는다. GPU 도 안 쓴다.

사용
  python3 training/code/topk_check.py
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", default="archive/outputs/tile_dets_wbf03_tissue.json")
    ap.add_argument("--cache", default="docs/crossfit_cache.npz")
    ap.add_argument("--tile-frac", type=float, default=0.30)
    ap.add_argument("--lam", default="0.15,0.35")
    ap.add_argument("--cut", default="0.504,0.519",
                    help="종류 순서대로 점수 임계값. 운영값과 같아야 한다")
    ap.add_argument("--topks", default="1,2,3,5")
    a = ap.parse_args()

    raw = json.loads(Path(a.dets).read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    lam = {k: float(v) for k, v in zip(kinds, a.lam.split(","))}
    cut = {k: float(v) for k, v in zip(kinds, a.cut.split(","))}
    topks = [int(x) for x in a.topks.split(",") if x.strip()]

    p = Path(a.cache)
    side = p.with_suffix(".json")
    if not (p.is_file() and side.is_file()):
        sys.exit(f"[중단] 캐시가 없다: {p}\n  crossfit.py 를 먼저 한 번 돌릴 것.")
    z = np.load(p)
    j = json.loads(side.read_text())
    imgs = set(j["imgs"])

    print("=" * 84)
    print("topk 를 몇으로 둘지 — 결정 근거")
    print("=" * 84)
    print(f"  설정  타일 {a.tile_frac} · λ {lam} · 임계값 {cut}")
    print(f"  영상 {len(imgs):,}장")

    # 운영 설정을 그대로 씌운 뒤 영상·종류별로 점수 내림차순 정렬
    per = {k: defaultdict(list) for k in kinds}
    n_gt = {}
    for k in kinds:
        tf, dp, tp = z[f"tf_{k}"], z[f"dp_{k}"], z[f"tp_{k}"]
        for i, d in enumerate(raw[k]):
            u = str(d["img"])
            if u not in imgs or np.isnan(tf[i]) or tf[i] < a.tile_frac:
                continue
            s = float(d["score"])
            if lam[k] > 0 and not np.isnan(dp[i]):
                s *= (1.0 - lam[k] + lam[k] * float(dp[i]))
            if s < cut[k]:
                continue
            per[k][u].append((s, bool(tp[i]), tuple(d["box"])))
        for u in per[k]:
            per[k][u].sort(key=lambda x: -x[0])
        n_gt[k] = sum(len(v) for u, v in j["gt"][k].items() if u in imgs)

    print(f"\n{'종류':<16}{'정답':>7}{'검출':>9}{'영상당 중앙':>12}"
          f"{'90퍼':>7}{'최대':>7}{'2개 초과 영상':>14}")
    counts = {}
    for k in kinds:
        c = np.array([len(per[k].get(u, [])) for u in imgs])
        counts[k] = c
        print(f"{k:<16}{n_gt[k]:>7,}{int(c.sum()):>9,}{np.median(c):>12.1f}"
              f"{np.percentile(c, 90):>7.0f}{c.max():>7.0f}"
              f"{100*float((c > 2).mean()):>13.0f}%")

    def covers(box, g, thr=0.3):
        cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        if g[0] <= cx <= g[2] and g[1] <= cy <= g[3]:
            return True
        ix1, iy1 = max(box[0], g[0]), max(box[1], g[1])
        ix2, iy2 = min(box[2], g[2]), min(box[3], g[3])
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return False
        ua = ((box[2]-box[0])*(box[3]-box[1]) + (g[2]-g[0])*(g[3]-g[1]) - inter)
        return ua > 0 and inter / ua >= thr

    print(f"\n{'종류':<16}{'topk':>6}{'남는 검출':>11}{'덮은 병변':>11}"
          f"{'잃는 병변':>11}{'병변 손실률':>13}{'영상당 오탐':>12}")
    print("  ※ '병변' 단위다. 한 병변에 검출이 여럿 붙어 있으면 상위만 남겨도")
    print("    병변은 안 잃는다 — 검출 단위로 세면 손실이 과대평가된다.")
    for k in kinds:
        gt_k = {u: v for u, v in j["gt"][k].items() if u in imgs}
        base = None
        for tk in [0] + topks:
            kept = kept_fp = 0
            hit = 0
            for u in imgs:
                lst = per[k].get(u, [])
                if tk:
                    lst = lst[:tk]
                kept += len(lst)
                kept_fp += sum(1 for _s, t, _b in lst if not t)
                for g in gt_k.get(u, ()):
                    if any(covers(b, g) for _s, _t, b in lst):
                        hit += 1
            if base is None:
                base = hit
            lost = base - hit
            tag = "제한 없음" if tk == 0 else str(tk)
            print(f"{k:<16}{tag:>6}{kept:>11,}{hit:>11,}{lost:>11,}"
                  f"{100*lost/max(1,base):>12.1f}%{kept_fp/len(imgs):>12.2f}")

    print("\n" + "=" * 84)
    print("읽는 법")
    print("=" * 84)
    print("  · '2개 초과 영상' 이 작으면 topk=2 는 사실상 아무 일도 안 한다.")
    print("    그러면 서빙(0)과 채점(2)의 차이가 수치에 거의 안 나타나고,")
    print("    어느 쪽으로 맞추든 실질 차이가 없다는 뜻이다.")
    print("  · '잃는 병변' 이 결정의 핵심이다. 암을 놓치는 비용이 추가 검사보다")
    print("    크므로, 이 값이 크면 제한을 두면 안 된다.")
    print("    (검출 단위가 아니라 병변 단위다 — 한 병변에 검출이 여럿이면")
    print("     상위만 남겨도 병변은 안 잃는다)")
    print("  · '영상당 오탐' 은 불필요한 조직검사 권고의 상한이다. 다만 이 검출이")
    print("    전부 서술어를 거쳐 '조직검사 권고' 가 되는 것은 아니므로")
    print("    끝단 수치와 직접 비교하면 안 된다.")


if __name__ == "__main__":
    main()
