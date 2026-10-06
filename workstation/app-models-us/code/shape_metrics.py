#!/usr/bin/env python3
"""
마스크 → 외곽선 폴리곤 + 형태 지표 + 마스크 신뢰도.

    predict() 의 이진 마스크 → 여기 → JSON 의 polygons · shape · mask_reliability

⚠ 단위는 전부 픽셀이다. pixel spacing 이 데이터에 없어 mm 환산 근거가 없다.
⚠ 지표는 단순화한 폴리곤이 아니라 원본 마스크에서 계산한다 — 단순화가 경계 요철을 지운다.
⚠ "불규칙" 같은 판정 임계값을 정할 근거가 없다. 수치 그대로만 내보낸다.

배경·검증 수치는 ../README.md
"""

import numpy as np

try:
    import cv2
except ImportError:                                   # pragma: no cover
    cv2 = None

# 표시용 폴리곤에서 뺄 조각의 크기 상한(전체 면적 대비).
# ⚠ "최대 성분만 남기기"는 쓰지 않는다 — 큰 쪽이 오답일 때 위험하다(README).
SPECK_FRAC = 0.01


def _contours(mask):
    """RETR_CCOMP 로 외곽선과 구멍을 함께 얻는다."""
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return [], []
    hier = hier[0]
    outer = [c for c, h in zip(cs, hier) if h[3] < 0]
    holes = [c for c, h in zip(cs, hier) if h[3] >= 0]
    return outer, holes


def extract_polygons(mask, epsilon=0.5, drop_specks=True):
    """이진 마스크 → 표시용 폴리곤(원본 픽셀 좌표계). SVG 로 그린다.

    epsilon 을 키우면 경계 요철이 사라진다 — 작게 둘 것.
    """
    if cv2 is None or mask is None or not mask.any():
        return {"outer": [], "holes": [], "n_components": 0, "dropped_specks": 0}

    outer, holes = _contours(mask)
    areas = [cv2.contourArea(c) for c in outer]
    total = sum(areas) or 1.0
    n_all = len(outer)

    keep = list(zip(outer, areas))
    dropped = 0
    if drop_specks and n_all > 1:
        kept = [(c, a) for c, a in keep if a / total >= SPECK_FRAC]
        dropped = n_all - len(kept)
        if kept:
            keep = kept

    def simp(c):
        c = cv2.approxPolyDP(c, epsilon, True) if epsilon and epsilon > 0 else c
        return [[int(x), int(y)] for x, y in c.reshape(-1, 2)]

    return {
        "outer": [simp(c) for c, _ in keep],
        "holes": [simp(c) for c in holes],
        "n_components": n_all,
        "dropped_specks": dropped,
    }


def shape_metrics(mask):
    """원본 마스크 → 형태 지표. 전부 픽셀 단위 · 단위 없는 비율."""
    if cv2 is None or mask is None or not mask.any():
        return None

    outer, _ = _contours(mask)
    if not outer:
        return None
    c = max(outer, key=cv2.contourArea)
    A = float(cv2.contourArea(c))
    P = float(cv2.arcLength(c, True))
    if A <= 0 or P <= 0:
        return None

    hull = cv2.convexHull(c)
    Ah = float(cv2.contourArea(hull))
    Ph = float(cv2.arcLength(hull, True))
    x, y, w, h = cv2.boundingRect(c)

    pts = hull.reshape(-1, 2).astype(np.float64)
    feret = float(np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).max()) \
        if len(pts) > 1 else 0.0

    hw = float(h) / max(int(w), 1)
    return {
        "unit": "px",                        # mm 아님 — 모듈 docstring 참조
        "area_px": int(mask.sum()),
        "max_diameter_px": round(feret, 1),
        "bbox_w_px": int(w),
        "bbox_h_px": int(h),
        "height_width_ratio": round(hw, 3),
        "taller_than_wide": bool(hw > 1.0),
        "solidity": round(A / Ah, 3) if Ah > 0 else None,
        "boundary_irregularity": round(P / Ph, 3) if Ph > 0 else None,
        "circularity": round(4 * np.pi * A / (P * P), 3),
        "n_components": len(outer),
    }


def orientation_label(m):
    """화면 표기용 문구. ⚠ 사실만 적는다 — "악성 의심" 같은 해석은 판독의 몫."""
    if not m:
        return None
    return "세로로 긴 병변" if m["taller_than_wide"] else "가로로 긴 병변"


# 판독문 생성기(MedGemma)에 넘겨도 되는 값 — 크기·위치·등급·조치만 허용한다.
# 위치는 검사 정보(DICOM ImageLaterality 등) 입력값을 그대로 옮기며 생성하지 않는다.
# 파일명의 -l/-r 은 좌우가 아니라 같은 병변의 다른 뷰다 — 좌우로 해석하지 말 것.
# 형태 지표를 문장으로 옮기면 검증 게이트에서 반려한다(서술어 라벨로 검증되지 않았다).
REPORTABLE_KEYS = ("area_px", "max_diameter_px", "bbox_w_px", "bbox_h_px")


def mask_reliability(max_score, n_detections):
    """마스크를 믿어도 되는지. 등급 확신도와는 별개 축이다
    ("병변을 찾았나" vs "등급이 확실한가"). 구간 기준은 ../README.md

    운영에서 "낮음" 비율의 상승은 도메인 이동 신호다.
    """
    if max_score is None or n_detections is None or n_detections == 0:
        return {"level": "낮음", "reason": "검출 없음", "dim_shape_metrics": True}
    if max_score >= 0.90 and n_detections == 1:
        return {"level": "높음", "reason": None, "dim_shape_metrics": False}
    if n_detections > 1:
        return {"level": "낮음", "reason": f"검출 {n_detections}개",
                "dim_shape_metrics": True}
    if max_score >= 0.80:
        return {"level": "보통", "reason": None, "dim_shape_metrics": False}
    return {"level": "낮음", "reason": f"검출 점수 {max_score:.2f}",
            "dim_shape_metrics": True}