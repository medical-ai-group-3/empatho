"""
Socket1 5개 후보의 추론 속도(이미지당 ms) 및 학습 파라미터 수 비교.
"""
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from train_virchow2_linear_head import build_virchow2, VirchowLinearHead, TissueSegDataset
from train_virchow2_linear_tand import VirchowLinearHeadTAND
from train_efficientnet_unet_virchow_fusion import VirchowFusionUNet, TissueSegDatasetFull as DatasetFull_effnet
from train_ptc_efficientunet_virchow2 import EfficientUNetWithPTC, TissueSegDatasetFull as DatasetFull_ptc
from train_virchow2_dpt import VirchowDPT, TissueSegDatasetFull as DatasetFull_dpt


def count_params(module):
    return sum(p.numel() for p in module.parameters())


def benchmark(model, sample_input, device, n_warmup=3, n_runs=20):
    model.eval()
    with torch.no_grad():
        for _ in range(n_warmup):
            _ = model(*sample_input) if isinstance(sample_input, tuple) else model(sample_input)
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(n_runs):
            _ = model(*sample_input) if isinstance(sample_input, tuple) else model(sample_input)
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
    return (elapsed / n_runs) * 1000  # ms per batch


def main():
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    root = Path("../data")

    print("Virchow2 인코더 로딩...")
    virchow_model, mean, std, image_size = build_virchow2(None)

    ds = TissueSegDataset(root, "val", image_size, mean, std)
    imgs, _ = next(iter(DataLoader(ds, batch_size=1)))
    imgs = imgs.to(device)

    ds_full = DatasetFull_effnet(root, "val", image_size, mean, std)
    imgs_full, _ = next(iter(DataLoader(ds_full, batch_size=1)))
    imgs_full = imgs_full.to(device)

    ds_ptc = DatasetFull_ptc(root, "val", image_size, mean, std)
    img_raw, img_norm, _ = next(iter(DataLoader(ds_ptc, batch_size=1)))
    img_raw, img_norm = img_raw.to(device), img_norm.to(device)

    print(f"\n{'모델':20s} {'파라미터(학습)':>15s} {'파라미터(전체)':>15s} {'추론(ms/img)':>15s}")

    model = VirchowLinearHead(virchow_model).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = count_params(model)
    ms = benchmark(model, imgs, device)
    print(f"{'linear_head':20s} {trainable:>15,d} {total:>15,d} {ms:>15.2f}")

    model = VirchowLinearHeadTAND(virchow_model).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = count_params(model)
    ms = benchmark(model, imgs, device)
    print(f"{'linear_tand':20s} {trainable:>15,d} {total:>15,d} {ms:>15.2f}")

    model = VirchowFusionUNet(virchow_model, image_size).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = count_params(model)
    ms = benchmark(model, imgs_full, device)
    print(f"{'efficientnet_unet':20s} {trainable:>15,d} {total:>15,d} {ms:>15.2f}")

    model = EfficientUNetWithPTC(virchow_model).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = count_params(model)
    ms = benchmark(model, (img_raw, img_norm), device)
    print(f"{'ptc_efficientunet':20s} {trainable:>15,d} {total:>15,d} {ms:>15.2f}")

    model = VirchowDPT(virchow_model, image_size).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = count_params(model)
    ms = benchmark(model, imgs_full, device)
    print(f"{'dpt':20s} {trainable:>15,d} {total:>15,d} {ms:>15.2f}")


if __name__ == "__main__":
    main()
