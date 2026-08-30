"""
Socket1 (조직 분할) 5개 디코더 후보를 val set으로 평가/비교하는 스크립트.
각 학습 스크립트에서 모델과 데이터셋 클래스를 그대로 재사용합니다.
주의: TissueSegDatasetFull은 파일마다 반환값 개수가 다르므로 반드시 해당 모델의 파일에서 import.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from train_virchow2_linear_head import build_virchow2, VirchowLinearHead, TissueSegDataset, pixel_accuracy
from train_virchow2_linear_tand import VirchowLinearHeadTAND
from train_efficientnet_unet_virchow_fusion import VirchowFusionUNet, TissueSegDatasetFull as DatasetFull_effnet
from train_ptc_efficientunet_virchow2 import EfficientUNetWithPTC, TissueSegDatasetFull as DatasetFull_ptc
from train_virchow2_dpt import VirchowDPT, TissueSegDatasetFull as DatasetFull_dpt


def evaluate_2input(model, loader, device):
    """imgs, masks -> model(imgs) 형태"""
    model.eval()
    accs = []
    with torch.no_grad():
        for imgs, masks in loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            accs.append(pixel_accuracy(logits, masks))
    return float(np.mean(accs))


def evaluate_ptc(model, loader, device):
    """img_raw, img_norm, masks -> model(img_raw, img_norm) -> (ptc_out, final_out) 형태"""
    model.eval()
    accs = []
    with torch.no_grad():
        for img_raw, img_norm, masks in loader:
            img_raw, img_norm, masks = img_raw.to(device), img_norm.to(device), masks.to(device)
            _, final_out = model(img_raw, img_norm)
            accs.append(pixel_accuracy(final_out, masks))
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

    print("\n[1/5] linear_head 평가 중...")
    ds = TissueSegDataset(root, "val", image_size, mean, std)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowLinearHead(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_head.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    results["linear_head"] = evaluate_2input(model, loader, device)
    print(f"  val_acc: {results['linear_head']:.4f}")

    print("\n[2/5] linear_tand 평가 중...")
    model = VirchowLinearHeadTAND(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_tand.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    results["linear_tand"] = evaluate_2input(model, loader, device)
    print(f"  val_acc: {results['linear_tand']:.4f}")

    print("\n[3/5] efficientnet_unet 평가 중...")
    ds_effnet = DatasetFull_effnet(root, "val", image_size, mean, std)
    loader_effnet = DataLoader(ds_effnet, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowFusionUNet(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "efficientnet_unet.pth", map_location=device, weights_only=False)
    model.virchow_proj.load_state_dict(ckpt["virchow_proj_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    results["efficientnet_unet"] = evaluate_2input(model, loader_effnet, device)
    print(f"  val_acc: {results['efficientnet_unet']:.4f}")

    print("\n[4/5] ptc_efficientunet 평가 중...")
    ds_ptc = DatasetFull_ptc(root, "val", image_size, mean, std)
    loader_ptc = DataLoader(ds_ptc, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = EfficientUNetWithPTC(virchow_model).to(device)
    ckpt = torch.load(cdir / "ptc_efficientunet.pth", map_location=device, weights_only=False)
    model.ptc.load_state_dict(ckpt["ptc_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    results["ptc_efficientunet"] = evaluate_ptc(model, loader_ptc, device)
    print(f"  val_acc: {results['ptc_efficientunet']:.4f}")

    print("\n[5/5] dpt 평가 중...")
    ds_dpt = DatasetFull_dpt(root, "val", image_size, mean, std)
    loader_dpt = DataLoader(ds_dpt, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowDPT(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "dpt.pth", map_location=device, weights_only=False)
    model.dpt_head.load_state_dict(ckpt["dpt_head_state_dict"])
    results["dpt"] = evaluate_2input(model, loader_dpt, device)
    print(f"  val_acc: {results['dpt']:.4f}")

    print("\n===== 최종 비교 =====")
    for name, acc in sorted(results.items(), key=lambda x: -x[1]):
        print(f"{name:20s}: {acc:.4f}")


if __name__ == "__main__":
    main()
