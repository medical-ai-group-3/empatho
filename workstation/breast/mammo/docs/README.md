# 맘모그래피 판독 — 한 장 안내

2026-09-09 기준. **이 문서는 요약이다.** 수치의 근거와 계약의 원본은
아래 문서들에 있다. 어긋나면 그쪽이 맞다.

---

## 1. 무엇을 하는 것인가

유방촬영 DICOM 한 장을 받아 **병변의 자리와 등급**을 낸다.

```
DICOM → norm8(상위 0.1% 자름) → 조직 상자(여백 32)
      → 1008px 타일(겹침 256) → 검출 → 겹침 합치기 wbf@0.3
      → 타일 조직 비율 0.30 미만 버림 → 깊이 가중(석회 0.15 · 종괴 0.35)
      → 임계값(석회 0.448 · 종괴 0.462) → 자르기(+20px)
      → 서술어 → 규칙표 → BI-RADS
```

**판독 보조기다. 검진 선별기가 아니다.** 이 구분이 왜 중요한지는
`screening_limit.md` 에 실측과 함께 있다.

---

## 2. 지금 수치

| | 값 |
|---|---|
| 검출기 | MedSAM3 + LoRA r16 α32 · 458 모듈 · **에폭 8** |
| 서술어 | 석회 ep23 F1 0.660 (13축) · 종괴 ep19 F1 0.569 (12축) |
| 임계값 | 석회 **0.448** · 종괴 **0.462** |
| 작동점 | **종류당 오탐 2개/영상** (영상당 예산 4개) |
| 최대 재현율 | 석회 94.9 · 종괴 95.3 |
| 끝에서 끝까지 | 위치를 알려주면 **90.0%** · 스스로 찾으면 **70.2%** |
| 그 분해 | 검출기 79.7% × 서술어 88.0% |
| 영상당 | 표시 3.87개 · 조직검사 권고 2.72개 |

**정상 유방에서 무엇이 나오나** — VinDr BI-RADS 1, 75건 300장 실측.

```
조용한 영상          5.3%
영상당 조직검사 권고  81.0%
검사 단위            100%      ← 네 장 중 하나는 반드시 걸린다
```

**고장이 아니라 이 작동점의 대가다.** 영상당 2.30개는 예산(4개) 안이다.
서술어 모델에 「소견 없음」 항목이 없어서 그렇고, 고치려면 정상 조각을
넣어 다시 학습해야 한다. 발표 뒤로 미뤘다.

**판독 시간** (RTX 5090 · 32GB 공유)

| | 카드 단독 | 다른 작업과 공유 |
|---|---|---|
| 사진 1장 (p95) | 12.2초 | 26.9초 |
| 검사 1건 (4장) | 49초 | 108초 |

적재 20~33초 · GPU 최고 10.6GB. **워커는 1개다.** 자세한 것은
`serving_capacity.md`.

---

## 3. 돌리는 법

### 판독 한 장

```bash
cd ~/workspace/breast/mammo
python3 training/code/infer_mammo.py --image <파일.dcm> --json /tmp/out.json
```

### 서빙 점검 — 고치고 나면 이것부터

```bash
python3 training/code/check_serving.py --stage 1    # GPU 안 씀
python3 training/code/check_serving.py --stage 2    # 실제로 태운다
```

**2단계는 GPU 여유가 14GB 넘어야 돈다.** 모자라면 스스로 거부한다.
`--force` 는 남의 작업을 밀어내므로 쓰지 않는다.

2단계가 응답을 `mammo_api.md` 선언과 **완전히 대조**한다. 키가 하나만
많거나 적어도 실패한다. **응답 구조를 건드린 날에는 그날 안에 한 번
태울 것** — 안 돌리면 코드와 선언이 조용히 갈라진다.

### 자리 정리

```bash
python3 training/code/survey_disk.py     # 무엇이 자리를 먹나 (읽기만)
python3 training/code/tidy.py            # 큰 것 — 묶음별로 켠다
python3 training/code/declutter.py       # 묵은 파일 — 참조 확인 후
```

셋 다 기본은 보기만 하고, `--go` 를 줘야 지운다.

---

## 4. 문서 — 무엇이 어디 있나

| 문서 | 무엇 |
|---|---|
| **`mammo_api.md`** | **응답 계약.** §5.2 가 `detail` 키 목록의 **원본**이다 |
| `boundary.md` | 무엇을 하고 무엇을 안 하는지, 그 결정의 근거 |
| `evidence_text.md` | 판독문 문안 규칙. 금지 넷 |
| `screening_limit.md` | 정상 유방 실측과 한계 |
| `serving_capacity.md` | 판독 속도·용량·타임아웃 |
| `results_for_presentation.md` | 발표 근거 전체 |

DB 는 **v10** 을 따른다. 응답의 크기 필드는 `ai_size_*`(AI 원본·불변)이고
판독의 캘리퍼 값 `measured_size_*` 는 우리가 안 건드린다. `certainty` 는
축 수가 종류마다 달라 `certainty_axes` 를 같이 낸다 — 종류를 섞어
정렬하려면 나눠 써야 한다(`mammo_api.md` §5.3).

---

## 5. 건드리면 안 되는 것

```
medsam3/ckpt · configs · sam3 · lora_layers.py · merge_medsam3.py
    전부 심볼릭 링크다. 지우면 링크 너머 3.4GB 백본이 날아간다.

training/ckpt/last_lora.pt
    서빙이 쓰는 검출기다.
training/ckpt/mammo_{calc,mass}_trunk_last_grid4_pad0_clip999_lora.pt
    서술어 둘.

~/workspace/breast/train   MRI — 다른 팀
~/workspace/breast/us      초음파 — 다른 팀
~/workspace/breast/data    다른 팀. 단 data/vindr 는 맘모 팀 것
```

`runs/det_run/checkpoints/checkpoint.pt` (9.3GB)는 **기준선**이다 —
LoRA 를 안 쓰고 통째로 미세조정한 대조군. 「왜 LoRA 냐」를 다시 보여줄
수 있는 유일한 파일이라 발표 전까지 둔다.

---

## 6. 이 저장소는 밖으로 나가지 않는다

**원격이 없다. 절대 push 하지 않는다.** 이유가 둘이다.

- 병합 체크포인트에 **SAM 3 가중치**가 들어 있다 — SAM 라이선스상
  외부 공유·공개 저장소 업로드 금지
- `docs/examples/` 의 그림은 **CBIS-DDSM 파생**이다. 재배포 금지

그 밖의 자료 조건

| | |
|---|---|
| CBIS-DDSM | 재배포 금지. 각자 TCIA 에서 받는다 |
| Mammo-CLIP | CC BY-NC-SA 4.0 — 비영리, 파생물도 같은 조건 |
| Virchow2 | CC BY-NC-ND 4.0 · HF 승인 필요 |
| EMBED | DUA 서명함. **자료·접근 정보를 누구와도 공유하지 않는다.** 같은 기관 동료 포함. `chmod 700` 폴더에 둔다 |

PhysioNet 인증 정보는 `~/.netrc`(600)에 있다. **로그나 명령 이력에
찍히지 않게 할 것.**

---

## 7. 자리를 되돌리려면

작업 폴더에서 지운 것은 대부분 git 안에 그대로 있다.

```bash
git checkout -- docs/            # 통째로
git checkout -- <파일>            # 한 개
git log --oneline -10            # 언제 무엇이 바뀌었나
```

`*.pt` · `*.npz` · `*.tar` · `archive/` · `runs/` · `data/` ·
`training/ckpt/` · `*.bak*` 는 무시 규칙에 걸려 **git 에 없다.**
이것들은 지우면 다시 만들거나 다시 받아야 한다.
