#!/usr/bin/env python3
"""[실험] SAM3-UNet 분할 단독 — 본 파이프라인과 분리해서 비교만 한다.

  인코더  medsam3_merged.pt 의 trunk 재사용 (원본 sam3.pt 받지 않음)
  디코더  SAM3-UNet (github.com/WZH0120/SAM3-UNet, arXiv 2512.01789)
  태스크  BUS-BRA lesion 분할만. 등급 헤드 없음.

비교 대상 — 2차 조인트 best  Dice 0.902 · IoU 0.833 · p10 0.805 · 실패 0장

Dice/IoU 는 eval_us_lora.py 의 함수를 import 해서 쓴다. 다시 구현하면
비교가 성립하지 않는다 — 정답은 원본 해상도 그대로, 예측 로짓만
bilinear 로 내린 뒤 sigmoid → 이진화 (SAM3 공식 후처리 순서).

  python3 us/code/experiments/train_sam3unet.py --epochs 30
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image as PILImage
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import v2
from tqdm import tqdm

CODE = Path(__file__).resolve().parent.parent      # us/code
US_ROOT = CODE.parent                              # us/
sys.path.insert(0, str(CODE))

from eval_us_lora import decode_gt_union, dice_iou, pred_union   # noqa: E402
from train_us_lora import start_run_log                          # noqa: E402

MEDSAM3 = Path("/home/wsuser/workspace/MedSAM3")
MERGED = MEDSAM3 / "ckpt" / "medsam3_merged.pt"
TRUNK_PREFIX = "backbone.vision_backbone.trunk."


def set_seed(s):
    random.seed(s), np.random.seed(s), torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


# ── SAM3-UNet 원본 구조 (github.com/WZH0120/SAM3-UNet/SAM3UNet.py) ──────────
# 원 코드를 그대로 옮기되 체크포인트 로딩만 우리 병합본에 맞춘다.
# 원본은 'detector.backbone.vision_backbone.trunk.' 접두사를 벗기는데,
# medsam3_merged.pt 는 'detector.' 없이 저장돼 있다.

class LightBlock(nn.Module):
    def __init__(self, in_c, out_c):
        super().__init__()
        self.conv_in = nn.Sequential(nn.Conv2d(in_c, in_c // 4, 1),
                                     nn.BatchNorm2d(in_c // 4), nn.GELU())
        self.conv_out = nn.Sequential(nn.Conv2d(in_c // 2, out_c, 1),
                                      nn.BatchNorm2d(out_c), nn.GELU())
        d = in_c // 8
        self.dw1 = nn.Sequential(nn.Conv2d(d, d, 3, 1, 1, groups=d),
                                 nn.BatchNorm2d(d), nn.GELU())
        self.dw2 = nn.Sequential(nn.Conv2d(d, d, 3, 1, 1, groups=d),
                                 nn.BatchNorm2d(d), nn.GELU())

    def forward(self, x):
        x = self.conv_in(x)
        x1, x2 = torch.split(x, x.shape[1] // 2, 1)
        x3 = self.dw1(x2)
        x4 = self.dw2(x3)
        return self.conv_out(torch.cat([x1, x2, x3, x4], dim=1))


class Up(nn.Module):
    def __init__(self, in_c, out_c):
        super().__init__()
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
        self.conv = LightBlock(in_c, out_c)

    def forward(self, x1, x2=None):
        if x2 is not None:
            dy, dx = x1.size(2) - x2.size(2), x1.size(3) - x2.size(3)
            x2 = F.pad(x2, [dx // 2, dx - dx // 2, dy // 2, dy - dy // 2])
            x1 = torch.cat([x1, x2], dim=1)
        return self.conv(self.up(x1))


class Adapter(nn.Module):
    """ViT 블록 앞에 얇은 MLP 프롬프트를 더한다. 블록 자체는 동결된 채로 둔다."""

    def __init__(self, blk):
        super().__init__()
        self.block = blk
        dim = blk.attn.qkv.in_features
        self.prompt_learn = nn.Sequential(
            nn.Linear(dim, 32), nn.GELU(), nn.Linear(32, dim), nn.GELU())
        for m in self.prompt_learn:
            if isinstance(m, nn.Linear):
                nn.init.trunc_normal_(m.weight, std=0.02)
                nn.init.constant_(m.bias, 0)

    def forward(self, x):
        return self.block(x + self.prompt_learn(x))


class SAM3UNet(nn.Module):
    def __init__(self, img_size, merged_ckpt=None):
        super().__init__()
        from sam3.model.vitdet import ViT
        self.vit = ViT(
            img_size=img_size, pretrain_img_size=336, patch_size=14,
            embed_dim=1024, depth=32, num_heads=16, mlp_ratio=4.625,
            norm_layer="LayerNorm", drop_path_rate=0.1, qkv_bias=True,
            use_abs_pos=True, tile_abs_pos=True,
            global_att_blocks=(7, 15, 23, 31), rel_pos_blocks=(),
            use_rope=True, use_interp_rope=True, window_size=24,
            pretrain_use_cls_token=True, retain_cls_token=False,
            ln_pre=True, ln_post=False, return_interm_layers=False,
            bias_patch_embed=False, compile_mode=None,
        )
        if merged_ckpt:
            sd = torch.load(str(merged_ckpt), map_location="cpu", mmap=True)
            w = sd.get("model", sd)
            new = {k[len(TRUNK_PREFIX):]: v for k, v in w.items()
                   if k.startswith(TRUNK_PREFIX) and "freqs_cis" not in k}
            r = self.vit.load_state_dict(new, strict=False)
            print(f"      trunk 로드 {len(new)}키 · missing {len(r.missing_keys)}"
                  f"(freqs_cis) · unexpected {len(r.unexpected_keys)}")
            assert not r.unexpected_keys, "예상 못한 키가 있다 — 구조 불일치"

        for p in self.vit.parameters():
            p.requires_grad = False
        self.vit.blocks = nn.Sequential(*[Adapter(b) for b in self.vit.blocks])

        self.reduce = nn.ModuleList([nn.Conv2d(1024, 128, 1) for _ in range(4)])
        self.up4 = Up(128, 128)
        self.up3 = Up(256, 128)
        self.up2 = Up(256, 128)
        self.up1 = Up(256, 128)
        self.head = nn.Conv2d(128, 1, 1)

    def forward(self, x):
        B, C, H, W = x.shape
        f = self.vit(x)[-1]
        if f.dim() == 4 and f.shape[-1] == 1024:      # (B,h,w,C) → (B,C,h,w)
            f = f.permute(0, 3, 1, 2).contiguous()
        xs = [F.interpolate(self.reduce[i](f), size=(H // s, W // s),
                            mode="bilinear", align_corners=False)
              for i, s in enumerate((4, 8, 16, 32))]
        y = self.up4(xs[3])
        y = self.up3(y, xs[2])
        y = self.up2(y, xs[1])
        y = self.up1(y, xs[0])
        out = F.interpolate(self.head(y), size=(H, W),
                            mode="bilinear", align_corners=False)
        return out                                    # (B,1,H,W) 로짓


def structure_loss(pred, mask):
    """SAM2/SAM3-UNet 계열 표준 손실 — 경계 화소에 가중치를 준 BCE + IoU."""
    w = 1 + 5 * torch.abs(F.avg_pool2d(mask, 31, 1, 15) - mask)
    bce = F.binary_cross_entropy_with_logits(pred, mask, reduction="none")
    wbce = (w * bce).sum(dim=(2, 3)) / w.sum(dim=(2, 3))
    p = torch.sigmoid(pred)
    inter = ((p * mask) * w).sum(dim=(2, 3))
    union = ((p + mask) * w).sum(dim=(2, 3))
    wiou = 1 - (inter + 1) / (union - inter + 1)
    return (wbce + wiou).mean()


# ── 데이터 ──────────────────────────────────────────────────────────────────
class USSegDataset(Dataset):
    """이진 분할 전용. 이미지당 어노 1개가 실측된 전제라 클래스 union 한 장을 낸다."""

    def __init__(self, root, split, R, augment=False, seed=42):
        self.dir = Path(root) / split
        self.R = R
        self.augment = augment
        self.rng = random.Random(seed)
        coco = json.loads((self.dir / "_annotations.coco.json").read_text())
        self.images = {im["id"]: im for im in coco["images"]}
        self.ids = sorted(self.images)
        self.anns = {}
        for a in coco["annotations"]:
            self.anns.setdefault(a["image_id"], []).append(a)
        self.to_t = v2.Compose([v2.ToImage(), v2.ToDtype(torch.float32, scale=True)])
        self.norm = v2.Normalize(mean=[0.5] * 3, std=[0.5] * 3)

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, i):
        img_id = self.ids[i]
        info = self.images[img_id]
        pil = PILImage.open(self.dir / info["file_name"]).convert("RGB")
        ow, oh = pil.size
        gt = decode_gt_union(self.anns.get(img_id, []), oh, ow)

        x = self.to_t(pil.resize((self.R, self.R), PILImage.BILINEAR))
        m = torch.from_numpy(gt).float()[None, None]
        m = F.interpolate(m, size=(self.R, self.R), mode="nearest")[0]

        if self.augment:
            x, m = self._aug(x, m)
        return self.norm(x), m, img_id

    def _aug(self, x, m):
        import torchvision.transforms.v2.functional as TF
        r = self.rng
        if r.random() < 0.5:                       # 좌우 반전만 — 위아래는 안 한다
            x, m = TF.hflip(x), TF.hflip(m)        # 후방음영이 항상 병변 '아래'라
        if r.random() < 0.7:                       # 상하 반전은 물리를 깨뜨린다
            kw = dict(angle=r.uniform(-10, 10), scale=r.uniform(0.9, 1.1),
                      translate=[int(r.uniform(-.05, .05) * self.R)] * 2,
                      shear=[0.0, 0.0])
            x2 = TF.affine(x, interpolation=TF.InterpolationMode.BILINEAR, **kw)
            m2 = TF.affine(m, interpolation=TF.InterpolationMode.NEAREST, **kw)
            if m2.sum() > 0:                       # 회전으로 병변이 잘려나가면 되돌린다
                x, m = x2, m2
        if r.random() < 0.5:                       # 광도 — 정규화 전에
            x = (x * r.uniform(0.85, 1.15) + r.uniform(-0.08, 0.08)).clamp(0, 1)
        return x, m


@torch.no_grad()
def validate(model, ds_dir, R, device, mask_th=0.5, limit=None):
    """본 파이프라인과 같은 방식으로 잰다 — 정답은 원본 해상도, 예측만 내린다."""
    coco = json.loads((ds_dir / "_annotations.coco.json").read_text())
    images = {im["id"]: im for im in coco["images"]}
    anns = {}
    for a in coco["annotations"]:
        anns.setdefault(a["image_id"], []).append(a)
    to_t = v2.Compose([v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
                       v2.Normalize(mean=[0.5] * 3, std=[0.5] * 3)])
    model.eval()
    dices, ious, empty = [], [], 0
    ids = sorted(images)[:limit] if limit else sorted(images)
    for img_id in tqdm(ids, desc="  valid", leave=False):
        pil = PILImage.open(ds_dir / images[img_id]["file_name"]).convert("RGB")
        ow, oh = pil.size
        x = to_t(pil.resize((R, R), PILImage.BILINEAR))[None].to(device)
        logit = model(x)[0]                                     # (1,R,R)
        pred = pred_union(logit, [0], oh, ow, mask_th)          # 같은 후처리 순서
        gt = decode_gt_union(anns.get(img_id, []), oh, ow)
        d, i = dice_iou(pred, gt)
        dices.append(d), ious.append(i)
        empty += int(pred.sum() == 0)
    return (float(np.mean(dices)), float(np.mean(ious)),
            float(np.percentile(dices, 10)), empty)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    # LightBlock 이 BatchNorm2d 를 쓴다. batch 2 면 표본 2개로 통계를 내는
    # 셈이라 불안정하고, 그 상태로 재면 디코더 성능과 BN 불안정이 뒤섞인다.
    # 원 저자는 batch 12 로 학습했다. peak 5.7GB(batch 2) 라 여유가 있다.
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--accum", type=int, default=2)   # 유효 16
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--resolution", type=int, default=1008)
    ap.add_argument("--no-augment", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--run-name", default="unet")
    ap.add_argument("--ckpt-dir", default=str(US_ROOT / "ckpt" / "experiments"))
    ap.add_argument("--smoke", type=int, default=None)
    args = ap.parse_args()

    if args.smoke:
        args.epochs = 1

    log_path = start_run_log(args.run_name, extra={"exp": "SAM3-UNet 분할 단독"})
    print("=" * 70)
    print("[실험] SAM3-UNet 분할 단독 — BUS-BRA lesion")
    print("=" * 70)
    print(f"로그 {log_path}")
    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 필요")
    device = "cuda"
    print(f"GPU  {torch.cuda.get_device_name(0)}")
    set_seed(args.seed)

    sys.path.insert(0, str(MEDSAM3))
    os.chdir(MEDSAM3)                       # 저장소가 상대경로를 하드코딩한다

    print(f"\n[1/3] 모델 — trunk 재사용 {MERGED}")
    model = SAM3UNet(args.resolution, MERGED).to(device)
    tot = sum(p.numel() for p in model.parameters())
    tr = sum(p.numel() for p in model.parameters() if p.requires_grad)
    ad = sum(p.numel() for n, p in model.named_parameters()
             if p.requires_grad and "prompt_learn" in n)
    print(f"      전체 {tot:,}  학습대상 {tr:,}  ({100 * tr / tot:.3f}%)")
    print(f"      내역 — Adapter {ad:,} · 디코더 {tr - ad:,}")
    assert 0.1 < 100 * tr / tot < 5.0, "학습 대상 비율이 예상 범위를 벗어났다"

    root = US_ROOT / "data"
    ds = USSegDataset(root, "train", args.resolution,
                      augment=not args.no_augment, seed=args.seed)
    val_dir = root / "valid"
    print(f"\n[2/3] 데이터 — train {len(ds)} · valid "
          f"{len(json.loads((val_dir / '_annotations.coco.json').read_text())['images'])}"
          f" · 증강 {'off' if args.no_augment else 'on'}")

    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True,
                    num_workers=0, pin_memory=True, drop_last=True)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = AdamW(params, lr=args.lr, weight_decay=args.weight_decay)

    ckpt_dir = Path(args.ckpt_dir)
    if args.smoke:
        ckpt_dir = ckpt_dir / "_smoke"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    best_path = ckpt_dir / "sam3unet_best.pt"
    last_path = ckpt_dir / "sam3unet_last.pt"

    print(f"\n[3/3] 학습 시작 — {args.epochs} epoch · batch {args.batch_size}"
          f" x accum {args.accum} · lr {args.lr}")
    print(f"      비교 대상 — 2차 조인트 best  Dice 0.902 · IoU 0.833 · p10 0.805")
    print("=" * 70)

    best = -1.0
    best_ep = 0
    for ep in range(args.epochs):
        model.train()
        losses = []
        opt.zero_grad(set_to_none=True)
        pbar = tqdm(dl, desc=f"epoch {ep + 1}/{args.epochs}")
        for step, (x, m, _) in enumerate(pbar):
            x, m = x.to(device), m.to(device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = structure_loss(model(x), m)
            (loss / args.accum).backward()
            if (step + 1) % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                opt.zero_grad(set_to_none=True)
            losses.append(float(loss.detach()))
            pbar.set_postfix(loss=f"{losses[-1]:.4f}")
            if args.smoke and step + 1 >= args.smoke:
                break

        t0 = time.time()
        d, i, p10, empty = validate(model, val_dir, args.resolution, device,
                                    limit=args.smoke)
        peak = torch.cuda.max_memory_allocated() / 1e9
        mark = ""
        if d > best:
            best, best_ep = d, ep + 1
            torch.save(model.state_dict(), str(best_path) + ".tmp")
            os.replace(str(best_path) + ".tmp", best_path)
            mark = "  ← best"
        torch.save(model.state_dict(), str(last_path) + ".tmp")
        os.replace(str(last_path) + ".tmp", last_path)

        print(f"epoch {ep + 1}/{args.epochs}  train {np.mean(losses):.4f}  "
              f"val_dice {d:.4f}  val_iou {i:.4f}  p10 {p10:.4f}  "
              f"빈예측 {empty}장  peak {peak:.1f}GB{mark}  (val {time.time() - t0:.0f}s)")

    print("=" * 70)
    print(f"완료 — best Dice {best:.4f} (epoch {best_ep})")
    print(f"  비교: 2차 조인트 best 0.902 → 차이 {best - 0.902:+.4f}")
    print(f"  {best_path}")


if __name__ == "__main__":
    main()