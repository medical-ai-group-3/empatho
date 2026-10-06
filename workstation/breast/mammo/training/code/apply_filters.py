#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""검출 파일에 후처리를 씌워 새 검출 파일들을 쓴다. 채점은 score_dets.py 가 한다.

좌표계 — 여기서 한 번 틀렸으니 적어 둔다
  eval_mammo_det 는 조직 상자로 **잘라낸** 영상 위에서 추론한다.

      cx0, cy0, cx1, cy1 = tissue_bbox(mask, pad)
      img = u8[cy0:cy1, cx0:cx1]

  그래서 저장된 검출 상자는 원본 좌표가 아니라 **자른 영상 기준 좌표**다.
  타일 격자도 자른 영상 위에서 (0,0) 부터 시작한다. 원본 좌표로 격자를
  만들어 맞추면, 상자 원점이 (0,0) 이 아닌 영상에서 전부 어긋난다.
  아래는 자른 영상 위에서만 계산한다.

타일 조직 비율도 eval 과 같게 잰다 — 가장자리 타일은 0 으로 채워 넣으므로
분모를 타일 전체 넓이로 둔다. 실제로 모델이 보는 것이 그 그림이다.

무엇을 씌우나
  T 타일 조직 문턱   조직 비율이 낮은 타일에서 나온 검출을 버린다.
  N 영상별 점수 정규화   영상 안에서 점수를 그 영상 최고점으로 나눈다.
      FROC 는 영상당 오탐으로 재는데 점수는 전체를 한 줄로 세워 매긴다.
      그래서 높은 점수 오탐을 쏟아내는 영상 하나가 모두의 오탐 예산을 먹는다.
      종괴는 후보 안에 병변이 대부분 들어 있는데 1FP 민감도가 낮다 —
      상자가 아니라 순서가 병목이라는 뜻이라 여기를 건드린다.

원본은 절대 덮어쓰지 않는다.

사용
  python3 training/code/apply_filters.py
  python3 training/code/apply_filters.py --tile-fracs 0.1,0.2,0.3
"""

import argparse
import copy
import json
import sys
from pathlib import Path

try:
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def grid_of(mask_crop, tile, stride):
    """자른 영상 위 타일 격자와 조직 비율.

    eval 의 두 겹 반복(바깥 positions(H), 안쪽 positions(W))과 같은 순서·같은
    좌표다. 가장자리 타일은 0 으로 채워지므로 분모를 타일 전체 넓이로 둔다.
    """
    H, W = mask_crop.shape[:2]
    area = float(tile * tile)
    out = []
    for ty in E.positions(H, tile, stride):
        for tx in E.positions(W, tile, stride):
            sub = mask_crop[ty:ty + tile, tx:tx + tile]
            out.append((tx, ty, tx + tile, ty + tile, float(np.sum(sub)) / area))
    return out


def in_any(box, tiles):
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    for tx1, ty1, tx2, ty2, _f in tiles:
        if tx1 <= cx <= tx2 and ty1 <= cy <= ty2:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--tile", type=int, default=1008)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--tile-fracs", default="0.1,0.2,0.3")
    ap.add_argument("--dets", default="archive/outputs/tile_dets_wbf03_tissue.json")
    ap.add_argument("--out-dir", default="archive/outputs")
    a = ap.parse_args()
    stride = max(1, a.tile - a.overlap)
    tfr = [float(x) for x in a.tile_fracs.split(",") if x.strip()]

    src = Path(a.dets)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = json.loads(src.read_text())
    kinds = [k for k in raw if isinstance(raw[k], list)]
    det_keys = {str(d["img"]) for k in kinds for d in raw[k]}
    print(f"원본 {src}")
    print(f"  검출 {sum(len(raw[k]) for k in kinds):,}건 · 영상 {len(det_keys):,}장 "
          f"· 종류 {kinds}")

    ents = E.load_gt(a.split)
    if not ents:
        die("load_gt 가 비었다.")
    # 검출 파일의 img 는 eval 이 uid 를 그대로 넣은 값이다. 그래도 확인한다.
    hit = sum(1 for u in ents if str(u) in det_keys)
    print(f"  이름 잇기 uid ({hit}/{len(ents)})")
    if hit < 0.9 * min(len(ents), len(det_keys)):
        die("uid 로 안 이어진다.\n"
            f"    검출 예시 {sorted(det_keys)[:2]}\n    색인 예시 {sorted(map(str, ents))[:2]}")

    print("\n화소 읽는 중 (영상당 한 번)")
    keep = {t: {} for t in tfr}
    uids = sorted(u for u in ents if str(u) in det_keys)
    miss, shifted = [], 0
    for i, uid in enumerate(uids, 1):
        try:
            arr = pydicom.dcmread(str(ents[uid]["dcm"])).pixel_array
        except Exception:
            miss.append(uid)
            continue
        if arr.ndim != 2:
            miss.append(uid)
            continue
        u8 = E.norm8(arr, a.clip)
        mask = E.tissue_mask(u8)
        tb = E.tissue_bbox(mask, a.pad)
        if tb is None:
            miss.append(uid)
            continue
        cx0, cy0, cx1, cy1 = tb
        if cx0 or cy0:
            shifted += 1
        grid = grid_of(mask[cy0:cy1, cx0:cx1], a.tile, stride)
        for t in tfr:
            keep[t][str(uid)] = [g for g in grid if g[4] >= t]
        if i % 20 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}", end="", flush=True)
    print()
    print(f"  조직 상자 원점이 (0,0) 이 아닌 영상 {shifted}/{len(uids)}장")
    if miss:
        # 못 읽은 영상의 검출은 손대지 않고 넘긴다. 조용히 버리면 필터 효과와
        # 읽기 실패가 뒤섞여 숫자를 해석할 수 없게 된다.
        print(f"  ⚠ 화소를 못 읽은 영상 {len(miss)}장 — 그 검출은 그대로 남긴다")

    def f_tile(t):
        def g(d):
            kt = keep[t].get(str(d["img"]))
            return kt is None or in_any(d["box"], kt)
        return g

    def normalize(obj):
        out = copy.deepcopy(obj)
        for k in kinds:
            top = {}
            for d in out[k]:
                img = str(d["img"])
                top[img] = max(top.get(img, 0.0), float(d["score"]))
            for d in out[k]:
                mx = top[str(d["img"])]
                if mx > 0:
                    d["score"] = float(d["score"]) / mx
        return out

    jobs = [(f"t{int(round(t*100)):02d}", f_tile(t), False,
             f"타일 조직 {t:.0%} 미만 버림") for t in tfr]
    jobs.append(("norm", None, True, "영상별 점수 정규화만"))
    jobs += [(f"t{int(round(t*100)):02d}norm", f_tile(t), True,
              f"타일 조직 {t:.0%} 미만 + 점수 정규화") for t in tfr]

    print(f"\n{'파일':<40}{'설명':<34}" + "".join(f"{k[:13]:>13}" for k in kinds))
    made = []
    for suffix, keepfn, do_norm, desc in jobs:
        obj = {k: (list(raw[k]) if keepfn is None
                   else [d for d in raw[k] if keepfn(d)]) for k in kinds}
        for k in raw:
            if k not in kinds:
                obj[k] = raw[k]
        if do_norm:
            obj = normalize(obj)
        dst = out_dir / f"{src.stem}_{suffix}.json"
        if dst.resolve() == src.resolve():
            die("출력이 원본과 같다. 덮어쓰지 않는다.")
        dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
        made.append(str(dst))
        print(f"{dst.name:<40}{desc:<34}"
              + "".join(f"{len(obj[k]):>13,}" for k in kinds))
    print(f"{'(원본)':<40}{'':<34}" + "".join(f"{len(raw[k]):>13,}" for k in kinds))

    print("\n다음 — 채점한다")
    print("  python3 training/code/score_dets.py \\\n      " + str(src) + " \\\n      "
          + " \\\n      ".join(made))


if __name__ == "__main__":
    main()
