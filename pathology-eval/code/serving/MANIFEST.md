# sTIL 파이프라인 서빙 매니페스트

`code/serving/` — 서버 담당자용. 작성 2026-09-01. 파이프라인 버전 `stil-serving-1.0.0`.

인터페이스:

```python
from serving import load_model, predict          # code/serving/ 를 PYTHONPATH 에

bundle = load_model(config)        # 서버 기동 시 1회. fp32 ~12s, 모델 4종 로드
result = predict(bundle, image)    # 요청마다. 1024px 이미지 기준 ~1s (+ 세포 수·MC 비례)
```

- `image`: 파일 경로(str/Path) | RGB ndarray(H,W,3 uint8) | PIL.Image
- `predict` 는 **스레드 안전하지 않음** — 단일 워커 + 요청 큐로 직렬화할 것 (GPU 1장 가정).
- `config` 는 `None` 가능(전부 기본값). 아는 키만 허용(오타 시 `ValueError`).

---

## 1. 체크포인트 파일 (4종)

| 이름 | 서빙 config 키 | 개발 워크스테이션 경로 | 크기 | sha256 (앞 16) | 배치 필요? |
|---|---|---|---|---|---|
| 조직분할 head (linear_tand) | `tissue_checkpoint` | `~/models/cellvitpp/logs_local/virchow2_linear_tand/best_head.pth` | 17.8 KB | `eacbd8de14a1bbfe` | ✅ 직접 배치 |
| 세포분류 head (weighted) | `cell_head` | `~/pathology-eval/candidates/socket2/model_best.pth` | 3.95 MB | `e54f5c8ec452bd5a` | ✅ 직접 배치 |
| CellViT-SAM-H (세포검출) | `cellvit_path` | `~/models/cellvitpp/checkpoints/CellViT-SAM-H-x40-AMP.pth` | 2.80 GB | `356418f19d9d4781` | ✅ 직접 배치 |
| Virchow2 (조직분할 인코더) | — (timm 자동) | HF 허브 → `~/.cache/huggingface/hub` | 2.4 GB | safetensors `8d6cea947eb2418c` | ⬇️ HF 다운로드 |

전체 sha256: `code/serving/checksums.sha256` (→ `sha256sum -c`).
`git` 에는 없음 — `.gitignore` 가 `*.pth *.safetensors candidates/` 를 제외. 별도 채널로 전달.

### 1a. 조직분할 head / 세포분류 head 출처
- 둘 다 이 저장소에서 학습한 산출물. `code/train_virchow2_linear_tand.py`,
  `2026-08-31T071447_tiger-til-binary-samh-tiled-weighted` 런.
- 조직분할 head 는 `head.weight(3,1280)` + `head.bias(3)` + `log_temperature(1)` = 3,844 파라미터.
- 세포분류 head 는 `LinearClassifier(embed_dim=1280, hidden_dim=256, num_classes=2)`,
  `training.drop_rate=0.5` 로 학습 (MC Dropout 근거).

### 1b. CellViT-SAM-H
- 업스트림 사전학습 가중치. CellViT-plus-plus 배포본 `CellViT-SAM-H-x40-AMP.pth`.
- 원본: https://github.com/TIO-IKIM/CellViT-plus-plus (checkpoints 안내 참조).

### 1c. Virchow2 — **gated HF 모델, 토큰 필요**
- repo `paige-ai/Virchow2`, revision `3158645804b69e3f3bc4439d4116edddf0840a72`.
- 접근 승인(HF 웹에서 라이선스 동의) 후 토큰 필요:
  ```bash
  export HF_TOKEN=hf_xxx           # 또는 huggingface-cli login
  # 최초 load_model() 이 timm 통해 자동 다운로드 → ~/.cache/huggingface 캐시
  ```
- 오프라인 서버: 위 경로의 HF 캐시 디렉터리(`models--paige-ai--Virchow2/`)를 통째로 복사하고
  `HF_HUB_OFFLINE=1` 설정. timm 이 `hf_hub:paige-ai/Virchow2` 를 캐시에서 해결.
- timm 이 `timm.layers.SwiGLUPacked` + `SiLU` 로 모델을 만듦 (코드에 고정, 건드릴 것 없음).

---

## 2. 하드코딩된 절대경로 — 서버에서 바꿔야 할 곳

| 위치 | 값 | 처리 |
|---|---|---|
| `serving.DEFAULT_CONFIG["tissue_checkpoint"]` | `~/models/cellvitpp/logs_local/.../best_head.pth` | `config` 로 덮어쓰기 |
| `serving.DEFAULT_CONFIG["cell_head"]` | `~/pathology-eval/candidates/socket2/model_best.pth` | `config` 로 덮어쓰기 |
| `serving.DEFAULT_CONFIG["cellvit_path"]` | `~/models/cellvitpp/checkpoints/CellViT-SAM-H-x40-AMP.pth` | `config` 로 덮어쓰기 |
| `serving.py` `_REPO_ROOT` | `~/models/cellvitpp` (CellViT-plus-plus 패키지) | **`CELLVIT_REPO` 환경변수** 로 지정. 없으면 기동 시 `RuntimeError` |
| `stil_inference_pipeline.py:36` `REPO_ROOT` | `~/models/cellvitpp` (하드코딩) | serving.py 가 먼저 유효 경로를 `sys.path` 에 넣어 무력화됨. 단 `~/models/cellvitpp` 가 "존재하지만 다른 내용"이면 안 됨 — 없는 게 나음 |
| `extract_socket2_tokens.py:41` `REPO_ROOT` | 동상 | 동상 |
| `stil_inference_pipeline.py` argparse 기본값들 | 위 경로 3종 + `~/data/...` (images_dir) | 서빙은 argparse 안 씀. 무관 |
| `EXPECTED_SHA` (serving.py `load_model` 내부) | 체크포인트 sha256 3개 | 체크포인트 교체 시 갱신 |

`CELLVIT_REPO` 로 지정할 디렉터리 = CellViT-plus-plus 체크아웃(패키지 `cellvit/` 포함).
이 저장소에 `CellViT-plus-plus/` 로 이미 동봉돼 있음 (git commit `463c5c4`, 업스트림과 동일).
`export CELLVIT_REPO=/path/to/pathology-eval/CellViT-plus-plus` 로 쓰면 됨.

---

## 3. 조정 가능한 임계값 (config 키)

| 키 | 기본값 | 의미 / 조정 가이드 |
|---|---|---|
| `til_threshold` | `0.5` | `P(TIL) ≥ 값` → 면역세포. 큰 이미지 recall 낮으면 0.3~0.4 로(한계 2-3). |
| `nc_ratio` | `1.5` | 핵→세포 면적 보정계수. 형질세포 비중 크면 ~2.0. 코호트별 캘리브 대상(한계 2-1). |
| `mc_samples` | `50` | MC Dropout 반복. `0` 이면 구간 계산 안 함(`stil_interval_*`=None). 비용 거의 0 → 50~100 무방. |
| `mc_drop_rate` | `0.5` | 소켓2 헤드 학습 시 값. **바꾸지 말 것** (MC Dropout 이론상 학습값과 일치해야). |
| `mc_ci` | `95.0` | 신뢰구간 % → 2.5 / 97.5 백분위수. |
| `dedup_radius` | `10.0` | 타일 경계 중복 세포 제거 반경(px, 원본해상도). |
| `tile_overlap` | `64` | 큰 이미지(>512px) 타일링 overlap(px). |
| `mpp` | `0.5` | µm/px. sTIL **비율엔 무관**(분자·분모 상쇄). µm² 환산·sanity 전용. 슬라이드 메타데이터 있으면 넣기. |
| `batch_size` | `4` | 큰 이미지 타일 추론 배치. OOM 시 낮춤(자동 1-폴백 있음). |
| `gpu` | `0` | `cuda:N`. `-1` → CPU (매우 느림, 권장 안 함). |
| `fp16` | `False` | 가중치 half. 저VRAM 환경. §5 참조. |
| `return_tissue_mask` | `True` | `False` 면 `result["tissue_mask"]=None` (페이로드 절감). `predict(..., return_tissue_mask=)` 로 요청별 override 가능. |
| `verify_checksums` | `True` | `load_model` 시 sha256 확인(2.7GB 포함, +약 3~5s). 신뢰 환경이면 `False`. |
| `pair_dist` | `15.0` | GT 페어링 거리 — **추론 미사용**. 무시. |

`predict` 반환 dict 키:
`stil_percent`, `stil_interval_low`, `stil_interval_high`, `stil_mc_mean`, `stil_mc_std`,
`mc_samples`, `tsr_tumor_percent`, `tsr_stroma_percent`, `stroma_status`(`ok`/`absent`),
`n_cells_total`, `n_cells_til`, `n_cells_til_stromal`, `tumor_area_px`, `stroma_area_px`,
`immune_nucleus_area_px`, `immune_cell_area_px`, `img_w`, `img_h`, `mpp`, `nc_ratio`,
`til_threshold`, `tissue_mask`((H,W) uint8 0/1/2 또는 None), `tissue_mask_legend`,
`predict_seconds`, `model_version`(dict — git commit·체크섬·HF revision·로드시각).

- `stroma_status=absent` → 간질 픽셀 0 → `stil_percent` 및 `stil_interval_*` = `None`.
  "0%" 아님, "평가 불가". 슬라이드 단위 집계 시 분자·분모 모두에서 제외(한계 문서 §3).
- `stil_interval_*` 는 **소켓2 분류 재현성 하한**. 조직분할·검출·캘리브 불확실성 제외 → "신뢰구간" 아님(한계 2-8).
- `stil_percent` 는 결정론적 점추정(dropout off). `stil_mc_mean` 은 진단용.

---

## 4. GPU 상주 메모리 (RTX 5090, torch 2.12+cu130, 측정치)

| 모드 | load 후 allocated | 예측 중 peak (max_allocated) | reserved peak | 권장 여유 예산 |
|---|---|---|---|---|
| **fp32** (기본) | ~5.4 GB | ~6.8 GB | ~7.7 GB | **8 GB** |
| **fp16** (`fp16=True`) | ~2.7 GB | ~4.1 GB | ~6.0 GB | **6 GB** |

- 측정 조건: 1024×1024 입력, `mc_samples=10`. **입력이 크면 peak 증가** (타일링 배치) — 예: 4000px 급은 `batch_size` 를 2~4 로, 필요 시 fp16.
- CUDA 컨텍스트 + cupy(postproc) 오버헤드 별도 ~0.5–1 GB 이미 포함된 수치.
- fp32/fp16 정확도 차이: sTIL 비율 기준 무시할 수준(핵 면적·소프트맥스). 저VRAM 아니면 fp32 권장.
- load 시간: fp32 ~12s (체크섬 검증 포함), Virchow2 는 HF 캐시에서. 최초 1회 다운로드는 ~5 GB.

---

## 5. Python 환경

**개발/검증 환경 = conda `cellvitpp` (Python 3.10.20).** 전체 freeze: `code/serving/requirements-serving.txt`.

핵심 (정확히 이 조합에서 검증됨):

| 패키지 | 버전 | 비고 |
|---|---|---|
| python | 3.10.20 | |
| torch | 2.12.1+cu130 | CUDA 13.0, cuDNN 9.2 |
| torchvision | 0.27.1 | |
| timm | 1.0.8 | Virchow2 로더 (SwiGLUPacked) |
| numpy | 1.26.4 | scipy 1.8.1 가 `<1.25` 경고 냄 — **무해**, 동작함 |
| scipy | 1.8.1 | |
| opencv-python-headless | 4.5.4.58 | |
| openslide-python | 1.3.1 | 시스템 `libopenslide` 4.0.0 필요 (apt: `libopenslide0`) |
| cupy-cuda12x | 12.3.0 | **torch 를 먼저 import 해야 함** (아래) |
| cupyx.scipy, ray 2.9.3, scikit-image 0.19.3, einops 0.6.1, h5py 3.9.0, albumentations 1.3.0 | | CellViT postproc 의존 |
| huggingface_hub 1.28.0, safetensors 0.8.0 | | Virchow2 다운로드 |

**cupy / libcudart 주의**: `cupy-cuda12x` 는 CUDA 12 런타임을 찾는데, 이 환경엔 시스템 CUDA 가
없다. torch(`nvidia-cuda-runtime-cu12` wheel 포함)를 **먼저 import** 하면 `libcudart.so.12` 가
프로세스에 로드되어 cupy 가 이를 재사용한다. `serving.py` 는 이 순서를 강제한다
(`import torch` 를 cupy 계열보다 먼저). 별도 진입점을 만들 때도 동일하게 할 것.

**시스템 패키지**: `libopenslide0` (openslide-python), 그 외는 wheel 로 해결.
GPU 드라이버: NVIDIA 595.84 / CUDA 13.2 런타임에서 검증 (드라이버가 cu130 지원하면 됨).

**CellViT-plus-plus 패키지**: pip 설치 아님. 저장소 동봉 `CellViT-plus-plus/` (commit `463c5c4`)
를 `CELLVIT_REPO` 로 지정 (§2). 이 디렉터리의 의존성(`environment.yaml`)은 이미 위 freeze 에 반영됨.

---

## 6. 서버 배치 체크리스트

1. conda 환경 복제: `conda create -n stil-serve python=3.10 && pip install -r code/serving/requirements-serving.txt`
   (또는 `cellvitpp` env tarball 이관). `apt install libopenslide0`.
2. 체크포인트 3종을 원하는 위치에 배치 → `sha256sum -c` 로 검증 (경로는 편집).
3. `CELLVIT_REPO` = CellViT-plus-plus 체크아웃 경로 export.
4. HF 토큰 설정 + 최초 Virchow2 캐싱 (또는 오프라인 캐시 복사 + `HF_HUB_OFFLINE=1`).
5. `python code/serving/healthcheck.py --json` → 종료 코드 0 확인.
   저VRAM 이면 `--fp16`. 빠르게: `--no-verify-checksums`.
6. 서버 코드에서:
   ```python
   bundle = load_model({
       "tissue_checkpoint": "/srv/models/best_head.pth",
       "cell_head":         "/srv/models/socket2_model_best.pth",
       "cellvit_path":      "/srv/models/CellViT-SAM-H-x40-AMP.pth",
       "gpu": 0, "fp16": False,
   })
   ```
   요청마다 `predict(bundle, image)`. 단일 워커 직렬화.

---

## 7. 관련 문서
- 파이프라인 한계·개선 로드맵: `docs/stil_pipeline_limitations.md`
- 타일 단위 원본 로직: `code/stil_inference_pipeline.py`
- WSI 단위 집계(검증용): `code/wsi_stil_pipeline.py`
