# `train_us_lora.py` 검증 보고서

※ 줄번호는 2026-08-26 로깅 코드 추가 이전 기준

초음파(경로 B) 1차 시험 학습 스크립트 — BUS-BRA lesion 분할.

**검증 방법** — 정적 분석에 더해, 실제 병합 체크포인트(`medsam3_merged.pt`, 3.37 GB)를
RTX 5090에 올려 train/val 스텝을 직접 실행했다. 아래 수치는 전부 실측이다.

| 시험 | 결과 |
|---|---|
| 미수정 상태 train 스텝 | `TypeError("'NoneType' object is not callable")` |
| `model.matcher` 주입 후 train | loss 63.5422, peak 12.75 GB |
| `model.matcher` 주입 후 eval | loss 5.6323, peak 8.56 GB |
| 학습 파라미터 | 18,497,664 / 859,007,414 = **2.153%** |

---

## 1. 차단 결함 — 첫 학습 배치에서 죽는다

**증상**

```
AS-WRITTEN TRAIN STEP FAILED: TypeError("'NoneType' object is not callable")
```

**경로**

| 단계 | 위치 | 내용 |
|---|---|---|
| ① | `sam3/model_builder.py:311-324` | `matcher = None`, `if not eval_mode:` 일 때만 생성 |
| ② | `merge_medsam3.py:126` | `build_sam3_image_model(..., eval_mode=True)` → **matcher=None 확정** |
| ③ | `train_us_lora.py:368` | `model.train()` → `self.training = True` |
| ④ | `sam3/model/sam3_image.py:491` | `if self.training or ...: self._compute_matching(...)` |
| ⑤ | `sam3/model/sam3_image.py:579` | `out["indices"] = self.matcher(out, targets)` → **None 호출** |

`load_merged_model()` 이 돌려주는 모델은 추론용(`eval_mode=True`)으로 지어진 것이라
matcher 가 없다. 학습 모드로 바꾸는 순간 모델이 **내부에서** 매칭을 시도한다.

`train_us_lora.py:295-303` 의 수동 matcher 루프는 `model(inp)` 가 **이미 끝난 뒤에**
실행되므로 이 크래시를 막지 못한다.

빈 모델(랜덤 초기화)로도, 실제 병합본으로도 동일하게 재현된다.

**참고** — matcher 를 주입하면 나머지 배선은 전부 정상 동작한다:

```
TRAIN STEP OK  loss=63.5422  peak=12.75GB
EVAL  STEP OK  loss= 5.6323  peak= 8.56GB
```

또한 matcher 가 주입되면 학습 모드에서 수동 루프는 **중복 계산**이 된다
(모델이 이미 `out["indices"]` 를 채워둔 상태). eval 모드에서는 `self.training=False` 라
모델이 매칭을 하지 않으므로 수동 루프가 반드시 필요하다 — 즉 이 루프는 지울 게 아니라
`model.training` 일 때 건너뛰어야 하는 성격의 코드다.

---

## 2. 손실 충실도 — 주석의 주장과 실제가 다르다

`train_us_lora.py:257` 은

> 가중치는 MedSAM3 저장소 학습 스크립트의 값을 그대로 쓴다(임의 조정 없음).

라고 적혀 있으나, `IABCEMdetr` 에서 **`weak_loss` 가 빠졌다.**

- 참조 설정은 명시적으로 `weak_loss: False`
  (`sam3/train/configs/roboflow_v100/roboflow_v100_full_ft_100_images.yaml:91`)
- 생성자 기본값은 `weak_loss=True` (`sam3/train/loss/loss_fns.py:274`)

결과가 단순한 값 차이가 아니다. `weak_loss=True` 면 `loss_fns.py:443-457` 분기를 타고
`loss_bce.sum() / loss_mask.sum()` 으로 끝난다. 즉 **함께 넘긴 `pad_n_queries=200` 이
도달 불가능한 죽은 인자가 된다** (`loss_fns.py:493-499` 는 else 분기).

**정량적 영향**

디코더 `query_embed` 는 200개, `decoder.dac=True` (실측).
학습 모드에서는 `num_o2o = 200//2 = 100`, 평가 모드에서는 200.

| | CE 정규화 분모 (train) | CE 정규화 분모 (eval) |
|---|---|---|
| 의도 (`weak_loss=False`) | 200 (패딩) | 200 |
| 실제 (`weak_loss=True`) | 100 | 200 |

→ CE 항이 참조 설정 대비 **2배**, 게다가 train/val 간에 또 2배 어긋난다.

`is_exhaustive=True` 만 쓰는 데이터라 마스킹 자체는 무해하지만,
정규화 분모가 바뀌는 부작용이 남는다.

---

## 3. `train X / val Y` 출력은 비교 불가능한 두 수치다

`train_us_lora.py:409-411` 이 두 값을 나란히 찍지만 산출식이 다르다.

`sam3/model/sam3_image.py:343-386` 의 `update_aux=self.training` 과
`if num_o2m > 0 and self.training:` 때문에

| | aux_outputs (디코더 중간층) | o2m 항 | 실측 loss |
|---|---|---|---|
| train | 포함 | 포함 | **63.54** |
| eval | 없음 | 없음 | **5.63** |

**같은 배치, 같은 가중치로 11배 차이가 난다.**

best 체크포인트 선택은 val 끼리만 비교하므로 논리적으로는 문제없다. 다만 출력만 보면
"train 63 / val 5.6" 이 극단적 과소적합처럼 읽힌다 — 실제로는 아무 의미 없는 숫자 쌍이다.

---

## 4. 분할 과제인데 분할 지표가 없다

목표는 lesion 분할인데 Dice/IoU 를 전혀 계산하지 않는다.
`best_val` 은 box(5/2) + CE(20) + presence(20) + mask(200) + dice(10) 가 섞인 합산 손실이고,
여기에 §3 의 항 구성 차이까지 얹힌다.
마스크가 실제로 좋아졌는지 판단할 근거가 학습 로그에 남지 않는다.

---

## 5. 사소하거나 잠재적인 것

| 위치 | 내용 |
|---|---|
| `train_us_lora.py:165-166` | `by_class["object"] = []` 폴백 — 타깃 없는 쿼리 + 양성 사례가 한 번도 없는 텍스트("object")를 만든다. 공식 파이프라인은 `FilterEmptyTargets` 로 이런 쿼리를 제거한다. **BUS-BRA 는 이미지당 어노테이션이 정확히 1개, 무어노테이션 이미지 0개**라 현재는 죽은 코드지만, 다른 데이터로 재사용하면 바로 터진다 |
| `train_us_lora.py:180` | `raw_images=[pil]` — 1008² PIL 이 워커 IPC 로 샘플당 ~3 MB 씩 넘어가는데 학습에선 쓰이지 않는다 |
| `train_us_lora.py:157` | `area` 가 픽셀 면적이 아니라 정규화 `w*h`. loss/matcher 어디서도 `area` 를 참조하지 않는 것을 확인 — 무해 |
| `lora_layers.py:524` | `save_lora_weights` 가 `nn.Parameter` 를 그대로 저장(CUDA, requires_grad 포함). `load_lora_strict` 는 `copy_` 라 로드는 되지만 파일에 autograd 메타가 실린다 |
| `train_us_lora.py:353` | LR 스케줄러·워밍업 없음. 참조 설정은 warmup 20 / cooldown 20 |
| `train_us_lora.py:105-109` | 증강 전무. 참조 학습 파이프라인은 multi-scale `RandomResizeAPI`(min 480) + `PadToSizeAPI` 사용. 1495장 · 학습 파라미터 18.5M · 5 epoch 조합에서 과적합 여지 |
| `train_us_lora.py:382` | `loss.item()` 이 그래프 텐서에 걸려 `requires_grad` 경고 발생 — 표시상의 문제 |

---

## 6. 검증해서 **맞다고 확인한** 부분

여기는 문제 없다. 특히 눈에 띄게 잘 잡은 것들:

- **정규화·해상도가 공식 파이프라인과 정확히 일치.**
  `mean=std=[0.5,0.5,0.5]`, `resolution: 1008` 은
  `sam3/train/configs/odinw13/odinw_visual_only.yaml:51-54` 및
  `sam3/model/io_utils.py:33-34` 와 동일.

- **1008 은 "판단"이 아니라 강제 조건이다.**
  448 로 낮춰 시험해 보니 ViTDet RoPE 의 `freqs_cis` 가 고정 크기라
  `sam3/model/vitdet.py:63` 에서 `AssertionError`.
  설정 주석의 `# [판단] SAM3 네이티브 해상도` 는 사실 선택지가 없다.

- **bbox 변환 정확.** COCO xywh → 정규화 cxcywh 가 `NormalizeAPI`
  (`basic_for_api.py:896-903`) 의 `box_xyxy_to_cxcywh` 후 `/(w,h,w,h)` 와 수식상 일치.
  이미지 50장에서 `pil.size` 와 JSON `width/height` 불일치 0건.

- **마스크 경로 정확.** `frPyObjects(seg, orig_h, orig_w)` 인자 순서 맞음.
  collate 출력 실측: `img [2,3,1008,1008]`, `text ['lesion']`,
  `num_boxes [1,1]`, `segments [2,1008,1008]`, `is_valid [True,True]`.

- **LoRA 재주입 정상.** MHA 교체 0건(주석대로), LoRA 458개 모듈,
  **18,497,664 / 859,007,414 = 2.153%** — 설정에 적힌 실측치와 정확히 일치하고
  1.0~3.0% 게이트 통과. `check_trainable` 의 게이트 설계 자체가 좋다.

- **손실 가중치 일치.** bbox 5 / giou 2 / ce 20 / presence 20 / pos_weight 10 /
  mask 200 / dice 10, `o2m_weight 2.0`, `BinaryOneToManyMatcher(0.3, 0.4, 4)`,
  `compute_aux=False` 모두 참조 설정과 동일 (`weak_loss` 하나만 예외 — §2).

- **`normalization="local"` 은 올바른 단일 GPU 선택.**
  기본값 `"global"` 은 `torch.distributed.all_reduce` 를 호출해 단일 프로세스에서 죽는다.

- **경사 누적 정확.** 1495장 / bs 2 / drop_last → 747 스텝, `747 % 8 = 3` 이므로
  `train_us_lora.py:385-388` 의 잔여 flush 가 올바르게 발동.

- **bf16 autocast + GradScaler 없음** — 맞는 조합.

- **`SAM3Output.iteration_mode` 사용법 정확** (`model_misc.py:397` 정적 메서드 시그니처와 일치).

- **cwd 처리 안전.** `--config` 를 `os.chdir` 전에 `resolve()` 하고 출력 경로도 전부 절대경로.

- **메모리 여유 충분.** bs=2 에서 peak 12.75 GB (학습) / 8.56 GB (평가), 32 GB 중.
  설정의 "보수적" 판단은 맞았고 bs=4 도 들어갈 여지가 있다.

---

## 정리

| | 항목 | 영향 |
|---|---|---|
| 1 | `model.matcher is None` | **학습 자체가 불가능.** 첫 배치에서 TypeError |
| 2 | `weak_loss` 미지정 | CE 항 2배 + `pad_n_queries=200` 무력화 + train/val 스케일 어긋남 |
| 3 | train/val 손실 항 구성 상이 | 로그 오독 유발 (best 선택 자체는 유효) |
| 4 | 분할 지표 부재 | 마스크 품질 판단 불가 |
| 5 | 빈 쿼리 폴백·증강/스케줄러 부재 등 | 현 데이터에선 미발현, 재사용 시 위험 |

데이터 파이프라인·정규화·LoRA 주입·손실 배선은 저장소 규약을 정확히 따랐다.
문제는 **병합본이 `eval_mode=True` 로 지어진다는 사실이 학습 스크립트 쪽에
전달되지 않은 것** 하나에 집중되어 있고, 나머지는 그보다 한 단계 낮은 층위다.
