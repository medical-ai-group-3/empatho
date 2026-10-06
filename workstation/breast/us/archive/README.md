# 보관 — 서버에 올리지 않는다

재학습·재검정·논문에 필요할 수 있는 것들. **지우지 말 것.**

```
eval_out/          5.8 MB   표본별 평가 CSV
ckpt/              3.8 GB   과거 실험 체크포인트 · last · 옵티마이저 · 크래시 잔재
  experiments/     3.6 GB
  _crashed_run_0603/  71 MB
data/              194 MB   BUS-BRA train/valid + BrEaST test
logs/              832 KB   학습 로그
code/               28 KB   실험 스크립트
```

---

## `eval_out/` — **가장 중요하다. 절대 지우지 말 것**

표본별 평가 CSV. **대응 검정에 반드시 필요하다.**

두 설정을 비교할 때는 같은 데이터를 두 모델이 평가한 것이므로 대응 비교를 해야 하고,
그러려면 **이미지 하나하나의 결과**가 있어야 한다. 집계값(평균 Dice)만으로는 검정이 불가능하다.

실제로 SAM3-UNet 실험이 이 CSV 를 남기지 않아 한동안 "분할 상한" 주장을 검정하지
못했다. 나중에 모델을 다시 로드해 `dump_sam3unet_valid.py` 로 재생성해야 했다.

| 파일 | 내용 |
|---|---|
| `valid_joint_best.csv` | 조인트 30 epoch (등급 기준선) |
| `valid_aug_best.csv` · `valid_aug_last.csv` | 증강 실험 (기각) |
| `valid_unet_best.csv` | UNet 픽셀 디코더 조인트 |
| `valid_sam3unet_best.csv` | 분할 전용 (분할 상한) |
| `valid.csv` · `valid_last.csv` | 초기 5 epoch 분할만 |
| `valid_nolora.csv` | 병합본 단독 (LoRA 없음 기준선) |
| `test_final.csv` | **외부 검증 BrEaST — 1회 한정** |
| `threshold_sweep.csv` | 임계값 5,832 조합 |
| `valid/` | 시각화 PNG (재생성 가능) |

`training/code/paired_compare.py` 로 두 CSV 를 비교한다.

---

## `ckpt/experiments/`

과거 실험 체크포인트.

| | 내용 |
|---|---|
| `sam3unet_best.pt` · `sam3unet_last.pt` | 분할 전용 모델. "분할 상한"의 근거 |
| `aug_0826/` | 조인트 30 epoch 결과. 등급 기준선 |

`sam3unet_best.pt` 는 다른 아키텍처(`vit` + `up1~up4` + `reduce` + `head`)라
`eval_us_lora.py` 로 평가할 수 없다. `training/code/dump_sam3unet_valid.py` 를 쓴다.

---

## `ckpt/_crashed_run_0603/` — **결함 증거**

30 epoch 학습이 epoch 4 저장 중 저수준 I/O 오류로 죽었을 때의 잔재.

```
us_lora_best.pt         0 bytes   ← 저장하다 죽은 것
us_lora_last.pt      74 MB        ← 이전 epoch 것, 정상
us_heads_best.pt     10 KB
us_heads_last.pt     10 KB
```

**남겨두는 이유는 두 가지 문제를 동시에 보여주기 때문이다.**

1. **0바이트 파일이 정상 파일처럼 남는다.** `torch.save` 가 중간에 실패해도
   파일은 그대로 있어 크기를 확인하지 않으면 알 수 없다.
2. **`load_lora_weights` 는 `strict=False` 라 조용히 넘어간다.** 0바이트를 로드하면
   에러 없이 아무것도 안 싣고, **LoRA 가 전부 0 인 채로 추론하게 된다.**

또 `best` 와 `last` 의 epoch 이 어긋난 채 남아 어느 것이 짝인지 알 수 없었다.

이후 `atomic_save()`(`.tmp` 에 쓰고 성공 시 rename)와 매니페스트(`epoch · run · saved_at`)를
넣었다. 자세한 것은 `../docs/experiments.md` 11-2.

---

## `data/`

```
train/   BUS-BRA 1,495장 (병변 850개)
valid/   BUS-BRA   374장 (병변 212개)
test/    BrEaST    197장   ← 외부 검증 전용. 이미 1회 사용
```

**서버에 두지 않는다.** 동작 확인은 웹 업로드 → DB → 추론 흐름으로 하며,
파일을 미리 두면 실제와 다른 조건이 된다.

**주의** — 파일명 `-l` / `-r` 은 좌·우 유방이 아니라 **같은 병변의 다른 뷰**다.
따라서 이미지 1,495장은 병변 850개이고, 통계 검정은 **case 단위**로 해야 한다.

---

## `logs/`

학습 실행 로그. `<run-name>_<타임스탬프>.log` 형식.
`train_us_30ep_20260826_060323.log` 에 위 크래시의 traceback 이 남아 있다.

---

## `code/`

`experiments/train_sam3unet.py` — 분할 전용 모델 학습 스크립트.
`experiments/run_overnight.sh` — 야간 실행 셸.

---

## 정리해도 되는 것

- `eval_out/valid/` (4.6 MB) — 시각화 PNG. 재생성 가능하지만 논문 그림에 쓸 수 있어 남겨둠
- `ckpt/experiments/sam3unet_last.pt` (1.7 GB) — `best` 만 있으면 충분하다면 삭제 가능

**그 외에는 지우지 말 것.**