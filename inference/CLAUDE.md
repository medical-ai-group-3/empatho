# EMPATHO — 유방암 CDSS

유방 영상(맘모 · 초음파 · MRI)과 병리 슬라이드를 AI 가 판독해 의사의 판독을 돕는 시스템.
AI 산출은 전부 제안 · 후보이고, 최종 판정은 의사가 한다.

2026-09-15 코드 기준. 이 레포는 워크스테이션 쪽이다.

---

## 공간 두 개

| | 레포 | 위치 | 하는 일 |
|---|---|---|---|
| **앱 서버** | `empatho-app` | app-host · Windows + Docker Desktop | API · DB · 파일 저장 · 판독 요청 · 화면 진입점 |
| **워크스테이션** | `empatho-inference` (이 레포) | `ssh -p 22 wsuser@ws-host` · GPU 32 GB · 학습 작업과 공유 | 판독 서버 · 리포트 서버 |

**GPU 는 워크스테이션에만 있다.** 모델은 앱 서버에 올라가지 않고, 앱 서버는 HTTP 로 부른다.

워크스테이션의 서비스는 전부 `127.0.0.1` 에만 열려 있다. 앱 서버의 `tunnel` 컨테이너가
SSH 포트 넘김으로 `8001`(판독) · `8002`(리포트) 두 포트만 잇는다.

```
앱 서버 (Docker 네트워크)                              워크스테이션
┌────────────────────────────────────────────┐        ┌──────────────────────────────┐
│ nginx :80 ── 밖에 열린 유일한 포트            │        │ 판독 서버   :8001  main.py     │
│ web (Django)   worker (Celery)   redis      │        │ 리포트 서버 :8002  report.py   │
│ file-gateway · llm-proxy · notify (Go)      │        │ Ollama     :11434 gemma3 12B │
│ postgres · garage · orthanc                 │        │ supervisor 가 8001 · 8002 관리 │
│ tunnel ════════════ SSH ═══════════════╪═══════▶│                              │
└────────────────────────────────────────────┘        └──────────────────────────────┘
```

---

## 데이터가 흐르는 길

```
[업로드]
화면 ─ 파일 + 티켓 ─▶ nginx ─▶ Go file-gateway ─▶ Garage empatho-original
                                  └─ 파일 등록 콜백 ─▶ Django: storage_object 행
                                  └─ DICOM 이면 ─▶ Orthanc ─ DICOM 정보 콜백 ─▶ Django ─▶ Garage 사본 삭제

[판독]
Django: ai_result 행(queued) ─▶ Redis ─▶ Celery worker (core/tasks.py run_inference)
  worker ─ 티켓 ─▶ Go ─▶ Garage 파일 / Orthanc 인스턴스 / Orthanc 시리즈 zip 받기
  worker ─▶ tunnel ─▶ 판독 서버 POST /analyze/{소켓} ─▶ 판독 결과 JSON

[리포트]
Go llm-proxy ─▶ tunnel ─▶ 리포트 서버 POST /report/{소켓} ─▶ Ollama ─▶ 소견문
Go ─ 소견문 저장 콜백 ─▶ Django: report 행

[파생물]
worker ─ 파생물 티켓 ─▶ Go /svc/v1/derived ─▶ Garage empatho-derived ─ 파일 등록 콜백 ─▶ Django: image 행
```

**아직 이어지지 않은 구간** (2026-09-15)

| 구간 | 상태 |
|---|---|
| 판독 요청 → 태스크 투입 | Django `POST /studies/{id}/ai-results` 가 `ai_result`(queued)만 만들고 태스크를 넣지 않는다 |
| 판독 결과 → `ai_result` 기록 | worker 가 결과를 로그와 Redis 요약으로만 남긴다 |
| 판독 → 리포트 요청 | 부르는 곳이 없다. Django 에 리포트 티켓 발급 용도가 없다 |
| MRI 메시 → 파생물 저장 | Go · 설정은 준비됐고 worker 의 업로드 코드가 없다 |
| 완료 알림 | notify 에 발행하는 곳이 없다 |

---

## 이 레포

| 파일 | 역할 |
|---|---|
| `main.py` | 판독 서버(8001). `POST /analyze/{소켓}` · `GET /healthz` |
| `report.py` | 리포트 서버(8002). `POST /report/{소켓}` · `GET /health` |
| `sockets/base.py` | 소켓 공통부 — 적재 · 상태 · 락 |
| `sockets/gpu.py` | GPU 락 하나 · 유휴 시계 하나 · 수거자 하나 |
| `sockets/medsam3.py` | MedSAM3 백본 공유 |
| `sockets/us · mammo · mri · pathology.py` | 모달리티별 적재 · 판독 |
| `prompts/` | 모달리티별 판독값 → 사실 문장 · 안내 · 보존할 수치 |
| `thresholds.yaml` | 소켓별 임계값 덮어쓰기 |
| `smoke.py` | 배포 뒤 `/analyze` 점검 |
| `supervisord.conf` | `inference`(8001) · `report`(8002) 프로그램 |
| `models/` | 가중치 · 모델 코드 링크 (git 에 없다) |

supervisor 명령: `/usr/local/bin/python3.12 -m supervisor.supervisorctl -c ~/app/supervisord.conf status`

---

## 소켓

| 요청 소켓 | 처리 소켓 | 대상 | 입력 | 응답 결과 |
|---|---|---|---|---|
| 5 · 4 | **5** | 초음파 | PNG · JPG 1장 | 병변 유무 · 형태 지표 · 등급 · 윤곽 좌표 |
| 4b | **4b** | 맘모 | DICOM 1장 | 병변 상자 · 서술어 · BI-RADS · 생검 권고 |
| 3 | **3** | MRI | 조영 전 볼륨(`image`) + 조영 후 볼륨(`post`, 선택) · zip 또는 NIfTI | 조영 전만: 밀도(phases=1) · 둘 다: 병변 + 밀도(phases=2) · 3D 메시 포함 |
| 1 · 2 | **1** | 병리 | 크롭 이미지 1장 | sTIL · 세포 수 · 면적 |

- 4 → 5, 2 → 1 로 넘긴다. 같은 파이프라인이다. 넘어가면 응답에 `requested_socket_id` 가 실린다.
- 판독이 안 되면 HTTP 200 에 `abstained: true` 와 `reason` 을 준다. 500 을 내지 않는다.
- 초음파 픽셀 마스크는 소켓이 응답에서 뺀다. 병리 조직 마스크는 꺼 두었다. 병리 세포 좌표는 모델이 응답에 넣지 않는다.
- MRI 응답은 48 MB 안팎이고 대부분이 3D 메시다. 앱 서버가 메시를 떼어 파생물로 저장한다.
- 환자 식별자는 받지 않는다. MRI 응답의 `patient_id` 는 모델 기본값 `"unknown"` 이다.

**MedSAM3 백본(3.37 GB)은 한 벌만 올리고** 소켓 3 · 5 · 4b 가 어댑터만 바꿔 쓴다.
어댑터 자리는 가장 넓은 설정(458)으로 한 번만 만들고, 교체 때마다 B 행렬을 0 으로 비운 뒤 적재한다.
초음파가 바꾸는 픽셀 디코더는 교체 때 되돌린다.

GPU 는 요청이 없으면 30초 뒤 프로세스를 끝내 회수한다(supervisor 가 다시 띄운다).
그래서 유휴 뒤 첫 요청은 모델 적재 시간이 붙는다 — 맘모 약 20~70초, MRI 약 50초~3분 (2026-09-11 · 14 실측).

**리포트 서버**는 `/report/{소켓}` 에 소켓 번호(`5` · `4b` · `3` · `1`)와 이름(`us` · `mammo` · `mri` · `pathology`)을 모두 받는다.
수치와 판단은 코드가 문장으로 만들고, 모델(온도 0)은 엮기만 한다. 모델이 수치를 바꾸면 코드가 만든 문장으로 대체한다(`fallback`).

---

## 저장

| 무엇 | 어디에 |
|---|---|
| **DICOM (맘모 · MRI)** | **Orthanc 에만.** Garage 에 먼저 저장했다가 Orthanc 저장과 DICOM 정보 콜백이 성공하면 Garage 사본을 지운다. Orthanc 전송이 실패하면 Garage 에 남는다 |
| 초음파 이미지 · 병리 슬라이드 · PDF | Garage `empatho-original` |
| MRI 메시 등 파생물 | Garage `empatho-derived` |

DB `storage_object` 행은 DICOM 이면 `orthanc_series_id` · `sop_instance_uid` 를, 나머지면 `bucket` · `object_key` 를 가리킨다.

---

## 지키는 규칙

1. **DB 는 Django 코드만 쓴다.** Go 는 콜백으로 Django 가 쓰게 한다. Celery worker 는 Django 코드라 직접 쓴다.
2. **파일 바이트는 Go 만 다룬다.** worker 도 저장소에 직접 가지 않고 Go 에서 받는다. Go 는 Django 가 서명한 티켓만 받는다.
3. **판독 서버 · 리포트 서버는 실패를 기권으로 돌려준다.** HTTP 200 · `abstained`.
4. **환자 식별자를 워크스테이션으로 보내지 않는다.** 영상은 디스크에 쓰지 않는다(MRI 만 임시 폴더에 풀고 지운다).
5. 설명 · 문서에 명세 번호를 쓰지 않는다. 「파일 등록 콜백」 「DICOM 정보 콜백」 「소견문 저장 콜백」처럼 하는 일로 쓴다.

---

## 배포

| 레포 | 트리거 | 순서 |
|---|---|---|
| `empatho-inference` | `main` push | 워크스테이션 러너 → `git pull` → 문법 검사 → supervisor `restart inference report` → `/healthz` → `smoke.py` → 실패하면 이전 커밋으로 `git reset` |
| `empatho-app` | `main` push | 앱 서버 러너 → 설정 복사(`~/empatho-conf`) → `docker compose up -d --build` → `migrate` → nginx 문법 검사 · 다시 읽기 → 경로 확인 |

**push 가 곧 운영 배포다.** 앱 서버는 개발 PC 이자 운영 서버이자 배포 러너다.

설정 파일은 git 에 없다 — 앱 서버 `conf/*.env` · `conf/garage/garage.toml` · `conf/ws/`(SSH 자격).
