#!/usr/bin/env python3
"""
SAM3-UNet(분할 전용, 실험 4) 의 표본별 valid 결과를 CSV 로 남긴다.

이 실험만 표본별 기록이 없어서 다른 실험과 **대응 비교(paired test)** 를 할 수 없었다.
"분할 상한 0.9124" 라는 서술의 근거가 되는 +0.0104 가 유의한지 검정하려면 필요하다.

집계 방식은 train_sam3unet.py 의 validate() 와 동일하다 —
pred_union · decode_gt_union · dice_iou 를 그대로 쓰므로 본 파이프라인 수치와 비교 가능하다.

  python3 dump_sam3unet_valid.py
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image as PILImage
from torchvision.transforms import v2
from tqdm import tqdm

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "experiments"))

US = CODE.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(US / "ckpt" / "experiments" / "sam3unet_best.pt"))
    ap.add_argument("--data", default=str(US / "data" / "valid"))
    ap.add_argument("--out", default=str(US / "eval_out" / "valid_sam3unet_best.csv"))
    ap.add_argument("--resolution", type=int, default=1008)
    ap.add_argument("--mask-threshold", type=float, default=0.5)
    a = ap.parse_args()

    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 가 필요하다")
    device = "cuda"

    # train_sam3unet 은 import 시점에 sam3 경로를 잡는다(내부에서 MEDSAM3 사용)
    from train_sam3unet import SAM3UNet
    from eval_us_lora import decode_gt_union, dice_iou, pred_union

    ck = Path(a.ckpt)
    print(f"체크포인트 {ck}  ({ck.stat().st_size / 1e9:.2f} GB)")
    # 가중치를 통째로 덮어쓰므로 trunk 사전로드는 생략한다(merged_ckpt=None)
    model = SAM3UNet(a.resolution, merged_ckpt=None).to(device)
    sd = torch.load(str(ck), map_location="cpu")
    sd = sd.get("model", sd.get("state", sd))
    r = model.load_state_dict(sd, strict=False)
    print(f"  로드 완료 — missing {len(r.missing_keys)} · unexpected {len(r.unexpected_keys)}")
    if r.unexpected_keys:
        print(f"    unexpected 예: {r.unexpected_keys[:3]}")
    model.eval()

    sd_dir = Path(a.data)
    coco = json.loads((sd_dir / "_annotations.coco.json").read_text())
    images = {im["id"]: im for im in coco["images"]}
    anns = {}
    for x in coco["annotations"]:
        anns.setdefault(x["image_id"], []).append(x)

    to_t = v2.Compose([v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
                       v2.Normalize(mean=[0.5] * 3, std=[0.5] * 3)])

    rows = []
    with torch.no_grad():
        for img_id in tqdm(sorted(images), desc="  valid"):
            im = images[img_id]
            pil = PILImage.open(sd_dir / im["file_name"]).convert("RGB")
            ow, oh = pil.size
            x = to_t(pil.resize((a.resolution, a.resolution), PILImage.BILINEAR))[None].to(device)
            logit = model(x)[0]
            pred = pred_union(logit, [0], oh, ow, a.mask_threshold)
            gt = decode_gt_union(anns.get(img_id, []), oh, ow)
            d, i = dice_iou(pred, gt)
            rows.append({"file_name": im["file_name"], "dice": d, "iou": i,
                         "pred_area_px": int(np.asarray(pred).sum()),
                         "orig_w": ow, "orig_h": oh})

    dice = np.array([r_["dice"] for r_ in rows])
    iou = np.array([r_["iou"] for r_ in rows])
    print()
    print("=" * 66)
    print(f"SAM3-UNet 분할 전용 — valid {len(rows)}장")
    print(f"  Dice {dice.mean():.4f}   IoU {iou.mean():.4f}   "
          f"p10 {np.percentile(dice, 10):.4f}   빈 예측 {int((dice == 0).sum())}장")
    print(f"  (로그 기록값: Dice 0.9124 · IoU 0.8461 · p10 0.8390 · 빈예측 0)")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\n저장 {out}")
    print("→ 이제 valid_joint_best.csv · valid_unet_best.csv 와 대응 비교가 가능하다")


if __name__ == "__main__":
    main()