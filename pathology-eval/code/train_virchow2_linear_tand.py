"""
옵션 1 (정정판) — Xu et al. 2025 "Tissue Aware Nuclei Detection and Classification
Model for Histopathology Images" (arXiv:2511.13615)의 조직분할 브랜치를 정확히 따름.

정정 사항 (최초 버전 대비):
  1. 온도 스케일링(temperature-scaled softmax) 추가 — 학습 가능한 온도 파라미터
  2. 손실 함수: CrossEntropy 단독 -> CE + Soft-Dice + 픽셀단위 BCE 조합
  3. 평가지표: pixel accuracy 외에 per-class Dice score 추가 (논문 방식)

구조 자체(패치 토큰 위 Linear, 16x16 격자)는 최초 버전과 동일 — TAND 논문 확인 결과
조직분할 브랜치는 단일 스케일이 맞음 ("multi-scale"은 이 Q를 다른 브랜치에 넣을 때
여러 해상도로 업샘플한다는 뜻이지, 헤드 자체가 여러 스케일에서 예측한다는 뜻이 아님).
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
        scaled_logits = logits / temperature
        return scaled_logits


def dice_loss_soft(probs, targets_onehot, eps=1e-6):
    dims = (0, 2, 3)
    intersection = (probs * targets_onehot).sum(dims)
    union = probs.sum(dims) + targets_onehot.sum(dims)
    dice = (2 * intersection + eps) / (union + eps)
    return 1 - dice.mean()


def combined_loss(logits, targets):
    probs = torch.softmax(logits, dim=1)
    targets_onehot = F.one_hot(targets, num_classes=NUM_CLASSES).permute(0, 3, 1, 2).float()

    ce = F.cross_entropy(logits, targets)
    dice = dice_loss_soft(probs, targets_onehot)
    bce = F.binary_cross_entropy(probs.clamp(1e-6, 1 - 1e-6), targets_onehot)

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
        "hf_hub:paige-ai/Virchow2",
        pretrained=True,
        mlp_layer=timm.layers.SwiGLUPacked,
        act_layer=torch.nn.SiLU,
    )
    model.eval()
    data_cfg = timm.data.resolve_model_data_config(model)
    return model, data_cfg["mean"], data_cfg["std"], data_cfg["input_size"][-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", type=str, default=os.path.expanduser("~/data/tiger/tissue_segmentation"))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument(
        "--outdir", type=str, default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand")
    )
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowLinearHeadTAND(virchow_model).to(device)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"학습 대상 파라미터: {trainable} / 전체: {total} ({trainable/total*100:.4f}%)")

    root = Path(args.data_root)
    train_ds = TissueSegDataset(root, "train", image_size, mean, std)
    val_ds = TissueSegDataset(root, "val", image_size, mean, std)
    print(f"train: {len(train_ds)}, val: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_params, lr=args.lr)

    best_val_acc = 0.0
    class_names = ["기타", "종양", "간질"]
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.encoder.eval()
        train_losses, train_accs = [], []
        for imgs, masks in train_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            logits = model(imgs)
            loss = combined_loss(logits, masks)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_losses.append(loss.item())
            train_accs.append(pixel_accuracy(logits, masks))

        model.eval()
        val_losses, val_accs = [], []
        val_dices = []
        with torch.no_grad():
            for imgs, masks in val_loader:
                imgs, masks = imgs.to(device), masks.to(device)
                logits = model(imgs)
                loss = combined_loss(logits, masks)
                val_losses.append(loss.item())
                val_accs.append(pixel_accuracy(logits, masks))
                val_dices.append(per_class_dice(logits, masks))

        train_loss, train_acc = np.mean(train_losses), np.mean(train_accs)
        val_loss, val_acc = np.mean(val_losses), np.mean(val_accs)
        mean_dice_per_class = np.mean(val_dices, axis=0)
        temp = torch.exp(model.log_temperature).item()

        print(
            f"Epoch {epoch}/{args.epochs} - "
            f"train_loss: {train_loss:.4f} train_acc: {train_acc:.4f} - "
            f"val_loss: {val_loss:.4f} val_acc: {val_acc:.4f} - temp: {temp:.3f}"
        )
        print(f"  per-class Dice: " + ", ".join(f"{n}={d:.3f}" for n, d in zip(class_names, mean_dice_per_class)))

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(
                {"head_state_dict": model.head.state_dict(),
                 "log_temperature": model.log_temperature,
                 "val_acc": val_acc, "epoch": epoch},
                os.path.join(args.outdir, "best_head.pth"),
            )
            print(f"  -> best 갱신, 저장됨 (val_acc={val_acc:.4f})")

    print(f"학습 종료. 최고 val_acc: {best_val_acc:.4f}")
    print(f"체크포인트: {os.path.join(args.outdir, 'best_head.pth')}")


if __name__ == "__main__":
    main()
