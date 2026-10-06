# 초음파(경로 B)

BUS-BRA lesion 분할 + BI-RADS 등급(CORAL). 2026-08-28 재구성.

```
serving/     서버에 올릴 것 (80 MB)      → serving/README.md
training/    재학습할 때만 (2 MB)         → training/README.md
archive/     보관. 서버 제외 (4.0 GB)     → archive/README.md
docs/        실험 기록 · 발표용 수치
```

## 빠른 시작

**배포 후 제일 먼저:**

```bash
cd serving
pip install -r requirements.txt
python3 healthcheck.py                       # 파일·의존성·로드·추론·JSON 전부 점검
python3 healthcheck.py --image /경로/샘플.png  # 실제 영상으로
python3 healthcheck.py --skip-infer          # 파일·의존성만 (GPU 불필요)
```

**한 장 추론:**

```bash
python3 code/infer_us.py --config configs/us_lora.yaml --image /경로/샘플.png
```

**서버 코드에서:**

```python
from infer_us import load_model, predict
bundle = load_model("configs/us_lora.yaml")   # 프로세스당 1회
result = predict(bundle, image)               # 요청마다
```

## 서버에 함께 필요한 것

`serving/` 만으로는 안 된다. **MedSAM3 저장소**가 있어야 한다.

```
MedSAM3/
  sam3/ · lora_layers.py · merge_medsam3.py
  ckpt/medsam3_merged.pt      3.2 GB — US·MRI·맘모 공유
```

옮긴 뒤 `serving/configs/us_lora.yaml` 의 `model.*` 세 줄과 `output.ckpt_dir` 를
서버 기준으로 고칠 것.

## 꼭 알아야 할 것

- **등급 헤드는 앙상블**(`us_heads_ensemble.pt`)을 쓴다. 임계값을 확률 평균 위에서 골랐다.
- **`archive/eval_out/` 을 지우지 말 것.** 표본별 CSV 가 없으면 대응 검정을 할 수 없다.
- **위치 정보는 모델이 내지 않는다.** DICOM 에서 받는다. 파일명 `-l`/`-r` 은 좌우가 아니다.
- **크기는 픽셀 단위다.** pixel spacing 이 데이터에 없다.
- **전처리(mean/std 0.5)를 바꾸지 말 것.** 바꾸려면 재학습해야 한다.

자세한 내용은 각 폴더의 README 와 `docs/experiments.md`.
