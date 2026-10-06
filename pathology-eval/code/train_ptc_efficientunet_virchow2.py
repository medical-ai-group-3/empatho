"""
옵션 2 (정확 버전) — Lv et al. 2025 "Leveraging Pathology Foundation Models for
Panoptic Segmentation of Melanoma in H&E Images" (arXiv:2507.13974) 구조 그대로 구현.
PUMA Challenge 조직분할 1위 방법.

구조:
  1. 이미지 -> 224x224 -> Virchow2(동결) -> 패치 토큰(1280x256) -> (1280,16,16) 재배열
  2. PTC 모듈: ConvTranspose2d(1280->256) + Sigmoid -> ConvTranspose2d(256->64) + Sigmoid
              -> Conv2d 1x1(64->num_classes) + Sigmoid  => (num_classes, 224, 224)
  3. PTC 출력 + 원본 RGB 채널결합 -> Efficient-UNet(EfficientNetV2 encoder, SCSE decoder)
  4. 손실: DiceFL(2*Dice + Focal) 을 PTC 출력과 최종 출력 각각에 계산, 0.2*L_PTC + L_Output

우리 프로젝트는 5클래스가 아니라 3클래스(종양/간질/기타)로 축소.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import segmentation_models_pytorch as smp
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

NUM_CLASSES = 3
PATCH_GRID = 16
NUM_REGISTER_TOKENS = 4
ALPHA_FOCAL = 0.3
GAMMA_FOCAL = 3.5
PTC_LOSS_WEIGHT = 0.2


class TissueSegDatasetFull(Dataset):
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
        img_norm = (img_t - self.mean) / self.std

        mask = Image.open(self.mask_dir / f"{stem}.png")
        mask = mask.resize((self.image_size, self.image_size), Image.NEAREST)
        mask_t = torch.from_numpy(np.array(mask)).long()

        # img_t: 0~1 정규화 안 된 원본 (PTC 출력과 채널결합용)
        # img_norm: 인코더(Virchow2, EfficientNet)에 넣을 정규화된 버전
        return img_t, img_norm, mask_t


class PTCModule(nn.Module):
    """Progressive Transposed Convolution: 16x16 패치 토큰 -> 224x224 num_classes 맵"""

    def __init__(self, in_channels=1280, num_classes=NUM_CLASSES):
        super().__init__()
        # 16 -> 56 -> 224 (각 단계 4배 업샘플, kernel=8, stride=4, padding=2)
        self.deconv1 = nn.ConvTranspose2d(in_channels, 256, kernel_size=8, stride=4, padding=2)
        self.deconv2 = nn.ConvTranspose2d(256, 64, kernel_size=8, stride=4, padding=2)
        self.final_conv = nn.Conv2d(64, num_classes, kernel_size=1)

    def forward(self, x):
        x = torch.sigmoid(self.deconv1(x))   # 16 -> 64 (근사, 아래 보간으로 224 정확히 맞춤)
        x = torch.sigmoid(self.deconv2(x))
        x = self.final_conv(x)
        x = torch.sigmoid(x)
        # 정확히 224x224가 아닐 수 있어 최종 보정
        if x.shape[-1] != 224:
            x = F.interpolate(x, size=(224, 224), mode="bilinear", align_corners=False)
        return x


class EfficientUNetWithPTC(nn.Module):
    def __init__(self, virchow_model):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False

        self.ptc = PTCModule(in_channels=1280, num_classes=NUM_CLASSES)

        self.unet = smp.Unet(
            encoder_name="tu-tf_efficientnetv2_m",
            encoder_weights="imagenet",
            decoder_attention_type="scse",  # SCSE 모듈 (논문 명시)
            in_channels=3 + NUM_CLASSES,
            classes=NUM_CLASSES,
        )

    def forward(self, img_raw, img_norm):
        with torch.no_grad():
            tokens = self.encoder.forward_features(img_norm)
        patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]  # (B, 256, 1280)
        B = patch_tokens.shape[0]
        grid = patch_tokens.permute(0, 2, 1).reshape(B, 1280, PATCH_GRID, PATCH_GRID)

        ptc_out = self.ptc(grid)  # (B, num_classes, 224, 224) - 0~1 sigmoid 출력

        fused = torch.cat([img_raw, ptc_out], dim=1)  # (B, 3+num_classes, 224, 224)
        final_out = self.unet(fused)

        return ptc_out, final_out


def dice_loss(probs, targets_onehot, eps=1e-6):
    # probs, targets_onehot: (B, C, H, W)
    dims = (0, 2, 3)
    intersection = (probs * targets_onehot).sum(dims)
    union = probs.sum(dims) + targets_onehot.sum(dims)
    dice = (2 * intersection + eps) / (union + eps)
    return 1 - dice.mean()


def focal_loss(probs, targets_onehot, alpha=ALPHA_FOCAL, gamma=GAMMA_FOCAL, eps=1e-6):
    probs = probs.clamp(eps, 1 - eps)
    pos_term = -alpha * (1 - probs) ** gamma * torch.log(probs) * targets_onehot
    neg_term = -(1 - alpha) * probs ** gamma * torch.log(1 - probs) * (1 - targets_onehot)
    return (pos_term + neg_term).mean()


def dice_fl_loss(logits_or_probs, targets, already_prob=False):
    """logits_or_probs: (B, C, H, W). already_prob=True면 PTC 출력(이미 sigmoid 통과)."""
    B, C, H, W = logits_or_probs.shape
    targets_onehot = F.one_hot(targets, num_classes=C).permute(0, 3, 1, 2).float()

    if already_prob:
        probs = logits_or_probs
    else:
        probs = torch.softmax(logits_or_probs, dim=1)

    return 2 * dice_loss(probs, targets_onehot) + focal_loss(probs, targets_onehot)


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
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight_decay", type=float, default=5e-3)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument(
        "--outdir",
        type=str,
        default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_ptc_efficientunet"),
    )
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2()
    model = EfficientUNetWithPTC(virchow_model).to(device)

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
    optimizer = torch.optim.AdamW(trainable_params, lr=args.lr, weight_decay=args.weight_decay)

    best_val_acc = 0.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.encoder.eval()
        train_losses, train_accs = [], []
        for img_raw, img_norm, masks in train_loader:
            img_raw, img_norm, masks = img_raw.to(device), img_norm.to(device), masks.to(device)
            ptc_out, final_out = model(img_raw, img_norm)

            l_ptc = dice_fl_loss(ptc_out, masks, already_prob=True)
            l_output = dice_fl_loss(final_out, masks, already_prob=False)
            loss = PTC_LOSS_WEIGHT * l_ptc + l_output

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_losses.append(loss.item())
            train_accs.append(pixel_accuracy(final_out, masks))

        model.eval()
        val_losses, val_accs = [], []
        with torch.no_grad():
            for img_raw, img_norm, masks in val_loader:
                img_raw, img_norm, masks = img_raw.to(device), img_norm.to(device), masks.to(device)
                ptc_out, final_out = model(img_raw, img_norm)
                l_ptc = dice_fl_loss(ptc_out, masks, already_prob=True)
                l_output = dice_fl_loss(final_out, masks, already_prob=False)
                loss = PTC_LOSS_WEIGHT * l_ptc + l_output
                val_losses.append(loss.item())
                val_accs.append(pixel_accuracy(final_out, masks))

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
                    "ptc_state_dict": model.ptc.state_dict(),
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
