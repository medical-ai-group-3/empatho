"""
Socket1 (조직 분할) 6개 디코더 후보 최종 비교.

evaluate_socket1_stats.py 에 6번째 후보(linear_tand_weighted)를 추가하고,
전체 pixel accuracy 뿐 아니라 클래스별 Dice(기타/종양/간질)까지 계산한다.

후보:
  1. linear_head          - Virchow2(동결) + Linear, CE 손실, 16x16 grid
  2. linear_tand          - + 온도 스케일링 + CE/Dice/BCE 조합, 16x16 grid
  3. linear_tand_weighted - linear_tand 에 "기타" 클래스 3배 가중 손실, 16x16 grid
  4. efficientnet_unet    - EfficientNetV2-UNet + Virchow2 특징 융합, 224x224
  5. ptc_efficientunet    - PTC + SCSE Efficient-UNet (PUMA 1위 방식), 224x224
  6. dpt                  - Dense Prediction Transformer 디코더, 224x224

per-class Dice 는 각 후보의 학습/평가 해상도(linear 계열=16x16, 나머지=224x224)에서
val set 전체에 대해 누적(intersection / 합) 방식으로 계산한 global Dice 이다.
val 데이터: ~/data/tiger/tissue_segmentation (v1) 의 val 폴더.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from train_virchow2_linear_head import build_virchow2, VirchowLinearHead, TissueSegDataset
from train_virchow2_linear_tand import VirchowLinearHeadTAND
from train_virchow2_linear_weighted import VirchowLinearHeadTAND as VirchowLinearHeadTANDWeighted
from train_efficientnet_unet_virchow_fusion import VirchowFusionUNet, TissueSegDatasetFull as DatasetFull_effnet
from train_ptc_efficientunet_virchow2 import EfficientUNetWithPTC, TissueSegDatasetFull as DatasetFull_ptc
from train_virchow2_dpt import VirchowDPT, TissueSegDatasetFull as DatasetFull_dpt

NUM_CLASSES = 3
CLASS_NAMES = ["기타", "종양", "간질"]


class DiceAccumulator:
    """val set 전체에 대해 클래스별 intersection / pred합 / target합 을 누적."""

    def __init__(self, num_classes=NUM_CLASSES):
        self.inter = np.zeros(num_classes, dtype=np.float64)
        self.psum = np.zeros(num_classes, dtype=np.float64)
        self.tsum = np.zeros(num_classes, dtype=np.float64)

    def update(self, preds, masks):
        preds = preds.view(-1).cpu().numpy()
        masks = masks.view(-1).cpu().numpy()
        for c in range(len(self.inter)):
            pc = preds == c
            tc = masks == c
            self.inter[c] += np.logical_and(pc, tc).sum()
            self.psum[c] += pc.sum()
            self.tsum[c] += tc.sum()

    def dice(self, eps=1e-6):
        return (2 * self.inter + eps) / (self.psum + self.tsum + eps)


def per_image_accuracy(logits, masks):
    preds = logits.argmax(dim=1)
    return (preds == masks).float().mean(dim=(1, 2)).cpu().numpy()


def eval_2input(model, loader, device):
    model.eval()
    accs = []
    dice_acc = DiceAccumulator()
    with torch.no_grad():
        for imgs, masks in loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            accs.extend(per_image_accuracy(logits, masks))
            dice_acc.update(logits.argmax(dim=1), masks)
    return np.array(accs), dice_acc.dice()


def eval_ptc(model, loader, device):
    model.eval()
    accs = []
    dice_acc = DiceAccumulator()
    with torch.no_grad():
        for img_raw, img_norm, masks in loader:
            img_raw, img_norm, masks = img_raw.to(device), img_norm.to(device), masks.to(device)
            _, final_out = model(img_raw, img_norm)
            accs.extend(per_image_accuracy(final_out, masks))
            dice_acc.update(final_out.argmax(dim=1), masks)
    return np.array(accs), dice_acc.dice()


def summarize(name, accs, dice):
    mean = accs.mean()
    std = accs.std(ddof=1)
    se = std / np.sqrt(len(accs))
    ci95 = 1.96 * se
    dice_str = "  ".join(f"{n}={d:.4f}" for n, d in zip(CLASS_NAMES, dice))
    print(
        f"{name:20s}: acc={mean:.4f} (±{ci95:.4f})  "
        f"mDice={dice.mean():.4f}  [{dice_str}]"
    )
    return mean, std, dice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", type=str, default=os.path.expanduser("~/data/tiger/tissue_segmentation"))
    parser.add_argument("--candidates_dir", type=str, default="../candidates/socket1")
    parser.add_argument(
        "--weighted_ckpt",
        type=str,
        default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand_weighted/best_head.pth"),
    )
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--batch_size", type=int, default=16)
    args = parser.parse_args()

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    root = Path(args.data_root)
    cdir = Path(args.candidates_dir)
    print(f"val 데이터: {root / 'val'}")

    print("Virchow2 인코더 로딩...")
    virchow_model, mean, std, image_size = build_virchow2(None)

    all_accs, all_dice = {}, {}

    # --- 1. linear_head (16x16) ---
    ds = TissueSegDataset(root, "val", image_size, mean, std)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowLinearHead(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_head.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    all_accs["linear_head"], all_dice["linear_head"] = eval_2input(model, loader, device)

    # --- 2. linear_tand (16x16) ---
    model = VirchowLinearHeadTAND(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_tand.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    with torch.no_grad():
        model.log_temperature.copy_(ckpt["log_temperature"].to(device))
    all_accs["linear_tand"], all_dice["linear_tand"] = eval_2input(model, loader, device)

    # --- 3. linear_tand_weighted (16x16) ---
    model = VirchowLinearHeadTANDWeighted(virchow_model).to(device)
    ckpt = torch.load(args.weighted_ckpt, map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    with torch.no_grad():
        model.log_temperature.copy_(ckpt["log_temperature"].to(device))
    all_accs["linear_tand_weighted"], all_dice["linear_tand_weighted"] = eval_2input(model, loader, device)

    # --- 4. efficientnet_unet (224x224) ---
    ds_e = DatasetFull_effnet(root, "val", image_size, mean, std)
    loader_e = DataLoader(ds_e, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowFusionUNet(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "efficientnet_unet.pth", map_location=device, weights_only=False)
    model.virchow_proj.load_state_dict(ckpt["virchow_proj_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    all_accs["efficientnet_unet"], all_dice["efficientnet_unet"] = eval_2input(model, loader_e, device)

    # --- 5. ptc_efficientunet (224x224) ---
    ds_p = DatasetFull_ptc(root, "val", image_size, mean, std)
    loader_p = DataLoader(ds_p, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = EfficientUNetWithPTC(virchow_model).to(device)
    ckpt = torch.load(cdir / "ptc_efficientunet.pth", map_location=device, weights_only=False)
    model.ptc.load_state_dict(ckpt["ptc_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    all_accs["ptc_efficientunet"], all_dice["ptc_efficientunet"] = eval_ptc(model, loader_p, device)

    # --- 6. dpt (224x224) ---
    ds_d = DatasetFull_dpt(root, "val", image_size, mean, std)
    loader_d = DataLoader(ds_d, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowDPT(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "dpt.pth", map_location=device, weights_only=False)
    model.dpt_head.load_state_dict(ckpt["dpt_head_state_dict"])
    all_accs["dpt"], all_dice["dpt"] = eval_2input(model, loader_d, device)

    print(f"\n===== Socket1 6개 후보 비교 (val n={len(next(iter(all_accs.values())))}) =====")
    print("(acc = 이미지 단위 pixel accuracy 평균 ± 95% CI, Dice = val 전체 누적 global Dice)")
    results = {name: summarize(name, all_accs[name], all_dice[name]) for name in all_accs}

    print("\n----- accuracy 순 정렬 -----")
    for name in sorted(results, key=lambda n: -results[n][0]):
        mean, _, dice = results[name]
        print(f"{name:20s}: acc={mean:.4f}  mDice={dice.mean():.4f}  " +
              "  ".join(f"{n}={d:.4f}" for n, d in zip(CLASS_NAMES, dice)))

    print("\n----- 종양+간질 평균 Dice 순 정렬 (기타 제외, 실질 조직 구분 성능) -----")
    for name in sorted(results, key=lambda n: -results[n][2][1:].mean()):
        mean, _, dice = results[name]
        print(f"{name:20s}: 종양간질 mDice={dice[1:].mean():.4f}  (종양={dice[1]:.4f}, 간질={dice[2]:.4f})  acc={mean:.4f}")

    # 상위 2개 후보 간 대응표본 t-검정 (같은 val 이미지셋)
    from scipy import stats
    names_sorted = sorted(results, key=lambda n: -results[n][0])
    top1, top2 = names_sorted[0], names_sorted[1]
    t_stat, p_val = stats.ttest_rel(all_accs[top1], all_accs[top2])
    print(f"\n{top1} vs {top2} 대응표본 t-검정: t={t_stat:.3f}, p={p_val:.4f}")
    print("  -> " + ("유의미한 차이 (p<0.05)" if p_val < 0.05 else "유의미하지 않음 (p>=0.05)"))


if __name__ == "__main__":
    main()
