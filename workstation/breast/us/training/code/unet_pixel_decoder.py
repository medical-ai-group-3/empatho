#!/usr/bin/env python3
"""④ UNet 스타일 픽셀 디코더 — segmentation_head.pixel_decoder 만 교체한다.

마스크 경로는 그대로다. SAM3 는 쿼리별 mask_embed 와 픽셀맵의 내적으로
마스크를 만들므로(maskformer_segmentation.py:33), 픽셀맵을 만드는 방식만
바꾸면 쿼리 200개 · 텍스트 프롬프트 · 등급 헤드 · 손실 항 수가 전부 유지된다.

원본 PixelDecoder (maskformer_segmentation.py:203)
    prev = curr + F.interpolate(prev, mode="nearest")
    prev = relu(norm(conv3x3(prev)))

block_type
  fuse   (기본, A안) nearest→bilinear · 고정덧셈→학습 가능한 1x1 융합.
         변수 2개만 바뀌는 깨끗한 ablation.
  light  (B안) SAM3-UNet 의 LightBlock 을 잔차로 얹는다. 원본의 BatchNorm 은
         GroupNorm 으로 치환했다 — batch 3 에서 표본 3개로 통계를 내는 것이
         원본 유지보다 더 큰 왜곡이다.

두 경로 모두 시작 시점 출력이 원본과 같다(초기 붕괴 없음).
  fuse   1x1 융합을 [I | I] 로 두면 출력이 정확히 curr+up. conv/norm 은 원본 복사.
  light  원본 경로를 그대로 두고 LightBlock 을 gamma=0 게이트로 더한다.
         구조가 달라 가중치 복사는 불가능하지만, 잔차 형태로 같은 보호를 얻는다.

해상도는 288² 유지. pred_masks 가 (B,200,H,W) 라 쿼리 200개가 곱해져
288²→504² 는 +2~4GB 로 추정된다 — 별도 실험으로 분리했다.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class LightBlock(nn.Module):
    """SAM3-UNet 의 LightBlock. BatchNorm2d → GroupNorm 치환."""

    def __init__(self, in_c, out_c, groups=8):
        super().__init__()
        mid, d = in_c // 4, in_c // 8
        self.conv_in = nn.Sequential(
            nn.Conv2d(in_c, mid, 1), nn.GroupNorm(min(groups, mid), mid), nn.GELU())
        self.dw1 = nn.Sequential(
            nn.Conv2d(d, d, 3, 1, 1, groups=d), nn.GroupNorm(min(groups, d), d), nn.GELU())
        self.dw2 = nn.Sequential(
            nn.Conv2d(d, d, 3, 1, 1, groups=d), nn.GroupNorm(min(groups, d), d), nn.GELU())
        self.conv_out = nn.Sequential(
            nn.Conv2d(in_c // 2, out_c, 1),
            nn.GroupNorm(min(groups, out_c), out_c), nn.GELU())

    def forward(self, x):
        x = self.conv_in(x)
        x1, x2 = torch.split(x, x.shape[1] // 2, 1)
        x3 = self.dw1(x2)
        x4 = self.dw2(x3)
        return self.conv_out(torch.cat([x1, x2, x3, x4], dim=1))


class DecoderStage(nn.Module):
    def __init__(self, C, block_type="fuse", groups=8):
        super().__init__()
        self.block_type = block_type
        self.conv = nn.Conv2d(C, C, 3, 1, 1)          # 원본에서 복사할 대상
        self.norm = nn.GroupNorm(groups, C)
        if block_type == "fuse":
            self.fuse = nn.Conv2d(2 * C, C, 1)
            with torch.no_grad():                      # [I | I] → 출력이 curr+up
                self.fuse.weight.zero_()
                eye = torch.eye(C)
                self.fuse.weight[:, :C, 0, 0] = eye
                self.fuse.weight[:, C:, 0, 0] = eye
                self.fuse.bias.zero_()
        elif block_type == "light":
            self.light = LightBlock(2 * C, C, groups)
            # gamma=0 게이트 — 시작 시점에 잔차 기여가 정확히 0 이라 원본과 같다.
            # conv_out 을 zero-init 하는 방법도 있지만 GroupNorm 뒤라 그래디언트가
            # 죽는다. 스칼라 게이트는 그래디언트가 살아 있으면서 항등에서 출발한다.
            self.gamma = nn.Parameter(torch.zeros(1, C, 1, 1))
        else:
            raise ValueError(f"block_type 은 fuse|light — 받은 값 {block_type}")

    def forward(self, curr, up):
        if self.block_type == "fuse":
            x = self.fuse(torch.cat([curr, up], dim=1))
            return F.relu(self.norm(self.conv(x)))
        base = F.relu(self.norm(self.conv(curr + up)))     # 원본 경로 그대로
        return base + self.gamma * self.light(torch.cat([curr, up], dim=1))


class UNetPixelDecoder(nn.Module):
    """원본과 같은 인터페이스: forward(backbone_feats) -> pixel_embed.

    backbone_feats 는 [고해상도 ... 저해상도] 순, 전부 hidden_dim 채널.
    (해상도가 큰 순서. 마지막은 DETR 인코더 출력)
    출력은 backbone_feats[0] 해상도 = 288².
    """

    def __init__(self, hidden_dim=256, num_stages=3, block_type="fuse", groups=8):
        super().__init__()
        self.stages = nn.ModuleList(
            [DecoderStage(hidden_dim, block_type, groups) for _ in range(num_stages)])
        self.block_type = block_type
        self.out_dim = hidden_dim

    @torch.no_grad()
    def warm_start_from(self, original):
        """원본 conv/norm 을 복사한다. fuse·light 모두 이 경로를 쓴다."""
        n = min(len(self.stages), len(original.conv_layers))
        for i in range(n):
            self.stages[i].conv.load_state_dict(original.conv_layers[i].state_dict())
            self.stages[i].norm.load_state_dict(original.norms[i].state_dict())
        return n

    def forward(self, backbone_feats):
        prev = backbone_feats[-1]
        for i, curr in enumerate(backbone_feats[:-1][::-1]):
            up = F.interpolate(prev, size=curr.shape[-2:],
                               mode="bilinear", align_corners=False)
            prev = self.stages[i](curr, up)
        return prev


def gamma_stats(model):
    """light 경로의 잔차 게이트가 얼마나 열렸는지. fuse 면 None.
    0 에서 시작해 커지는 속도를 보면 LightBlock 기여가 언제부터 붙는지 알 수 있다."""
    vals = [m.gamma.detach().abs() for m in model.modules()
            if isinstance(m, DecoderStage) and hasattr(m, "gamma")]
    if not vals:
        return None
    return (float(torch.stack([v.max() for v in vals]).max()),
            float(torch.stack([v.mean() for v in vals]).mean()))


def find_pixel_decoder(model):
    """경로가 빌드 방식에 따라 달라져서 하드코딩하지 않고 찾는다."""
    mods = dict(model.named_modules())
    for name, mod in mods.items():
        if name.endswith("pixel_decoder") and (hasattr(mod, "conv_layers")
                                               or isinstance(mod, UNetPixelDecoder)):
            return mods[name.rsplit(".", 1)[0]], name, mod
    return None, None, None


def swap_in(model, block_type="fuse", warm_start=True, verbose=True):
    """원본 pixel_decoder 를 교체하고 새 모듈의 파라미터 수를 돌려준다."""
    parent, name, orig = find_pixel_decoder(model)
    if orig is None:
        raise RuntimeError("pixel_decoder 를 찾지 못했다 — 모델 구조를 확인할 것")

    hidden = orig.conv_layers[0].out_channels
    stages = len(orig.conv_layers)
    groups = orig.norms[0].num_groups
    p0 = next(orig.parameters())

    new = UNetPixelDecoder(hidden, stages, block_type, groups)
    copied = new.warm_start_from(orig) if warm_start else 0
    new = new.to(p0.device, dtype=p0.dtype)
    setattr(parent, "pixel_decoder", new)

    n_old = sum(p.numel() for p in orig.parameters())
    n_new = sum(p.numel() for p in new.parameters())
    if verbose:
        print(f"      pixel_decoder 교체 — {name}")
        print(f"      block_type {block_type} · 단계 {stages} · hidden {hidden}")
        print(f"      파라미터 {n_old:,} → {n_new:,}  ({n_new - n_old:+,})")
        print(f"      warm start — conv/norm {copied}단계 복사"
              + (" · 융합=항등합" if block_type == "fuse" else " · 잔차 gamma=0"))
    return n_new