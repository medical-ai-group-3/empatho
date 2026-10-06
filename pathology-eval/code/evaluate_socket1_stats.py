"""
Socket1 5개 후보의 val_acc를 이미지 단위로 계산하여 평균/표준편차/95% CI를 비교.
전체 평균만으로는 후보 간 근소한 차이가 유의미한지 판단하기 어려워 통계 검증용으로 작성.
"""
import argparse
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from train_virchow2_linear_head import build_virchow2, VirchowLinearHead, TissueSegDataset
from train_virchow2_linear_tand import VirchowLinearHeadTAND
from train_efficientnet_unet_virchow_fusion import VirchowFusionUNet, TissueSegDatasetFull as DatasetFull_effnet
from train_ptc_efficientunet_virchow2 import EfficientUNetWithPTC, TissueSegDatasetFull as DatasetFull_ptc
from train_virchow2_dpt import VirchowDPT, TissueSegDatasetFull as DatasetFull_dpt


def per_image_accuracy(logits, masks):
    """배치가 아니라 이미지 1장 단위 pixel accuracy."""
    preds = logits.argmax(dim=1)  # (B, H, W)
    correct = (preds == masks).float().mean(dim=(1, 2))  # (B,) 이미지별 정확도
    return correct.cpu().numpy()


def eval_2input_per_image(model, loader, device):
    model.eval()
    accs = []
    with torch.no_grad():
        for imgs, masks in loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            accs.extend(per_image_accuracy(logits, masks))
    return np.array(accs)


def eval_ptc_per_image(model, loader, device):
    model.eval()
    accs = []
    with torch.no_grad():
        for img_raw, img_norm, masks in loader:
            img_raw, img_norm, masks = img_raw.to(device), img_norm.to(device), masks.to(device)
            _, final_out = model(img_raw, img_norm)
            accs.extend(per_image_accuracy(final_out, masks))
    return np.array(accs)


def summarize(name, accs):
    mean = accs.mean()
    std = accs.std(ddof=1)
    se = std / np.sqrt(len(accs))
    ci95 = 1.96 * se
    print(f"{name:20s}: mean={mean:.4f}  std={std:.4f}  n={len(accs)}  95% CI=[{mean-ci95:.4f}, {mean+ci95:.4f}]")
    return mean, std, accs


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

    all_accs = {}

    ds = TissueSegDataset(root, "val", image_size, mean, std)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = VirchowLinearHead(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_head.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    all_accs["linear_head"] = eval_2input_per_image(model, loader, device)

    model = VirchowLinearHeadTAND(virchow_model).to(device)
    ckpt = torch.load(cdir / "linear_tand.pth", map_location=device, weights_only=False)
    model.head.load_state_dict(ckpt["head_state_dict"])
    all_accs["linear_tand"] = eval_2input_per_image(model, loader, device)

    ds_effnet = DatasetFull_effnet(root, "val", image_size, mean, std)
    loader_effnet = DataLoader(ds_effnet, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowFusionUNet(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "efficientnet_unet.pth", map_location=device, weights_only=False)
    model.virchow_proj.load_state_dict(ckpt["virchow_proj_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    all_accs["efficientnet_unet"] = eval_2input_per_image(model, loader_effnet, device)

    ds_ptc = DatasetFull_ptc(root, "val", image_size, mean, std)
    loader_ptc = DataLoader(ds_ptc, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = EfficientUNetWithPTC(virchow_model).to(device)
    ckpt = torch.load(cdir / "ptc_efficientunet.pth", map_location=device, weights_only=False)
    model.ptc.load_state_dict(ckpt["ptc_state_dict"])
    model.unet.load_state_dict(ckpt["unet_state_dict"])
    all_accs["ptc_efficientunet"] = eval_ptc_per_image(model, loader_ptc, device)

    ds_dpt = DatasetFull_dpt(root, "val", image_size, mean, std)
    loader_dpt = DataLoader(ds_dpt, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = VirchowDPT(virchow_model, image_size).to(device)
    ckpt = torch.load(cdir / "dpt.pth", map_location=device, weights_only=False)
    model.dpt_head.load_state_dict(ckpt["dpt_head_state_dict"])
    all_accs["dpt"] = eval_2input_per_image(model, loader_dpt, device)

    print("\n===== 이미지 단위 통계 =====")
    results = {name: summarize(name, accs) for name, accs in all_accs.items()}

    # 상위 2개 후보 간 대응표본 t-검정 (같은 val 이미지셋이므로 paired)
    from scipy import stats
    names_sorted = sorted(results.keys(), key=lambda n: -results[n][0])
    top1, top2 = names_sorted[0], names_sorted[1]
    t_stat, p_val = stats.ttest_rel(all_accs[top1], all_accs[top2])
    print(f"\n{top1} vs {top2} 대응표본 t-검정: t={t_stat:.3f}, p={p_val:.4f}")
    if p_val < 0.05:
        print("  -> 통계적으로 유의미한 차이 (p<0.05)")
    else:
        print("  -> 통계적으로 유의미하지 않음 (p>=0.05), 두 모델 성능 차이 불확실")


if __name__ == "__main__":
    main()
