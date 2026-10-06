# MRI 소켓(소켓3) 서빙

2026-09-04 최신화 · `mri/serving/code/` 기준

MRI 볼륨(pre[+post] contrast) → 종양 위치·부피·최대직경·개수·유두거리·사분면(post 있을 때) +
유방 밀도(%, 항상) + 3D 시각화 메시(STL/JSON).

⚠ 이 문서는 파트간 인터페이스 대조(2026-09-04) 및 Go 담당·팀 최종 결정
(`파트별_수정목록_20260904.md`) 반영 후 상태 기준이다. 그 이전 버전 README와는
입력·출력 스펙이 다르다.

---

## 폴더 구조

```
mri/serving/code/
  ├─ infer_mri.py     predict() 조립 로직 + CLI (여기가 핵심)
  ├─ model_io.py       모델 로딩 (load_model, DEFAULTS)
  ├─ normalize.py       tumor/density 정규화 로직 (분리됨, 2026-09-04)
  ├─ derived_io.py      Go 파생물 게이트웨이 연동 + 로컬 저장 폴백 (구 garage_io.py)
  └─ healthcheck.py     배포 후 자가진단 스크립트

mri/postprocess_3d/code/   (별도 폴더 - infer_mri.py가 import만 함, 수정 안 함)
  ├─ build_3d_from_predictions_v9.py
  ├─ build_mesh_from_mask.py
  └─ compute_stage1_metrics.py

mri/training/code/preprocess/   (별도 폴더 - 리샘플링 로직만 재사용)
  └─ preprocess_mamamia.py
```

`build_3d_from_predictions_v9.py` 등은 **원본 그대로**다 — `infer_mri.py`가 그 안의 함수만
가져다 쓰는 구조라, 이번 서빙 경로 정리로 손댈 필요가 없었다(자세한 이유는 아래 "합쳐도
안 건드린 것" 참조).

---

## 설치

```bash
pip install torch numpy SimpleITK scipy scikit-image requests pyyaml pillow --break-system-packages
```

⚠ `boto3`는 더 이상 필요 없다 — Garage 직접 통신 코드를 전부 제거했다(아래 참조).

---

## 사용법

### Python API

```python
from infer_mri import load_model, predict, preprocess_raw_to_volume

bundle = load_model("configs/mri_lora.yaml")   # 프로세스당 한 번

# post가 있으면 종양+밀도, 없으면 밀도만 (post_path는 선택 인자)
tumor_volume, density_volume, geometry = preprocess_raw_to_volume(
    pre_path, post_path=None, return_geometry=True
)

result = predict(bundle, tumor_volume, density_volume, geometry=geometry)
```

### CLI

```bash
# 종양 + 밀도 둘 다
python3 infer_mri.py --pre-path a_pre.nii.gz --post-path a_post.nii.gz --patient-id ISPY2_242370

# 밀도만 (post 없음)
python3 infer_mri.py --pre-path a_pre.nii.gz --patient-id DUKE_043

# 메시 생성 생략 (정량값만, 빠름)
python3 infer_mri.py --pre-path ... --post-path ... --no-mesh
```

### 자가진단 (배포 후 가장 먼저 돌릴 것)

```bash
python3 healthcheck.py                                   # 파일·의존성·GPU·Go 게이트웨이 점검
python3 healthcheck.py --pre-path ... --post-path ...     # 실제 추론까지 테스트
python3 healthcheck.py --pre-path ...                     # 밀도 단독 경로 테스트 (post 없이)
```

---

## 입력

| 인자 | 필수 | 설명 |
|---|---|---|
| `pre_path` | ✅ | 원본 pre-contrast (nii.gz 또는 DICOM 시리즈 폴더) |
| `post_path` | ❌ | 원본 post-contrast. 없으면 종양(tumor)은 계산하지 않고 밀도만 낸다 |
| `patient_id` | ❌ | 기본값 "unknown" |
| `geometry` | ❌ | `preprocess_raw_to_volume(..., return_geometry=True)`가 반환한 값. 넘기면 evidence 좌표가 원본 DICOM 좌표계로 자동 변환됨 |

**원본은 앱 서버가 파일로 직접 넘긴다.** 저장소는 Orthanc(원본)이고, 이 서비스가 Garage나
Orthanc을 직접 다운로드하러 가지 않는다 — 앱 서버가 이미 꺼내서 올려준 파일을 받는다.

---

## 출력

```jsonc
{
  "patient_id": "...",
  "n_slices": 158,
  "phases": 2,                    // post 있었으면 2, 없었으면 1
  "params": { /* 이번 요청에 실제 쓰인 임계값 echo */ },

  "tumor": {                      // phases=1이면 이 자리가 null
    "lesion_count": 3,            // 부피 큰 순 최대 max_lesions개 (기본 10)
    "lesions": [
      {
        "lesion_index": 0, "volume_cm3": 2.18, "max_diameter_mm": 20.7,
        "centroid_z": 69.6, "centroid_y": 82.3, "centroid_x": 73.8,
        "nipple_distance_mm": 68.4, "quadrant": "하부(inferior)-외측(lateral)",
        "score_max": 0.874,       // 2026-09-29 — 병변 안 복셀들의 쿼리 점수 최대/평균.
        "score_mean": 0.712,      //   보정 안 된 점수(확률 아님), 표시용. 매칭 실패 시 null
        "mesh": { "vertex_count": ..., "triangle_count": ..., "stl_path": "...", "json_path": "..." }
      }
    ],
    "location_note": "...",       // 위치가 근사치라는 안내문 (응답에 포함되어 옴)
    "body_mesh": { ... },         // breast_mesh 조각남 문제의 임시 대안 (몸통 윤곽)
    "evidence": [
      { "id": "MR-01", "kind": "lesion", "image": {...}, "box": [...], "frame": "..." }
    ],
    "filter_stats": {             // 2026-09-29 — 후처리 필터별 제거 수 (QA·안내 문구용)
      "candidates": 15,           //   3D 연결성분 후보 수 = 아래 dropped_* 합 + kept
      "dropped_small": 3,         //   min_voxels 미달
      "dropped_short_span": 2,    //   min_contiguous_slices 미달
      "dropped_flat": 6,          //   시트형 필터(flat_min_*)
      "dropped_low_score": 2,     //   병변 평균 점수 < min_lesion_score_mean
      "dropped_below_min_voxels": 0, // 요약 단계 20복셀 컷 (min_voxels<20일 때만 0 아님)
      "dropped_over_cap": 1,      //   max_lesions 상한 초과
      "kept": 3
    },
    "truncated": true             // 상한에 잘린 병변이 있었으면 true
  },

  "density": {                    // 항상 존재
    "breast_voxels": ..., "dense_voxels": ...,
    "dense_density_pct": 23.4,    // breast_voxels=0이면 null
    "breast_mesh": { ... }, "dense_tissue_mesh": { ... }
  }
}
```

### 근거(evidence) id 형식

`MR-01`부터 시작(2자리, 1-base) — `US-01`·`MG-01`·`PA-01`과 형식 통일. `patient_id`에
의존하지 않는다(응답 하나 안에서만 유일하면 됨).

### 산출되지 않는 것

- BI-RADS 등급, 악성확률 — 구조적 제외
- benign/malignant lesion 위치 — 스코프 제외(3~4차 학습 F1 0.03~0.35, 실사용 불가)
- 형태 지표(구형도·경계불규칙도 등) — 미착수

---

## 정규화 — tumor와 density는 다른 통계를 쓴다

```python
# normalize.py
zscore_two_phases(pre, post)   # tumor용 — pre+post 합산 mean/std
zscore_pre_only(pre)           # density용 — pre 단독 mean/std, post 관여 없음
```

원본 pre/post는 한 번만 읽지만, `preprocess_raw_to_volume()`이 이 자리에서 통계를 각각
따로 계산해 `tumor_volume`(post 있을 때만)과 `density_volume`(항상)을 만든다. 두 정규화를
섞어 쓰면 density 모델이 학습 때와 다른 분포의 입력을 받게 된다 — 실제로 한 번 이 실수를
했다가(정규화를 하나로 합칠 뻔함) 바로잡은 이력이 있다.

---

## 임계값

`model_io.py`의 `DEFAULTS` 기준(배포 config `mri_lora.yaml`에 `inference:` 섹션이 없어
DEFAULTS가 그대로 적용됨):

| 항목 | 값 |
|---|---|
| tumor_score_threshold | 0.5 |
| dense_tissue_score_threshold | 0.5 |
| breast_score_threshold | 0.8 |
| min_voxels | 30 |
| min_contiguous_slices | 2 (tumor 기준) |
| mesh_smooth_iters | 1 |
| mask_pixel_threshold | 0.5 |
| flat_min_aspect_ratio | 0.3 (시트형 필터) |
| flat_min_thin_axis_mm | 4.0 (시트형 필터) |
| max_lesions | 10 (부피 큰 순 상한) |
| min_lesion_score_mean | 0.6 (병변 평균 점수 하한, 0이면 끔) |

2026-09-29부터 위 값은 전부 `predict(..., 키=값)` kwarg나 config `inference:` 섹션으로 바꿀 수 있다
(이전엔 `mask_pixel_threshold`가 미사용, 시트형 필터 기준과 상한은 모듈 상수로 고정이었다).
응답의 `params`에 실제 쓰인 값이 그대로 실린다.

⚠ 시트형 필터 기준과 상한은 환자 1명·임계값 0.7 실측으로 정한 값이라 아직 미검증이다.
tumor 임계값 스윕도 0.5/0.8 두 점(2D 슬라이스 기준)뿐이다 —
[결과 문서](../docs/results_for_presentation_mri.md) 4절 참고.

---

## 3D 메시 → Go 업로드

`predict()`는 메시를 **로컬(STL/JSON)까지만** 저장한다. Go 파생물 게이트웨이
(`POST /svc/v1/derived`)로 실제 업로드하는 건 `predict()` 밖의 일이다 — 티켓이 요청마다
Django가 발급하는 1회용 값이라 `predict()`가 스스로 처리할 수 없기 때문이다.

```python
from derived_io import upload_mesh

result = upload_mesh(gateway_url, ticket, stl_bytes, filename="mesh.stl")
# {"object_key", "bucket", "byte_size", "checksum_sha256", "content_type"}
```

- 요청 형식은 **multipart가 아니다** — 본문에 파일 바이트를 그대로 스트리밍
- 체크섬은 서버가 계산해서 돌려준다(클라이언트는 로컬 값과 대조해서 전송 손상만 검증)
- **티켓은 1회용** — 재시도하려면 새 티켓이 필요
- 파일 하나당 티켓 하나 — STL과 JSON을 각각 올리려면 티켓 두 장. 메타데이터(JSON)는
  올리지 말고 `predict()` 응답 본문에 그대로 담는 걸 권장(그러면 STL 하나만 올리면 됨)

⚠ **갑안/을안 미결정** — "MRI가 Go를 직접 호출"(을안, 위 코드) 대신 "응답에 메시를 실어
Django/Celery가 대신 올림"(갑안)으로 갈 수도 있다. STL 실제 크기 확인 후 결정 예정 —
갑안이면 `derived_io.py`의 업로드 관련 부분은 통째로 삭제 대상이다.

---

## 알려진 제약 / 확인 대기

| 항목 | 상태 |
|---|---|
| 시리즈 기하 검사(`check_series_geometry`) | **호출 불가능한 죽은 코드.** 앱 서버가 파일만 주고 시리즈 메타데이터는 안 줘서 부를 재료가 없다. 시리즈 단위 기하 판정·차단은 **Django가 전담**하며, 걸린 시리즈는 MRI에 아예 안 넘어오는 걸로 최종 확정됨 |
| 판독 실측(적재·추론 시간) | 미실측 — GPU 대기 |
| `include_mesh` 켠/끈 시간 차이 | 미실측 — GPU 대기 |
| Go 업로드 갑/을안 | STL 실제 크기 확인 후 결정 예정 |
| 판독 타임아웃 값 | 위 실측 이후 결정 |

---

## 이번 대화에서 바뀐 것 (변경 이력)

이전 버전 대비 바뀐 것만 요약. 이유·배경은 파트간 인터페이스 대조 문서 참조.

1. **`dataset_tag` 완전 폐지** — `mamamia`/`duke`로 나누던 것을 없애고, 원본 pre(+post)
   하나로 tumor·density를 (가능한 만큼) 항상 같이 계산해서 반환
2. **`post_path` 선택 인자화** — 처음엔 실수로 필수로 만들었다가, 밀도 단독 산출 경로가
   막힌다는 지적을 받고 다시 선택으로 되돌림. 응답에 `"phases": 1|2` 추가
3. **정규화 로직 분리** (`normalize.py` 신규) — tumor는 pre+post 합산 통계, density는
   pre 단독 통계. 서로 다른 계산이라는 걸 명확히 갈라둠
4. **Garage 직접 다운로드 코드 전부 제거** — `preprocess_from_garage`,
   `fetch_series_from_garage`, `_garage_readonly_client`, CLI `--pre-keys`/`--post-keys`.
   원본은 앱 서버가 파일로 직접 넘기고, 저장소도 Garage가 아니라 Orthanc
5. **`garage_io.py` → `derived_io.py` 개명** — 남은 책임이 "파생물(메시) 업로드"뿐이라
   역할 기준 이름으로 변경
6. **Go 메시 업로드 함수 재작성** — 처음엔 추측(multipart, 클라이언트 체크섬 계산)으로
   짰다가, Go 담당 확인 후 실제 스펙(원시 바이트 스트리밍, 서버측 체크섬, 티켓 인증)에
   맞춰 전면 재작성. `predict()` 안에서 자동 업로드하던 것도 뺌(티켓 문제)
7. **근거(evidence) id 형식 통일** — `MRI-{patient_id}-{lesion_index}` →
   처음엔 `MR-00`(0-base)로 바꿨다가, 다른 모달리티가 전부 1부터 시작한다는 지적을
   받고 `MR-01`(1-base)로 재수정
8. **기하 검사 함수 결론** — `check_series_geometry()`를 "방어선으로 유지"라고
   적었다가, 실제로는 호출할 재료(series_meta)가 없어 부를 수 없다는 게 밝혀져
   "죽은 코드"로 주석 정정. 시리즈 기하 차단은 Django 전담으로 최종 확정
9. **병변 오탐 검토 1단계 (2026-09-29)** — 기본값 기준 검출 결과는 그대로, 응답·설정만 확장.
   병변별 `score_max`/`score_mean`, `tumor.filter_stats`/`truncated` 추가, 시트형 필터 기준·
   병변 상한을 파라미터로 노출, 미사용이던 `mask_pixel_threshold` 연결.
   `build_3d_from_predictions_v9.py`·`compute_stage1_metrics.py`는 옵션 인자만 추가(기존 호출 동작 동일)
10. **병변 평균 점수 필터 (2026-09-29)** — `min_lesion_score_mean=0.6` 기본 적용. **검출 결과가 바뀌는 변경.**
   val 40명(3D, 병변 단위) 기준 환자당 순수 오탐 3.73 → 2.30, 주 병변 40/40 유지, 병변 민감도 0.706 그대로
   (환자 5-fold 교차검증에서 매 fold 0.6 선택). 3차 모델 점수 분포 기준값이라 모델 교체 시 재조정 필요.
   근거: `postprocess_3d/code/analyze_component_rules.py`, `results/lesion_fp_analysis/`

---

## 합쳐도 안 건드린 것

`build_3d_from_predictions_v9.py`는 처음엔 dataset_tag 분기를 고쳐야 한다고 판단했지만,
`predict()`가 그 파일의 `run_pipeline_for_patient()`(dataset_tag로 분기하는 함수)를
애초에 쓰지 않는다는 게 확인되어 손대지 않았다. `predict()`는 `volume_to_rgb_slices` 등
개별 함수만 가져다 쓰고, `"mamamia"`/`"duke"`라는 태그 이름은 이제 "환자 구분"이 아니라
"2-phase RGB냐 1-phase RGB냐"를 고르는 내부 스위치로만 재활용한다.
