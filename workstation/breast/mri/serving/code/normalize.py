#!/usr/bin/env python3
"""
MRI 정규화 로직 — tumor(2-phase)와 density(1-phase)가 서로 다른 통계를 쓴다는 것이
2026-09-04 파트간 인터페이스 대조(H-3)에서 확인됨.

- tumor(mamamia 학습, preprocess_mamamia.py::zscore_two_phases)
    → pre+post를 합쳐서 낸 mean/std로 두 phase를 함께 정규화
- density(duke 학습, preprocess_duke_density.py 인라인 로직)
    → post 관여 없이 pre 볼륨 자체의 mean/std로만 정규화

두 정규화를 섞어 쓰면(예: 2-phase 볼륨의 pre 채널을 density 쿼리에 그대로 재사용)
density 모델이 학습 때 본 분포와 어긋난다 — 이게 H-3에서 실제로 잡힌 문제다.

⚠ 이 두 함수는 각각 preprocess_mamamia.py::zscore_two_phases,
   preprocess_duke_density.py의 인라인 정규화 로직과 반드시 동일해야 한다.
   두 배치 스크립트는 sitk.Image를 받는 버전이고 여긴 이미 array로 변환된 뒤를
   다루는 버전 — 계산식 자체는 동일하다. 배치 스크립트 쪽을 고치면 이 파일도
   같이 고칠 것 (복붙 금지 원칙의 예외 — 오프라인 학습 스크립트와 실시간 서빙이
   물리적으로 분리돼 있어 import로 공유가 안 되므로 부득이 로직을 미러링한다).
"""

import numpy as np


def zscore_two_phases(pre_arr: np.ndarray, post_arr: np.ndarray):
    """tumor(mamamia) 학습과 동일 — pre+post를 합쳐서 낸 통계로 두 phase를 정규화.
    preprocess_mamamia.py::zscore_two_phases와 동일 계산식."""
    combined = np.concatenate([pre_arr.ravel(), post_arr.ravel()])
    mean, std = combined.mean(), combined.std()
    std = std if std > 1e-6 else 1.0
    return (pre_arr - mean) / std, (post_arr - mean) / std


def zscore_pre_only(pre_arr: np.ndarray):
    """density(duke) 학습과 동일 — post 관여 없이 pre 볼륨 자체 통계로만 정규화.
    preprocess_duke_density.py 인라인 로직과 동일 계산식:
        mean, std = img_arr.mean(), img_arr.std()
    tumor 쪽 zscore_two_phases와 절대 섞어 쓰지 말 것 — 2026-09-04 H-3에서 잡힌
    정규화 불일치의 원인이 정확히 이 둘을 헷갈려 쓰는 것이었다."""
    mean, std = pre_arr.mean(), pre_arr.std()
    std = std if std > 1e-6 else 1.0
    return (pre_arr - mean) / std
