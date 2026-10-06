#!/usr/bin/env python3
"""
MRI 모델 로딩 — 체크포인트 적재, 추론 파라미터 병합.

infer_mri.py에서 분리(2026-09-03). 초음파 model_io.py와 이름을 맞췄다 —
둘이 정확히 같은 역할(로딩)을 하니 나중에 공통 유틸로 합칠 여지를 남겨둔다.

    from model_io import load_model
    bundle = load_model("configs/mri_lora.yaml")   # 프로세스당 한 번
"""

import os
import sys
from pathlib import Path

import torch

# ── mri/ 폴더 구조 기준 경로 (mri_folder_structure.html, 2026-08-31 정리본) ──
# 이 파일은 mri/serving/code/에 있다고 가정. postprocess_3d/code의 학습·평가
# 로직을 그대로 가져다 쓴다(복붙 금지 원칙, 문서 3.1).
MRI_ROOT = Path(__file__).resolve().parents[2]  # mri/
POSTPROCESS_3D_CODE = MRI_ROOT / "postprocess_3d" / "code"

if str(POSTPROCESS_3D_CODE) not in sys.path:
    sys.path.insert(0, str(POSTPROCESS_3D_CODE))

from eval_mri_lora_v3 import load_config, import_medsam3, build_model  # noqa: E402


DEFAULTS = {
    # 2026-09-01 threshold 스윕 실험(150장) 결과 반영. 재학습 없이 설정만 조정.
    "tumor_score_threshold": 0.5,        # 올리면 Dice 급락(0.72→0.44) - 기본값 유지
    "dense_tissue_score_threshold": 0.5, # 올리면 Dice 급락(0.48→0.17) - 기본값 유지
    "breast_score_threshold": 0.8,       # Dice 거의 그대로(0.966→0.948), 오탐율 51%→35% 순이득
    "mask_pixel_threshold": 0.5,         # 2026-09-29 실제 연결됨(이전엔 미사용 - infer_slice_mask가 모듈 상수를 씀)
    "min_voxels": 30,
    "min_contiguous_slices": 2,
    "mesh_smooth_iters": 1,              # build_mesh_from_mask.py CLI 기본값과 통일(0=계단무늬, 1~3 권장)
    # 2026-09-29 신규 — 상수로 박혀 있던 tumor 후처리 기준을 kwarg/config로 조정 가능하게 노출.
    # 값은 기존 상수와 동일(동작 변화 없음). ⚠ 셋 다 환자 1명·임계값 0.7 실측으로 정한 값이라 미검증.
    "flat_min_aspect_ratio": 0.3,        # = v9 MIN_ASPECT_RATIO (시트형 필터)
    "flat_min_thin_axis_mm": 4.0,        # = v9 MIN_THIN_AXIS_MM (시트형 필터)
    "max_lesions": 10,                   # = compute_stage1_metrics MAX_LESIONS_PER_PATIENT (부피 큰 순 상한)
    # 2026-09-29 — 병변 후보 평균 점수 하한(0이면 끔). val 40명 5-fold 교차검증에서 매 fold 0.6 선택:
    # 환자당 순수 오탐 3.73→2.27, 주 병변 40/40, 민감도 0.706 그대로. 3차 모델 기준값 — 모델 교체 시 재조정.
    "min_lesion_score_mean": 0.6,
    # 2026-10-01 — 필터 전 z축 빈틈 메우기 반경(0=끔, k면 빈 슬라이스 최대 2k장). 3차 모델엔 끔 유지.
    # 6차 모델(tumor 음성 학습)이 병변을 z로 끊어 예측하는 문제 대응 — 6차 후보 설정은 1.
    "z_gap_fill": 0,
}


def _merge_defaults(cfg):
    d = dict(DEFAULTS)
    d.update(cfg.get("inference", {}) or {})
    return d


def load_model(config, weights=None, device=None, keep_cwd=False):
    """모델을 한 번 올려 두고 재사용한다. 반환값을 predict()에 넘긴다.

    가중치 경로를 생략하면 <ckpt_dir>/mri_lora_best.pt를 쓴다.
    ⚠ 내부에서 os.chdir 한다(MedSAM3가 상대경로를 하드코딩). 기본은 끝나고 되돌린다.
    """
    cwd0 = os.getcwd()
    cfg_path = Path(config).resolve()
    cfg = load_config(cfg_path)
    ck = Path(cfg["output"]["ckpt_dir"])

    w = Path(weights).resolve() if weights else ck / "mri_lora_best.pt"
    for q in (cfg_path, w):
        if not Path(q).exists():
            raise FileNotFoundError(q)

    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        M = import_medsam3(cfg["model"]["medsam3_repo"])   # 여기서 os.chdir 한다
        model = build_model(cfg, str(w), M, dev)
        model.eval()
    finally:
        if not keep_cwd:
            os.chdir(cwd0)

    return {
        "model": model, "M": M, "cfg": cfg, "device": dev,
        "resolution": cfg["data"]["resolution"],
        "params": _merge_defaults(cfg),
        "paths": {"config": str(cfg_path), "weights": str(w)},
    }
