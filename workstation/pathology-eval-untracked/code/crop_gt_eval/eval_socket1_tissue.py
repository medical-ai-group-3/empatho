#!/usr/bin/env python3
"""분석 1: 조직분할(socket1) 정확도 — 크롭 단위 GT, 원본 해상도.

크롭마다 16x16 로짓을 1회만 계산한 뒤 두 방식으로 분기:
  nearest  (기존, 서빙과 동일) : argmax(16x16) -> cv2 INTER_NEAREST 업샘플
  bilinear (수정안)            : softmax -> bilinear(align_corners=False) -> argmax
GT = masks/*.png 7-class -> remap_tissue_masks.REMAP 3-class, 원본 해상도 유지.

출력: results/socket1_crop_gt.csv, results/socket1_pooled.json,
      results/socket1_masks/{id}_{gt,nearest,bilinear}.png (라벨값 0/1/2) + {id}_logits16.npy

실행: ~/miniconda3/envs/cellvitpp/bin/python code/crop_gt_eval/eval_socket1_tissue.py [--fp16]
"""
from __future__ import annotations

import argparse
import json
import time

import cv2
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from PIL import Image

import common as C
import stil_inference_pipeline as sip  # noqa: E402  (common 이 sys.path 설정)


@torch.inference_mode()
def logits16(model, img: Image.Image, mean, std, image_size, device) -> torch.Tensor:
    """sip.tissue_stroma_mask 의 전처리를 그대로 재현해 (1,3,16,16) logits 만 얻는다."""
    r = img.resize((image_size, image_size), Image.BILINEAR)
    t = torch.from_numpy(np.array(r)).permute(2, 0, 1).float() / 255.0
    t = (t - torch.tensor(mean).view(3, 1, 1)) / torch.tensor(std).view(3, 1, 1)
    t = t.unsqueeze(0).to(device).to(next(model.parameters()).dtype)
    return model(t).float()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--n-sanity", type=int, default=5,
                    help="앞쪽 N장은 sip.tissue_stroma_mask 와 nearest 결과가 같은지 대조")
    a = ap.parse_args()

    val, s2 = C.check_split()
    ids = C.crop_ids(val)
    out_masks = C.RESULTS / "socket1_masks"
    out_masks.mkdir(parents=True, exist_ok=True)

    C.gpu_guard(3.0 if a.fp16 else 5.0, a.fp16, a.gpu)
    device = f"cuda:{a.gpu}"
    t0 = time.time()
    model, mean, std, image_size = sip.load_tissue_model(C.TISSUE_CKPT, device, fp16=a.fp16)
    print(f"[load] tissue model {time.time() - t0:.1f}s, image_size={image_size}")

    pooled = {k: C.PooledDice() for k in ("grid16", "nearest", "bilinear")}
    acc16 = []
    rows = []
    t0 = time.time()
    for n, stem in enumerate(val):
        cid = ids[stem]
        img = C.load_image(stem)
        W, H = img.size
        gt = C.load_gt_mask(stem)
        assert gt.shape == (H, W), (stem, gt.shape, (H, W))
        g16 = C.gt16(gt)

        lg = logits16(model, img, mean, std, image_size, device)              # (1,3,16,16)
        pred16 = lg.argmax(1)[0].cpu().numpy().astype(np.uint8)
        m_near = cv2.resize(pred16, (W, H), interpolation=cv2.INTER_NEAREST)
        prob = torch.softmax(lg, dim=1)
        m_bil = F.interpolate(prob, size=(H, W), mode="bilinear", align_corners=False)
        m_bil = m_bil.argmax(1)[0].cpu().numpy().astype(np.uint8)

        if n < a.n_sanity:  # 서빙 경로와 동일한지 확인 (로짓 재계산 1회 추가)
            ref, ref16 = sip.tissue_stroma_mask(model, img, mean, std, image_size, device, W, H)
            assert np.array_equal(ref16, pred16) and np.array_equal(ref, m_near), f"sanity 불일치 {stem}"

        pooled["grid16"].update(pred16, g16)
        pooled["nearest"].update(m_near, gt)
        pooled["bilinear"].update(m_bil, gt)
        acc16.append(float((pred16 == g16).mean()))

        npx = H * W
        gt_s = int((gt == 2).sum())
        r = {
            "crop_id": cid, "stem": stem, "W": W, "H": H,
            "in_socket2_train": stem in s2,
            "gt_stroma_frac": gt_s / npx, "gt_tumor_frac": float((gt == 1).mean()),
            "gt_other_frac": float((gt == 0).mean()),
        }
        for name, m in (("nearest", m_near), ("bilinear", m_bil)):
            r[f"stroma_dice_{name}"] = C.dice(m, gt, 2)
            r[f"tumor_dice_{name}"] = C.dice(m, gt, 1)
            r[f"pixel_acc_{name}"] = float((m == gt).mean())
            ai_s = int((m == 2).sum())
            r[f"ai_stroma_frac_{name}"] = ai_s / npx
            r[f"stroma_area_ratio_{name}"] = ai_s / gt_s if gt_s else float("nan")  # AI/GT
        r["stroma_dice_16"] = C.dice(pred16, g16, 2)
        r["tumor_dice_16"] = C.dice(pred16, g16, 1)
        r["pixel_acc_16"] = acc16[-1]
        r["near_bil_pixel_diff_frac"] = float((m_near != m_bil).mean())
        rows.append(r)

        for tag, m in (("gt", gt), ("nearest", m_near), ("bilinear", m_bil)):
            Image.fromarray(m).save(out_masks / f"{cid}_{tag}.png")
        np.save(out_masks / f"{cid}_logits16.npy", lg[0].cpu().numpy().astype(np.float32))

        if (n + 1) % 50 == 0 or n + 1 == len(val):
            print(f"  {n + 1}/{len(val)}  {time.time() - t0:.0f}s")

    df = pd.DataFrame(rows)
    df.to_csv(C.RESULTS / "socket1_crop_gt.csv", index=False)

    summ = {
        "n_crops": len(df),
        "pooled_dice": {k: dict(zip(C.CLASS_NAMES, map(float, v.dice()))) for k, v in pooled.items()},
        "pixel_acc_16_mean": float(np.mean(acc16)),
        "pixel_acc_full_mean": {k: float(df[f"pixel_acc_{k}"].mean()) for k in ("nearest", "bilinear")},
        "fp16": a.fp16,
        "tissue_checkpoint": C.TISSUE_CKPT,
    }
    (C.RESULTS / "socket1_pooled.json").write_text(json.dumps(summ, indent=2, ensure_ascii=False))
    print(json.dumps(summ["pooled_dice"], indent=2))
    print(f"pixel acc 16x16 mean = {summ['pixel_acc_16_mean']:.4f}")
    print(f"saved -> {C.RESULTS / 'socket1_crop_gt.csv'}")


if __name__ == "__main__":
    main()
