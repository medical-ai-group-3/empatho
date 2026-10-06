#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""저장된 검출 파일을 채점한다 — eval_mammo_det 의 함수를 그대로 불러 쓴다.

왜 필요한가
  eval_mammo_det.py 는 검출 파일을 입력으로 못 받는다. 추론을 돌려서
  저장만 한다. 후처리를 바꿔 가며 재는데 매번 GPU 83분을 쓸 수는 없다.

왜 지표를 다시 구현하지 않나
  froc · at_fp · iou · center_in 을 eval_mammo_det 에서 import 한다.
  정답 만드는 경로도 그쪽 main() 을 한 줄씩 그대로 옮겼다 —
    · 마스크 크기가 영상과 다르면 **버린다** (다시 재지 않는다)
    · 정답이 하나도 없는 영상은 통째로 건너뛴다
    · 조직 상자로 자른 뒤 **상자 기준 좌표로 옮긴다**
  마지막 줄이 핵심이다. 검출 파일의 상자는 원본 좌표가 아니라 조직 상자
  기준 좌표다. 이걸 놓치면 상자 원점이 밀린 영상에서 전부 어긋난다.

검증
  원본 검출 파일을 넣었을 때 docs/merge_tissue.json 의 wbf@0.3 과
  같은 값이 나와야 한다. 안 나오면 정답 만드는 경로가 아직 다른 것이다.

사용
  python3 training/code/score_dets.py archive/outputs/tile_dets_wbf03_tissue*.json
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402


def need(*names):
    miss = [n for n in names if not hasattr(E, n)]
    if miss:
        sys.exit(f"[중단] eval_mammo_det 에 {miss} 가 없다. 이름이 바뀌었으면 알려 달라.")


need("load_gt", "mask_box", "norm8", "tissue_mask", "tissue_bbox",
     "froc", "at_fp", "iou", "center_in", "CAT", "FP_POINTS")
PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])


def build_gt(split, clip, pad, n):
    """eval_mammo_det.main() 의 정답 구성 부분을 그대로 옮긴 것."""
    ents = E.load_gt(split)
    uids = sorted(ents)
    if n:
        uids = uids[:n]
    name_of = {v: k for k, v in E.CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}
    gts = {p: defaultdict(list) for p in PROMPTS}
    origin, done, skipped = {}, 0, 0

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
        boxes = []
        for cid, mp in e["masks"]:
            b, shp = E.mask_box(mp)
            if b is not None and shp == arr.shape[:2]:
                boxes.append((cid, b))
        if not boxes:                       # 정답이 없으면 eval 은 통째로 건너뛴다
            skipped += 1
            continue
        u8 = E.norm8(arr, clip)
        mask = E.tissue_mask(u8)
        tb = E.tissue_bbox(mask, pad)
        if tb is None:
            skipped += 1
            continue
        cx0, cy0, cx1, cy1 = tb
        origin[uid] = (cx0, cy0, cx1 - cx0, cy1 - cy0)
        for cid, b in boxes:
            gts[alias[name_of[cid]]][uid].append(
                (b[0] - cx0, b[1] - cy0, b[2] - cx0, b[3] - cy0))
        done += 1
        if i % 20 == 0 or i == len(uids):
            print(f"\r  정답 만드는 중 {i}/{len(uids)}", end="", flush=True)
    print()
    return gts, origin, done, skipped


def score(path, gts, done, iou_thr, keep):
    raw = json.loads(Path(path).read_text())
    out = {}
    for name in PROMPTS:
        g = {u: v for u, v in gts[name].items() if v}
        n_gt = sum(len(v) for v in g.values())
        if not n_gt:
            continue
        d = [x for x in raw.get(name, []) if str(x["img"]) in keep]
        row = {"n_det": len(d), "n_gt": n_gt}
        for label, fn in (("center", lambda p, q: 1.0 if E.center_in(p, q) else 0.0),
                          ("iou", lambda p, q, t=iou_thr:
                           1.0 if E.iou(p, q) >= t else 0.0)):
            curve = E.froc(d, n_gt, done, fn, g)
            row[label] = {t: E.at_fp(curve, t)[0] for t in E.FP_POINTS}
            row[label]["max"] = (max(s for _, s, _ in curve) if curve else 0.0)
            # 그 작동점의 **점수 임계값**. 운영에 그대로 넣는 값이라 같이 낸다.
            # 후처리를 바꾸면 이 값이 움직인다 — 안 바꾸고 후처리만 넣으면
            # 검출이 확 줄어든다.
            row[label + "_thr"] = {t: E.at_fp(curve, t)[1] for t in E.FP_POINTS}
        out[name] = row
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--ref", default="docs/merge_tissue.json")
    ap.add_argument("--save", default="docs/score_dets.json")
    a = ap.parse_args()

    print("=" * 92)
    print("저장된 검출 채점 — eval_mammo_det 의 froc · at_fp 를 그대로 쓴다")
    print("=" * 92)
    gts, origin, done, skipped = build_gt(a.split, a.clip, a.pad, a.n)
    print(f"  영상 {done}장" + (f" · 건너뛴 영상 {skipped}장" if skipped else ""))
    for p in PROMPTS:
        print(f"  정답 {p:<14} {sum(len(v) for v in gts[p].values()):,}건")
    off = sum(1 for v in origin.values() if v[0] or v[1])
    print(f"  조직 상자 원점이 (0,0) 이 아닌 영상 {off}/{done}장"
          " — 여기서 좌표계를 틀리면 이만큼이 통째로 어긋난다")
    keep = set(origin)

    pts = list(E.FP_POINTS)
    hdr = f"{'파일':<26}{'종류':<14}{'':<7}" + "".join(f"{t:>8}" for t in pts) + f"{'max':>8}"

    res = {}
    for f in a.files:
        res[Path(f).name] = score(f, gts, done, a.iou, keep)

    ref = Path(a.ref)
    if ref.is_file():
        rj = json.loads(ref.read_text())
        node = next((rj[x] for x in rj if "wbf" in x and "0.3" in x), None)
        if node:
            r = {}
            for p in PROMPTS:
                if p not in node:
                    continue
                row = {"n_det": node[p].get("n_det", 0), "n_gt": 0}
                for m in ("center", "iou"):
                    d = node[p].get(m, {})
                    row[m] = {t: d.get(str(t), float("nan")) for t in pts}
                    row[m]["max"] = d.get("max", float("nan"))
                r[p] = row
            res["(참조) merge_tissue wbf@0.3"] = r

    for mode in ("center", "iou"):
        print(f"\n{'='*92}\n{mode} 기준 · 영상당 오탐별 민감도\n{'='*92}")
        print(hdr)
        for fname, r in res.items():
            for p in PROMPTS:
                if p not in r:
                    continue
                v = r[p][mode]
                print(f"{fname[:26]:<26}{p[:14]:<14}{r[p]['n_det']:>7,}"
                      + "".join(f"{v[t]:>8.3f}" for t in pts)
                      + f"{v['max']:>8.3f}")

    print(f"\n{'='*92}\n운영에 넣을 점수 임계값 — center 기준, 각 작동점\n{'='*92}")
    print("이 값을 infer_mammo.DEFAULTS 의 score_calc · score_mass 에 넣는다.")
    print("후처리를 바꿨으면 **반드시 다시 뽑아야 한다** — 안 바꾸고 후처리만")
    print("넣으면 임계값이 너무 높아 검출이 확 줄어든다.")
    print(hdr)
    for fname, r in res.items():
        for p in PROMPTS:
            if p not in r or "center_thr" not in r[p]:
                continue
            v = r[p]["center_thr"]
            print(f"{fname[:26]:<26}{p[:14]:<14}{r[p]['n_det']:>7,}"
                  + "".join(f"{v[t]:>8.3f}" if v[t] is not None else f"{'—':>8}"
                            for t in pts) + f"{'':>8}")

    if a.save:
        sp = Path(a.save)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(res, ensure_ascii=False, default=float, indent=1))
        print(f"\n저장 -> {sp}")
    print("\n※ 원본 파일 줄이 (참조) 줄과 같아야 한다. 다르면 정답 만드는 경로가")
    print("  아직 eval_mammo_det 와 다른 것이니 그 상태로 아래 비교를 믿으면 안 된다.")


if __name__ == "__main__":
    main()
