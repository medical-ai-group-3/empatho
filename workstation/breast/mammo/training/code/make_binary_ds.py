#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""병변/정상 이진 분류기의 학습 목록을 만든다.

왜 만드나
  CBIS 는 병변이 있는 영상만 모은 집합이다. 검출기는 **정상 유방을 제대로
  본 적이 없다.** 그래서 밝은 덩어리마다 후보를 만들고, 그중 무엇이 그냥
  정상 조직인지 말하지 못한다.

  지금까지 시도한 11가지 중 성공한 둘(조직 마스크 · 유방 두께)은 전부
  **검출기가 볼 수 없는 정보**를 들여왔다. 실패한 아홉은 이미 본 것을
  재배열했다. 정상 조직의 생김새는 검출기가 못 본 정보다.

재료
  data/det_tile1008/annotations/train.json
    타일 7,857장 · 주석 4,204개
    병변 있는 타일 3,960 · **정상 타일 3,897**
    주석 bbox 는 타일 안 좌표(COCO xywh)라 변환이 필요 없다.

만드는 것
  양성  주석 상자마다 조각 하나
  음성  정상 타일에서 무작위로 뜬 상자

설계에서 조심한 것

  ① **음성의 크기 분포를 양성과 맞춘다.**
     아무 크기나 뜨면 분류기가 생김새가 아니라 **크기**를 배운다. 그러면
     시험에서는 잘 맞고 실제 검출 상자에는 안 통한다. 종류별 양성 상자
     크기에서 뽑아 쓴다.

  ② **음성도 조직 안에서만 뜬다.**
     서빙에서 분류기가 받게 될 검출 상자는 이미 조직 필터를 통과한
     것들이다(박스 면적의 절반 이상이 조직). 학습 음성이 공기나 배경이면
     분류기가 실전에서 만나지 않을 문제를 푼다.

  ③ **환자 단위로 나눈다.**
     같은 유방의 CC/MLO 가 학습과 검증에 갈라져 들어가면 성능이 부풀려진다.
     오늘 교차적합에서 겪은 것과 같은 함정이다. uid -> 환자 대응을 ROI
     색인에서 만들고, 못 만들면 **멈춘다** — 조용히 uid 로 나누면 새는 줄
     모른다.

나중에 붙일 것
  어려운 음성 — 학습 split 에서 검출기가 낸 오탐 상자.
  --hard 로 검출 파일을 주면 함께 담는다. **반드시 학습 split 이어야 한다.**
  test 오탐을 쓰면 시험 문제로 공부하는 셈이다.

사용
  python3 training/code/make_binary_ds.py
  python3 training/code/make_binary_ds.py --neg-per-tile 2 --val 0.15
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402

CAT = {1: "mass", 2: "calcification"}


def load_patients(index_dir):
    """uid -> 환자. ROI 색인에서 만든다. 못 만들면 빈 dict."""
    import csv
    out, cols_seen = {}, set()
    for p in sorted(Path(index_dir).glob("roi_index_*_train.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            cols_seen |= set(rd.fieldnames or [])
            pid_col = next((c for c in ("patient_id", "patient", "PatientID")
                            if c in (rd.fieldnames or [])), None)
            uid_col = next((c for c in ("uid", "series_uid", "sop_uid")
                            if c in (rd.fieldnames or [])), None)
            if not pid_col:
                continue
            for row in rd:
                u = row.get(uid_col) if uid_col else None
                if not u:
                    # image_path 의 뒤에서 두 번째 조각이 uid 인 규약
                    ip = row.get("image_path") or ""
                    parts = [s for s in ip.split("/") if s]
                    u = parts[-2] if len(parts) >= 2 else None
                if u:
                    out[u] = row[pid_col]
    return out, sorted(cols_seen)


def tissue_of(img, clip):
    return E.tissue_mask(E.norm8(img, clip))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", default="data/det_tile1008/annotations/train.json")
    ap.add_argument("--images", default="data/det_tile1008/images")
    ap.add_argument("--index", default="/home/wsuser/workspace/breast/labels/index")
    ap.add_argument("--out", default="data/binary_ds.json")
    ap.add_argument("--neg-per-tile", type=int, default=1,
                    help="정상 타일 하나에서 뜰 음성 개수")
    ap.add_argument("--tissue-frac", type=float, default=0.5,
                    help="서빙의 박스 조직 필터와 같은 값이어야 한다")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--val", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=20260904)
    ap.add_argument("--hard", default="",
                    help="어려운 음성으로 쓸 **학습 split** 검출 파일")
    ap.add_argument("--limit", type=int, default=0, help="정상 타일 맛보기")
    a = ap.parse_args()

    rnd = random.Random(a.seed)
    ann = json.loads(Path(a.ann).read_text())
    imgs = {im["id"]: im for im in ann["images"]}
    by_img = defaultdict(list)
    for x in ann["annotations"]:
        by_img[x["image_id"]].append(x)

    print("=" * 78)
    print("병변/정상 이진 분류기 — 학습 목록")
    print("=" * 78)
    print(f"  타일 {len(imgs):,} · 주석 {len(ann['annotations']):,}")
    print(f"  병변 타일 {len(by_img):,} · 정상 타일 {len(imgs)-len(by_img):,}")

    # ── 환자 대응 ────────────────────────────────────────────────
    pat, cols = load_patients(a.index)
    uids = {im["uid"] for im in imgs.values()}
    hit = sum(1 for u in uids if u in pat)
    print(f"\n  uid {len(uids):,}개 중 환자를 찾은 것 {hit:,}개")
    if hit < len(uids) * 0.9:
        print(f"  색인 열 이름: {cols}")
        sys.exit("[중단] uid -> 환자 대응이 부족하다. uid 로 나누면 같은 유방의 "
                 "CC/MLO 가 갈라져 성능이 부풀려진다. 열 이름을 알려 달라.")

    # ── 양성 ─────────────────────────────────────────────────────
    rows, sizes = [], defaultdict(list)
    for iid, anns in by_img.items():
        im = imgs[iid]
        for x in anns:
            bx, by, bw, bh = x["bbox"]
            if bw <= 2 or bh <= 2:
                continue
            kind = CAT.get(x["category_id"], "?")
            rows.append({"file": im["file_name"], "uid": im["uid"],
                         "box": [bx, by, bx + bw, by + bh],
                         "label": 1, "kind": kind, "src": "gt"})
            sizes[kind].append((bw, bh))

    print(f"\n  양성 {len(rows):,}개")
    for k, v in sizes.items():
        w = np.array([s[0] for s in v]); h = np.array([s[1] for s in v])
        print(f"    {k:<14} 가로 중앙 {np.median(w):6.0f} · "
              f"세로 중앙 {np.median(h):6.0f}  (n={len(v):,})")

    all_sizes = [s for v in sizes.values() for s in v]
    if not all_sizes:
        sys.exit("[중단] 양성이 없다.")

    # ── 음성 ① 정상 타일 ──────────────────────────────────────────
    normals = [im for iid, im in imgs.items() if iid not in by_img]
    if a.limit:
        normals = normals[:a.limit]
    print(f"\n  정상 타일 {len(normals):,}장에서 음성을 뜬다 "
          f"(타일당 {a.neg_per_tile}개 · 조직 {a.tissue_frac})")

    root = Path(a.images)
    n_neg, n_skip_read, n_skip_tissue = 0, 0, 0
    for i, im in enumerate(normals, 1):
        img = cv2.imread(str(root / im["file_name"]), cv2.IMREAD_UNCHANGED)
        if img is None:
            n_skip_read += 1
            continue
        if img.ndim == 3:
            img = img[:, :, 0]
        H, W = img.shape[:2]
        mask = tissue_of(img, a.clip).astype(np.float32)
        got = 0
        for _ in range(a.neg_per_tile * 25):
            if got >= a.neg_per_tile:
                break
            bw, bh = all_sizes[rnd.randrange(len(all_sizes))]
            bw, bh = min(bw, W - 2), min(bh, H - 2)
            x0 = rnd.uniform(0, W - bw); y0 = rnd.uniform(0, H - bh)
            sub = mask[int(y0):int(y0 + bh), int(x0):int(x0 + bw)]
            if sub.size == 0 or sub.mean() < a.tissue_frac:
                continue
            rows.append({"file": im["file_name"], "uid": im["uid"],
                         "box": [x0, y0, x0 + bw, y0 + bh],
                         "label": 0, "kind": "none", "src": "normal"})
            got += 1; n_neg += 1
        if got == 0:
            n_skip_tissue += 1
        if i % 200 == 0 or i == len(normals):
            print(f"\r    {i}/{len(normals)}  음성 {n_neg:,}", end="", flush=True)
    print()
    if n_skip_read:
        print(f"    못 읽은 타일 {n_skip_read}장")
    if n_skip_tissue:
        print(f"    조직이 모자라 하나도 못 뜬 타일 {n_skip_tissue}장")

    # ── 음성 ② 어려운 음성 ────────────────────────────────────────
    if a.hard:
        print(f"\n  ⚠ 어려운 음성은 아직 안 붙였다 — {a.hard}")
        print("    학습 split 검출 파일이 필요하고, 타일 좌표로 되돌리는 "
              "변환을 먼저 검증해야 한다. 별도 작업으로 뺀다.")

    # ── 환자 단위 분할 ────────────────────────────────────────────
    pats = sorted({pat[r["uid"]] for r in rows if r["uid"] in pat})
    rnd.shuffle(pats)
    n_val = max(1, int(len(pats) * a.val))
    val_set = set(pats[:n_val])
    for r in rows:
        r["patient"] = pat.get(r["uid"], "?")
        r["split"] = "val" if r["patient"] in val_set else "train"

    cnt = Counter((r["split"], r["label"]) for r in rows)
    print(f"\n  환자 {len(pats):,}명 · 검증 {len(val_set):,}명")
    print(f"\n  {'':8}{'양성':>9}{'음성':>9}{'합':>9}")
    for sp in ("train", "val"):
        p, n = cnt[(sp, 1)], cnt[(sp, 0)]
        print(f"  {sp:<8}{p:>9,}{n:>9,}{p+n:>9,}")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "images_root": str(root), "tissue_frac": a.tissue_frac,
        "clip": a.clip, "seed": a.seed, "rows": rows,
    }, ensure_ascii=False))
    print(f"\n  저장 -> {out}  ({len(rows):,}줄)")

    print("""
  다음 — 특징을 뽑고 헤드를 학습한다 (GPU)

    python3 training/code/train_binary.py --ds data/binary_ds.json --cache

  백본이 동결이라 특징은 한 번만 뽑으면 되고, 그다음 헤드 학습은 몇 초다.
  설정을 여러 개 시험할 수 있다.""")


if __name__ == "__main__":
    main()
