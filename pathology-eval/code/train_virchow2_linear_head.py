"""
Virchow2(동결) + Linear head로 3클래스 조직 분할(종양/간질/기타) 학습.

구조:
  이미지(224x224) -> Virchow2 -> 패치 토큰(256개, 16x16 격자, 1280차원)
  -> Linear(1280->3) -> 16x16x3 예측 맵
  -> 정답 마스크도 16x16으로 nearest 리샘플링해서 CrossEntropyLoss로 비교

Virchow2 파라미터는 전부 동결(freeze), Linear head(1280*3+3 = 3,843개 파라미터)만 학습.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

NUM_CLASSES = 3
PATCH_GRID = 16  # 224 / 14 (patch_size)
NUM_REGISTER_TOKENS = 4  # Virchow2는 CLS 1개 + register 4개 + patch 256개


class TissueSegDataset(Dataset):
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
        # 패치 격자(16x16) 해상도로 바로 nearest 리샘플링
        mask = mask.resize((PATCH_GRID, PATCH_GRID), Image.NEAREST)
        mask_t = torch.from_numpy(np.array(mask)).long()

        return img_t, mask_t


class VirchowLinearHead(nn.Module):
    def __init__(self, virchow_model):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.head = nn.Linear(1280, NUM_CLASSES)

    def forward(self, x):
        with torch.no_grad():
            tokens = self.encoder.forward_features(x)  # (B, 1+4+256, 1280)
        patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]  # (B, 256, 1280)
        logits = self.head(patch_tokens)  # (B, 256, 3)
        B = logits.shape[0]
        logits = logits.permute(0, 2, 1).reshape(B, NUM_CLASSES, PATCH_GRID, PATCH_GRID)
        return logits


def build_virchow2(model_path: str):
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
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--outdir", type=str, default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_head"))
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2(None)
    model = VirchowLinearHead(virchow_model).to(device)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"학습 대상 파라미터: {trainable} / 전체: {total} ({trainable/total*100:.4f}%)")

    root = Path(args.data_root)
    train_ds = TissueSegDataset(root, "train", image_size, mean, std)
    val_ds = TissueSegDataset(root, "val", image_size, mean, std)
    print(f"train: {len(train_ds)}, val: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    optimizer = torch.optim.AdamW(model.head.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    best_val_acc = 0.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.encoder.eval()  # 동결된 인코더는 항상 eval 모드 (BatchNorm/Dropout 영향 방지)
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
                {"head_state_dict": model.head.state_dict(), "val_acc": val_acc, "epoch": epoch},
                os.path.join(args.outdir, "best_head.pth"),
            )
            print(f"  -> best 갱신, 저장됨 (val_acc={val_acc:.4f})")

    print(f"학습 종료. 최고 val_acc: {best_val_acc:.4f}")
    print(f"체크포인트: {os.path.join(args.outdir, 'best_head.pth')}")


if __name__ == "__main__":
    main()
