#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""검출 파일에 종류별 점수 임계값을 미리 적용한다.

왜 필요한가
  eval_end2end.py 의 --score 는 값이 하나뿐이라 종류별로 못 준다. 게다가
  기본값이 0.0 이라 **임계값을 아예 안 쓴다** — 검출 파일을 통째로 받아
  topk 로만 고른다. 그래서 지금까지 잰 끝단 수치는

      점수가 얼마든 영상·종류당 상위 2개를 무조건 넘긴다

  는 조건이고, **서빙도 CLI 도 그렇게 동작하지 않는다.** 둘 다 임계값으로
  자른 뒤 제한 없이 넘긴다.

  실제 동작을 재려면 임계값을 미리 적용한 파일을 만들어
  `--topk 0 --score 0` 으로 넣으면 된다.

사용
  python3 training/code/cut_dets.py \\
      --dets archive/outputs/tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json \\
      --cut 0.504,0.519
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", required=True)
    ap.add_argument("--cut", default="0.504,0.519",
                    help="종류 순서대로. infer_mammo.DEFAULTS 와 같아야 한다")
    ap.add_argument("--topk", type=int, default=0,
                    help="0 이면 제한 없음. 서빙과 같게 두는 것이 기본")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    src = Path(a.dets)
    raw = json.loads(src.read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    cuts = [float(x) for x in a.cut.split(",") if x.strip()]
    if len(cuts) != len(kinds):
        sys.exit(f"[중단] --cut 개수가 종류 {kinds} 와 안 맞는다: {cuts}")
    cut = dict(zip(kinds, cuts))

    print(f"원본 {src}")
    obj = {k: v for k, v in raw.items() if k not in kinds}
    for k in kinds:
        keep = [d for d in raw[k] if float(d["score"]) >= cut[k]]
        if a.topk:
            per = defaultdict(list)
            for d in keep:
                per[str(d["img"])].append(d)
            keep = []
            for u, lst in per.items():
                lst.sort(key=lambda d: -float(d["score"]))
                keep += lst[:a.topk]
        obj[k] = keep
        n_img = len({str(d["img"]) for d in keep})
        print(f"  {k:<16} {len(raw[k]):>7,} → {len(keep):>7,}건 "
              f"(임계값 {cut[k]}) · 영상 {n_img}장 · 영상당 "
              f"{len(keep)/max(1, n_img):.2f}개")

    tag = f"cut{int(round(cuts[0]*1000)):03d}"
    if a.topk:
        tag += f"_top{a.topk}"
    dst = Path(a.out) if a.out else src.with_name(f"{src.stem}_{tag}.json")
    if dst.resolve() == src.resolve():
        sys.exit("[중단] 출력이 원본과 같다.")
    dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
    print(f"\n저장 -> {dst}")
    print("\n다음 — 끝단을 잰다 (임계값이 이미 적용됐으니 --score 0 --topk 0)")
    print(f"  python3 eval_end2end.py --dets {dst.resolve()} --topk 0 --score 0")


if __name__ == "__main__":
    main()
