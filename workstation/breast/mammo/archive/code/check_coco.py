#!/usr/bin/env python
"""
COCO 변환 결과를 검사한다 — 박스가 실제 병변 위에 있는가.

왜 필요한가
  JSON 이 읽힌다는 것과 박스가 옳은 자리에 있다는 것은 다른 문제다.
  마스크 좌표계가 어긋나 있으면 형식은 완벽한데 내용이 어긋난 데이터로
  학습을 돌리게 된다. 그 실패는 손실 곡선만 봐서는 알아채기 어렵다.

무엇으로 판단하나 — 눈 없이도 되는 세 가지
  1. 박스가 유방 조직 위에 있는가
     유방촬영은 배경이 검다. 박스 안 평균 밝기가 배경 수준이면 어긋난 것이다.
     '박스 안 밝기'와 '영상 전체 밝기'를 비교한다.
  2. 박스 크기가 그럴듯한가
     종괴는 화면의 수 퍼센트, 석회 군집은 그보다 작다. 화면의 절반을
     차지하거나 몇 화소밖에 안 되면 마스크를 잘못 읽은 것이다.
  3. 종괴와 석회의 크기 분포가 갈리는가
     둘이 구분되지 않으면 범주 배정이 섞였을 가능성이 있다.

그리고 눈으로 볼 것
  --save 로 박스를 그린 PNG 를 몇 장 남긴다. 위 지표가 통과해도
  한 번은 봐야 한다.

사용
  python3 check_coco.py                      # 학습·검증 둘 다
  python3 check_coco.py --save overlay/      # 그림도 남긴다
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}  ->  pip install pillow")

HOME = Path.home()
COLOR = {1: (255, 80, 80), 2: (80, 200, 255)}     # mass 붉은색, calc 하늘색


def pct(vals, p):
    return float(np.percentile(vals, p)) if len(vals) else float("nan")


def analyse(root, split_name, img_split, save_dir, n_save):
    ann_path = root / "annotations" / f"{split_name}.json"
    if not ann_path.is_file():
        print(f"  없음: {ann_path}")
        return
    coco = json.loads(ann_path.read_text(encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in coco["categories"]}
    by_img = defaultdict(list)
    for an in coco["annotations"]:
        by_img[an["image_id"]].append(an)
    imgs = {im["id"]: im for im in coco["images"]}

    print(f"\n{'='*74}\n{split_name}  —  영상 {len(imgs)}  주석 {len(coco['annotations'])}\n{'='*74}")

    rec = defaultdict(lambda: {"frac": [], "contrast": [], "dark": 0, "n": 0})
    missing = 0
    saved = 0

    for img_id, im in sorted(imgs.items()):
        p = root / "images" / img_split / im["file_name"]
        if not p.is_file():
            missing += 1
            continue
        arr = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
        H, W = arr.shape
        # 배경 기준선: 하위 25% 밝기. 유방촬영 배경은 거의 0 이다.
        bg = float(np.percentile(arr, 25))
        whole = float(arr.mean())

        draw_im = None
        if save_dir and saved < n_save:
            draw_im = Image.open(p).convert("RGB")
            d = ImageDraw.Draw(draw_im)

        for an in by_img[img_id]:
            x, y, w, h = an["bbox"]
            x0, y0 = int(max(0, x)), int(max(0, y))
            x1, y1 = int(min(W, x + w)), int(min(H, y + h))
            if x1 <= x0 or y1 <= y0:
                continue
            patch = arr[y0:y1, x0:x1]
            c = cats.get(an["category_id"], "?")
            r = rec[c]
            r["n"] += 1
            r["frac"].append(100.0 * (x1 - x0) * (y1 - y0) / (H * W))
            r["contrast"].append(float(patch.mean()) - whole)
            # 배경 수준이면 유방 밖에 찍힌 것이다
            if float(patch.mean()) <= bg + 5:
                r["dark"] += 1
            if draw_im is not None:
                col = COLOR.get(an["category_id"], (255, 255, 0))
                d.rectangle([x0, y0, x1, y1], outline=col, width=3)
                d.text((x0 + 4, max(0, y0 - 12)), c, fill=col)

        if draw_im is not None:
            out = save_dir / f"{split_name}_{im['file_name']}"
            draw_im.save(out)
            saved += 1

    if missing:
        print(f"  ! PNG 없음 {missing}건")

    print(f"\n  {'범주':14s} {'개수':>5s} {'화면비율 중앙':>12s} {'25~75%':>14s} "
          f"{'박스안 대비':>11s} {'배경 위':>8s}")
    print("  " + "-" * 72)
    ok = True
    for c, r in sorted(rec.items()):
        if not r["n"]:
            continue
        med = pct(r["frac"], 50)
        lo, hi = pct(r["frac"], 25), pct(r["frac"], 75)
        con = float(np.mean(r["contrast"]))
        bad = r["dark"]
        flag = ""
        # 비율로 본다. 하한을 두면 표본이 적을 때 어긋난 박스를 통과시킨다.
        if bad / r["n"] > 0.05:
            flag, ok = "  <- 배경 위 박스가 많다", False
        elif con <= 0:
            flag, ok = "  <- 박스가 배경보다 어둡다", False
        print(f"  {c:14s} {r['n']:5d} {med:11.2f}% {lo:6.2f}~{hi:5.2f}% "
              f"{con:+10.1f} {bad:5d}건{flag}")

    print(f"\n  판정")
    print(f"    · 박스안 대비가 양수여야 한다 (병변은 배경보다 밝다)")
    print(f"    · 배경 위 박스가 5% 를 넘으면 좌표가 어긋난 것이다")
    print(f"    · 종괴가 석회 군집보다 큰 것이 정상이다")
    if ok:
        print(f"\n  -> 통과. 전체 변환을 돌려도 된다.")
    else:
        print(f"\n  -> 어긋난 박스가 많다. 전체 변환 전에 원인을 찾아야 한다.")
    if save_dir:
        print(f"\n  그림 {saved}장 저장: {save_dir}")
        print(f"    붉은 상자 = 종괴 · 하늘색 상자 = 석회")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HOME / "workspace/breast/mammo/det"))
    ap.add_argument("--save", default="", help="박스를 그린 PNG 를 남길 폴더")
    ap.add_argument("--n-save", type=int, default=6, help="분할마다 몇 장")
    a = ap.parse_args()

    root = Path(a.root).expanduser()
    save_dir = Path(a.save).expanduser() if a.save else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 74)
    print("COCO 변환 검사 — 박스가 병변 위에 있는가")
    print("=" * 74)
    print(f"  대상 {root}")

    for split_name, img_split in (("train", "train"), ("val", "test")):
        analyse(root, split_name, img_split, save_dir, a.n_save)


if __name__ == "__main__":
    main()
