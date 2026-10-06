#!/usr/bin/env python
"""
서술어 모델의 백본을 Mammo-CLIP 으로 갈아끼운다.

왜
  지금 백본(SAM3 vision_backbone)은 맘모그래피를 배운 적이 없다.
  Mammo-CLIP 은 맘모 영상과 판독문 쌍으로 사전학습된 EfficientNet-B5 다.
  같은 조각·같은 머리·같은 지표로 백본만 바꿔 재면 순수한 비교가 된다.

어떻게
  train_mammo.py 를 고치지 않는다. 그 파일은 우리 σ 기준선과 최종 체크포인트를
  만든 코드라 손대면 비교의 근거가 흔들린다.
  대신 백본을 만드는 함수 두 개만 바꿔 끼우고(monkey patch) main() 을 그대로 부른다.

    load_merged_model  ->  Mammo-CLIP EfficientNet 을 돌려주는 것으로 교체
    FeatExtractor      ->  그대로 통과시키는 것으로 교체

  풀링·머리·학습·평가·캐시는 전부 원래 코드가 한다.

입력 규격 맞추기
  데이터셋은 (B,3,S,S) 를 (v-0.5)/0.5 로 정규화해 내놓는다.
  Mammo-CLIP 은 흑백을 3채널로 복제해 쓰고 평균 0.3089279 ·
  표준편차 0.25053555408335154 로 정규화한다 (체크포인트의 _conv_stem 이
  [48,3,3,3] 이라 3채널이 확인된다).
  래퍼 안에서 [0,1] 로 되돌렸다가 다시 정규화한다 — 데이터셋은 안 건드린다.

캐시 분리
  train_mammo 는 --ckpt 파일 이름을 캐시 키에 넣는다. 체크포인트 이름이 다르니
  SAM3 특징과 섞이지 않는다. 자동으로 분리된다.

사용
  python3 train_mclip.py --kind calc --cache --no-pad --pool grid --grid 4 \
      --ckpt ckpt/mammoclip/b5-model-best-epoch-7.tar

  나머지 인자는 train_mammo.py 와 완전히 같다.
"""

import sys
import types
from pathlib import Path

import torch
import torch.nn as nn

import train_mammo

# 공식 설정에서 확인한 값 (체크포인트의 config.base 와 일치)
MEAN = 0.3089279
STD = 0.25053555408335154
ARCH = "efficientnet-b5"
PREFIX = "image_encoder."


class MammoClipVB(nn.Module):
    """
    Mammo-CLIP 시각 인코더. train_mammo 의 FeatExtractor 자리에 그대로 들어간다.
    forward 는 특징 지도 하나를 담은 목록을 돌려준다 — pool_feats 가 그 형태를 받는다.
    """

    def __init__(self, net, in_ch=3):
        super().__init__()
        self.net = net
        self.in_ch = in_ch

    def forward(self, x):
        # 들어오는 x 는 (B,3,S,S) 이고 (v-0.5)/0.5 로 정규화돼 있다.
        v = x if self.in_ch == 3 else x[:, :self.in_ch]
        v = v * 0.5 + 0.5                     # [0,1] 로 되돌린다
        v = (v - MEAN) / STD                  # Mammo-CLIP 규격으로 다시
        return [self.net.extract_features(v)]


def build_mammoclip(ckpt_path, device):
    """체크포인트에서 시각 인코더만 꺼내 만든다. 안 맞으면 멈춘다."""
    try:
        from efficientnet_pytorch import EfficientNet
    except ImportError:
        sys.exit("efficientnet_pytorch 없음  ->  pip install efficientnet_pytorch")

    p = Path(ckpt_path)
    if not p.is_file():
        sys.exit(f"체크포인트가 없다: {p}")

    print(f"    Mammo-CLIP  {p.name}")
    obj = torch.load(str(p), map_location="cpu", weights_only=False)
    sd = obj["model"] if isinstance(obj, dict) and "model" in obj else obj

    sub = {k[len(PREFIX):]: v for k, v in sd.items() if k.startswith(PREFIX)}
    if not sub:
        sys.exit(f"체크포인트에 '{PREFIX}' 로 시작하는 키가 없다. 구조가 다르다.")

    # 입력 채널 수는 첫 층 모양이 알려준다. 짐작하지 않는다.
    stem = sub.get("_conv_stem.weight")
    if stem is None:
        sys.exit("_conv_stem.weight 가 없다 — EfficientNet 구조가 아니다.")
    in_ch = int(stem.shape[1])
    print(f"    입력 채널 {in_ch}  (첫 층 {tuple(stem.shape)} 에서 읽음)")

    net = EfficientNet.from_name(ARCH, in_channels=in_ch)
    missing, unexpected = net.load_state_dict(sub, strict=False)

    # 검증 — 조용히 절반만 얹히는 사고를 막는다.
    #   빠져도 되는 것은 분류기 머리(_fc)뿐이다. CLIP 학습 때 떼어냈다.
    bad_missing = [k for k in missing if not k.startswith("_fc")]
    if unexpected or bad_missing:
        print(f"    ! 키가 안 맞는다")
        print(f"      예상 밖 {len(unexpected)}개: {sorted(unexpected)[:5]}")
        print(f"      빠짐   {len(bad_missing)}개: {sorted(bad_missing)[:5]}")
        sys.exit("    가중치가 온전히 안 얹혔다 — 중단한다.")

    n = sum(v.numel() for v in sub.values())
    print(f"    가중치 {len(sub)}개 · {n/1e6:.1f}M 로드   "
          f"(분류기 머리 {len(missing)}개는 원래 없다)")

    net = net.to(device).eval()
    for q in net.parameters():
        q.requires_grad = False
    return MammoClipVB(net, in_ch).to(device)


class _FakeFull:
    """train_mammo 가 full.backbone.vision_backbone 을 꺼내가므로 그 모양만 맞춘다."""

    def __init__(self, vb):
        self.backbone = types.SimpleNamespace(vision_backbone=vb)


def install():
    """백본을 만드는 두 지점만 바꿔 끼운다."""
    def _load(ckpt, cfg=None, device="cuda", **kw):
        return _FakeFull(build_mammoclip(ckpt, device))

    def _ext(vb, src):
        if src not in ("trunk", "vb"):
            print(f"    (참고) --src {src} 는 Mammo-CLIP 에서 의미가 없다. 무시한다.")
        return vb          # 이미 목록을 돌려주는 형태다

    train_mammo.load_merged_model = _load
    train_mammo.FeatExtractor = _ext


def main():
    if "--ckpt" not in sys.argv:
        print("! --ckpt 로 Mammo-CLIP 체크포인트를 지정해야 한다.")
        print("  예: --ckpt ckpt/mammoclip/b5-model-best-epoch-7.tar")
        print("  (이 이름이 특징 캐시 키에 들어가 SAM3 특징과 분리된다)")
        sys.exit(1)

    print("=" * 70)
    print("서술어 모델 — 백본을 Mammo-CLIP 으로 교체")
    print("=" * 70)
    print(f"  구조    {ARCH}  (1채널)")
    print(f"  정규화  평균 {MEAN}  표준편차 {STD}")
    print(f"  풀링·머리·학습·평가는 train_mammo.py 원본을 그대로 쓴다")
    print("=" * 70)

    install()
    train_mammo.main()


if __name__ == "__main__":
    main()
