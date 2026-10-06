# 초음파 추론 서빙

백엔드에서 `infer_us.py` 를 import 해 쓴다. 모델을 프로세스당 한 번 올리고
요청마다 `predict()` 만 호출한다.

배포 후 **먼저 `python3 healthcheck.py` 를 돌릴 것.** 되는지 안 되는지 바로 알려준다.

---

## 1 · 필요한 것

### 이 폴더 (80 MB)

```
code/     infer_us.py · model_io.py · heads.py · shape_metrics.py · unet_pixel_decoder.py
ckpt/     us_lora_best.pt (71M) · us_pd_best.pt (8.3M) · us_heads_ensemble.pt (88K)
          us_best_manifest.json
configs/  us_lora.yaml
healthcheck.py · requirements.txt
```

세 `.pt` 는 **같은 학습 실행에서 나온 짝**이어야 한다. 섞으면 조용히 잘못된 결과가 나온다.

### MedSAM3 저장소 — **함께 있어야 한다**

```
MedSAM3/
  sam3/ · lora_layers.py · merge_medsam3.py
  ckpt/medsam3_merged.pt         3.2 GB   ← 세 모달리티(US·MRI·맘모) 공유
  configs/medsam3_v1.yaml
```

`sam3/` 는 통째로 복사한다. 일부만 추리지 말 것 — 지연 임포트가 있어 특정 경로에서만 터진다.

### 파이썬

`requirements.txt` 참조. Python 3.12 / CUDA 13.0 에서 검증.

---

## 2 · 서버로 옮길 때 고쳐야 할 경로

`configs/us_lora.yaml` 이 전부 절대경로다. **네 줄을 서버 기준으로 고친다.**

```yaml
model:
  checkpoint:         .../MedSAM3/ckpt/medsam3_merged.pt
  merge_lora_config:  .../MedSAM3/configs/medsam3_v1.yaml
  medsam3_repo:       .../MedSAM3
output:
  ckpt_dir:           .../us/serving/ckpt
```

서버 코드에서 파일 경로는 **전부 절대경로**로 쓸 것 — `load_model()` 이 내부에서
`os.chdir` 하기 때문이다(끝나면 되돌리지만, 상대경로는 호출 시점에 따라 의미가 달라진다).

---

## 3 · 실행 방법

```python
from infer_us import load_model, predict

bundle = load_model("configs/us_lora.yaml")   # 프로세스당 1회 · 약 10초
result = predict(bundle, image)               # 요청마다 · 약 420 ms
```

`image` 는 **파일 경로 · PIL.Image · numpy 배열** 아무거나 받는다.

### FastAPI 예시

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile
from PIL import Image
import io, sys
sys.path.insert(0, "/절대경로/us/serving/code")
from infer_us import load_model, predict

BUNDLE = {}

@asynccontextmanager
async def lifespan(app):
    BUNDLE["us"] = load_model("/절대경로/us/serving/configs/us_lora.yaml")
    yield
    BUNDLE.clear()

app = FastAPI(lifespan=lifespan)

@app.post("/us/predict")
async def us_predict(file: UploadFile):
    img = Image.open(io.BytesIO(await file.read()))
    r = predict(BUNDLE["us"], img)
    r.pop("_mask", None)          # numpy 배열 — JSON 직렬화 전에 반드시 제거
    return r
```

**워커는 1개로 둘 것.** 프로세스마다 모델이 올라가 `N × 6.5 GB` 가 필요해진다.
GPU 는 어차피 직렬 처리이므로 동시 요청은 큐로 넘긴다.

### 로딩 순서 — 바꾸면 안 된다

```
1  import_medsam3()              sys.path 추가 + os.chdir
2  build_model(load_lora=False)  병합본 로드 + LoRA 구조 주입
3  load_pixel_decoder()          UNet 픽셀 디코더로 교체
4  load_lora_weights()           학습된 LoRA 적재
5  load_grading_heads()          등급 헤드(앙상블)
```

**3 과 4 의 순서가 핵심이다.** 디코더를 먼저 교체한 뒤 LoRA 를 실어야 한다.
반대로 하면 디코더가 무작위 초기값으로 남는데 **에러가 나지 않는다.**

---

## 4 · 출력 JSON

```jsonc
{
  "file": "case001.png",                 // PIL/numpy 입력이면 null
  "image": { "width": 274, "height": 351 },
  "lesion_found": true,
  "score": 0.912764,                     // argmax 쿼리 검출 점수
  "n_detections": 1,                     // threshold 를 넘은 쿼리 수
  "mask_from": "argmax_query",
  "mask_area_px": 1321,

  "mask_reliability": {                  // "병변을 제대로 찾았나"
    "level": "높음",                      // 높음 | 보통 | 낮음
    "reason": null,                      // 낮음일 때만 사유
    "dim_shape_metrics": false           // true 면 형태 지표를 흐리게 표시
  },

  "grade": {
    "display": "4~5",                    // ★ 화면에 그대로 출력
    "value": 5,
    "is_range": true,                    // true 면 구간 표기
    "confidence": "보통",                 // "등급이 확실한가" — 위와 별개 축
    "ambiguity": 0.1234,
    "boundary_p": [0.547, 0.369, 0.216], // [P(y>2), P(y>3), P(y>4)]
    "malignancy": 0.000222               // 참고값 — 화면 비노출
  },

  "shape": {                             // 병변 미검출이면 null
    "unit": "px",                        // ★ mm 아님
    "area_px": 1321, "max_diameter_px": 63.9,
    "bbox_w_px": 62, "bbox_h_px": 39,
    "height_width_ratio": 0.629, "taller_than_wide": false,
    "solidity": 0.914, "boundary_irregularity": 1.071, "circularity": 0.571,
    "n_components": 1
  },
  "orientation_label": "가로로 긴 병변",

  "polygons": {                          // 원본 픽셀 좌표계
    "outer": [ [[186,82],[185,80], ...] ],
    "holes": [],
    "n_components": 1,
    "dropped_specks": 0
  },

  "params": { ... },
  "_mask": "<numpy bool>"                // ★ JSON 직렬화 전에 제거
}
```

### 화면 표기 규칙

| 표시할 것 | 하면 안 되는 것 |
|---|---|
| `grade.display` 그대로 ("4~5", "3") | `is_range` 무시하고 단일 등급으로 바꾸기 |
| `orientation_label` ("세로로 긴 병변") | "비평행 — 악성 의심" 같은 해석 |
| 형태 지표 수치 그대로 | "불규칙한 경계" 같은 서술어 생성 |
| 크기에 "px" 명시 | mm 로 환산 |

`dim_shape_metrics` 가 `true` 면 형태 지표를 흐리게 하거나 감춘다.

`polygons` 는 SVG 로 그린다. 테두리는 `stroke`, 내부는 `fill-opacity` — 판독의가
투명도만 실시간 조절할 수 있다(서버 재호출 불필요). `holes` 가 있으면 `fill-rule="evenodd"`.

**중간 등급(3·4)에서는 확신도 "높음"이 나올 수 없다.** CORAL 구조상 필연이며 버그가 아니다.
UI 안내문에 넣을 것.

---

## 5 · 자원과 성능

| 항목 | 값 |
|---|---|
| VRAM — 로딩 후 | 3.90 GB |
| VRAM — 추론 peak | **5.69 GB** (reserved 6.46 GB) |
| 로딩 시간 | 약 10 초 (파일 캐시가 더울 때) |
| 추론 시간 | 약 420 ms/장 (1008×1008) |
| 시스템 RAM | 로딩 중 병합본을 CPU 로 올리므로 8 GB 여유 |

RTX 5090(32 GB) · torch 2.13.0+cu130 · **다른 학습과 GPU 공유 중** 실측.
**워커 1개면 VRAM 8 GB 로 충분하다.**

---

## 6 · 임계값·확신도 경계 — **운영 정책 영역**

우리가 고정할 값이 아니다. 과소평가(실제 5인데 4로)와 과잉검사 중 무엇을 피할지는
임상에서 정한다. 기본값은 "5 재현율 ≥ 0.80 을 유지하는 조합 중 정확도 최대"일 뿐이다.

```yaml
# configs/us_lora.yaml — 서버 전체 기본값
inference:
  t4: 0.50
  conf_hi: 0.35
```
```python
predict(bundle, img, t4=0.50)      # 요청 단위
```

**`t2 · t3` 는 두고 `t4` 만 조정하는 것을 권한다** — 전체 격자 최적점은
374장에 과적합돼 순서가 뒤집힌 구석으로 간다.

`t4` 단독 조정 시 (valid 374장):

| t4 | 정확도 | 4 재현율 | **5 재현율** | 4→5 오분류 |
|---|---|---|---|---|
| 0.40 | 0.5107 | 0.331 | **0.917** | 67 |
| **0.45 (기본)** | 0.5321 | 0.393 | **0.889** | 58 |
| 0.50 | 0.5561 | 0.483 | 0.778 | 45 |
| 0.60 | 0.5749 | 0.552 | 0.694 | 35 |
| 0.95 | 0.5909 | 0.669 | **0.389** | 18 |

**정확도가 가장 높은 지점(t4=0.95)이 임상적으로 가장 위험하다** — 5 재현율 0.389.
전체 5,832 조합은 `archive/eval_out/threshold_sweep.csv`.

확신도 경계 `0.10 / 0.30` 도 조정 가능하지만 0.10 이 분리력 최대점이다
(0.12 를 넘으면 "낮음"이 절반을 넘고 그 이상 올려도 나머지 구간이 좋아지지 않는다).

---

## 7 · 성능 — valid 와 외부 검증

**두 숫자를 함께 볼 것.** valid 는 개발에 썼으므로 낙관 편향이 있다.

| | valid (BUS-BRA 374장) | **test (BrEaST 197장)** |
|---|---|---|
| 성격 | 개발용 — 헤드 선택·임계값 조정에 사용 | **외부 검증 — 1회만, 조정 안 함** |
| Dice | 0.9102 | **0.7882** |
| IoU | 0.8432 | 0.6873 |
| p10 | 0.8351 | 0.5010 |
| 빈 예측 | 0장 | 4장 (2.0%) |
| 등급 정확도 | 0.5321 | 0.4619 |
| ±1 이내 | 0.9412 | **0.9492** |
| 화면 표기 적중률 | 0.6979 | 0.8173 |
| '4~5' 구간 포함률 | 0.910 | **0.974** |
| BI-RADS 5 재현율 | 0.889 | **0.935** |

**운영 기대치는 test 쪽에 가깝게 잡을 것.**

### 분할이 −0.122 떨어진 이유

**장비 단서를 외운 것이 아니라 도메인 이동이다.** 근거 셋 —
① 등급별 균일 하락(4a 0.797 · 4b 0.774 · 4c 0.780 · 5 0.799),
② 하락이 꼬리에서 옴(73% 는 Dice 0.80 이상, 중앙값 0.8598),
③ 다중 검출이 6.1% → 22.3% 로 늘어 "확신이 흩어지는" 형태.

전처리 차이(밝기 −20% · RGBA 알파)로 설명되는 몫은 **10% 미만**이다.

### 화면 적중률이 오른 것은 성능 향상이 아니다

BrEaST 는 BI-RADS 4·5 가 **185/197(93.9%)** 로 몰려 있어 "4~5" 구간 표기가
58.9% 에 적용된다(valid 는 48.4%). **인구 구성 차이**다.
실제로 검증된 것은 **포함률 0.974** 와 확신도 단조성(0.972 → 0.833 → 0.662)이다.

### ⚠ 이 수치는 "검진 성능"이 아니다

두 데이터셋 모두 **조직검사가 필요하다고 판단된 병변**을 모은 집합이다.

| | 악성 비율 |
|---|---|
| BUS-BRA (train/valid) | 32.4% / 32.1% |
| BrEaST (test) | 49.7% |
| **실제 검진 인구** | **약 0.6%** |

**50~80배 차이다.** 무증상 검진 인구에 그대로 적용하면 위양성이 폭증한다.
같은 이유로 `grade.malignancy` 의 **절대값을 신뢰하면 안 된다**(순위 지표로만).
화면에 노출하지 않는 이유도 이것이다.

### 알려진 약점

- **BI-RADS 4 재현율 0.309** — test 139장 중 70장을 5로 올린다. BUS-BRA 에
  4a/4b/4c 세분이 없어 4↔5 분리 상한 자체가 AUC 0.758 이다.
- **BI-RADS 3 은 평가되지 않았다** — test 에 12장뿐. 특이도 0.417 의 CI 가 매우 넓다.
- **BI-RADS 2 는 전혀 평가되지 않았다** — test 에 0장.

---

## 8 · 마스크 신뢰도 "낮음" 비율 — 도메인 이동 감시

`mask_reliability.level` 의 분포를 **집계해서 모니터링할 것.**
입력 영상 성격이 학습 데이터와 달라지면 이 값이 먼저 움직인다.

| 구간 | 학습 도메인(valid) | 다른 도메인(test) |
|---|---|---|
| 높음 | 81.3% | 58.4% |
| 보통 | 16.6% | 16.2% |
| **낮음** | **2.1%** | **25.4%** |

같은 규칙인데 "낮음"이 **12배** 늘었고, 실제 Dice 도 0.9102 → 0.7882 로 떨어졌다.
**모델이 스스로 "처음 보는 영상"임을 신고한 셈이다.**

```
낮음 비율 < 5%      정상
        5 ~ 15%     주의 — 장비·프로토콜 변경 여부 확인
        > 15%       경고 — 분할 품질 저하 가능. 재학습·재보정 검토
```

일간·장비별로 집계할 것. **개별 요청이 아니라 비율의 변화가 신호다.**

---

## 9 · 주의사항

**① 위치는 모델이 내지 않는다**

판독문의 "좌측 유방 상외측"은 모델 출력이 아니다. 모델은 좌·우도 사분면도 모른다.
**검사 정보에서 받는다** — DICOM `ImageLaterality`(0020,0062) · `ViewPosition` 등.
사분면·시계방향은 DICOM 표준 태그에 없어 검사자 입력이나 오더 정보가 필요하다.

**② 파일명 `-l` / `-r` 은 좌·우가 아니다**

BUS-BRA 의 `bus_0001-l.png` / `-r.png` 는 **같은 병변의 다른 뷰**다
(645쌍 중 644쌍이 등급·병리까지 동일). **파일명에서 좌우를 뽑는 코드를 넣지 말 것.**

**③ 크기는 픽셀 단위다**

BUS-BRA·BrEaST 어디에도 pixel spacing 이 없고 이미지마다 잘라낸 범위가 달라
**이미지 간 크기 비교도 불가능하다.** 화면에 "px" 를 반드시 표기한다.
운영에서 DICOM 을 받으면 `PixelSpacing`(0028,0030) 으로 환산할 것.

**④ MedGemma 판독문 게이트**

판독문에 들어갈 수 있는 값은 **크기 · 위치 · 등급 · 조치뿐**이다.

| 항목 | 규칙 |
|---|---|
| 크기 | 마스크에서 계산(px). mm 로 환산하지 않는다 |
| **위치** | **입력값 그대로만. 생성 금지.** 입력이 없으면 적지 않는다 |
| 등급 | 구간 표기(`4~5`)를 단일 등급으로 바꾸지 않는다 |
| 조치 | 규칙표 결과 그대로 |

형태 지표를 문장으로 옮기거나("경계가 불규칙하고…") 확신도를 임상 판단으로
바꾸면("비평행 — 악성 의심") **반려**한다. 그 서술어를 검증할 라벨이 없다.

**⑤ 그 밖에**

- `_mask` 를 JSON 으로 내보내지 말 것 (numpy 배열).
- `n_detections > 1` 이면 판독의에게 알린다 — 마스크는 최고 점수 하나만 표시한다.
- 등급 헤드는 **앙상블**(`us_heads_ensemble.pt`)을 쓴다. 확정 설정이 seed 10개 확률
  평균이며 임계값도 그 위에서 골랐다. 단일 헤드를 쓰면 근거와 어긋난다.
- **전처리(mean/std 0.5)를 바꾸지 말 것.** LoRA·디코더가 이 전처리로 학습됐다.
  바꾸려면 재학습이 필요하다.

---

## 10 · 배포 후 확인

```bash
cd us/serving
pip install -r requirements.txt
python3 healthcheck.py                      # 파일·로드·추론·JSON 스키마 전부 점검
python3 healthcheck.py --image /경로/샘플.png # 실제 이미지로
```

CLI 로 한 장 돌려보기:

```bash
python3 code/infer_us.py --config configs/us_lora.yaml --image /경로/샘플.png
```

`infer_out/` 에 마스크 PNG 와 JSON 이 생기고 콘솔에 BI-RADS·확신도·크기·마스크
신뢰도가 나오면 정상이다.

---

자세한 실험 근거는 `../docs/experiments.md`, 발표용 수치는
`../docs/results_for_presentation.md`.
