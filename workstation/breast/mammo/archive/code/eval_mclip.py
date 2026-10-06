#!/usr/bin/env python
"""
Mammo-CLIP 백본으로 학습한 머리를 끝에서 끝까지 평가한다.

왜
  F1 은 서술어 단계의 지표다. 우리가 보고하는 것은 조직검사 판단 정확도이고,
  형태 축에서 난 +0.026 이 그 지표에서는 다르게 나타날 수도 있다.
  그것만 확인하고 이 갈래를 닫는다.

어떻게
  eval_e2e.py 는 train_mammo 에서 load_merged_model 과 FeatExtractor 를
  '이름으로' 가져온다(from ... import). 그래서 train_mammo 쪽을 고쳐도 이미
  묶인 이름은 안 바뀐다. eval_e2e 의 이름을 직접 바꿔 끼워야 한다.

  체크포인트 메타데이터에 백본 경로가 들어 있으므로 --ckpt 만 주면 된다.
  LoRA 가 없는 동결 머리 체크포인트라 LoRA 주입 경로는 자동으로 건너뛴다.

사용
  python3 eval_mclip.py --ckpt ckpt/mammo_calc_trunk_last_grid4_pad0_clip999_b5-model-best-epoch-7_head.pt
"""

import sys

import eval_e2e
from train_mclip import build_mammoclip, _FakeFull


def install():
    def _load(ckpt, cfg=None, device="cuda", **kw):
        return _FakeFull(build_mammoclip(ckpt, device))

    def _ext(vb, src):
        return vb          # 이미 특징 목록을 돌려주는 형태다

    eval_e2e.load_merged_model = _load
    eval_e2e.FeatExtractor = _ext


if __name__ == "__main__":
    print("=" * 70)
    print("끝에서 끝까지 평가 — 백본 Mammo-CLIP")
    print("=" * 70)
    install()
    eval_e2e.main()
