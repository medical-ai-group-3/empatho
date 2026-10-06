"""
옵션 2: EfficientNetV2 U-Net + Virchow2(동결) 특징 융합으로 3클래스 조직분할 학습.

옵션 1(Linear head)과 다르게:
  - 원본 해상도(224x224)에서 직접 학습 (16x16 저해상도 grid가 아님)
  - Virchow2 패치 토큰을 저차원(8채널)으로 투영 -> 224x224로 업샘플 -> RGB 이미지와 채널 결합(3+8=11채널)
  - EfficientNetV2 기반 U-Net(encoder+decoder 전체 학습 가능)이 이 11채널 입력을 받아 분할 예측

Virchow2 백본만 동결, 나머지(projection, U-Net 전체)는 학습 대상.
파이지 챌린지(PUMA) 우승 방식의 단순화 버전 — 정확한 재현이 아니라 근사 비교용.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import segmentation_models_pytorch as smp
import timm
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset

NUM_CLASSES = 3
PATCH_GRID = 16
NUM_REGISTER_TOKENS = 4
VIRCHOW_PROJ_DIM = 8


class TissueSegDatasetFull(Dataset):
    """옵션 1과 다르게 마스크를 원본 해상도(224x224)로 유지."""

    def __init__(self, root: Path, split: str, image_size: int, mean, std):
        self.image_dir = root / split / "images"
        self.mask_dir = root / split / "masks"
        self.files = sorted([p.stem for p in self.image_dir.glob("*.png")])
        self.image_size = image_size
        self.mean = torch.tensor(mean).view(3, 1, 1)
        self.std = torch.tensor(std).view(3, 1, 1)

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        stem = self.files[idx]
        img = Image.open(self.image_dir / f"{stem}.png").convert("RGB")
        img = img.resize((self.image_size, self.image_size), Image.BILINEAR)
        img_t = torch.from_numpy(np.array(img)).permute(2, 0, 1).float() / 255.0
        img_t = (img_t - self.mean) / self.std

        mask = Image.open(self.mask_dir / f"{stem}.png")
        mask = mask.resize((self.image_size, self.image_size), Image.NEAREST)
        mask_t = torch.from_numpy(np.array(mask)).long()

        return img_t, mask_t


class VirchowFusionUNet(nn.Module):
    def __init__(self, virchow_model, image_size: int):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.image_size = image_size

        self.virchow_proj = nn.Linear(1280, VIRCHOW_PROJ_DIM)

        self.unet = smp.Unet(
            encoder_name="tu-efficientnetv2_rw_s",
            encoder_weights="imagenet",
            in_channels=3 + VIRCHOW_PROJ_DIM,
            classes=NUM_CLASSES,
        )

    def forward(self, x):
        with torch.no_grad():
            tokens = self.encoder.forward_features(x)
        patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]  # (B, 256, 1280)

        proj = self.virchow_proj(patch_tokens)  # (B, 256, P) - 학습 대상
        B = proj.shape[0]
        proj = proj.permute(0, 2, 1).reshape(B, VIRCHOW_PROJ_DIM, PATCH_GRID, PATCH_GRID)
        proj = nn.functional.interpolate(
            proj, size=(self.image_size, self.image_size), mode="bilinear", align_corners=False
        )

        fused_input = torch.cat([x, proj], dim=1)  # (B, 3+P, H, W)
        logits = self.unet(fused_input)
        return logits


def build_virchow2():
    model = timm.create_model(
        "hf_hub:paige-ai/Virchow2",
        pretrained=True,
        mlp_layer=timm.layers.SwiGLUPacked,
        act_layer=torch.nn.SiLU,
    )
    model.eval()
    data_cfg = timm.data.resolve_model_data_config(model)
    return model, data_cfg["mean"], data_cfg["std"], data_cfg["input_size"][-1]


def pixel_accuracy(logits, targets):
    preds = logits.argmax(dim=1)
    return (preds == targets).float().mean().item()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", type=str, default=os.path.expanduser("~/data/tiger/tissue_segmentation"))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument(
        "--outdir",
        type=str,
        default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_efficientnet_unet"),
    )
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowFusionUNet(virchow_model, image_size).to(device)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"학습 대상 파라미터: {trainable} / 전체: {total} ({trainable/total*100:.2f}%)")

    root = Path(args.data_root)
    train_ds = TissueSegDatasetFull(root, "train", image_size, mean, std)
    val_ds = TissueSegDatasetFull(root, "val", image_size, mean, std)
    print(f"train: {len(train_ds)}, val: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_params, lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    best_val_acc = 0.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.encoder.eval()
        train_losses, train_accs = [], []
        for imgs, masks in train_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            loss = criterion(logits, masks)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_losses.append(loss.item())
            train_accs.append(pixel_accuracy(logits, masks))

        model.eval()
        val_losses, val_accs = [], []
        with torch.no_grad():
            for imgs, masks in val_loader:
                imgs, masks = imgs.to(device), masks.to(device)
                logits = model(imgs)
                loss = criterion(logits, masks)
                val_losses.append(loss.item())
                val_accs.append(pixel_accuracy(logits, masks))

        train_loss, train_acc = np.mean(train_losses), np.mean(train_accs)
        val_loss, val_acc = np.mean(val_losses), np.mean(val_accs)
        print(
            f"Epoch {epoch}/{args.epochs} - "
            f"train_loss: {train_loss:.4f} train_acc: {train_acc:.4f} - "
            f"val_loss: {val_loss:.4f} val_acc: {val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(
                {
                    "virchow_proj_state_dict": model.virchow_proj.state_dict(),
                    "unet_state_dict": model.unet.state_dict(),
                    "val_acc": val_acc,
                    "epoch": epoch,
                },
                os.path.join(args.outdir, "best_model.pth"),
            )
            print(f"  -> best 갱신, 저장됨 (val_acc={val_acc:.4f})")

    print(f"학습 종료. 최고 val_acc: {best_val_acc:.4f}")
    print(f"체크포인트: {os.path.join(args.outdir, 'best_model.pth')}")


if __name__ == "__main__":
    main()
