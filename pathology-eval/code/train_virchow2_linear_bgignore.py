"""
옵션 1 (배경 제외 + 가중치 최종판)

변경사항 (가중치판 대비):
  - 마스크에 배경(원본 라벨 0)은 255(IGNORE_LABEL)로 표시되어 있음
  - CE: ignore_index=255로 배경 픽셀을 손실 계산에서 완전히 제외
  - Dice/BCE: valid_mask(배경이 아닌 픽셀)만 사용하도록 마스킹
  - "기타" 클래스는 이제 배경 없이 순수 조직(정상선조직/괴사/나머지)만 의미
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
IGNORE_LABEL = 255
CLASS_WEIGHTS = torch.tensor([3.0, 1.0, 1.0])  # 기타, 종양, 간질


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


class VirchowLinearHeadTAND(nn.Module):
    def __init__(self, virchow_model):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.head = nn.Linear(1280, NUM_CLASSES)
        self.log_temperature = nn.Parameter(torch.zeros(1))

    def forward(self, x):
        with torch.no_grad():
            tokens = self.encoder.forward_features(x)
        patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]
        logits = self.head(patch_tokens)
        B = logits.shape[0]
        logits = logits.permute(0, 2, 1).reshape(B, NUM_CLASSES, PATCH_GRID, PATCH_GRID)

        temperature = torch.exp(self.log_temperature)
        return logits / temperature


def dice_loss_soft_masked(probs, targets_onehot, valid_mask, class_weights, eps=1e-6):
    # valid_mask: (B, 1, H, W)
    probs = probs * valid_mask
    targets_onehot = targets_onehot * valid_mask
    dims = (0, 2, 3)
    intersection = (probs * targets_onehot).sum(dims)
    union = probs.sum(dims) + targets_onehot.sum(dims)
    dice_per_class = (2 * intersection + eps) / (union + eps)
    loss_per_class = (1 - dice_per_class) * class_weights
    return loss_per_class.mean()


def combined_loss(logits, targets, class_weights):
    valid = (targets != IGNORE_LABEL)  # (B, H, W)
    targets_clamped = targets.clone()
    targets_clamped[~valid] = 0  # one_hot 에러 방지용 임시값, 아래서 마스킹으로 제외됨

    probs = torch.softmax(logits, dim=1)
    targets_onehot = F.one_hot(targets_clamped, num_classes=NUM_CLASSES).permute(0, 3, 1, 2).float()
    valid_mask = valid.unsqueeze(1).float()  # (B,1,H,W)

    # CE: ignore_index로 배경 픽셀 완전 제외
    ce = F.cross_entropy(logits, targets_clamped.masked_fill(~valid, IGNORE_LABEL), weight=class_weights, ignore_index=IGNORE_LABEL)

    # Dice: valid_mask 적용
    dice = dice_loss_soft_masked(probs, targets_onehot, valid_mask, class_weights)

    # BCE: raw logits 사용 + valid_mask 적용, 유효 픽셀 수로 나눔
    bce_raw = F.binary_cross_entropy_with_logits(logits, targets_onehot, reduction="none")  # (B,C,H,W)
    bce_raw = bce_raw * valid_mask
    denom = valid_mask.sum(dim=(0, 2, 3)).clamp(min=1.0)  # (1,) broadcast 주의
    bce_per_class = bce_raw.sum(dim=(0, 2, 3)) / valid.sum().clamp(min=1)
    bce = (bce_per_class * class_weights).mean()

    return ce + dice + bce


def per_class_dice_masked(logits, targets, eps=1e-6):
    valid = (targets != IGNORE_LABEL)
    preds = logits.argmax(dim=1)
    dices = []
    for c in range(NUM_CLASSES):
        pred_c = ((preds == c) & valid).float()
        target_c = ((targets == c) & valid).float()
        intersection = (pred_c * target_c).sum()
        union = pred_c.sum() + target_c.sum()
        dices.append(((2 * intersection + eps) / (union + eps)).item())
    return dices


def pixel_accuracy_masked(logits, targets):
    valid = (targets != IGNORE_LABEL)
    preds = logits.argmax(dim=1)
    correct = ((preds == targets) & valid).float().sum()
    total = valid.float().sum().clamp(min=1)
    return (correct / total).item()


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
    parser.add_argument("--outdir", type=str, default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_bgignore"))
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowLinearHeadTAND(virchow_model).to(device)
    class_weights = CLASS_WEIGHTS.to(device)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"학습 대상 파라미터: {trainable} / 전체: {total} ({trainable/total*100:.4f}%)")
    print(f"클래스 가중치 (기타, 종양, 간질): {CLASS_WEIGHTS.tolist()}, 배경(ignore={IGNORE_LABEL}) 학습 제외")

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
                val_accs.append(pixel_accuracy_masked(logits, masks))
                val_dices.append(per_class_dice_masked(logits, masks))

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
