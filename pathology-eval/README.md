# empatho-pathology-eval

병리(유방 sTIL) 파이프라인의 **정식 저장소**입니다.

- 원격: https://github.com/medical-ai-group-3/empatho-pathology-eval
- 로컬(워크스테이션): `~/pathology-eval`

## ⚠️ 구 폴더는 동결되었습니다

`~/workspace/breast/pathology/` 는 **2026-08-30 이후 동결(deprecated)** 되었고
2026-09-02 에 삭제되었습니다(자리에는 안내 stub 만 남음). pathology-eval 에 없던
소켓2 weighted 재학습 이전 체크포인트·로그는
`candidates/socket2/_pre_weighted_2026-08-26/` 에 보존했습니다.

아래 항목들은 **이 저장소에만** 반영되어 있습니다. 구 폴더를 참조하면 낡은 코드/공식을 쓰게 됩니다.

| 항목 | 구 `pathology` (동결) | 이 저장소 |
|---|---|---|
| **세포검출 recall 수정** (`code/detect_all_cells_binary.py`) | 큰 이미지를 256으로 축소해 recall 붕괴하던 원래 코드 | v2: 큰 이미지 256 타일링 + NMS 로 recall 복구 |
| **sTIL 공식** (`code/stil_inference_pipeline.py`) | `면역세포 ÷ (면역세포 + 사이조직)` 데모 버전 | 국제 TIL Working Group 표준 `(간질 내 면역세포 면적 / 전체 간질 면적) × 100` + 공간 게이팅 + MC Dropout |
| **소켓2 분류기 재학습** | 없음 (weighted 이전 체크포인트) | `configs/tiger_samh_fold_0_weighted.yaml` + `candidates/socket2/model_best.pth` (weighted CE 재학습본) |
| **소켓1 평가** | 없음 | `code/evaluate_socket1_{candidates,dice,stats}.py`, `code/benchmark_socket1_speed.py` |
| **WSI 파이프라인** | 없음 | `code/wsi_stil_pipeline.py` (WSI 82장 검증), `code/wsi_stil_validate.py` |
| **서빙** | 없음 | `code/serving/` (serving.py, healthcheck, MANIFEST, checksums) |
| **문서** | 없음 | `docs/stil_pipeline_limitations.md`, `docs/db_changes_pathology_G2_G3_G13*.md` |

구 폴더에서 학습 스크립트(`train_virchow2_*.py`)와 기본 config는 분기 이후 변경되지 않아 이 저장소의 것과 동일합니다.

## 확정 모델

| 소켓 | 역할 | 체크포인트 |
|---|---|---|
| 소켓1 | 조직분할 (기타/종양/간질) | `linear_tand` — Virchow2 + Linear TAND head (`candidates/socket1/linear_tand.pth`) |
| 소켓2 | 세포 TIL 분류 | weighted LinearClassifier head (`candidates/socket2/model_best.pth`) |
| 검출 | 전체 세포 검출 | CellViT-SAM-H (`~/models/cellvitpp/checkpoints/CellViT-SAM-H-x40-AMP.pth`) |

> `candidates/` 와 `data/` 는 `.gitignore` 대상입니다(용량). 모델 가중치는 별도로 공유하세요.

## 레이아웃

```
code/            파이프라인·학습·평가·전처리 스크립트
code/serving/    추론 서빙 패키지
configs/         학습 config (tiger_samh_*.yaml), val split CSV
docs/            파이프라인 한계·DB 스키마 변경안 문서
candidates/      확정 모델 가중치 (gitignore)
CellViT-plus-plus/  로컬 패치 적용된 CellViT++ (cellvitpp_local_patch.diff)
```
