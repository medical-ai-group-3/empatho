"""
Socket1 (조직 분할) 5개 디코더 후보를 val set으로 평가/비교하는 스크립트.
각 학습 스크립트에서 모델 클래스를 재사용하여 재학습 없이 val_acc만 재계산합니다.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

# 각 학습 스크립트에서 필요한 클래스 재사용
from train_virchow2_linear_head import build_virchow2, VirchowLinearHead, TissueSegDataset, pixel_accuracy
from train_virchow2_linear_tand import VirchowLinearHeadTAND
from train_efficientnet_unet_virchow_fusion import VirchowFusionUNet, TissueSegDatasetFull
from train_ptc_efficientunet_virchow2 import EfficientUNetWithPTC
from train_virchow2_dpt import VirchowDPT


def evaluate(model, val_loader, device):
    model.eval()
    accs = []
    with torch.no_grad():
        for imgs, masks in val_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            accs.append(pixel_accuracy(logits, masks))
    return float(np.mean(accs))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", type=str, default="../data")
    parser.add_argument("--candidates_dir", type=str, default="../candidates/socket1")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--batch_size", type=int, default=16)
    args = parser.parse_args()

    device = f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu"
    root = Path(args.data_root)
    cdir = Path(args.candidates_dir)

    print("Virchow2 인코더 로딩...")
    virchow_model, mean, std, image_size = build_virchow2(None)

    results = {}

    # ---- linear_head ----
    print("\n[1/5] linear_head 평가 중...")
    ds = TissueSegDataset(root, "val", image_size, mean, std)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowLinearHead(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_head.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    results["linear_head"] = evaluate(model, loader, device)
    print(f"  val_acc: {results['linear_head']:.4f} (저장된 값: {ckpt.get('val_acc', 'N/A')})")

    # ---- linear_tand ----
    print("\n[2/5] linear_tand 평가 중...")
    model = VirchowLinearHeadTAND(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_tand.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    results["linear_tand"] = evaluate(model, loader, device)
    print(f"  val_acc: {results['linear_tand']:.4f} (저장된 값: {ckpt.get('val_acc', 'N/A')})")

    # ---- efficientnet_unet ----
    print("\n[3/5] efficientnet_unet 평가 중...")
    ds_full = TissueSegDatasetFull(root, "val", image_size, mean, std)
    loader_full = DataLoader(ds_full, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowFusionUNet(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "efficientnet_unet.pth", map_location=device, weights_only=False)
    model.virchow_proj.load_state_dict(ckpt["virchow_proj_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    results["efficientnet_unet"] = evaluate(model, loader_full, device)
    print(f"  val_acc: {results['efficientnet_unet']:.4f}")

    # ---- ptc_efficientunet ----
    print("\n[4/5] ptc_efficientunet 평가 중...")
    model = EfficientUNetWithPTC(virchow_model).to(device)
    ckpt = torch.load(cdir / "ptc_efficientunet.pth", map_location=device, weights_only=False)
    model.ptc.load_state_dict(ckpt["ptc_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    results["ptc_efficientunet"] = evaluate(model, loader_full, device)
    print(f"  val_acc: {results['ptc_efficientunet']:.4f}")

    # ---- dpt ----
    print("\n[5/5] dpt 평가 중...")
    model = VirchowDPT(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "dpt.pth", map_location=device, weights_only=False)
    model.dpt_head.load_state_dict(ckpt["dpt_head_state_dict"])
    results["dpt"] = evaluate(model, loader_full, device)
    print(f"  val_acc: {results['dpt']:.4f} (저장된 값: {ckpt.get('val_acc', 'N/A')})")

    print("\n===== 최종 비교 =====")
    for name, acc in sorted(results.items(), key=lambda x: -x[1]):
        print(f"{name:20s}: {acc:.4f}")


if __name__ == "__main__":
    main()
