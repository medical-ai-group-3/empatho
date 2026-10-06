#!/usr/bin/env python
"""
맘모 추론 — 영상 한 장 → 병변 박스 · BI-RADS 서술어 · 등급 · 조직검사 여부.

서빙용 API 와 CLI 를 겸한다. 초음파 파트 infer_us.py 와 같은 모양이다.

    from infer_mammo import load_model, predict
    bundle = load_model()                 # 프로세스당 한 번 (17초 · 상주 6.7GB)
    result = predict(bundle, "a.dcm")     # 요청마다 (영상당 5~20초)

CLI

    python3 infer_mammo.py --image a.dcm

주의 — load_model 은 내부에서 os.chdir 한다(MedSAM3 가 상대경로를 하드코딩).
기본값은 로드가 끝나면 원래 작업 디렉토리로 되돌린다. keep_cwd=True 로 끌 수 있다.

초음파와 다른 점
  · 마스크가 아니라 박스를 낸다. 맘모 학습 데이터에 분할 라벨이 없다.
  · 등급 경로가 하나뿐이다 — 서술어 → 규칙표(경로 A). CORAL 헤드가 없어
    category_model · boundaries · gate_flags 를 못 채운다. result["limitations"]
    에 그 사실과 이유를 넣어 내보낸다. 비워서 보내면 받는 쪽이 '확인했는데
    문제 없음' 으로 읽는다.
  · 종류가 둘이라(종괴 · 미세석회) 서술어 모델도 둘이다.

확정 운영점 (2026-08-31 · 에폭 6)
    합치기 wbf@0.3 + 조직 마스크 필터 0.5
    점수 임계값 석회 0.594 · 종괴 0.767   (FROC 오탐 1개/영상 지점)
    끝단 성능 — 조직검사 대상 병변의 70.2% (위치를 알려주면 90.0%)  ← PERF
    정상 유방 — 영상당 표시 2.30개 · 검사 단위 재소환 100%  ← NORMAL
                **검진 선별용이 아니다.** docs/screening_limit.md
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 조각화 완화. CUDA 할당자가 이 값을 초기화 때 읽으므로 torch 사용 전에
# 걸어야 한다. 실측에서 1.90GiB 가 "예약됐지만 미사용" 으로 놀다가
# 1.60GiB 할당이 실패했다 — OOM 메시지가 직접 권하는 설정이다.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mammo_io import (BIOPSY_CUT, KIND_OF, PROMPTS, RES,           # noqa: E402
                      build_descriptor, build_detector, crop_to_tensor,
                      expand_box, filter_tissue, import_medsam3, make_batch,
                      merge_boxes_one, norm8, positions, read_mammogram,
                      read_out, tissue_bbox, tissue_mask)
from paths import CKPT, MEDSAM3                                    # noqa: E402

# 확정 설정. predict(**over) 로 요청 단위로 덮어쓸 수 있다.
# 임계값은 운영 정책 영역이다 — 근거는 docs/results_for_presentation.md 6-3절.
DEFAULTS = {
    "tile": RES, "overlap": 256, "pad": 32, "clip": 99.9,
    "thr": 0.05,              # 타일 단계 후보 문턱. 낮게 두고 아래로 거른다
    "merge": "wbf", "nms": 0.3,
    "tissue_frac": 0.5,       # 박스 면적 중 조직 비율 하한
    # 타일 조직 필터. 조직 비율이 이 값 미만인 타일에서 나온 검출을 버린다.
    # 공기가 아니라 **유방 경계선** 오탐을 지운다 — 검출 상자 안 조직 비율로는
    # 안 잡힌다(5퍼센타일이 이미 0.52). 0 이면 안 거른다.
    "tile_frac": 0.30,
    # 깊이 가중. 유방 경계로부터의 거리로 점수를 다시 매긴다. 버리지는 않는다.
    # 종류마다 다른 이유 — 측정된 깊이 분리도(석회 8.2% · 종괴 19.3%)에 1.8 을
    # 곱한 값이고, 두 종류의 실측 최적과 각각 일치했다.
    "depth_lambda": {"calcification": 0.15, "mass": 0.35},
    # FROC 오탐 1개/영상 지점. **위 두 후처리를 넣은 뒤 다시 뽑은 값이다.**
    # 깊이 가중이 점수 척도를 내리므로 옛 값(0.594/0.767)을 그대로 쓰면
    # 종괴 검출이 붕괴한다. 0.25개/영상(0.671/0.822)은 애초에 0건이 된다.
    # ⚠ 후처리를 끄거나 문턱을 바꾸면 반드시 다시 뽑을 것 —
    #   score_dets.py 의 '운영에 넣을 점수 임계값' 표.
    # 작동점 오탐 2개/영상 (2026-09-04 결정). 1개 기준은
    # 석회 0.504 · 종괴 0.519 였다.
    # **후처리를 바꾸면 반드시 다시 뽑아야 한다** — score_dets.py 가 낸다.
    "score_calc": 0.448, "score_mass": 0.462,
    # 미세석회 표식의 크기. 조직 상자 넓이의 몇 % 인가.
    # 0.5% 면 한 변이 조직 폭의 약 7% 되는 정사각형이다.
    "marker_frac": 0.5,
    "topk": 0,                # 0 = 제한 없음. 임계값이 판단한다
    "thr_desc": 0.5,          # 희소 축을 채택할 최소 확률
    "always": ("shape", "margin", "calctype", "calcdist"),
    "batch": 4,
    "conf_low": 0.60,         # 서술어 확신도가 이보다 낮으면 「직접 확인」
    # 시야를 받는 쪽이 알려줄 수 있다 — LCC · LMLO · RCC · RMLO.
    # DICOM 에 ViewPosition 이 없는 영상이 있고(CBIS 가 그렇다), DB 의
    # storage_object.series_role 에는 값이 있다. 그때 이리로 넣는다.
    # ⚠ 태그에 값이 있는데 이것과 다르면 이름표를 안 붙인다 — 뒤바뀜이다.
    "view_code": None,
}

DEFAULT_CKPT = {
    "det": CKPT / "last_lora.pt",
    "calc": CKPT / "mammo_calc_trunk_last_grid4_pad0_clip999_lora.pt",
    "mass": CKPT / "mammo_mass_trunk_last_grid4_pad0_clip999_lora.pt",
}

# 우리 시스템으로 못 채우는 팀 명세 필드. 비워서 보내면 받는 쪽이
# '확인했는데 문제 없음' 으로 읽는다. 이유를 붙여 내보낸다.
# 끝단 실측 성능. **여기가 유일한 출처다.**
#
# 같은 숫자가 여러 파일에 흩어져 있다가 셋 다 다른 시점의 값이 된 적이 있다
# (2026-09-04 에 발견 — 화면에는 조직 필터 넣기 전 값이 뜨고 있었다).
# 성능이 바뀌면 여기만 고치고, 아래 '가리키는 곳' 의 산문도 같이 손볼 것.
#
# 가리키는 곳
#   predict.py  report() 의 화면 문구 (이 사전에서 읽는다)
#   이 파일 머리말 · LIMITATIONS 의 서술어 문구 (산문이라 숫자를 직접 적는다)
#   docs/mammo_api.md §10 · docs/results_for_presentation.md
#   docs/screening_limit.md (NORMAL 의 근거 · 정상 유방 실측)
#
# 조건 — CBIS-DDSM test 598장 · 조직검사 대상 병변 459건 · 에폭 6 ·
#        wbf@0.3 + 조직 마스크 필터 + 조직 타일 30% + 깊이 가중
PERF = {
    # 2026-09-08 정정 — 서빙과 같은 조건으로 다시 잰 값(patch_bd2)이
    # 문서에는 반영됐는데 여기만 뒤처져 있었다. 유도가 맞물린다 —
    # 검출기 366/459 = 79.7% · 서술어 322/366 = 88.0% · 곱하면 70.2%.
    "e2e": 70.2,              # 사진만 주고 조직검사 판단까지 (322/459)
    "e2e_calc": 77.3,         # 미세석회
    "e2e_mass": 63.8,         # 종괴
    "roi": 90.0,              # 위치를 알려줬을 때 (462건 중 46건 놓침)
    "setting": "wbf@0.3 + 조직타일 30% + 깊이 가중",
    "n_images": 598,
    "epoch": 6,
}

# 정상 유방 실측 (2026-09-08). **여기가 유일한 출처다** — PERF 와 같은 이유.
#
# 조건 — VinDr-Mammo test · 유방 단위 BI-RADS 1 · 네 유방이 전부 1 인 검사만
#        75 검사 · 300장 · 밀도 C 가 79%
#
# ⚠ 이 값은 작동점의 **예산 안**이다. 「종류당 영상당 오탐 2개」로 잡았으므로
#   영상당 4개까지 허용한 값이고 실측이 2.30 이다. 모델이 시끄러운 것이
#   아니라 그 작동점이 검진용이 아니다.
#
# ⚠ 문턱을 올려도 해결되지 않는다 — 재소환을 11% 로 낮추면 병변을 100건 중
#   2~6건밖에 못 찾는다(같은 자료 VinDr 로 확인). docs/screening_limit.md 5절.
NORMAL = {
    "marks_per_image": 2.30,   # 영상당 표시 수
    "marks_mass": 1.70,
    "marks_calc": 0.60,
    "quiet_image": 5.3,        # 검출이 하나도 없는 사진 %
    "study_recall": 100.0,     # 검사 단위 재소환 %
    "n_images": 300,
    "n_studies": 75,
    "source": "VinDr-Mammo BI-RADS 1 · test",
}

LIMITATIONS = {
    "category_model": "CORAL 등급 헤드가 없다. 경로 A(서술어→규칙표)만 구현했다",
    "microcalc_extent": "미세석회는 위치 표식만 낸다. 검출 상자가 병변 크기가 "
                        "아니다 — 실측으로 정답 대비 가로 0.58 · 세로 0.53 이고 "
                        "편차가 커서(25퍼 0.28 · 75퍼 1.11) 크기를 주장하지 "
                        "않는다. display.claims_extent 가 false 다.",
    "boundaries": "등급 경계 확률(ge_2·ge_3·ge_4·eq_5)은 CORAL 헤드에서 나온다",
    "path_agreement": "경로가 하나뿐이라 교차검증이 성립하지 않는다",
    "gate_flags": "게이트 1(단조성)·5(3↔4 경계)는 CORAL 확률이 필요하다. "
                  "대신 서술어 확신도(certainty)를 제공한다",
    "clock_position": "유두 검출을 하지 않는다",
    "distance_from_nipple_mm": "유두 검출을 하지 않는다",
}


def _params(over):
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (over or {}).items() if v is not None})
    return p


# ────────────────────────────── 로딩 ──────────────────────────────
def load_model(det=None, calc=None, mass=None, device=None, repo=None,
               keep_cwd=False, verbose=True):
    """
    모델을 한 번 올려 두고 재사용한다. 반환값을 predict() 에 넘긴다.

    검출기 1개 + 서술어 2개를 전부 상주시킨다(실측 6.7GB · 17초).
    ⚠ 6.7GB 는 '올려만 둔' 값이다. 추론 중에는 타일 어텐션 활성값이 붙어
      최대 11.3GB 까지 간다(실측). 용량은 11~13GB 로 잡을 것.
    요청마다 올렸다 내리면 영상 처리 시간보다 적재가 더 걸린다.
    ⚠ 내부에서 os.chdir 한다. 기본은 끝나고 되돌린다.
    """
    cwd0 = os.getcwd()
    paths = {"det": Path(det or DEFAULT_CKPT["det"]).expanduser().resolve(),
             "calc": Path(calc or DEFAULT_CKPT["calc"]).expanduser().resolve(),
             "mass": Path(mass or DEFAULT_CKPT["mass"]).expanduser().resolve()}
    for k, p in paths.items():
        if not p.is_file():
            raise FileNotFoundError(f"{k} 가중치가 없다: {p}")
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if dev == "cpu":
        # SAM3 가 position_encoding.py 에서 device="cuda" 를 하드코딩한다.
        raise RuntimeError("CPU 로는 못 돌린다 — SAM 3 가 cuda 를 하드코딩한다")

    try:
        if verbose:
            print("모델 적재 중…")
        M = import_medsam3(repo or MEDSAM3)      # 여기서 os.chdir 한다
        detector = build_detector(M, paths["det"], dev, verbose=verbose)
        desc = {}
        for kind in ("calc", "mass"):
            ext, head, meta = build_descriptor(paths[kind], dev, verbose=verbose)
            desc[kind] = dict(ext=ext, head=head, meta=meta)
    finally:
        if not keep_cwd:
            os.chdir(cwd0)

    from eval_e2e import find_rules, import_rules
    from mammo_data import axis_slices, load_schema
    from train_mammo import SCHEMA
    rules = import_rules(find_rules())
    schema = load_schema(SCHEMA)
    for kind in desc:
        desc[kind]["slices"] = axis_slices(schema, kind)

    if verbose:
        print(f"적재 완료  ({dev})")
    return {"M": M, "detector": detector, "desc": desc, "rules": rules,
            "device": dev, "params": dict(DEFAULTS),
            "paths": {k: str(v) for k, v in paths.items()},
            "operating_point": "wbf@0.3 + tissue 0.5 · 1FP thresholds · epoch 6"}


# 받는 쪽이 반드시 화면에 함께 표시해야 하는 것.
# ⚠ 끝단 수치가 들어 있다. 재측정하면 여기도 같이 고쳐야 한다.
# ⚠ 두 방향을 다 경고해야 한다. 놓치는 쪽만 적으면 받는 쪽이
#   「표시가 떴다 = 뭔가 있다」로 읽는다. 검진 인구는 대부분 정상이고
#   그 영상마다 표시가 두세 개씩 뜬다.
DISCLAIMER = ("판독 보조이며 진단이 아니다. 조직검사가 확정된 사례로 "
              "학습·평가돼 검진 상황의 확률과 다르다. 놓친 병변은 "
              "이 결과에 나타나지 않는다 (끝단 민감도 70.2%). "
              "반대로 병변이 없는 유방에서도 영상당 2.3개의 표시가 "
              "나온다 — 표시가 있다고 병변인 것은 아니다 "
              "(정상 300장 실측).")

# 기권 사유. 새 사유를 늘릴 때 여기에 먼저 적는다 — 응답에 나가는 값이라
# 받는 쪽이 분기하는 문자열이고, 흩어지면 오타를 아무도 못 잡는다.
ABSTAIN_REASONS = {
    "no_detection_above_threshold": "임계값을 넘는 검출이 없다",
    "load_failed": "모델을 적재하지 못했다",
}


# ───────────────────── 근거 이름표 (llm-proxy G-L1) ─────────────────────
# 판독문은 **검사 단위**로 쓰는데 맘모는 검사 1건이 사진 4장이다.
# 사진마다 병변 번호가 1부터 다시 시작하므로 번호만으로 이름표를 만들면
# 한 검사 안에 같은 이름표가 네 개 생긴다.
#
# llm-proxy 는 문장이 인용한 id 가 근거 목록에 있는지만 본다. 네 개 중
# 하나라도 있으면 통과한다 — **통과하면서 틀린다.** 그래서 시야를 박는다.

VIEW_CODES = {("L", "CC"): "LCC", ("L", "MLO"): "LMLO",
              ("R", "CC"): "RCC", ("R", "MLO"): "RMLO"}

# read_mammogram 이 어떤 이름으로 넣는지에 기대지 않는다. 여러 철자를 본다.
_LAT_KEYS = ("laterality", "image_laterality", "ImageLaterality",
             "Laterality", "side")
_VIEW_KEYS = ("view", "view_position", "ViewPosition", "position")


def _pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v).strip().upper()
    return None


def view_code(dmeta):
    """LCC · LMLO · RCC · RMLO 중 하나. 못 정하면 None.

    ⚠ 못 정할 때 아무 값이나 지어내면 안 된다. 파일명으로 때우면 서빙에서
      이름이 안 올 때(<upload>) 네 장이 다시 같은 값이 된다. 모르면 비운다.
    """
    if not isinstance(dmeta, dict):
        return None
    lat = _pick(dmeta, _LAT_KEYS)
    vp = _pick(dmeta, _VIEW_KEYS)
    if lat:
        lat = lat[0]                       # LEFT · RIGHT 도 받는다
    if vp and vp.startswith("MLO"):        # MLO_LEFT 같은 변형
        vp = "MLO"
    return VIEW_CODES.get((lat, vp))


def stamp_evidence(lesions, dmeta, override=None):
    """병변마다 판독문이 가리킬 이름표를 붙인다 — MG-RCC-01.

    번호는 lesion["id"](점수 내림차순 1부터) 를 그대로 쓴다.

    시야를 정하는 순서
        ① DICOM 태그        읽히면 그것이 기준이다
        ② 받는 쪽(override)  태그가 **없을 때만** 쓴다
                             DB 의 storage_object.series_role 이 이 값이다

    ⚠ 둘 다 값이 있는데 다르면 **아무것도 안 붙인다.**
      영상이 뒤바뀐 것이고, 한쪽을 골라 이름표를 붙이면 판독문이 좌우를
      바꿔 쓴다. 사람이 봐야 하는 상태이지 코드가 골라도 되는 상태가 아니다.

    ⚠ 시야를 못 정해도 **좌우는 따로 대조한다.** ViewPosition 이 없는
      영상이 있는데(CBIS 가 그렇다), 그때도 Laterality 는 읽힌다.
      절반만 아는 정보도 틀린 값을 거르는 데는 충분하다.

      좌우 오기가 시야 오기보다 훨씬 위험하다 — LCC 를 LMLO 로 쓰면 같은
      가슴의 다른 각도지만, LCC 를 RCC 로 쓰면 **반대쪽 가슴을 가리킨다.**
    """
    tag = view_code(dmeta)
    lat = _pick(dmeta, _LAT_KEYS) if isinstance(dmeta, dict) else None
    tag_side = lat[0] if lat else None          # L · R. 시야를 몰라도 이건 안다
    vc, why = tag, "no_view_tag"
    if override:
        o = str(override).strip().upper()
        if o not in set(VIEW_CODES.values()):
            vc, why = None, "bad_view_override"
        elif tag is not None and tag != o:
            vc, why = None, f"view_conflict:tag={tag},given={o}"
        elif tag is None and tag_side and o[0] != tag_side:
            # 시야는 못 정했지만 좌우가 다르다. 이것만으로 충분히 거절한다.
            vc, why = None, f"side_conflict:tag={tag_side},given={o[0]}"
        else:
            vc, why = o, None
    for l in lesions:
        if vc:
            l["evidence_id"] = f"MG-{vc}-{int(l['id']):02d}"
            l["evidence_id_omitted_reason"] = None
        else:
            # 사진 안에서만 유일한 번호를 이름표로 쓰면 검사 단위 판독문에서
            # 다른 시야의 병변과 구별되지 않는다. 비워서 내보낸다.
            l["evidence_id"] = None
            l["evidence_id_omitted_reason"] = why
    return lesions


def _dicom_out(dmeta):
    """응답의 dicom 칸. 우리가 태그에서 읽어 정한 시야를 같이 낸다.

    받는 쪽이 storage_object.series_role 과 맞춰 볼 수 있다. 둘이 다르면
    영상이 뒤바뀐 것이고, 그건 판독문이 좌우를 바꿔 쓰는 사고가 된다.
    """
    if not isinstance(dmeta, dict):
        return dmeta
    return dict(dmeta, view_code=view_code(dmeta))


def add_display(lesions, tb, mm, P):
    # 좌표계를 값에 박는다 — box · display.box · crop 은 전부 **원본
    # 화소 기준**이다. 내부 검출 파일은 조직 상자 기준이라 서로 다르고,
    # 문서만으로는 언젠가 갈린다. DB 스키마 v8 의 lesion.detail.frame
    # 이 이 값을 그대로 받는다.
    for _l in lesions:
        _l["frame"] = "original_pixel"

    """화면에 그릴 영역과 크기 표기를 정한다. **종류마다 다르다.**

    미세석회는 크기를 주장하지 않는 고정 표식, 종괴는 검출 상자 그대로다.
    근거는 실측이다 — 석회 상자는 정답의 절반 크기이고 편차가 커서 일률적
    보정이 안 된다. 종괴 상자는 정확하다.

    ⚠ lesions[i]["box"] 는 건드리지 않는다. 서술어 모델이 그 상자로 조각을
      떼어내므로 바꾸면 등급이 달라진다. 표시는 별도 칸으로 낸다.

    infer_mammo.predict 와 predict.py 가 **같은 함수를 부른다.** 두 곳에서
    따로 만들면 화면에 뜨는 것이 서로 달라진다.
    """
    side = None
    if tb is not None:
        w, h = float(tb[2] - tb[0]), float(tb[3] - tb[1])
        if w > 0 and h > 0:
            side = (w * h * float(P.get("marker_frac", 0.5)) / 100.0) ** 0.5

    for l in lesions:
        bw = float(l["box"][2] - l["box"][0])
        bh = float(l["box"][3] - l["box"][1])
        if l.get("kind") == "calcification" and side:
            cx = (l["box"][0] + l["box"][2]) / 2.0
            cy = (l["box"][1] + l["box"][3]) / 2.0
            r = side / 2.0
            l["display"] = {
                "shape": "marker", "claims_extent": False,
                "box": [round(cx - r, 1), round(cy - r, 1),
                        round(cx + r, 1), round(cy + r, 1)]}
            # 크기를 내지 않는다. 절반으로, 그것도 들쭉날쭉 틀리게 말하느니
            # 말하지 않는 것이 맞다.
            #
            # 이름은 DB v10 을 따른다 — lesion.ai_size_* 는 **AI 원본값이고
            # 불변**이다. 판독의가 캘리퍼로 잰 값은 measured_* 로 따로 들어가고
            # 우리는 그쪽을 안 건드린다.
            l["ai_size_px"] = None
            l["ai_size_mm"] = None
            l["ai_size_measurable"] = False
            l["size_omitted_reason"] = "microcalc_extent_unreliable"
            l["aspect_ratio"] = None
        else:
            l["display"] = {
                "shape": "box", "claims_extent": True,
                "box": [round(float(v), 1) for v in l["box"][:4]]}
            l["ai_size_px"] = round(max(bw, bh), 1)
            l["ai_size_mm"] = round(max(bw, bh) * mm, 1) if mm else None
            l["ai_size_measurable"] = mm is not None
            l["size_omitted_reason"] = None
            l["aspect_ratio"] = round(bh / bw, 3) if bw > 0 else None
    return lesions


def abstain_result(reason, name=None):
    """추론을 아예 못 했을 때의 응답. **봉투 모양이 predict() 와 같다.**

    적재 실패처럼 모델이 없어서 판정 자체를 못 하는 경우에 쓴다. 호출하는
    쪽이 이 모양을 손으로 만들면 predict() 와 갈라지므로 여기 하나만 둔다.

    ⚠ 사유의 자세한 내용(예외 문자열)은 담지 않는다. 경로가 섞여 나갈 수
      있어서다. 그건 서버 로그와 /health 에 있다.
    """
    if reason not in ABSTAIN_REASONS:
        raise ValueError(f"모르는 기권 사유: {reason!r} — "
                         f"ABSTAIN_REASONS 에 먼저 등록할 것")
    return {
        "file": name or "<upload>",
        "image": {"width": None, "height": None,
                  "pixel_spacing_mm": None, "tissue_bbox": None},
        "dicom": None,
        "lesions": [],
        "summary": {"n_lesions": 0, "max_birads": None, "biopsy": False,
                    "abstained": True, "abstain_reason": reason},
        "detection": {"tiles": 0, "per_class": {}},
        "model": None,
        "params": None,
        "limitations": LIMITATIONS,
        "elapsed_sec": 0.0,
        "disclaimer": DISCLAIMER,
    }


def _tile_grid(tsub, tile, stride):
    """자른 영상 위 타일 격자와 각 타일의 조직 비율.

    _detect 의 두 겹 반복과 **같은 순서·같은 좌표**여야 한다. 가장자리 타일은
    0 으로 채워 넣으므로 분모를 타일 전체 넓이로 둔다 — 모델이 실제로 보는
    그림이 그것이다.
    """
    H, W = tsub.shape[:2]
    area = float(tile * tile)
    out = []
    for ty in positions(H, tile, stride):
        for tx in positions(W, tile, stride):
            sub = tsub[ty:ty + tile, tx:tx + tile]
            out.append((tx, ty, tx + tile, ty + tile, float(np.sum(sub)) / area))
    return out


def _in_any(box, tiles):
    """상자 중심이 남은 타일 하나에라도 들어가는가."""
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    for tx1, ty1, tx2, ty2, _f in tiles:
        if tx1 <= cx <= tx2 and ty1 <= cy <= ty2:
            return True
    return False


def _depth_map(tsub):
    """유방 경계로부터의 거리. 그 영상의 최댓값으로 나눠 0~1 로 맞춘다.

    영상마다 유방 두께가 다르므로 절대 화소로 비교하면 안 된다.
    """
    d = cv2.distanceTransform(tsub.astype(np.uint8), cv2.DIST_L2, 5)
    m = float(d.max())
    return d / m if m > 0 else d


def _depth_at(depth, box):
    H, W = depth.shape[:2]
    x = int(round((box[0] + box[2]) / 2.0))
    y = int(round((box[1] + box[3]) / 2.0))
    if x < 0 or y < 0 or x >= W or y >= H:
        return 0.0
    return float(depth[y, x])


# ────────────────────────────── 추론 ──────────────────────────────
@torch.no_grad()
def _detect(bundle, arr, P):
    """유방 전체를 타일로 훑는다. 좌표는 원본 기준으로 돌려준다."""
    M, model, dev = bundle["M"], bundle["detector"], bundle["device"]
    u8 = norm8(arr, P["clip"])
    tmask = tissue_mask(u8)
    tb = tissue_bbox(tmask, P["pad"])
    if tb is None:
        return {n: [] for n in PROMPTS}, None, 0, {}
    cx0, cy0, cx1, cy1 = tb
    img = u8[cy0:cy1, cx0:cx1]
    tsub = tmask[cy0:cy1, cx0:cx1] > 0
    H, W = img.shape[:2]
    stride = max(1, P["tile"] - P["overlap"])

    # 후처리에 쓸 것을 여기서 한 번만 만든다. 영상당 한 번이면 된다.
    keep_tiles = None
    if P.get("tile_frac", 0) > 0:
        keep_tiles = [g for g in _tile_grid(tsub, P["tile"], stride)
                      if g[4] >= P["tile_frac"]]
    depth = _depth_map(tsub) if P.get("depth_lambda") else None

    raw = {n: [] for n in PROMPTS}
    n_tiles = 0
    with torch.inference_mode():
        for ty in positions(H, P["tile"], stride):
            for tx in positions(W, P["tile"], stride):
                sub = img[ty:ty + P["tile"], tx:tx + P["tile"]]
                if sub.shape != (P["tile"], P["tile"]):
                    q = np.zeros((P["tile"], P["tile"]), np.uint8)
                    q[:sub.shape[0], :sub.shape[1]] = sub
                    sub = q
                got = read_out(model(make_batch(M, sub, dev)), P["thr"])
                n_tiles += 1
                for n, lst in got.items():
                    for b in lst:
                        raw[n].append((b[0] + tx, b[1] + ty,
                                       b[2] + tx, b[3] + ty, b[4]))

    out, stats = {}, {}
    for n in PROMPTS:
        cand, n_out = filter_tissue(raw[n], tsub, P["tissue_frac"])
        merged = merge_boxes_one(cand, P["merge"], P["nms"])

        # 타일 조직 필터 — 조직이 거의 없는 타일에서 나온 검출을 버린다.
        # 합치기 **뒤**에 건다. 측정을 그 순서로 했다.
        n_thin = 0
        if keep_tiles is not None:
            n_before = len(merged)
            merged = [b for b in merged if _in_any(b, keep_tiles)]
            n_thin = n_before - len(merged)

        # 깊이 가중 — 경계에 붙은 것을 눌러 순위를 바꾼다. 아무것도 안 버린다.
        # 최저 (1-λ)배까지만 곱해 절대 점수를 유지한다 — 영상별 정규화처럼
        # 절대 점수를 버리는 방식은 전부 실패했다.
        lam = float((P.get("depth_lambda") or {}).get(n, 0.0))
        if lam > 0 and depth is not None:
            merged = [(b[0], b[1], b[2], b[3],
                       b[4] * (1.0 - lam + lam * _depth_at(depth, b)))
                      for b in merged]
            merged.sort(key=lambda b: -b[4])   # topk 가 정렬을 전제한다

        cut = P["score_calc"] if n == "calcification" else P["score_mass"]
        kept = [b for b in merged if b[4] >= cut]
        n_low = len(merged) - len(kept)
        if P["topk"]:
            kept = kept[:P["topk"]]
        stats[n] = dict(candidates=len(raw[n]), outside_tissue=n_out,
                        thin_tile=n_thin,
                        below_threshold=n_low, kept=len(kept), threshold=cut)
        out[n] = [(b[0] + cx0, b[1] + cy0, b[2] + cx0, b[3] + cy0, b[4])
                  for b in kept]
    return out, tb, n_tiles, stats


@torch.no_grad()
def _describe(bundle, arr, dets, P):
    """박스마다 조각을 만들어 서술어 · 등급을 낸다."""
    from eval_e2e import (level_of, to_category, to_category_fine,
                          to_onehot)
    R, dev = bundle["rules"], bundle["device"]
    always = set(P["always"])
    lesions = []
    for name in PROMPTS:
        boxes = dets.get(name) or []
        if not boxes:
            continue
        kind = KIND_OF[name]
        D = bundle["desc"][kind]
        meta, cols, slices = D["meta"], D["meta"]["cols"], D["slices"]

        crops, keep = [], []
        for b in boxes:
            e = expand_box(b[:4], 20.0, arr.shape)   # 실측 여백 20px
            if e is None:
                continue
            crops.append(crop_to_tensor(arr[e[1]:e[3], e[0]:e[2]],
                                        meta["size"], meta["pad"], meta["clip"]))
            keep.append((b, e))
        for i in range(0, len(crops), P["batch"]):
            x = torch.stack(crops[i:i + P["batch"]]).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                from train_mammo import pool_feats
                logit = D["head"](pool_feats(D["ext"](x), meta["pool"],
                                             meta["levels"], meta["grid"]))
            probs = torch.sigmoid(logit.float()).cpu().numpy()
            for k, p in enumerate(probs):
                b, e = keep[i + k]
                oh = to_onehot(p, cols, slices, P["thr_desc"], always)
                # 축별 채택값과 그 확률을 같이 낸다 — 명세의 descriptor.confidence
                dd, picks = {}, []
                for ax, (s, en) in slices.items():
                    j = int(np.argmax(p[s:en]))
                    col, pr = cols[s + j], float(p[s + j])
                    picks.append(pr)
                    if oh.get(col):
                        dd[ax] = {"value": col.split("__", 1)[1],
                                  "confidence": round(pr, 4),
                                  "verify": pr < P["conf_low"]}
                lv = level_of(R, kind, oh)
                # 두 벌이 필요하다. 문자열은 화면·DB 로 나가는 값이고,
                # 정수는 조직검사 판정(>= 4)에 쓴다. 문자열로 비교하면
                # "4a" >= 4 가 성립하지 않는다.
                cat = to_category(R, lv)
                cat_s = to_category_fine(R, lv)
                # 우리가 가진 확신도. CORAL 이 없어 gate_flags 를 못 채우는
                # 대신 이것을 낸다. 초음파의 ambiguity 와 같은 뜻은 아니다.
                # 축 개수가 종류마다 다르다 — 석회 2축(최대 1.0) ·
                # 종괴 3축(최대 1.5). 합만 내보내면 받는 쪽이 종류를 섞어
                # 정렬할 때 **석회가 구조적으로 덜 확실해 보인다.**
                # 축 수를 같이 내서 나눌 수 있게 한다.
                cert = float(np.sum(np.abs(np.array(picks) - 0.5)))
                lesions.append(dict(
                    kind=name, box=[round(float(v), 1) for v in b[:4]],
                    score=round(float(b[4]), 4),
                    crop=[int(v) for v in e],
                    descriptors=dd,
                    birads=cat_s,
                    biopsy=bool(cat is not None and cat >= BIOPSY_CUT),
                    certainty=round(cert, 4),
                    certainty_axes=len(picks),
                    confidence="low" if any(v["verify"] for v in dd.values())
                               else "high"))
    lesions.sort(key=lambda x: -x["score"])
    for i, l in enumerate(lesions, 1):
        l["id"] = i
    return lesions


def predict(bundle, image, name=None, **over):
    """
    image 는 경로(DICOM/PNG) 또는 bytes. 반환 dict 의 스키마는 docs 참조.
    name 은 결과에 적을 이름 — bytes 를 넘길 때(서빙) 원본 파일명을 준다.

    over 로 파라미터를 요청 단위로 덮어쓴다 — 임계값을 낮춰 민감도를 올리는
    식의 운영 조정이 재적재 없이 가능하다.
    """
    P = _params(over)
    t0 = time.time()
    arr, mm, dmeta = read_mammogram(image)
    dets, tb, n_tiles, stats = _detect(bundle, arr, P)
    lesions = _describe(bundle, arr, dets, P) if tb is not None else []

    add_display(lesions, tb, mm, P)         # 표시 영역 · 크기 표기
    stamp_evidence(lesions, dmeta, P.get("view_code"))   # 이름표

    from eval_e2e import max_category
    grades = [l["birads"] for l in lesions if l["birads"] is not None]
    summary = dict(
        n_lesions=len(lesions),
        max_birads=max_category(grades),
        biopsy=any(l["biopsy"] for l in lesions),
        # 임계값을 넘는 검출이 없으면 기권이다. '정상' 이 아니다 —
        # 서술어 모델에 '소견 없음' 클래스가 없어서 판정 자체를 못 한다.
        abstained=len(lesions) == 0,
        abstain_reason=None if lesions else "no_detection_above_threshold")

    return {
        "file": name or (Path(image).name
                         if isinstance(image, (str, Path)) else "<upload>"),
        "image": {"width": int(arr.shape[1]), "height": int(arr.shape[0]),
                  "pixel_spacing_mm": mm, "tissue_bbox":
                      [int(v) for v in tb] if tb is not None else None},
        "dicom": _dicom_out(dmeta),
        "lesions": lesions,
        "summary": summary,
        "detection": {"tiles": n_tiles, "per_class": stats},
        "model": {"detector": Path(bundle["paths"]["det"]).name,
                  "calc": Path(bundle["paths"]["calc"]).name,
                  "mass": Path(bundle["paths"]["mass"]).name,
                  "operating_point": bundle["operating_point"]},
        "params": {k: (list(v) if isinstance(v, tuple) else v)
                   for k, v in P.items()},
        "limitations": LIMITATIONS,
        "elapsed_sec": round(time.time() - t0, 2),
        # 받는 쪽이 반드시 화면에 함께 표시해야 하는 것
        "disclaimer": DISCLAIMER,
    }


# ────────────────────────────── CLI ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--det", default=None)
    ap.add_argument("--calc", default=None)
    ap.add_argument("--mass", default=None)
    ap.add_argument("--json", default="")
    ap.add_argument("--score-calc", type=float, default=None)
    ap.add_argument("--score-mass", type=float, default=None)
    ap.add_argument("--tissue-frac", type=float, default=None)
    ap.add_argument("--topk", type=int, default=None)
    ap.add_argument("--view", default=None,
                    help="LCC · LMLO · RCC · RMLO — 태그가 없는 영상용")
    a = ap.parse_args()

    img = str(Path(a.image).expanduser().resolve())
    out = str(Path(a.json).expanduser().resolve()) if a.json else ""

    bundle = load_model(a.det, a.calc, a.mass)
    r = predict(bundle, img, score_calc=a.score_calc, score_mass=a.score_mass,
                tissue_frac=a.tissue_frac, topk=a.topk, view_code=a.view)

    # 결과 저장이 화면 출력보다 먼저다. 아래 표시 코드가 터져도 json 은
    # 남는다 — 표시는 편의고 결과는 산출물이다.
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"  -> {out}")

    print("\n" + "=" * 70)
    print(f"{r['file']}   {r['image']['width']}x{r['image']['height']}"
          + (f"   {r['image']['pixel_spacing_mm']}mm/px"
             if r["image"]["pixel_spacing_mm"] else "   화소 간격 없음"))
    print("=" * 70)
    for n, s in r["detection"]["per_class"].items():
        print(f"  {n:14s} 후보 {s['candidates']:5,} → 조직밖 -{s['outside_tissue']:,}"
              f" · 점수<{s['threshold']:.3f} -{s['below_threshold']:,}"
              f"  → {s['kept']}건")
    for l in r["lesions"]:
        # 미세석회는 ai_size_px 가 None 이다 — 크기를 주장하지 않기로 했다
        # (검출 상자가 정답의 절반). 그대로 포맷하면 터진다.
        if l.get("ai_size_px") is None:
            sz = "크기 미산출"
            if l.get("size_omitted_reason"):
                sz += f" ({l['size_omitted_reason']})"
        else:
            sz = f"{l['ai_size_px']:.0f}px"
            if l.get("ai_size_mm"):
                sz += f" · {l['ai_size_mm']:.1f}mm"
        ev = f"   {l['evidence_id']}" if l.get("evidence_id") else ""
        print(f"\n  [{l['id']}] {l['kind']}   점수 {l['score']:.3f}   {sz}{ev}")
        for ax, d in l["descriptors"].items():
            print(f"      {ax:10s} {d['value']:22s} {d['confidence']:.2f}"
                  + ("  ← 직접 확인" if d["verify"] else ""))
        print(f"      BI-RADS {l['birads']}"
              f"   {'조직검사 권고' if l['biopsy'] else '추적 관찰'}"
              f"   확신도 {l['confidence']}")
    s = r["summary"]
    print("\n" + "-" * 70)
    if s["abstained"]:
        print("  기권 — 임계값을 넘는 검출이 없다")
        print("  ※ '정상' 이 아니다. 서술어 모델에 '소견 없음' 클래스가 없어")
        print("    판정 자체를 하지 못한다는 뜻이다.")
    else:
        print(f"  병변 {s['n_lesions']}건 · 최고 등급 {s['max_birads']} · "
              f"{'조직검사 권고' if s['biopsy'] else '추적 관찰'}")
    print(f"  {r['elapsed_sec']}초")
    print(f"\n  ※ {r['disclaimer']}")



if __name__ == "__main__":
    main()
