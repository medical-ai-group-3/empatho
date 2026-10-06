#!/usr/bin/env python3
"""
BI-RADS 등급 헤드 — CORAL 순서형 + 악성 확률.

    쿼리 임베딩(256) → CoralHead → 경계 3개 로짓 [P(y>2), P(y>3), P(y>4)]
                    → MalignancyHead → 악성 로짓

설계 근거와 검증 수치는 ../README.md
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

BIRADS_MIN = 2                      # US 는 2·3·4·5 네 등급
NUM_GRADES = 4
NUM_BOUNDARIES = NUM_GRADES - 1     # P(y>2), P(y>3), P(y>4)


def normalize_birads(v):
    """'4a'/'4b'/'4c' → 4, int/str 혼재 정규화. BrEaST(test) 대응."""
    s = str(v).strip().lower()
    return 4 if s.startswith("4") else int(s)


def normalize_pathology(ann):
    """BUS-BRA 는 'pathology', BrEaST 는 'classification' 필드를 쓴다."""
    v = ann.get("pathology", ann.get("classification"))
    return 1 if str(v).strip().lower() == "malignant" else 0


class CoralHead(nn.Module):
    """K개 등급 → K-1개 이진 문제. 공유 가중치 + 경계별 바이어스.

    ⚠ 바이어스 정렬 제약(softplus 누적합)을 빼지 말 것 —
      "4 이상인데 3 이상은 아니다" 같은 모순이 나올 수 있다.
    """

    def __init__(self, in_dim, hidden=None, dropout=0.0):
        super().__init__()
        if hidden:
            self.trunk = nn.Sequential(
                nn.LayerNorm(in_dim), nn.Linear(in_dim, hidden), nn.GELU(),
                nn.Dropout(dropout), nn.Linear(hidden, 1, bias=False),
            )
        else:
            self.trunk = nn.Sequential(nn.LayerNorm(in_dim),
                                       nn.Linear(in_dim, 1, bias=False))
        self.b0 = nn.Parameter(torch.zeros(1))
        self.delta = nn.Parameter(torch.zeros(NUM_BOUNDARIES - 1))

    def biases(self):
        steps = torch.cumsum(F.softplus(self.delta), dim=0)
        return torch.cat([self.b0, self.b0 - steps])          # 내림차순 보장

    def forward(self, feat):
        return self.trunk(feat) + self.biases()               # (B, 3) 로짓


class MalignancyHead(nn.Module):
    """악성 확률 스칼라.

    ⚠ 화면에 노출하지 않는다. 학습 데이터의 악성 비율이 실제 검진과 크게 달라
      확률의 절대값을 신뢰할 수 없다(README). 순위 지표로만 쓴다.
    """

    def __init__(self, in_dim, hidden=None, dropout=0.0):
        super().__init__()
        if hidden:
            self.net = nn.Sequential(
                nn.LayerNorm(in_dim), nn.Linear(in_dim, hidden), nn.GELU(),
                nn.Dropout(dropout), nn.Linear(hidden, 1),
            )
        else:
            self.net = nn.Sequential(nn.LayerNorm(in_dim), nn.Linear(in_dim, 1))

    def forward(self, feat):
        return self.net(feat).squeeze(-1)                     # (B,) 로짓


class GradingHeads(nn.Module):
    """두 헤드를 한 모듈로 묶어 저장/로드를 단순화한다."""

    def __init__(self, in_dim=256, hidden=None, dropout=0.0):
        super().__init__()
        self.coral = CoralHead(in_dim, hidden, dropout)
        self.malignancy = MalignancyHead(in_dim, hidden, dropout)

    def forward(self, feat):
        return self.coral(feat), self.malignancy(feat)


def coral_targets(grades):
    """등급 → 경계별 이진 타깃. grades (B,) long, 값은 2~5."""
    ks = torch.arange(BIRADS_MIN, BIRADS_MIN + NUM_BOUNDARIES,
                      device=grades.device)
    return (grades[:, None] > ks[None, :]).float()            # (B, 3)


def coral_loss(logits, grades, pos_weight=None):
    """CORAL 손실. 경계별 이진 교차엔트로피.

    pos_weight 를 경계별로 받는다 — 없으면 전부 음성으로 수렴하는 쪽이 국소 최적이 된다.
    """
    t = coral_targets(grades)
    return F.binary_cross_entropy_with_logits(
        logits, t, pos_weight=pos_weight, reduction="mean")


def coral_decode(logits):
    """로짓 → 등급. ⚠ 임계값 0.5 고정이다. 다른 임계값을 쓰려면 확률로 직접 계산할 것."""
    return BIRADS_MIN + (logits > 0).sum(dim=1)               # σ>0.5 ⟺ 로짓>0


def compute_pos_weights(anns, device="cpu"):
    """경계별 pos_weight(neg/pos)와 악성 pos_weight 를 산출한다."""
    ys = [normalize_birads(a["birads"]) for a in anns]
    n = len(ys)
    w = []
    for k in range(BIRADS_MIN, BIRADS_MIN + NUM_BOUNDARIES):
        p = sum(1 for y in ys if y > k)
        w.append((n - p) / max(p, 1))
    m = sum(normalize_pathology(a) for a in anns)
    return (torch.tensor(w, dtype=torch.float32, device=device),
            torch.tensor((n - m) / max(m, 1), dtype=torch.float32, device=device))