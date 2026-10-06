#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""이진 분류기 학습 목록 2판 — DICOM 에서 직접, 어려운 음성까지.

1판과 무엇이 다른가

  1판은 1008px 타일 PNG 에서 조각을 오렸다. 그런데 실전에서 분류기가 받는
  것은 **조직 상자로 자른 DICOM 배열**에서 오린 조각이다. 어긋남이 넷 있었다.
    · 원본이 다르다 (타일 PNG vs DICOM 배열)
    · 잘리는 경계가 다르다 (타일 경계 vs 조직 상자 경계)
    · 타일 PNG 는 이미 한 번 정규화된 것이다
    · 음성이 «무작위 조직» 이었다. 실전 음성은 «검출기가 착각한 자리» 다

  2판은 전부 DICOM 에서 오린다. 앞의 셋이 사라지고, 네 번째는 어려운 음성으로
  메운다.

세 갈래 재료

  양성       정답 병변 상자                    label 1
  쉬운 음성  조직 안 무작위 상자               label 0 · src=easy
  어려운 음성 검출기가 냈는데 정답과 안 겹친 것  label 0 · src=hard

  어려운 음성이 핵심이다. 「병변처럼 생겼는데 아닌 것」을 직접 가르친다.

좌표계
  모든 상자는 **조직 상자 기준**이다. 검출 파일과 같은 기준이라 변환이 없다.
  목록에는 DICOM 경로와 조직 상자 원점을 같이 적어, 읽는 쪽이 같은 자리를
  다시 만들 수 있게 한다.

조심한 것

  ① 음성 크기를 양성 분포에서 뽑는다 (쉬운 음성). 아무 크기나 뜨면 분류기가
     생김새가 아니라 크기를 배운다.
  ② 쉬운 음성도 조직 안에서만 뜬다. 실전 검출 상자는 이미 조직 필터를
     통과한 것들이다.
  ③ **환자 단위로 나눈다.** 같은 유방의 CC/MLO 가 갈라지면 부풀려진다.
  ④ 어려운 음성은 **점수 높은 것부터** 고른다. 낮은 것은 어차피 화면에
     안 뜨므로 가르칠 값어치가 없다.

사용
  # 어려운 음성 없이 (검출 파일이 아직 없을 때)
  python3 training/code/make_binary_ds2.py --n 600

  # 어려운 음성까지
  python3 training/code/make_binary_ds2.py --n 600 \\
      --hard archive/outputs/tile_dets_train600.json
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 저장소 뿌리를 스스로 찾는다. 작업 디렉터리가 어디든 상대 경로가 맞게
# 풀리도록 — 같은 실수를 세 번 했다.
ROOT = Path(__file__).resolve().parents[2]


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)

import eval_mammo_det as E                                    # noqa: E402

PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])
ALIAS = {"calc": "calcification", "mass": "mass"}


def patients(index_dir):
    out = {}
    for p in Path(index_dir).glob("roi_index_*_train.csv"):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                parts = [x for x in (row.get("image_path") or "").split("/") if x]
                if len(parts) >= 2 and row.get("patient_id"):
                    out[parts[-2]] = row["patient_id"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train")
    ap.add_argument("--index", default="/home/wsuser/workspace/breast/labels/index")
    ap.add_argument("--out", default="data/binary_ds2.json")
    ap.add_argument("--hard", default="", help="**학습 split** 검출 파일")
    ap.add_argument("--n", type=int, default=600, help="영상 수. 0 이면 전부")
    ap.add_argument("--easy-per-img", type=int, default=4)
    ap.add_argument("--hard-per-img", type=int, default=6)
    ap.add_argument("--tissue-frac", type=float, default=0.5)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--val", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=20260904)
    a = ap.parse_args()

    rnd = random.Random(a.seed)
    pat = patients(a.index)

    print("=" * 78)
    print("이진 분류기 학습 목록 2판 — DICOM 에서 직접")
    print("=" * 78)

    ents = E.load_gt(a.split)
    uids = sorted(ents)
    if a.n:
        uids = uids[:a.n]
    print(f"  영상 {len(uids):,}장 (split={a.split})")

    miss = [u for u in uids if u not in pat]
    if len(miss) > len(uids) * 0.1:
        sys.exit(f"[중단] 환자를 못 찾은 영상 {len(miss)}장. 환자 단위로 못 나눈다.")

    # ── 어려운 음성 재료 ─────────────────────────────────────────
    hard = defaultdict(list)
    if a.hard:
        raw = json.loads(Path(a.hard).read_text())
        for kind in PROMPTS:
            for d in raw.get(kind, []):
                hard[str(d["img"])].append(
                    (tuple(map(float, d["box"])), float(d["score"]), kind))
        for u in hard:
            hard[u].sort(key=lambda t: -t[1])
        print(f"  검출 파일 {Path(a.hard).name} · 영상 {len(hard):,}장")
    else:
        print("  어려운 음성 없음 (--hard 를 주면 붙는다)")

    name_of = {v: k for k, v in E.CAT.items()}
    rows, sizes, skipped = [], [], 0

    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr16 = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            skipped += 1
            continue
        if arr16.ndim != 2:
            skipped += 1
            continue

        boxes = []
        for cid, mp in e["masks"]:
            b, shp = E.mask_box(mp)
            if b is not None and shp == arr16.shape[:2]:
                boxes.append((ALIAS[name_of[cid]], b))
        if not boxes:
            skipped += 1
            continue

        u8 = E.norm8(arr16, a.clip)
        mask = E.tissue_mask(u8)
        tb = E.tissue_bbox(mask, a.pad)
        if tb is None:
            skipped += 1
            continue
        cx0, cy0, cx1, cy1 = tb
        crop = [int(cx0), int(cy0), int(cx1 - cx0), int(cy1 - cy0)]
        sub = mask[cy0:cy1, cx0:cx1].astype(np.float32)
        H, W = sub.shape
        common = dict(dcm=str(e["dcm"]), crop=crop, uid=uid,
                      patient=pat.get(uid, "?"))

        # 양성 — 조직 상자 기준으로 옮긴다
        gt_here = []
        for kind, b in boxes:
            q = (b[0] - cx0, b[1] - cy0, b[2] - cx0, b[3] - cy0)
            gt_here.append(q)
            rows.append(dict(box=[float(v) for v in q], label=1,
                             kind=kind, src="gt", **common))
            sizes.append((q[2] - q[0], q[3] - q[1]))

        # 쉬운 음성 — 조직 안 무작위. 크기는 양성 분포에서
        pool = sizes or [(200.0, 200.0)]
        got = 0
        for _ in range(a.easy_per_img * 30):
            if got >= a.easy_per_img:
                break
            bw, bh = pool[rnd.randrange(len(pool))]
            bw, bh = min(bw, W - 2), min(bh, H - 2)
            if bw < 8 or bh < 8:
                continue
            x0 = rnd.uniform(0, W - bw); y0 = rnd.uniform(0, H - bh)
            q = (x0, y0, x0 + bw, y0 + bh)
            if any(E.center_in(q, g) for g in gt_here):
                continue                     # 정답 위에 뜬 것은 음성이 아니다
            s = sub[int(y0):int(y0 + bh), int(x0):int(x0 + bw)]
            if s.size == 0 or s.mean() < a.tissue_frac:
                continue
            rows.append(dict(box=[float(v) for v in q], label=0,
                             kind="none", src="easy", **common))
            got += 1

        # 어려운 음성 — 점수 높은 것부터, 정답과 안 겹치는 것만
        got = 0
        for q, sc, kind in hard.get(uid, []):
            if got >= a.hard_per_img:
                break
            if any(E.center_in(q, g) for g in gt_here):
                continue
            rows.append(dict(box=[float(v) for v in q], label=0,
                             kind=kind, src="hard", score=sc, **common))
            got += 1

        if i % 25 == 0 or i == len(uids):
            print(f"\r  {i}/{len(uids)}  줄 {len(rows):,}", end="", flush=True)
    print()
    if skipped:
        print(f"  건너뛴 영상 {skipped}장")

    # ── 환자 단위 분할 ────────────────────────────────────────────
    ps = sorted({r["patient"] for r in rows})
    rnd.shuffle(ps)
    val = set(ps[:max(1, int(len(ps) * a.val))])
    for r in rows:
        r["split"] = "val" if r["patient"] in val else "train"

    cnt = defaultdict(int)
    for r in rows:
        cnt[(r["split"], r["src"])] += 1
    print(f"\n  환자 {len(ps):,}명 · 검증 {len(val):,}명")
    print(f"\n  {'':8}{'양성':>9}{'쉬운음성':>10}{'어려운음성':>12}{'합':>9}")
    for sp in ("train", "val"):
        g, ee, h = cnt[(sp, "gt")], cnt[(sp, "easy")], cnt[(sp, "hard")]
        print(f"  {sp:<8}{g:>9,}{ee:>10,}{h:>12,}{g+ee+h:>9,}")

    if a.hard and cnt[("train", "hard")] == 0:
        print("\n  ⚠ 어려운 음성이 하나도 안 붙었다. 검출 파일의 img 값이 "
              "이 split 의 uid 와 다른 것이 아닌지 확인할 것.")

    op = Path(a.out).resolve()
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps({
        "mode": "dcm", "clip": a.clip, "pad": a.pad,
        "tissue_frac": a.tissue_frac, "seed": a.seed,
        "hard_from": a.hard, "rows": rows,
    }, ensure_ascii=False))
    print(f"\n  저장 -> {op}  ({len(rows):,}줄)")

    print("""
  다음 — 특징을 뽑고 헤드를 학습한다 (GPU)

    python3 training/code/train_binary.py --cache \\
      --ds  "$PWD/data/binary_ds2.json" \\
      --feat-cache "$PWD/data/binary_feats2.npz" \\
      --out "$PWD/training/ckpt/binary_head2.pt"

  1판 캐시(binary_feats.npz)와 파일 이름을 달리할 것. 조각 만드는 법이
  달라서 섞으면 안 된다.""")


if __name__ == "__main__":
    main()
