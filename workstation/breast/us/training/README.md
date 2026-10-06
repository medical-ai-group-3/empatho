# 초음파 재학습

재학습할 때만 쓴다. 서버에는 올리지 않는다.

```
code/      학습·평가·검정 스크립트
ckpt/      features_best.pt   헤드 재학습용 특징 캐시
configs/   us_lora.yaml
```

데이터·로그·과거 체크포인트는 `../archive/` 에 있다.

---

## 1 · 학습 순서

### 전체 재학습 (분할부터)

```bash
# 1) 분할 + 등급 조인트 학습          약 5시간 40분 (30 epoch)
python3 code/train_us_lora.py --config configs/us_lora.yaml --run-name <이름>

# 2) 정량 평가                        약 4분
python3 code/eval_us_lora.py --config configs/us_lora.yaml --split valid \
    --dump-csv ../archive/eval_out/valid_<이름>.csv
```

`--smoke N` 을 주면 train/valid 를 N 배치로 줄여 1 epoch 만 돈다.
체크포인트는 `ckpt/_smoke/` 로 격리되므로 본 실행을 덮어쓰지 않는다.
**본 학습 전에 한 번 돌려 저장이 되는지 확인할 것.**

### 헤드만 재학습 (분할 동결)

분할 LoRA·픽셀 디코더를 그대로 두고 등급 헤드만 다시 학습한다.
특징을 한 번 뽑아두면 설정 하나당 수 초에 끝난다.

```bash
# 1) 동결 상태의 쿼리 임베딩 추출      약 4분  (한 번만)
python3 code/cache_features.py --config configs/us_lora.yaml

# 2) 격자 탐색                        수 분
python3 code/train_heads_grid.py --config configs/us_lora.yaml

# 3) 확정 설정을 앙상블 파일로          약 1분
python3 code/make_heads_ensemble.py --config configs/us_lora.yaml

# 4) 임계값 격자표                     약 2분
python3 code/sweep_thresholds.py --config configs/us_lora.yaml --seeds 10
```

### 검정

```bash
# 두 설정 비교 — 대응 비교 + 케이스 단위 부트스트랩
python3 code/paired_compare.py \
    --a ../archive/eval_out/valid_A.csv \
    --b ../archive/eval_out/valid_B.csv --metric dice

# seed 편차 측정 (학습 재현성 확인용. 유의성 근거로 쓰지 않는다)
python3 code/analyze_variance.py --config configs/us_lora.yaml --seeds 10
```

### 외부 검증 — **1회 한정**

```bash
python3 code/eval_test_final.py --config configs/us_lora.yaml
```

**결과로 설정을 바꾸지 않는다.** 바꾸면 독립 기준선이 사라진다.
이미 한 번 썼으므로 **다음 외부 검증에는 새 데이터가 필요하다.**

---

## 2 · 확정된 설정과 근거

| 항목 | 값 | 왜 |
|---|---|---|
| 인코더 | MedSAM3 병합본 동결 | 모든 모달리티 공유 |
| LoRA | rank 16 · alpha 32 · 전 컴포넌트 | 학습 파라미터 약 2.4% |
| 픽셀 디코더 | UNet `fuse` (warm start) | 분할 수렴이 빠르다 |
| 등급 헤드 | **분리 학습** · `pos_weight` 지수 0.25 · 악성 보조입력 없음 | 아래 |
| 헤드 저장 | **seed 10개 앙상블** | 임계값을 확률 평균 위에서 골랐다 |
| 마스크 출처 | argmax 쿼리 하나 | 마스크와 등급이 같은 병변을 가리키게 |
| 임계값 | t2 0.50 · t3 0.50 · t4 0.45 | 운영 정책 영역 |
| 확신도 경계 | 0.10 / 0.30 | 분리력 최대점 |

**헤드를 분리한 이유** — 등급 손실이 분할을 유의하게 깎는다. 분할 전용으로 학습하면
조인트보다 Dice 가 높고, 반대로 분할을 키우려 픽셀 디코더를 조인트에 넣으면
등급이 유의하게 나빠졌다. **한 방향의 간섭**이 실측으로 확인된 것이고, 그래서
분할을 동결한 뒤 헤드만 따로 최적화한다.

**기각한 것** — 데이터 증강 · 악성 확률을 등급 보조 입력으로 · UNet 디코더 조인트 ·
최대 연결성분만 남기기. 근거는 `../docs/experiments.md` 와
`../../docs/negative_results.md`.

**중단한 것** — BI-RADS 4↔5 개선. 라벨 체계의 한계(BUS-BRA 에 4a/4b/4c 없음)라
헤드로 풀 수 있는 문제가 아니다. 대신 "4~5" 구간 표기로 우회했다.

---

## 3 · 다음 사이클 후보 — 전처리

**셋을 함께 적용한다.** 하나만 바꾸면 train/serve 불일치가 남는다.

1. **이미지별 z-score 정규화** — CLAHE 보다 안전하다. z-score 는 선형 변환이라
   후방음영 같은 진단적 특징을 보존한다. CLAHE 는 국소 대비를 조작해 그것을 바꾼다.
2. **알파 합성 처리** — `convert("RGB")` 는 알파를 배경에 합성하지 않고 버린다.
   그래서 투명 영역의 원본 RGB(거의 검정)가 그대로 남는다.
   `Image.alpha_composite` 로 합성하거나 투명 영역을 잘라낸다.
3. **train 부터 적용하고 valid 로 대응 검정.** test 는 건드리지 않는다.

**⚠ 추론에만 얹으면 안 된다.** LoRA·픽셀 디코더가 현재 전처리(mean/std 0.5)로
학습됐다. 바꾸면 train/serve 불일치가 되어 지금보다 나빠질 수 있다.

재학습하면 `../docs/experiments.md` 의 valid 수치를 전부 다시 재야 한다.

---

## 4 · 검정 규칙 — **반드시 지킬 것**

`../docs/experiments.md` 0-2 절에서 정했다. 한 번 틀린 판정을 낸 적이 있어 규칙으로 남긴다.

### ① 두 설정 비교는 **대응 비교 + 케이스 단위 부트스트랩**

같은 valid 를 두 모델이 평가하므로 독립 2군이 아니다. `paired_compare.py` 를 쓴다.

### ② **표본 수는 이미지 수가 아니다**

파일명 `-l` / `-r` 은 좌·우 유방이 아니라 **같은 병변의 다른 뷰**다.
두 뷰는 오차가 상관돼 있으므로 재표집은 **case 단위**로 해야 한다.
`paired_compare.py` 가 ICC 와 설계효과를 함께 출력한다.

### ③ **seed 편차로 유의성을 주장하지 않는다**

seed 편차는 "같은 데이터로 다시 학습하면 얼마나 흔들리나"이고,
표본오차는 "다른 환자 집단이면 얼마나 달라지나"다. **다른 축이다.**
seed 편차를 넘었다고 일반화되는 것이 아니다.

### ④ **표본별 CSV 를 반드시 남긴다**

`--dump-csv` 로 `../archive/eval_out/` 에 저장한다.
**없으면 나중에 대응 검정을 할 수 없다.** 실제로 SAM3-UNet 실험이 CSV 가 없어
한동안 검정을 못 했고, 나중에 `dump_sam3unet_valid.py` 로 다시 뽑아야 했다.

### ⑤ 스모크를 먼저 돌린다

`--smoke 2` 로 체크포인트 저장이 되는지 확인한다. 저장 코드가 조용히 실패하면
몇 시간 뒤 쓸 수 없는 체크포인트가 남는다.

---

## 5 · 스크립트 목록

| 파일 | 용도 |
|---|---|
| `train_us_lora.py` | 분할 + 등급 조인트 학습 |
| `eval_us_lora.py` | 정량 평가 (mAP · Dice · 등급) · 시각화 |
| `cache_features.py` | 동결 상태 쿼리 임베딩 추출 |
| `train_heads_grid.py` | 헤드 격자 탐색 |
| `make_heads_ensemble.py` | 확정 설정을 앙상블 파일로 |
| `sweep_thresholds.py` | 임계값 격자표 |
| `paired_compare.py` | 대응 비교 검정 |
| `analyze_variance.py` | seed 편차 · 경계 분리 가능성 |
| `eval_test_final.py` | 외부 검증 (1회 한정) |
| `compare_mask_source.py` | 마스크 출처 비교 |
| `dump_sam3unet_valid.py` | 분할 전용 모델 표본별 기록 |
| `model_io.py` · `heads.py` · `shape_metrics.py` · `unet_pixel_decoder.py` | 공통 모듈 (serving 과 동일) |

---

자세한 실험 기록은 `../docs/experiments.md`.