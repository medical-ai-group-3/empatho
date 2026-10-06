#!/usr/bin/env python3
"""
MRI 추론 — 볼륨 한 개 → 종양 위치·부피·최대직경·개수·유두거리·사분면
             + 유방 밀도(%)를 **가능하면 한 번에 함께** 반환
             + 3D 시각화 메시(STL/JSON, 유방 셸 또는 병변 덩어리)

서빙용 API와 CLI를 겸한다.

    from infer_mri import load_model, predict, preprocess_raw_to_volume
    bundle = load_model("configs/mri_lora.yaml")     # 프로세스당 한 번
    tumor_volume, density_volume, geometry = preprocess_raw_to_volume(
        pre_path, post_path, return_geometry=True
    )
    result = predict(bundle, tumor_volume, density_volume, geometry=geometry)

CLI
    python3 infer_mri.py --pre-path a_pre.nii.gz --post-path a_post.nii.gz   # 종양+밀도 둘 다
    python3 infer_mri.py --pre-path a_pre.nii.gz                             # 밀도만 (post 없음)

★ 2026-09-04 (1차) 변경 — dataset_tag 폐지, tumor/density 동시 산출, Garage 경로 제거,
  근거id 형식 통일. (파트간 인터페이스 대조, H-3/C-4/H-5)

★ 2026-09-04 (2차) 변경 — Go(file-gateway) 담당의 answer_mri.md 반영 (A-5, C-5)
  1. post_path를 다시 선택 인자로 되돌렸다. 1차 변경 때 필수로 만들었던 게 실수였다 —
     density(유방 밀도)는 원래 pre 단독으로도 나와야 하는데, post를 강제하면
     그 경로 자체가 막힌다(Go 담당 A-5 지적). post_path가 없으면 tumor는 계산하지
     않고 density만 낸다. 응답에 "phases": 1|2를 추가해 받는 쪽이 어느 경로를
     탔는지 알 수 있게 했다.
  2. predict()에서 Go 업로드를 자동으로 하지 않는다. 실제 Go API는 파일 하나당
     1회용 티켓이 필요한 구조라(answer_mri.md Q2·Q5), predict() 내부에서 스스로
     처리할 수 없다 — 티켓은 매 요청 Django가 발급해서 호출자(소켓 래퍼)에게
     내려주는 값이다. predict()는 로컬 저장까지만 하고, 업로드는 호출자가
     derived_io.upload_mesh(gateway_url, ticket, ...)로 별도 수행한다.
  3. derived_io.py의 함수 이름이 upload_mesh_to_go() -> upload_mesh()로 바뀌었다
     (실제 Go API에 맞춰 파일 단위 함수로 재설계, 요청 형식도 multipart가 아니라
     원시 바이트 스트리밍으로 정정됨). import 갱신.

★ 2026-09-06 변경 — 병변별 3D 메시 분리 (병변마다 다른 색으로 렌더링하고 싶다는
  화면 요구 반영). 학습·재추론 불필요, 후처리(마칭큐브 하는 부분)만 변경:
  1. 기존엔 오탐필터 통과한 tumor 마스크 전체를 한 번에 마칭큐브 처리해서
     result["tumor"]["mesh"] 하나로 냈다 — 병변이 여러 개면 메시 안에서 구분이
     안 됐다.
  2. 이제 연결성분(26-connectivity)으로 나눈 뒤 성분별로 따로 마칭큐브를 돌리고,
     각 병변(lesions[])에 자기 메시를 붙인다 — result["tumor"]["mesh"](top-level
     단일 메시)는 없어지고 result["tumor"]["lesions"][i]["mesh"]로 이동했다.
  3. 병변-성분 매칭은 compute_lesion_evidence()가 이미 하던 "centroid 최근접"
     로직을 그대로 재사용한다(_label_lesion_components). 라벨링을 evidence 쪽과
     따로 한 번 더 하지만(중복), 158장 기준 GPU 추론(수십~백여 초)에 비하면
     이 CPU 연산 비용은 무시할 수준이라 굳이 상태를 공유하도록 리팩터링하지 않았다.
  4. breast/dense tissue는 그대로 통짜 메시 하나 — 병변이 아니라 유방 전체
     셸이라 나눌 이유가 없다. 이번 변경 대상 아님.

★ 2026-09-29 변경 — MRI 병변 오탐 검토(백엔드·모델 팀 요청) 1단계. 기본값 기준 검출 결과는 동일.
  1. lesions[i]에 score_max/score_mean 추가 — 병변 성분 안 복셀들의 쿼리 점수 요약
     (infer_slice_mask가 OR로 합치면서 버리던 점수를 return_score_map으로 들고 옴).
     보정 안 된 점수라 표시용. Django Lesion.certainty 칼럼에 연결 가능.
  2. tumor.filter_stats 추가 — 후보 수와 필터별 제거 수(dropped_small / dropped_short_span /
     dropped_flat / dropped_over_cap)와 최종 kept. tumor.truncated는 상한에 잘린 병변 존재 여부.
  3. 상수로 박혀 있던 시트형 필터 기준·병변 상한을 DEFAULTS(flat_min_aspect_ratio,
     flat_min_thin_axis_mm, max_lesions)로 노출 — **over / config inference: 섹션으로 조정 가능.
  4. mask_pixel_threshold가 DEFAULTS에만 있고 실제론 안 쓰이던 문제 수정(infer_slice_mask로 전달).
  5. 평균 점수 낮은 병변 후보 제거(min_lesion_score_mean, 기본 0.6) — ⚠ 이것만은 검출 결과가 바뀐다.
     val 40명 교차검증: 환자당 순수 오탐 3.73 → 2.27, 주 병변 40/40, 병변 민감도 그대로.
     0으로 주면 끔. filter_stats.dropped_low_score에 제거 수.
  6. (2026-10-01) z_gap_fill 옵션 — 필터 전 z축 빈 슬라이스(최대 2*z_gap_fill장) 메우기. 기본 0(끔).
     6차 모델 후보 설정(임계 0.45, z_gap_fill=1, min_lesion_score_mean=0.55)용. 독립 검증 전.

★ 스코프 — benign/malignant lesion은 여전히 제외한다.
   3~4차 학습 결과 F1 0.03~0.35 수준으로 실사용 불가 판단(2026-08-31 확정, 변경 없음).

★ 3D 메시 — build_mesh_from_mask.py를 재추론 없이 재사용한다(2026-09-03 통합, 변경 없음).

★ 폴더 구조
   model_io.py      모델 로딩(load_model, DEFAULTS)
   normalize.py     tumor/density 정규화 로직 (2026-09-04 신규)
   derived_io.py    Go 파생물 게이트웨이 연동 + 로컬 저장 폴백 (구 garage_io.py)
   이 파일           predict() 조립 로직 + CLI

★ 2026-09-04 (3차) 변경 — 파트별_수정목록_20260904.md 반영 (팀 회의 결과, 결정 완료분)
  1. compute_lesion_evidence()의 id를 0-base(MR-00~)에서 1-base(MR-01~)로 수정 —
     US-01/MG-01/PA-01과 시작 숫자까지 맞춰야 한다는 지적 반영.
  2. check_series_geometry()는 최종적으로 "호출 불가능한 코드"로 결론남 — 앱 서버가
     series_meta를 주지 않아 부를 재료가 없다. 시리즈 기하 차단은 Django가 전담하며,
     차단된 시리즈는 MRI에 아예 안 넘어온다(플래그만 붙여 넘기지 않음). 함수는
     derived_io.py에 남아있지만 지금은 아무 효과가 없다 — 삭제하지 않은 이유는
     derived_io.py 주석 참조.
  3. Garage 관련 코드(다운로드 계열) 전부 제거 확인 완료 —
     preprocess_from_garage/fetch_series_from_garage/_garage_readonly_client/
     CLI --pre-keys·--post-keys, 이번 파일에는 애초에 남아있지 않았음.

★ 아직 확정 안 된 것 — 코드가 아니라 사람이 답해야 하는 부분
   - 갑안(응답에 메시를 실어 Django/Celery가 대신 올림) vs 을안(MRI가 Go를 직접
     호출) 미정 — STL 실제 크기(A-1) 확인 후 결정. 갑안이면 derived_io.py의
     upload_mesh() 관련 부분은 통째로 삭제 대상.
   - 판독 실측(적재·추론, include_mesh 켠/끈 값 따로) — GPU 대기, H-4.
   - FastAPI 쪽(sockets/mri.py) dataset_tag 제거 순서 — "인자를 받되 무시하는 판"을
     먼저 거쳐야 배포 순서 사고가 안 난다는 지침이 있으나, 그 파일 자체를 아직
     받은 적이 없어 이 저장소에서는 조치 대상이 아님. 담당자에게 전달만 하면 됨.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import SimpleITK as sitk
from scipy import ndimage

# ── mri/ 폴더 구조 기준 경로 ──
MRI_ROOT = Path(__file__).resolve().parents[2]          # mri/
POSTPROCESS_3D_CODE = MRI_ROOT / "postprocess_3d" / "code"
TRAINING_PREPROCESS = MRI_ROOT / "training" / "code" / "preprocess"

for _p in (POSTPROCESS_3D_CODE, TRAINING_PREPROCESS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# postprocess_3d/code에서 검증 완료한 로직을 그대로 가져다 쓴다(복붙 금지 원칙).
# ⚠ volume_to_rgb_slices(volume, "mamamia"|"duke")는 dataset_tag 이름을 그대로 재사용한다 —
#   여기서는 "환자 데이터셋 구분"이 아니라 "2-phase RGB냐 1-phase RGB냐"를 고르는
#   내부 스위치로만 쓴다. build_3d_from_predictions_v9.py 자체는 안 고쳤다.
from build_3d_from_predictions_v9 import (  # noqa: E402
    volume_to_rgb_slices,
    rgb_array_to_tensor,
    infer_slice_mask,
    filter_false_positives,
    filter_flat_artifacts,
)
from build_mesh_from_mask import mask_to_mesh  # noqa: E402
from skimage.measure import block_reduce  # noqa: E402
from compute_stage1_metrics import (  # noqa: E402
    summarize_lesions,
    find_body_silhouette_mask,
)

# preprocess_mamamia.py의 리샘플링 로직만 재사용(복붙 금지 원칙).
# 정규화는 더 이상 하나로 통일하지 않는다 - tumor/density가 서로 다른 통계를
# 쓰므로 normalize.py로 분리했다(2026-09-04, H-3).
from preprocess_mamamia import resample_to_isotropic  # noqa: E402
from normalize import zscore_two_phases, zscore_pre_only  # noqa: E402

# ── 2026-09-03 분리, 2026-09-04 garage_io.py -> derived_io.py 개명·재작성 ──
from model_io import load_model, DEFAULTS  # noqa: E402,F401
from derived_io import (  # noqa: E402
    check_series_geometry,  # noqa: F401  (2026-09-04 최종 결론: 호출 불가능한 죽은 코드.
    # 앱 서버가 series_meta를 안 줘서 부를 재료가 없음. 시리즈 기하 차단은 Django 전담.
    # 여기 import된 채로 남겨두는 것도 사실 의미 없음 - derived_io.py 주석 참조)
    save_mesh_files,
)


# ────────────────────────────── 실시간 전처리 (원본 -> tumor/density 볼륨) ──────────────────────────────
def preprocess_raw_to_volume(pre_path, post_path=None, return_geometry=False):
    """원본 pre(필수)/post(선택) 파일(nii.gz 또는 단일 시리즈 dcm 폴더) ->
    density용 1-phase 볼륨(항상) + tumor용 2-phase 볼륨(post 있을 때만).

    ⚠ 2026-09-04 재수정(A-5) — post_path를 다시 선택 인자로 되돌렸다. density
    (유방 밀도)는 원래 pre 단독으로도 나와야 하는데, 직전 버전에서 post를 필수로
    만들어 이 경로를 막았던 게 실수였다(Go 담당 지적).

    tumor_volume: post_path가 있을 때만 (2,Z,Y,X) — zscore_two_phases(pre+post
        합산 통계)로 정규화. post_path가 없으면 None.
    density_volume: 항상 (1,Z,Y,X) — zscore_pre_only(pre 단독 통계)로 정규화.
    같은 pre_img에서 나온 값이지만 정규화 자체는 서로 다르다 — 섞어 쓰지 말 것.

    return_geometry=True면 (tumor_volume, density_volume, geometry) 튜플을 반환한다.
    geometry는 {"resampled_img": <리샘플링된 sitk.Image>, "original_img": <원본 sitk.Image>}
    — evidence 박스를 원본 좌표계로 변환할 때 필요.
    """
    def _read(p):
        p = Path(p)
        if p.is_dir():  # DICOM 시리즈 폴더
            reader = sitk.ImageSeriesReader()
            names = reader.GetGDCMSeriesFileNames(str(p))
            reader.SetFileNames(names)
            return reader.Execute()
        return sitk.ReadImage(str(p))  # nii/nii.gz 단일 파일

    pre_img_orig = _read(pre_path)
    pre_img = resample_to_isotropic(pre_img_orig, is_label=False)
    pre_arr = sitk.GetArrayFromImage(pre_img).astype(np.float32)

    pre_density = zscore_pre_only(pre_arr)                  # density 전용 정규화 (post 관여 없음)
    density_volume = pre_density[None].astype(np.float32)   # (1,Z,Y,X)

    tumor_volume = None
    if post_path is not None:
        post_img_orig = _read(post_path)
        post_img = resample_to_isotropic(post_img_orig, is_label=False)
        post_arr = sitk.GetArrayFromImage(post_img).astype(np.float32)
        pre_tumor, post_tumor = zscore_two_phases(pre_arr, post_arr)   # tumor 전용 정규화
        tumor_volume = np.stack([pre_tumor, post_tumor], axis=0).astype(np.float32)  # (2,Z,Y,X)

    if return_geometry:
        return tumor_volume, density_volume, {"resampled_img": pre_img, "original_img": pre_img_orig}
    return tumor_volume, density_volume


# ────────────────────────────── 리포트 근거(evidence) ──────────────────────────────
def compute_lesion_evidence(mask_3d, lesions, id_prefix="MR"):
    """3D 마스크 + summarize_lesions() 결과(lesions, centroid_z/y/x 포함) ->
    리포트 서버(G-L1, POST /svc/v1/llm/report-narrative)에 보낼 evidence 리스트.

    id 형식은 다른 모달리티(US-01/MG-01/PA-01)와 맞춰 "MR-01"부터 시작(H-5, 파트별_수정목록
    §MRI-3에서 0-base였던 최초 구현이 다시 지적됨 — 1부터 시작하는 걸로 최종 확정).

    검모 님 확인 완료(2026-09-03, 변경 없음):
      ① "image" 필드 — Go가 해석하지 않고 그대로 통과시킨다.
      ② box 순서 — [x1,y1,x2,y2] 확정. x=열, y=행, 원점 좌상단.
    """
    if mask_3d.sum() == 0 or not lesions:
        return []

    structure = np.ones((3, 3, 3), dtype=int)
    labeled, n_components = ndimage.label(mask_3d, structure=structure)
    if n_components == 0:
        return []

    evidence = []
    for lesion in lesions:
        cz, cy, cx = lesion.get("centroid_z"), lesion.get("centroid_y"), lesion.get("centroid_x")
        if cz is None or cy is None or cx is None:
            continue

        best_id, best_dist = None, None
        for comp_id in range(1, n_components + 1):
            coords = np.argwhere(labeled == comp_id)
            centroid = coords.mean(axis=0)
            dist = float(np.sqrt((centroid[0]-cz)**2 + (centroid[1]-cy)**2 + (centroid[2]-cx)**2))
            if best_dist is None or dist < best_dist:
                best_id, best_dist = comp_id, dist
        if best_id is None:
            continue

        comp_mask = (labeled == best_id)
        per_slice_count = comp_mask.sum(axis=(1, 2))
        rep_slice = int(np.argmax(per_slice_count))
        ys, xs = np.where(comp_mask[rep_slice])
        if ys.size == 0:
            continue

        lesion_idx = lesion.get("lesion_index", best_id - 1)  # find_instances()가 0부터 세므로 -1 보정
        evidence.append({
            "id": f"{id_prefix}-{int(lesion_idx) + 1:02d}",  # ⚠ 2026-09-04 재수정 — US-01/MG-01/PA-01과
            # 맞춰 1부터 시작해야 함(파트별_수정목록 §MRI-3). lesion_index 자체(0-base)는 그대로 두고
            # 여기 표시할 때만 +1 한다 — lesions[] 배열의 lesion_index 필드는 내부 카운터라 안 건드림.
            "kind": "lesion",
            "image": {"slice_index": rep_slice, "orientation": "axial"},
            "box": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
            "pixel_spacing_mm": 1.0,
            "frame": "resampled_1mm",
        })

    return evidence


def _label_lesion_components(mask_3d, lesions):
    """3D 마스크를 연결성분(26-connectivity)으로 나누고, 각 lesion을 centroid가
    제일 가까운 성분에 매칭한다 — compute_lesion_evidence()가 쓰던 것과 동일한
    "최근접 centroid" 방식. 병변별 메시(2026-09-06 신규)와 evidence 생성이 이
    매칭 로직을 각자 독립적으로 수행한다(라벨링을 두 번 하지만 비용 무시 가능).

    반환: {lesion_index: component_mask(bool 3D ndarray)}
    centroid가 없는 lesion(위치 계산 실패)은 결과에서 빠진다 — 그 lesion의
    mesh는 predict()에서 None으로 처리됨.
    """
    if mask_3d.sum() == 0 or not lesions:
        return {}

    structure = np.ones((3, 3, 3), dtype=int)
    labeled, n_components = ndimage.label(mask_3d, structure=structure)
    if n_components == 0:
        return {}

    comp_centroids = {}
    for comp_id in range(1, n_components + 1):
        coords = np.argwhere(labeled == comp_id)
        comp_centroids[comp_id] = coords.mean(axis=0)

    matched = {}
    for lesion in lesions:
        cz, cy, cx = lesion.get("centroid_z"), lesion.get("centroid_y"), lesion.get("centroid_x")
        if cz is None or cy is None or cx is None:
            continue
        best_id, best_dist = None, None
        for comp_id, centroid in comp_centroids.items():
            dist = float(np.sqrt((centroid[0]-cz)**2 + (centroid[1]-cy)**2 + (centroid[2]-cx)**2))
            if best_dist is None or dist < best_dist:
                best_id, best_dist = comp_id, dist
        if best_id is not None:
            matched[lesion.get("lesion_index")] = (labeled == best_id)

    return matched


def _resampled_index_to_original(resampled_img, original_img, x_r, y_r, z_r):
    physical = resampled_img.TransformIndexToPhysicalPoint((int(x_r), int(y_r), int(z_r)))
    return original_img.TransformPhysicalPointToIndex(physical)


def transform_evidence_to_original(evidence, resampled_img, original_img):
    """compute_lesion_evidence()가 리샘플링 볼륨 좌표계로 낸 evidence를 원본 DICOM
    픽셀 좌표계로 바꾼다(변경 없음, 2026-09-03 검모 님 협의 그대로)."""
    sx, sy, sz = original_img.GetSpacing()
    if abs(sx - sy) > 1e-3:
        print(f"  ⚠ 원본 픽셀이 비정방(x={sx:.4f}mm, y={sy:.4f}mm) - pixel_spacing_mm은 x값 사용")

    out = []
    for e in evidence:
        x1, y1, x2, y2 = e["box"]
        z_r = e["image"]["slice_index"]
        corners = [(x1, y1), (x1, y2), (x2, y1), (x2, y2)]
        orig_pts = [_resampled_index_to_original(resampled_img, original_img, cx, cy, z_r)
                    for cx, cy in corners]
        xs_o = [p[0] for p in orig_pts]
        ys_o = [p[1] for p in orig_pts]
        zs_o = [p[2] for p in orig_pts]

        e2 = dict(e)
        e2["box"] = [int(min(xs_o)), int(min(ys_o)), int(max(xs_o)), int(max(ys_o))]
        e2["image"] = {**e["image"], "slice_index": int(round(sum(zs_o) / len(zs_o)))}
        e2["pixel_spacing_mm"] = round(float(sx), 4)
        e2["frame"] = "pixel"
        out.append(e2)
    return out


# ⚠ 2026-09-?? 신규 — mesh 정점을 evidence와 같은 원본 좌표계로 옮긴다.
# 문제: _build_mesh_entry()가 mask_to_mesh()로 만든 정점을 geometry 변환 없이 그대로
# 내보내고 있었다 - evidence.box는 원본 DICOM 픽셀 좌표인데, mesh는 리샘플링된
# 1mm 로컬 좌표 그대로라 같은 응답 안에서 두 좌표계가 섞여 있었다(프론트가 2D
# evidence 오버레이랑 3D mesh를 같이 그리면 어긋남).
#
# mask_to_mesh()가 낸 verts는 mask_3d(shape=(Z,Y,X))와 같은 축 순서, 즉 각 행이
# (z_r, y_r, x_r) - marching_cubes가 입력 배열 축 순서를 그대로 보존하기 때문이다.
# SimpleITK의 TransformContinuousIndexToPhysicalPoint는 (x,y,z) 순서를 요구하므로
# 넣고 뺄 때만 축을 바꿔주고, 반환값은 기존 verts와 같은 (z,y,x) 축 순서로 되돌린다
# - 이 함수를 쓰는 다른 코드(save_web_json 등)가 축 순서 가정을 깨지 않게 하기 위함.
#
# _resampled_index_to_original()과 달리 정수 인덱스가 아니라 마칭큐브가 낸 연속(sub-voxel)
# 좌표이므로 TransformContinuousIndexToPhysicalPoint / PhysicalPointToContinuousIndex를 쓴다
# (정수용 TransformIndexToPhysicalPoint를 쓰면 정점이 격자에 반올림되어 메시가 계단져 보인다).
def _resampled_verts_to_original(verts, resampled_img, original_img):
    """마칭큐브 정점(리샘플링 1mm 로컬 좌표, (z,y,x) 순서) -> 원본 DICOM 인덱스 좌표(같은 축 순서).
    verts: (N,3) ndarray. 반환도 (N,3) ndarray, 같은 (z,y,x) 축 순서."""
    out = np.empty_like(verts, dtype=np.float64)
    for i in range(verts.shape[0]):
        z_r, y_r, x_r = verts[i]
        physical = resampled_img.TransformContinuousIndexToPhysicalPoint(
            (float(x_r), float(y_r), float(z_r))
        )
        x_o, y_o, z_o = original_img.TransformPhysicalPointToContinuousIndex(physical)
        out[i] = (z_o, y_o, x_o)
    return out


def _gap_fill_z(mask_3d, radius):
    """2026-10-01 신규 — z축(슬라이스 방향)으로만 closing해서 최대 2*radius장 빈 슬라이스를 메운다.
    6차 모델(tumor 음성 슬라이스 학습)이 큰 병변을 z로 끊어 예측 → 조각마다 납작해 시트형 필터가
    주 병변을 지운 사례(ISPY2_883886, 정답 33x38x35mm인데 z 2/8/4장 조각 3개)에 대한 대응.
    원래 마스크와 OR — closing이 기존 복셀을 지우는 일은 없게. radius<=0이면 그대로."""
    if radius <= 0 or mask_3d.sum() == 0:
        return mask_3d
    closed = ndimage.binary_closing(mask_3d.astype(bool), structure=np.ones((2 * radius + 1, 1, 1), bool))
    return (closed | mask_3d.astype(bool)).astype(mask_3d.dtype)


def _filter_low_score_components(mask_3d, score_3d, min_score_mean, score_voxels=None):
    """2026-09-29 신규 — 병변 후보(26-연결 성분)의 평균 쿼리 점수가 min_score_mean 미만이면 제거.
    val 40명 3D 분석(postprocess_3d/code/analyze_component_rules.py, 환자 5-fold 교차검증)에서
    0.6이 5개 fold 모두 같은 값으로 선택됨: 환자당 순수 오탐 3.73 → 2.27, 주 병변 40/40 유지,
    병변 민감도 0.706 그대로. ⚠ 3차 모델 점수 분포 기준 값 — 모델을 바꾸면 다시 맞출 것.
    min_score_mean <= 0이면 아무것도 안 한다. 반환: (mask, 제거 개수).
    score_voxels(2026-10-01): 평균에 넣을 복셀(bool). gap-fill로 채운 복셀은 점수가 낮거나 0이라
    평균을 끌어내리므로 원래 예측 복셀만 쓴다. None이면 성분 전체(gap-fill 없을 땐 결과 동일)."""
    if min_score_mean <= 0 or mask_3d.sum() == 0:
        return mask_3d, 0
    labeled, n = ndimage.label(mask_3d, structure=np.ones((3, 3, 3), dtype=int))
    if n == 0:
        return mask_3d, 0
    ids = np.arange(1, n + 1)
    if score_voxels is None:
        means = ndimage.mean(score_3d.astype(np.float32), labeled, ids)
    else:
        w = score_voxels.astype(bool)
        means = ndimage.sum(score_3d.astype(np.float32) * w, labeled, ids) / \
            np.maximum(ndimage.sum(w, labeled, ids), 1)
    keep_ids = ids[means >= min_score_mean]
    out = np.isin(labeled, keep_ids).astype(mask_3d.dtype)
    return out, int(n - keep_ids.size)


def _downsample_mask(mask_3d, factor):
    """3D 마스크를 factor배 축소(3축 동일, max-pool 방식 — 얇은 부위가 사라지는 걸
    평균보다 덜 심하게 막아준다). 크기가 factor로 안 나눠떨어지면 block_reduce가
    자동으로 0-패딩 후 처리한다.

    ⚠ 2026-09-?? 신규 — body_silhouette mesh가 vertex 329만개로 나와(오늘 DUKE_001
    실측) 브라우저 3D 뷰어에서 못 버틸 수준이라 추가. voxel_spacing을 factor만큼
    키워서 mask_to_mesh를 돌리면, 출력 좌표는 그대로 "원본 1mm 스케일"로 나오므로
    _resampled_verts_to_original() 등 이후 좌표 변환 로직은 손댈 필요 없다."""
    if factor <= 1:
        return mask_3d
    return block_reduce(mask_3d, block_size=(factor, factor, factor), func=np.max, cval=0).astype(mask_3d.dtype)


# ────────────────────────────── 추론 ──────────────────────────────
@torch.no_grad()
def predict(bundle, tumor_volume, density_volume, patient_id="unknown",
            include_mesh=True, mesh_out_dir=None, geometry=None, **over):
    """tumor_volume: (2,Z,Y,X) 또는 None — None이면 종양 계산을 건너뛴다(post 없는 경우).
    density_volume: (1,Z,Y,X) — 항상 필수, 밀도는 언제나 계산한다.

    ⚠ 2026-09-04 재수정(A-5) — tumor_volume이 optional이 됐다. 응답에 "phases"
    필드(1 또는 2)를 넣어 어느 경로로 처리됐는지 받는 쪽이 알 수 있게 한다.

    ⚠ 2026-09-04 재수정(C-5) — 메시를 Go로 자동 업로드하지 않는다. mesh_out_dir을
    주면 로컬(STL/JSON)까지만 저장하고, 실제 Go 업로드는 호출자가 별도로
    derived_io.upload_mesh(gateway_url, ticket, file_bytes, filename)을 불러야
    한다 — 티켓은 매 요청 Django가 발급하는 1회용 값이라 predict()가 스스로
    구할 수 없다.

    include_mesh: True면 오탐필터까지 끝난 마스크로 3D 메시(STL/JSON)까지 생성한다.
    mesh_out_dir: 지정하면 메시를 이 폴더에 STL/JSON으로 저장하고 result에 경로를 담는다.
        생략하면 정점·삼각형 배열만 result에 담아 반환한다.
    geometry: preprocess_raw_to_volume(..., return_geometry=True)가 반환한 세 번째 값.
        넘기면 evidence 박스를 원본 DICOM 좌표계로 자동 변환한다.

    반환 dict는 JSON으로 바로 직렬화 가능(numpy 없음).
    ⚠ benign/malignant lesion은 스코프 제외 - 이 함수는 절대 그 결과를 내지 않는다.
    """
    if tumor_volume is None and density_volume is None:
        raise ValueError("tumor_volume, density_volume 둘 다 None입니다 - 최소 pre(density)는 있어야 합니다.")

    P = dict(bundle["params"]); P.update({k: v for k, v in over.items() if v is not None})
    M, model, dev, R = bundle["M"], bundle["model"], bundle["device"], bundle["resolution"]

    n_slices = density_volume.shape[1]
    if tumor_volume is not None and tumor_volume.shape[1] != n_slices:
        raise ValueError(
            f"tumor_volume과 density_volume의 슬라이스 수가 다릅니다 "
            f"({tumor_volume.shape[1]} vs {n_slices}) — 같은 원본에서 나온 값이어야 합니다."
        )

    density_rgb_slices = volume_to_rgb_slices(density_volume, "duke")

    thresholds = {
        "breast": P["breast_score_threshold"],
        "dense tissue": P["dense_tissue_score_threshold"],
    }
    volumes = {"breast": [], "dense tissue": []}
    for rgb in density_rgb_slices:
        image_tensor, orig_size = rgb_array_to_tensor(rgb, R)
        for cname in ("breast", "dense tissue"):
            mask_2d = infer_slice_mask(model, M, image_tensor, R, orig_size, cname, dev, thresholds[cname],
                                       mask_pixel_threshold=P["mask_pixel_threshold"])
            volumes[cname].append(mask_2d)
    volumes = {c: np.stack(s, axis=0).astype(np.uint8) for c, s in volumes.items()}

    result = {
        "patient_id": patient_id,
        "n_slices": n_slices,
        "phases": 2 if tumor_volume is not None else 1,
        "params": {k: P[k] for k in DEFAULTS},
    }

    def _build_mesh_entry(mask_3d, class_name, downsample=1):
        if not include_mesh or mask_3d.sum() == 0:
            return None
        mesh_mask = _downsample_mask(mask_3d, downsample)
        if mesh_mask.sum() == 0:  # 다운샘플하다가 얇은 구조가 통째로 사라진 경우
            print(f"  ⚠ {class_name}: downsample={downsample} 적용 후 마스크가 비어 mesh 생략")
            return None
        mesh = mask_to_mesh(mesh_mask, voxel_spacing=(float(downsample),) * 3, smooth_iters=P["mesh_smooth_iters"])
        if mesh is None:
            return None
        verts, faces, _normals = mesh

        # evidence와 같은 좌표계로 맞춘다. geometry가 없으면(예: geometry=None으로 호출된
        # 옛 경로) 변환 없이 리샘플링 로컬 좌표 그대로 내보내되, frame을 명시해 구분한다.
        if geometry is not None:
            verts = _resampled_verts_to_original(verts, geometry["resampled_img"], geometry["original_img"])
            frame = "pixel"  # evidence.box와 동일 규약 — 원본 DICOM 인덱스 좌표
        else:
            frame = "resampled_1mm"

        meta = {
            "patient_id": patient_id, "class_name": class_name,
            "smooth_iters": P["mesh_smooth_iters"], "frame": frame,
        }
        if mesh_out_dir is not None:
            paths = save_mesh_files((verts, faces, _normals), mesh_out_dir, patient_id, class_name, meta)
            return {"vertex_count": int(verts.shape[0]), "triangle_count": int(faces.shape[0]),
                    "frame": frame, **paths}
        return {
            "vertex_count": int(verts.shape[0]),
            "triangle_count": int(faces.shape[0]),
            "positions": verts.flatten().round(3).tolist(),
            "indices": faces.flatten().tolist(),
            "frame": frame,
        }

    # ---- tumor (post 있을 때만) ----
    if tumor_volume is not None:
        tumor_rgb_slices = volume_to_rgb_slices(tumor_volume, "mamamia")
        tumor_mask_slices = []
        tumor_score_slices = []  # 2026-09-29 — 병변별 점수 요약용(픽셀별 최대 쿼리 점수)
        for rgb in tumor_rgb_slices:
            image_tensor, orig_size = rgb_array_to_tensor(rgb, R)
            mask_2d, score_2d = infer_slice_mask(model, M, image_tensor, R, orig_size, "tumor", dev,
                                                 P["tumor_score_threshold"],
                                                 mask_pixel_threshold=P["mask_pixel_threshold"],
                                                 return_score_map=True)
            tumor_mask_slices.append(mask_2d)
            tumor_score_slices.append(score_2d.astype(np.float16))  # 메모리 절반(표시용이라 정밀도 충분)
        tumor_mask = np.stack(tumor_mask_slices, axis=0).astype(np.uint8)
        tumor_score = np.stack(tumor_score_slices, axis=0)

        # 2026-09-29 — 각 필터가 몇 개를 지웠는지 응답(filter_stats)에 싣는다. 기존엔 print로만 남았다.
        # 2026-10-01 — z축 빈틈 메우기(기본 0=끔). 크기·연속성·시트형 필터 전에 해야 끊긴 조각이
        # 하나로 합쳐져 판정된다.
        gap_filled = _gap_fill_z(tumor_mask, P["z_gap_fill"])
        filtered_tumor, fp_stats = filter_false_positives(
            gap_filled, min_voxels=P["min_voxels"], min_contiguous_slices=P["min_contiguous_slices"],
            return_stats=True,
        )
        filtered_tumor, flat_stats = filter_flat_artifacts(
            filtered_tumor, min_aspect_ratio=P["flat_min_aspect_ratio"],
            min_thin_axis_mm=P["flat_min_thin_axis_mm"], return_stats=True,
        )
        # 2026-09-29 — 평균 점수 낮은 후보 제거(상한 적용 전). 분석 땐 상한 뒤에 적용했지만,
        # 상한(10개)에 걸리는 환자가 드물어(상한 해제 시 오탐 +0.1/환자) 차이는 미미하고,
        # 상한 전에 거르는 쪽이 저점수 후보가 상한 자리를 차지하지 않아 더 합리적이다.
        filtered_tumor, n_low_score = _filter_low_score_components(
            filtered_tumor, tumor_score, P["min_lesion_score_mean"], score_voxels=tumor_mask
        )
        body_mask = find_body_silhouette_mask(tumor_volume[0])
        rows, n, cap_stats = summarize_lesions(filtered_tumor, patient_id, "tumor", breast_mask=body_mask,
                                               max_lesions=P["max_lesions"], return_stats=True)
        filter_stats = {**fp_stats, **flat_stats, "dropped_low_score": n_low_score, **cap_stats, "kept": n}

        # ⚠ 2026-09-?? 신규 — breast_mesh(SAM3 "breast" 쿼리) 대신 쓸 안정적인 대안.
        # 오늘 실측(DUKE_001)에서 breast 연결성분 8개로 조각남 재현 확인됨 - 예전
        # build_3d_from_predictions_v9.py가 MAMA-MIA 소스에서 겪었던 문제 그대로 서빙에도
        # 있었다. body_mask(명암 기반 몸통윤곽)는 이미 위에서 quadrant/nipple_distance
        # 계산에 쓰고 있고 안정적이라고 확인된 방법이니(location_note 참고), 같은 마스크를
        # mesh로도 만들어서 breast_mesh 문제가 해결되기 전까지 프론트가 대신 쓸 수 있게 한다.
        # 주의: 유방 윤곽이 아니라 몸통 전체 기준이라 팔·목 등이 같이 잡힐 수 있음 - 임시 대안이지
        # breast_mesh를 대체하는 정식 해결책은 아니다.
        body_mesh = None
        if body_mask is not None:
            body_mesh = _build_mesh_entry(body_mask.astype(np.uint8), "body_silhouette", downsample=4)

        evidence = compute_lesion_evidence(filtered_tumor, rows, id_prefix="MR")
        if geometry is not None and evidence:
            evidence = transform_evidence_to_original(
                evidence, geometry["resampled_img"], geometry["original_img"]
            )

        # 2026-09-06 — 병변별 메시. 성분(연결성분) 단위로 따로 마칭큐브를 돌려서
        # 프론트가 병변마다 다른 색으로 렌더링할 수 있게 한다. 매칭 실패(centroid
        # 없는 병변)면 그 병변만 mesh=None — 위치 정보가 애초에 null인 것과 같은 사유.
        lesion_component_masks = _label_lesion_components(filtered_tumor, rows)
        lesions_out = []
        for r in rows:
            lesion_entry = {k: v for k, v in r.items() if k not in ("patient_id", "class")}
            comp_mask = lesion_component_masks.get(r.get("lesion_index"))
            if comp_mask is not None:
                idx1 = int(r.get("lesion_index", 0)) + 1  # 파일명·표시용 1-base (evidence.id와 동일 규칙)
                lesion_entry["mesh"] = _build_mesh_entry(comp_mask, f"tumor_lesion{idx1:02d}")
                # 2026-09-29 — 병변 성분 안 복셀들의 쿼리 점수 요약. ⚠ 보정 안 된 모델 점수라
                # 확률이 아니다 — 화면의 "확신도 낮음" 표시용이지, 검증 전엔 필터 기준으로 쓰지 말 것.
                comp_scores = tumor_score[comp_mask].astype(np.float32)
                lesion_entry["score_max"] = round(float(comp_scores.max()), 3)
                lesion_entry["score_mean"] = round(float(comp_scores.mean()), 3)
            else:
                lesion_entry["mesh"] = None
                lesion_entry["score_max"] = None
                lesion_entry["score_mean"] = None
            lesions_out.append(lesion_entry)

        result["tumor"] = {
            "lesion_count": n,
            "lesions": lesions_out,
            "location_note": (
                "유두거리/사분면은 명암 기반 몸통 윤곽 근사치. "
                "축 방향(상/하/좌/우) 실측 검증 완료(2026-08-31), 좌표계 신뢰 가능. "
                "단 '유방 윤곽'이 아니라 '몸통 전체' 기준이라 팔·목 등이 섞일 수 있음. "
                f"부피 큰 순으로 최대 {P['max_lesions']}개까지만 반환됨(max_lesions)."
            ),
            "body_mesh": body_mesh,  # breast_mesh 조각남 문제의 임시 대안 - 위 주석 참고
            "evidence": evidence,
            # 2026-09-29 — QA/안내 문구용 메타. 기준값 자체는 result["params"]에 있다.
            "filter_stats": filter_stats,
            "truncated": cap_stats["dropped_over_cap"] > 0,  # True면 상한에 걸려 잘린 병변이 있음
        }
        # ⚠ 2026-09-06 변경 — top-level "mesh"(병변 전체 합친 단일 메시) 필드는
        # 없어졌다. 각 lesions[i].mesh로 대체됨(위 참조).
    else:
        result["tumor"] = None  # post 없어서 계산 안 함 - dataset_tag 없이도 이 상태로 구분 가능

    # ---- density (항상) ----
    breast_vox = int(volumes["breast"].sum())
    dense_vox = int(volumes["dense tissue"].sum())

    # ⚠ 2026-09-?? 신규 — breast mask 조각남 진단. build_3d_from_predictions_v9.py가
    # MAMA-MIA 소스에서 breast 모델이 22조각으로 쪼개지는 걸 발견하고 몸통윤곽 방식으로
    # 대체했던 바로 그 문제(오프라인 스크립트 주석 참조) - 서빙 경로(원본 실시간
    # 리샘플링)에서도 같은 문제가 재현되는지 아직 실측 전이라, 3D 뷰어까지 안 기다리고
    # 콘솔/응답 JSON에서 바로 숫자로 확인할 수 있게 추가. 조각이 여러 개면(특히 2개 초과 -
    # 좌우 유방이면 정상적으로 2개) breast_mesh가 프론트에서 깨져 보일 가능성이 높다는 신호.
    if breast_vox > 0:
        _structure = np.ones((3, 3, 3), dtype=int)
        _, _n_breast_components = ndimage.label(volumes["breast"], structure=_structure)
        print(f"  [breast 진단] 연결성분 {_n_breast_components}개 "
              f"(정상이면 좌우 2개 근처 - 3개 이상이면 조각남 의심, 3D mesh 확인 전에 먼저 체크)")
    else:
        _n_breast_components = 0
    result["density"] = {
        "breast_voxels": breast_vox,
        "dense_voxels": dense_vox,
        "dense_density_pct": round(dense_vox / breast_vox * 100, 2) if breast_vox > 0 else None,
        "breast_components": _n_breast_components,  # 진단용 - 3개 이상이면 조각남 의심
        "breast_mesh": _build_mesh_entry(volumes["breast"], "breast"),
        "dense_tissue_mesh": _build_mesh_entry(volumes["dense tissue"], "dense_tissue"),
    }

    return result


# ────────────────────────────── CLI ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(MRI_ROOT / "serving" / "configs" / "mri_lora.yaml"))
    ap.add_argument("--weights", default=None)
    ap.add_argument("--pre-path", required=True, help="원본 pre-contrast (nii.gz 또는 DICOM 폴더) - 필수")
    ap.add_argument("--post-path", default=None,
                     help="원본 post-contrast (nii.gz 또는 DICOM 폴더) - 선택. 없으면 밀도만 계산")
    ap.add_argument("--patient-id", default="unknown")
    ap.add_argument("--out", default=str(MRI_ROOT / "serving" / "infer_out"))
    ap.add_argument("--no-mesh", action="store_true", help="3D 메시 생성을 건너뛴다(정량값만 필요할 때)")
    ap.add_argument("--mesh-out", default=None,
                     help="메시 STL/JSON을 저장할 폴더. 생략하면 --out 아래 mesh/ 서브폴더 사용")
    a = ap.parse_args()

    out_dir = Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh_out_dir = Path(a.mesh_out).resolve() if a.mesh_out else (out_dir / "mesh")

    print("모델이 로딩 중 입니다.")
    bundle = load_model(a.config, a.weights)
    print("로딩 완료.")

    print(f"원본에서 실시간 전처리 중... (post {'있음 - 종양+밀도' if a.post_path else '없음 - 밀도만'})")
    tumor_volume, density_volume, geometry = preprocess_raw_to_volume(
        a.pre_path, a.post_path, return_geometry=True
    )

    r = predict(
        bundle, tumor_volume, density_volume, patient_id=a.patient_id,
        include_mesh=not a.no_mesh,
        mesh_out_dir=str(mesh_out_dir) if not a.no_mesh else None,
        geometry=geometry,
    )

    json_path = out_dir / f"{a.patient_id}.json"
    json_path.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"phases={r['phases']}")
    if r["tumor"] is not None:
        print(f"tumor 병변 {r['tumor']['lesion_count']}개 검출 (필터 통계 {r['tumor']['filter_stats']})")
        for lesion in r["tumor"]["lesions"]:
            idx1 = lesion.get("lesion_index", 0) + 1
            mesh = lesion.get("mesh")
            if mesh:
                print(f"  메시(병변 {idx1}): {mesh.get('stl_path', '(파일 미저장, 배열만 반환)')}")
            else:
                print(f"  메시(병변 {idx1}): 없음(centroid 매칭 실패 또는 --no-mesh)")
        body_mesh = r["tumor"].get("body_mesh")
        if body_mesh:
            print(f"  메시(body_silhouette, breast_mesh 임시 대안): {body_mesh.get('stl_path', '(파일 미저장, 배열만 반환)')}")
    else:
        print("tumor: 계산 안 함(post 없음)")
    print(f"밀도비율 {r['density']['dense_density_pct']}%")
    print(f"breast 연결성분 {r['density']['breast_components']}개"
          + (" ⚠ 조각남 의심 - 3D 확인 전에 원인 파악 권장" if r['density']['breast_components'] > 2 else " (정상 범위)"))
    for k in ("breast_mesh", "dense_tissue_mesh"):
        if r["density"][k]:
            print(f"  메시({k}): {r['density'][k].get('stl_path', '(파일 미저장, 배열만 반환)')}")
    print(f"  {json_path}")
    print("\n※ Go 업로드는 이 CLI가 하지 않음 - 갑/을안 미결정(A-1). 로컬 STL/JSON을")
    print("   derived_io.upload_mesh(gateway_url, ticket, ...)로 별도 올릴 것(티켓 필요).")


if __name__ == "__main__":
    main()