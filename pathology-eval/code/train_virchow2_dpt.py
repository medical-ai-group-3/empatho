"""
옵션 3 — DPT(Dense Prediction Transformer, Ranftl et al. 2021, "Vision Transformers
for Dense Prediction") 방식. 프로즌 ViT 백본 위에서 검증된 표준 분할 디코더로,
Linear head보다 강력하고 전체 CNN(옵션2)보다 훨씬 가벼운 중간 지점.

구조:
  1. Virchow2(동결)에서 서로 다른 4개 깊이(레이어)의 패치 토큰을 추출
     (CellViT가 SAM/Virchow 인코더에서 쓰던 extract_layers=[8,16,24,32] 방식과 동일한 아이디어)
  2. 각 레이어의 토큰(16x16x1280)을 "Reassemble" 모듈로 서로 다른 해상도의
     2D 특징맵으로 재조립 (얕은 층=고해상도, 깊은 층=저해상도)
  3. RefineNet 스타일 "Fusion" 블록으로 깊은 층부터 얕은 층 순서로 점진적으로 융합
  4. 최종 특징맵을 conv head로 픽셀별 클래스 로짓으로 변환, 원본 해상도로 업샘플
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
EXTRACT_LAYERS = [8, 16, 24, 32]  # Virchow2(32-depth ViT-H)에서 4개 지점 추출
REASSEMBLE_DIM = 256


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
        img_t = (img_t - self.mean) / self.std

        mask = Image.open(self.mask_dir / f"{stem}.png")
        mask = mask.resize((self.image_size, self.image_size), Image.NEAREST)
        mask_t = torch.from_numpy(np.array(mask)).long()

        return img_t, mask_t


class ResidualConvUnit(nn.Module):
    """RefineNet의 기본 구성 요소: pre-activation residual conv block"""

    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        out = self.relu(x)
        out = self.conv1(out)
        out = self.relu(out)
        out = self.conv2(out)
        return out + x


class FusionBlock(nn.Module):
    """깊은 층의 특징(작은 해상도)을 업샘플해서 얕은 층 특징과 합침"""

    def __init__(self, channels):
        super().__init__()
        self.rcu1 = ResidualConvUnit(channels)
        self.rcu2 = ResidualConvUnit(channels)

    def forward(self, x, skip=None):
        if skip is not None:
            x = x + skip
        x = self.rcu1(x)
        x = F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False)
        x = self.rcu2(x)
        return x


class ReassembleBlock(nn.Module):
    """(B, 256, 1280) 패치 토큰 -> (B, REASSEMBLE_DIM, 16, 16) -> 목표 해상도로 리사이즈"""

    def __init__(self, in_dim, out_dim, target_grid):
        super().__init__()
        self.proj = nn.Linear(in_dim, out_dim)
        self.target_grid = target_grid

    def forward(self, tokens):
        B = tokens.shape[0]
        x = self.proj(tokens)  # (B, 256, out_dim)
        x = x.permute(0, 2, 1).reshape(B, -1, PATCH_GRID, PATCH_GRID)
        if self.target_grid != PATCH_GRID:
            x = F.interpolate(x, size=(self.target_grid, self.target_grid), mode="bilinear", align_corners=False)
        return x


class DPTHead(nn.Module):
    """4개 레이어 토큰 -> 조직분할 예측"""

    def __init__(self, embed_dim=1280, num_classes=NUM_CLASSES, image_size=224):
        super().__init__()
        # 얕은 층일수록 더 고해상도로 재조립 (표준 DPT 방식: 1/4, 1/8, 1/16, 1/32 스케일)
        # 우리는 패치 격자가 16x16 하나뿐이라, 대신 4단계 업샘플 목표 해상도를 다르게 줌
        grids = [PATCH_GRID * 8, PATCH_GRID * 4, PATCH_GRID * 2, PATCH_GRID]  # 128, 64, 32, 16
        self.reassemble = nn.ModuleList(
            [ReassembleBlock(embed_dim, REASSEMBLE_DIM, g) for g in grids]
        )
        self.fusion = nn.ModuleList([FusionBlock(REASSEMBLE_DIM) for _ in range(4)])
        self.head = nn.Sequential(
            nn.Conv2d(REASSEMBLE_DIM, 128, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, num_classes, 1),
        )
        self.image_size = image_size

    def forward(self, layer_tokens):
        # layer_tokens: 리스트[4], 각 (B, 256, 1280), 얕은 층부터 깊은 층 순서
        reassembled = [self.reassemble[i](layer_tokens[i]) for i in range(4)]
        # 깊은 층(마지막)부터 시작해서 얕은 층 방향으로 융합
        x = self.fusion[3](reassembled[3], skip=None)
        x = self.fusion[2](x, skip=reassembled[2])
        x = self.fusion[1](x, skip=reassembled[1])
        x = self.fusion[0](x, skip=reassembled[0])
        x = self.head(x)
        x = F.interpolate(x, size=(self.image_size, self.image_size), mode="bilinear", align_corners=False)
        return x


class VirchowDPT(nn.Module):
    def __init__(self, virchow_model, image_size):
        super().__init__()
        self.encoder = virchow_model
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.dpt_head = DPTHead(embed_dim=1280, num_classes=NUM_CLASSES, image_size=image_size)
        self._hooked_outputs = {}
        self._register_hooks()

    def _register_hooks(self):
        blocks = self.encoder.blocks
        for idx in EXTRACT_LAYERS:
            block = blocks[idx - 1]

            def make_hook(layer_idx):
                def hook(module, inp, out):
                    self._hooked_outputs[layer_idx] = out
                return hook

            block.register_forward_hook(make_hook(idx))

    def forward(self, x):
        self._hooked_outputs = {}
        with torch.no_grad():
            self.encoder.forward_features(x)

        layer_tokens = []
        for idx in EXTRACT_LAYERS:
            tokens = self._hooked_outputs[idx]  # (B, 261, 1280)
            patch_tokens = tokens[:, 1 + NUM_REGISTER_TOKENS :, :]  # (B, 256, 1280)
            layer_tokens.append(patch_tokens)

        return self.dpt_head(layer_tokens)


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", type=str, default=os.path.expanduser("~/data/tiger/tissue_segmentation"))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument(
        "--outdir", type=str, default=os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_dpt")
    )
    args = parser.parse_args()

    device = f"cuda:{args.gpu}"
    os.makedirs(args.outdir, exist_ok=True)

    print("Virchow2 로딩 중...")
    virchow_model, mean, std, image_size = build_virchow2()
    model = VirchowDPT(virchow_model, image_size).to(device)

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
    class_names = ["기타", "종양", "간질"]
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
        val_losses, val_accs, val_dices = [], [], []
        with torch.no_grad():
            for imgs, masks in val_loader:
                imgs, masks = imgs.to(device), masks.to(device)
                logits = model(imgs)
                loss = criterion(logits, masks)
                val_losses.append(loss.item())
                val_accs.append(pixel_accuracy(logits, masks))
                val_dices.append(per_class_dice(logits, masks))

        train_loss, train_acc = np.mean(train_losses), np.mean(train_accs)
        val_loss, val_acc = np.mean(val_losses), np.mean(val_accs)
        mean_dice = np.mean(val_dices, axis=0)

        print(
            f"Epoch {epoch}/{args.epochs} - "
            f"train_loss: {train_loss:.4f} train_acc: {train_acc:.4f} - "
            f"val_loss: {val_loss:.4f} val_acc: {val_acc:.4f}"
        )
        print(f"  per-class Dice: " + ", ".join(f"{n}={d:.3f}" for n, d in zip(class_names, mean_dice)))

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(
                {"dpt_head_state_dict": model.dpt_head.state_dict(), "val_acc": val_acc, "epoch": epoch},
                os.path.join(args.outdir, "best_head.pth"),
            )
            print(f"  -> best 갱신, 저장됨 (val_acc={val_acc:.4f})")

    print(f"학습 종료. 최고 val_acc: {best_val_acc:.4f}")
    print(f"체크포인트: {os.path.join(args.outdir, 'best_head.pth')}")


if __name__ == "__main__":
    main()
