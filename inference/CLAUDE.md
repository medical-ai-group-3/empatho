# EMPATHO — 유방암 CDSS

유방 영상(맘모·초음파·MRI)과 병리 슬라이드를 AI 가 읽고 의사의 판독을 돕는 시스템.
AI 산출은 전부 제안·후보이고, 최종 판정은 의사가 한다.

---

## 전체 그림

```
앱 서버 / 팀원 PC — empatho-app            워크스테이션 — empatho-inference
┌──────────────────────────────┐          ┌──────────────────────────────┐
│ postgres      gateway (Go)   │          │ FastAPI                      │
│ web (Django)  garage·orthanc │══Tail═══▶│   소켓 1·2·3·4·4b·5 — GPU    │
│ redis         worker (Celery)│  scale   │ Ollama · MedGemma — 소켓 6   │
└──────────────────────────────┘          └──────────────────────────────┘
```

**GPU 는 워크스테이션에만 있다.** 그래서 모델은 앱 서버 어디에도 올라가지 않고, 앱 서버는 HTTP 로 부르는 쪽이 된다. 이 한 가지가 나머지 배치를 대부분 결정한다.

---

## 네 프로세스

| | 위치 | 하는 일 |
|---|---|---|
| **web** (Django) | 앱 서버 | 공개 API · 권한 판정 · **DB 쓰기 전담** · 전송 티켓 발급 |
| **worker** (Celery) | 앱 서버 | 추론 요청을 FastAPI 로 보내고 결과를 기록 |
| **gateway** (Go) | 앱 서버 | **바이트 전담** — 업로드·다운로드·타일 서빙 · Ollama 호출 |
| **inference** (FastAPI) | 워크스테이션 | **소켓 1~5 추론만** |

**두 줄로 갈린다.**
1. Django 만 DB 를 쓴다 — Go 는 `I-1`~`I-5` 콜백으로 Django 가 쓰게 한다.
2. Go 만 바이트를 만진다 — Django 가 서명한 티켓이 없으면 받지 않는다.

---

## 추론이 흐르는 길

```
POST /studies/{id}/ai-results  →  ai_result(queued)  →  Redis 큐
     →  Celery 워커  →  FastAPI(워크스테이션)  →  결과 기록  →  GET /ai-results/{id}
```

소켓 1~5 는 **워커가 FastAPI 를 직접 호출**한다. Go 를 경유하지 않는다.
Go 가 부르는 LLM 은 소켓 6(리포트 서술·챗봇)의 Ollama 뿐이다.

`INFERENCE_MODE` 값 하나로 전송 방식이 갈리고 호출부는 바뀌지 않는다 — `mock`(기본) / `direct`(Tailscale).
추론 서버가 안 닿으면 예외가 아니라 **기권 결과**를 돌려준다.

---

## 소켓 — 모델이 들어갈 자리

| 소켓 | 대상 | 백본 | 출력 |
|---|---|---|---|
| 1 | 병리 조직 분할 | Virchow2 | 조직 영역 |
| 2 | 병리 세포 검출 | SAM-H · CellViT++ | 세포 좌표 |
| 3 | MRI 병변 분할 | MedSAM3 | 마스크 |
| 4 | 초음파 분할 | MedSAM3 | 마스크 |
| 5 | 초음파 등급 | MedSAM3 | CORAL 등급 |
| 4b | 맘모 서술어 | MedSAM3 | 서술어 → 규칙표 → 등급 |
| 6 | 리포트 · 챗봇 | Ollama · MedGemma | 서술 문장 |

**MedSAM3 백본(3.2GB·동결)은 한 벌만 상주**하고, 소켓 3·4·5·4b 가 LoRA 어댑터와 헤드만 바꿔 쓴다.
병리 두 소켓은 백본을 완전히 얼려 두고 헤드만 다르다.

---

## 저장 — MRI 만 Orthanc

| 무엇 | 어디에 |
|---|---|
| **MRI** | **Orthanc** (DICOMweb) |
| 맘모 · 초음파 · 병리 WSI · PDF | Garage `empatho-original` |
| 타일 · 썸네일 · 마스크 | Garage `empatho-derived` |

어느 것도 두 곳에 두지 않는다. MRI 만 볼륨이라 진짜 DICOM 서버가 필요하고, 나머지는 2D 라 타일로 서빙한다.

---

## 레포 구조 — `empatho-app`

```
services/web/          Django — empatho/(settings·urls) + api/(models·views·tasks·inference)
services/gateway/      Go — main.go
mock_inference/        FastAPI 스텁 (개발용)
conf/                  garage.toml · orthanc.env  ← git 에 없다
scripts/               init-config · bootstrap · smoke · update-server · restore-db
compose.yml            개발 스택 (web · worker · gateway · redis · mock)
compose.server.yml     공유 데이터 (postgres · garage · orthanc)
compose.localdb.yml    로컬 DB 오버레이
```

`empatho-inference` 는 훨씬 작다 — `main.py`(FastAPI) + `models/`(가중치, 심볼릭 링크) + 배포 워크플로.

---

## 실행

```bash
docker compose -f compose.yml -f compose.localdb.yml up -d   # 팀원 기본
docker compose up -d web                                     # Django 만 고칠 때
docker compose -f compose.server.yml up -d                   # 서버 담당
```

**`/healthz` 가 진도표다.** 붙는 것이 늘 때마다 항목이 하나씩 는다.

```json
{ "status": "ok", "checks": { "postgres": "ok" } }
```

---

## API 표면

- 공개 API `/api/v1` — 89개. snake_case, 응답 봉투 `{success, data, error, trace_id}`
- Go 서비스 `/svc/v1` — 파일(`G-F*`) · 알림(`G-N*`) · LLM(`G-L*`)
- 내부 콜백 `/internal/v1` — `I-1`~`I-5`. Go 가 DB 를 쓰지 않기 위한 통로

상세는 `CDSS_API_명세서_v3.docx` 와 `CDSS_DB_설계문서_v3.docx`.
