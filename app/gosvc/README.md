# gosvc — Go 서비스 계층 (명세 19장)

Django = 인증 · 권한 판정 · DB 쓰기 전부.
Go = **바이트와 디스패치**. 소켓 1~5(GPU 추론)는 Celery → FastAPI 직결이고
Go 를 안 거친다.

```
cmd/file-gateway   G-F1~G-F5   업로드 · 다운로드 (명세 19-2)
cmd/llm-proxy      G-L1 · G-L3 Ollama 호출 · 결과 전송 (명세 19-4)
```

## 처음 받았으면

```bash
go version        # 1.22 이상. 의존성을 1.22 에서 도는 판으로 내려 맞춰 놨다
go mod download   # minio-go 하나뿐이다. vendor 는 17MB 라 커밋 안 했다
go build ./... && go test ./... -race
```

`empatho-app` 저장소 안에 `gosvc/` 로 둔다. Django 와 별개 모듈이라
파이썬 쪽 도구는 이 폴더를 안 본다.

## 명세가 못 박은 것 넷 — 두 서비스 공통

| | |
|---|---|
| 권한 | Go 는 **Django 가 서명한 티켓만 검증**한다. 자체 판정 없음 (exp 5분 · nonce 1회용) |
| DB | Go 는 **Postgres 에 직접 안 쓴다.** 결과는 내부 콜백(I-1 · I-4)으로만 |
| 근거 | **근거 좌표 없는 문장은 버린다.** 버린 문장은 `dropped_sentence_log` 로 되돌린다 |
| 실패 | **Ollama 가 죽어도 리포트는 발급된다** — 503 `UPSTREAM_LLM_UNAVAILABLE`, `narrative_text=null` |

---

# file-gateway (명세 19-2)

```
G-F1  POST /svc/v1/upload/init                  청크 개시 → upload_id
G-F2  PUT  /svc/v1/upload/{upload_id}/part/{n}  청크 (개별 재시도 가능)
G-F3  POST /svc/v1/upload/{upload_id}/complete  병합 · sha256 · 커밋 → I-1
G-F4  POST /svc/v1/files                        단일 파일 (DICOM 낱장 · PDF) → I-1
G-F5  GET  /svc/v1/files/{object_key}           스트리밍 다운로드 (Range 지원)
      GET  /svc/v1/health
```

## 설계에서 짚어둘 것 넷

**① `object_key` 는 클라이언트가 못 정한다.**
키는 `티켓의 object_key_prefix` + `우리가 만든 난수 이름` + `확장자`다.
클라이언트가 준 파일명은 **확장자만** 참고한다.
그러지 않으면 `filename="../P-99/x.dcm"` 하나로 남의 환자 자리에 쓴다.
→ `TestKeyForIgnoresClientPath`

**② 상한은 받으면서 잰다.**
`io.LimitReader` 로 막으면 상한에서 **조용히 EOF** 가 나서 *잘린 DICOM 이
정상처럼 커밋된다.* 이 계통에서 제일 나쁜 결과다. `capReader` 는 넘는 순간
읽기를 실패시켜 저장 자체를 중단한다.
→ `TestCapReader` · `TestPutFileRejectsOverMaxBytes`

**③ 조각이 빠지면 거부한다.**
번호가 `1..N` 으로 안 이어지면 400 이다. 검사를 안 하면 조각 하나 빠진
**짧은 파일이 성공으로 커밋되고 아무 로그도 안 남는다.**
→ `TestCompleteRejectsMissingPart`

**④ 티켓 접두사가 권한 경계다.**
G-F5 는 `object_key` 가 티켓 접두사 아래가 아니면 403 이다.
경계에 `/` 를 붙여 비교한다 — 안 붙이면 `P-7` 티켓으로 `P-77` 을 읽는다.
→ `TestDownloadPrefixIsPathBoundary`

Range · If-Range 는 `http.ServeContent` 에 맡긴다. 직접 짜면 반드시 틀린다.

## I-1 이 실패하면 502 다

파일은 Garage 에 있는데 Django DB 에 없으면 **고아 객체**다. 200 을 내면
클라이언트는 성공으로 알고 그 파일은 영영 아무도 안 찾는다. 그래서 502 를
내고 로그에 키를 남긴다. 멱등키는 `obj:<object_key>` — 재시도가 중복 행을
만들면 안 된다.

명세 21장의 *"I-1 이 성공해야 I-2 가 유효하다"* 순서가 여기에 걸린다.

## 실행

```bash
export TICKET_KEY=...          # Django 와 공유
export CALLBACK_BASE=https://django-internal
export CALLBACK_SECRET=...     # I-1 X-Signature 키
export CALLBACK_CERT=/etc/ssl/go.crt   # 운영 필수
export CALLBACK_KEY=/etc/ssl/go.key

# Garage (운영)
export GARAGE_ENDPOINT=127.0.0.1:3900
export GARAGE_ACCESS_KEY=... GARAGE_SECRET_KEY=... GARAGE_BUCKET=cdss

# 또는 로컬 디스크 (개발용. 지정하면 Garage 대신 이걸 쓴다)
export GW_LOCAL_ROOT=/var/tmp/gw-store

go run ./cmd/file-gateway      # :8091
```

---

# llm-proxy (명세 19-4)

```
G-L1  POST /svc/v1/llm/report-narrative   리포트 서술 (SSE) → I-4 콜백
G-L3  GET  /svc/v1/llm/models             Ollama 상주 모델
      GET  /svc/v1/llm/health
```

**생성은 요청 컨텍스트에 안 묶는다.** 화면이 중간에 닫혀도 서술을 끝까지
받아 I-4 로 저장해야 한다. `r.Context()` 를 쓰면 브라우저가 닫히는 순간
취소되고 그때까지 쓴 GPU 시간이 통째로 버려진다.
→ `TestClientDisconnectStillCallsBack`

**멱등키는 리포트당 고정**(`narrative:<report_id>`)이다.

`evidence` 가 비면 **400 으로 거부한다.** 근거 없는 서술은 어차피 전부
버려지므로 GPU 시간만 쓴다.

```json
POST /svc/v1/llm/report-narrative
Authorization: Bearer <Django 가 발급한 티켓>

{
  "report_id": "R1",
  "evidence": [
    {"id": "L1", "kind": "lesion", "text": "우상방 종괴 1.2cm"},
    {"id": "L2", "kind": "lesion", "text": "군집성 미세석회"}
  ]
}
```

```bash
export OLLAMA_MODEL=medgemma
go run ./cmd/llm-proxy         # :8090
```

---

## 팀과 맞춰야 하는 것 셋

**① 티켓 형식** — HS256 JWT 로 구현했다. Django 가
`jwt.encode(claims, key, algorithm="HS256")` 하면 그대로 맞는다.
클레임 이름은 명세 19-1 표 그대로다.

⚠ nonce 저장소가 프로세스 메모리다. **인스턴스를 여러 개 띄우면 Redis 로
옮겨야 한다** — 안 옮기면 A 에서 쓴 티켓을 B 가 받아준다.

**② 콜백 서명** — `HMAC-SHA256(timestamp + "." + body)`.
구분자를 넣은 이유는 없으면 `(ts="1", body="23")` 과 `(ts="12", body="3")`
이 같은 서명을 내기 때문이다. Django 도 같은 식으로 계산해야 한다.

**③ 근거 표시 형식** — 명세는 "근거 좌표가 붙지 않은 문장은 버린다" 까지만
정하고 표시 형식은 안 정했다. 여기서는 문장 끝에 `[[e:<id>]]` 를 붙이게 한다.

검사는 두 단계다.
1. 표시가 있는가
2. **그 id 가 우리가 넘긴 근거 목록 안에 있는가**

2번이 핵심이다. 1번만 보면 모델이 없는 근거를 지어내도 통과한다.
**지어낸 인용은 근거 없는 문장보다 나쁘다 — 확인된 것처럼 보인다.**

## 시험

```bash
go test ./... -race
```

34건. 가짜 Ollama · 가짜 Django · 임시 디스크 저장소를 세워 전 경로를 태운다.

시험이 잡은 실제 버그 하나 — **소수점에서 문장이 잘리던 것.**
`1.2cm` 의 점을 문장 끝으로 봐서 "우상방에 1." 이 근거 없는 문장으로
버려졌다. 판독 서술은 측정값이 도처에 있으므로 그대로 뒀으면 계속 깨졌다.

시험이 실제로 무언가를 잡는지 확인하려고 세 군데를 일부러 망가뜨려 봤다 —
접두사 경계의 `/` 제거 · `capReader` 를 `LimitReader` 로 · 조각 연속성 검사
제거. 셋 다 해당 시험이 잡았다.

## 아직 안 한 것

G-F6(썸네일) · G-F7(DICOM 파싱 · Orthanc → I-2) · 19-5 타일 피라미드
(G-F8~G-F12) · notify(G-N1~G-N5) · G-L2(챗봇).
