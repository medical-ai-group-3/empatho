#!/usr/bin/env python3
"""
안 (B) 검증 — 마스크를 argmax 쿼리 하나로 제한하면 Dice 가 어떻게 되나.

현재(안 C)  마스크 = score>threshold 인 쿼리 전부의 합집합, 등급 = argmax 쿼리
안 (B)      마스크 = argmax 쿼리 하나, 등급 = 같은 쿼리  → 둘이 같은 병변을 가리킴

전체 Dice 가 떨어지면 안 (B) 를 접고 (C) 로 되돌린다.

  python3 compare_mask_source.py --config configs/us_lora.yaml
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image as PILImage
from torchvision.transforms import v2
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_us_lora import (load_config, import_medsam3, build_model,      # noqa: E402
                          load_pixel_decoder, run_one_query, pred_union,
                          decode_gt_union, dice_iou)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--split", default="valid")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--mask-threshold", type=float, default=0.5)
    a = ap.parse_args()

    cfg = load_config(Path(a.config).resolve())
    ck = Path(cfg["output"]["ckpt_dir"])
    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 필요")
    dev = "cuda"

    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, ck / "us_lora_best.pt", M, dev)
    load_pixel_decoder(model, ck / "us_pd_best.pt", cfg, dev)
    model.eval()

    R = cfg["data"]["resolution"]
    sd = Path(cfg["data"]["root"]) / a.split
    d = json.load(open(sd / "_annotations.coco.json"))
    imgs = {i["id"]: i for i in d["images"]}
    anns = {x["image_id"]: x for x in d["annotations"]}
    tf = v2.Compose([v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
                     v2.Normalize(mean=[.5] * 3, std=[.5] * 3)])

    rows = []
    with torch.no_grad():
        for iid, im in tqdm(sorted(imgs.items()), desc=f"  {a.split}"):
            ann = anns.get(iid)
            if ann is None:
                continue
            pil = PILImage.open(sd / im["file_name"]).convert("RGB")
            ow, oh = pil.size
            out = run_one_query(model, M, tf(pil.resize((R, R), PILImage.BILINEAR)),
                                R, oh, ow, dev)
            sc = out["pred_logits"][0].sigmoid().amax(-1)
            keep = torch.where(sc > a.threshold)[0]
            qi = int(sc.argmax())
            gt = decode_gt_union([ann], oh, ow)
            mc = pred_union(out["pred_masks"][0], keep, oh, ow, a.mask_threshold)
            mb = pred_union(out["pred_masks"][0],
                            torch.tensor([qi], device=sc.device), oh, ow, a.mask_threshold)
            dc, ic = dice_iou(np.asarray(mc), gt)
            db, ib = dice_iou(np.asarray(mb), gt)
            rows.append((int(keep.numel()), float(sc[qi]), dc, db, ic, ib))

    nk = np.array([r[0] for r in rows])
    dc = np.array([r[2] for r in rows]); db = np.array([r[3] for r in rows])
    ic = np.array([r[4] for r in rows]); ib = np.array([r[5] for r in rows])

    print()
    print("=" * 76)
    print(f"마스크 출처 비교  ({a.split} {len(rows)}장)")
    print("=" * 76)
    print(f"{'':>28}{'Dice':>9}{'IoU':>9}{'p10':>9}{'빈예측':>8}")
    for nm, dd, ii in (("안 C · 전체 쿼리 합집합", dc, ic),
                       ("안 B · argmax 쿼리 하나", db, ib)):
        print(f"{nm:>28}{dd.mean():>9.4f}{ii.mean():>9.4f}"
              f"{np.percentile(dd,10):>9.4f}{int((dd==0).sum()):>8}")
    print(f"{'차이 (B − C)':>28}{db.mean()-dc.mean():>+9.4f}{ib.mean()-ic.mean():>+9.4f}"
          f"{np.percentile(db,10)-np.percentile(dc,10):>+9.4f}"
          f"{int((db==0).sum())-int((dc==0).sum()):>+8}")

    print(f"\n검출 수별")
    print(f"{'검출':>6}{'n':>6}{'C Dice':>10}{'B Dice':>10}{'차이':>9}")
    for k in sorted(set(nk.tolist())):
        s = nk == k
        print(f"{k:>6}{int(s.sum()):>6}{dc[s].mean():>10.4f}{db[s].mean():>10.4f}"
              f"{db[s].mean()-dc[s].mean():>+9.4f}")

    multi = nk > 1
    if multi.any():
        print(f"\n검출 2개 이상 {int(multi.sum())}장에서")
        print(f"  개선 {int((db[multi]>dc[multi]+1e-9).sum())}장 · "
              f"악화 {int((db[multi]<dc[multi]-1e-9).sum())}장")
        for k, (n, s, c, b) in enumerate(sorted(
                [(r[0], r[1], r[2], r[3]) for r in rows if r[0] > 1],
                key=lambda x: x[3] - x[2])):
            print(f"    검출 {n}개 score {s:.3f}   C {c:.4f} → B {b:.4f}  ({b-c:+.4f})")


if __name__ == "__main__":
    main()