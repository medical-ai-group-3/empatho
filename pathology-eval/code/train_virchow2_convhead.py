"""
옵션 1 확장판 — Linear head(3,844개) 대신 2층 Conv 헤드로 파라미터 확장.
Conv2d(1280->256, 1x1) -> ReLU -> Conv2d(256->3, 1x1)
기존 가중치판(88.08%, 기타 Dice 0.50~0.53) 대비 헤드 표현력만 키운 버전.
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
PATCH_GRID = 16
NUM_REGISTER_TOKENS = 4
CLASS_WEIGHTS = torch.tensor([3.0, 1.0, 1.0])


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
        mask = mask.resize((PATCH_GRID, PATCH_GRID), Image.NEAREST)
        mask_t = torch.from_numpy(np.array(mask)).long()

        return img_t, mask_t


class VirchowConvHead(nn.Module):
    def __init__(self, virchow_model):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.head = nn.Sequential(
            nn.Conv2d(1280, 256, kernel_size=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(256, NUM_CLASSES, kernel_size=1),
        )
        self.log_temperature = nn.Parameter(torch.zeros(1))

    def forward(self, x):
        with torch.no_grad():
            tokens = self.encoder.forward_features(x)
        patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]  # (B, 256, 1280)
        B = patch_tokens.shape[0]
        grid = patch_tokens.permute(0, 2, 1).reshape(B, 1280, PATCH_GRID, PATCH_GRID)

        logits = self.head(grid)  # (B, 3, 16, 16)
        temperature = torch.exp(self.log_temperature)
        return logits / temperature


def dice_loss_soft(probs, targets_onehot, class_weights, eps=1e-6):
    dims = (0, 2, 3)
    intersection = (probs * targets_onehot).sum(dims)
    union = probs.sum(dims) + targets_onehot.sum(dims)
    dice_per_class = (2 * intersection + eps) / (union + eps)
    loss_per_class = (1 - dice_per_class) * class_weights
    return loss_per_class.mean()


def combined_loss(logits, targets, class_weights):
    probs = torch.softmax(logits, dim=1)
    targets_onehot = F.one_hot(targets, num_classes=NUM_CLASSES).permute(0, 3, 1, 2).float()

    ce = F.cross_entropy(logits, targets, weight=class_weights)
    dice = dice_loss_soft(probs, targets_onehot, class_weights)

    bce_raw = F.binary_cross_entropy_with_logits(logits, targets_onehot, reduction="none")
    bce_per_class = bce_raw.mean(dim=(0, 2, 3))
    bce = (bce_per_class * class_weights).mean()

    return ce + dice + bce


def per_class_dice(logits, targets, eps=1e-6):
    preds = logits.argmax(dim=1)
    dices = []
    for c in range(NUM_CLASSES):
        pred_c = (preds == c).float()
        target_c = (targets == c).float()
        intersection = (pred_c * target_c).sum()
        union = pred_c.sum() + target_c.sum()
        dices.append(((2 * intersection + eps) / (union + eps)).item())
    return dices


def pixel_accuracy(logits, targets):
    preds = logits.argmax(dim=1)
    return (preds == targets).float().mean().item()


def build_virchow2():
    model = timm.create_model(
        "hf_hub:paige-ai/Virchow2", pretrained=True,
        mlp_layer=timm.layers.SwiGLUPacked, act_layer=torch.nn.SiLU,
    )
    model.eval()
    data_cfg = timm.data.resolve_model_data_config(model)
    return model, data_cfg["mean"], data_cfg["std"], data_cfg["input_size"][-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", type=str, default=os.path.expanduser("~/data/tiger/tissue_segmentation_v2"))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--outdir", type=str, default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_convhead"))
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowConvHead(virchow_model).to(device)
    class_weights = CLASS_WEIGHTS.to(device)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"학습 대상 파라미터: {trainable} / 전체: {total} ({trainable/total*100:.4f}%)")

    root = Path(args.data_root)
    train_ds = TissueSegDataset(root, "train", image_size, mean, std)
    val_ds = TissueSegDataset(root, "val", image_size, mean, std)
    print(f"train: {len(train_ds)}, val: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)

    best_val_acc = 0.0
    class_names = ["기타", "종양", "간질"]
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.encoder.eval()
        for imgs, masks in train_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            loss = combined_loss(logits, masks, class_weights)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        val_accs, val_dices = [], []
        with torch.no_grad():
            for imgs, masks in val_loader:
                imgs, masks = imgs.to(device), masks.to(device)
                logits = model(imgs)
                val_accs.append(pixel_accuracy(logits, masks))
                val_dices.append(per_class_dice(logits, masks))

        val_acc = np.mean(val_accs)
        mean_dice = np.mean(val_dices, axis=0)
        print(f"Epoch {epoch}/{args.epochs} - val_acc: {val_acc:.4f}")
        print("  per-class Dice: " + ", ".join(f"{n}={d:.3f}" for n, d in zip(class_names, mean_dice)))

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(
                {"head_state_dict": model.head.state_dict(), "log_temperature": model.log_temperature, "val_acc": val_acc},
                os.path.join(args.outdir, "best_head.pth"),
            )
            print(f"  -> best 갱신, 저장됨 (val_acc={val_acc:.4f})")

    print(f"최고 val_acc: {best_val_acc:.4f}")


if __name__ == "__main__":
    main()
