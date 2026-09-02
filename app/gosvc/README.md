# gosvc — Go 서비스 계층 (명세 19장)

Django = 인증 · 권한 판정 · DB 쓰기 전부.
Go = **바이트와 디스패치**. 소켓 1~5(GPU 추론)는 Celery → FastAPI 직결이고
Go 를 안 거친다.

```
cmd/file-gateway   :8091   G-F1~G-F5 · G-F7   업로드 · 다운로드 · DICOM (19-2)
cmd/llm-proxy      :8090   G-L1 · G-L2 · G-L3 Ollama 호출 · 결과 전송 (19-4)
cmd/notify         :8092   G-N1~G-N5          실시간 알림 (19-3)
```

## 처음 받았으면

```bash
go version        # 1.22 이상. 의존성을 1.22 에서 도는 판으로 내려 맞춰 놨다
go mod download   # minio-go 하나뿐이다. vendor 는 17MB 라 커밋 안 했다
go build ./... && go test ./... -race
```

`empatho-app` 저장소 안에 `gosvc/` 로 둔다. Django 와 별개 모듈이라
파이썬 쪽 도구는 이 폴더를 안 본다.

## 명세가 못 박은 것 넷 — 세 서비스 공통

| | |
|---|---|
| 권한 | Go 는 **Django 가 서명한 티켓만 검증**한다. 자체 판정 없음 (exp 5분 · nonce 1회용) |
| DB | Go 는 **Postgres 에 직접 안 쓴다.** 결과는 내부 콜백(I-1~I-4)으로만 |
| 근거 | **근거 좌표 없는 문장은 버린다.** 버린 문장은 `dropped_sentence_log` 로 되돌린다 |
| 실패 | **Ollama 가 죽어도 리포트는 발급된다** — 503 `UPSTREAM_LLM_UNAVAILABLE`, `narrative_text=null` |

---

# file-gateway (19-2)

```
G-F1  POST /svc/v1/upload/init                  청크 개시 → upload_id
G-F2  PUT  /svc/v1/upload/{upload_id}/part/{n}  청크 (개별 재시도 가능)
G-F3  POST /svc/v1/upload/{upload_id}/complete  병합 · sha256 · 커밋 → I-1 → I-2
G-F4  POST /svc/v1/files                        단일 파일 → I-1 → I-2
G-F5  GET  /svc/v1/files/{object_key}           스트리밍 다운로드 (Range 지원)
G-F7  (경로 없음)                                커밋 직후 DICOM 파싱 → I-2 · Orthanc
      GET  /svc/v1/health
```

## 설계에서 짚어둘 것 다섯

**① `object_key` 는 클라이언트가 못 정한다.**
키는 `티켓의 object_key_prefix` + `우리가 만든 난수 이름` + `확장자`다.
클라이언트가 준 파일명은 **확장자만** 참고한다.
그러지 않으면 `filename="../P-99/x.dcm"` 하나로 남의 환자 자리에 쓴다.

**② 상한은 받으면서 잰다.**
`io.LimitReader` 로 막으면 상한에서 **조용히 EOF** 가 나서 *잘린 DICOM 이
정상처럼 커밋된다.* 이 계통에서 제일 나쁜 결과다. `capReader` 는 넘는 순간
읽기를 실패시켜 저장 자체를 중단한다.

**③ 조각이 빠지면 거부한다.**
번호가 `1..N` 으로 안 이어지면 400 이다. 검사를 안 하면 조각 하나 빠진
**짧은 파일이 성공으로 커밋되고 아무 로그도 안 남는다.**

**④ 티켓 접두사가 권한 경계다.**
G-F5 는 `object_key` 가 티켓 접두사 아래가 아니면 403 이다.
경계에 `/` 를 붙여 비교한다 — 안 붙이면 `P-7` 티켓으로 `P-77` 을 읽는다.
Range · If-Range 는 `http.ServeContent` 에 맡긴다. 직접 짜면 반드시 틀린다.

**⑤ I-1 이 실패하면 502.**
파일은 Garage 에 있는데 Django DB 에 없으면 **고아 객체**다. 200 을 내면
클라이언트는 성공으로 알고 그 파일은 영영 아무도 안 찾는다.
멱등키는 `obj:<object_key>`.

## G-F7 — DICOM 파싱

라이브러리를 안 쓰고 직접 짰다(`internal/dicom`). 필요한 것이 머리말 태그
몇 개뿐이고, **화소는 아예 안 건드리기** 때문이다. 화소를 건드리면
JPEG2000·JPEG-LS 디코더가 필요해지고 그건 순수 Go 로 안 된다.
파서는 `(7FE0,0010) PixelData` 에서 멈춘다 — 수 GB 파일도 읽는 양은 앞쪽
수십 KB 다.

지원: 암시적 VR LE · 명시적 VR LE · 명시적 VR BE. 압축 전송 구문
(JPEG·JPEG2000·RLE)도 **머리말은 명시적 VR LE** 라 그대로 읽힌다.
CBIS-DDSM 이 JPEG 무손실이라 이게 안 되면 우리 자료가 통째로 안 읽힌다.

### 왜 화소 간격을 따로 챙기나

미세석회 민감도는 **해상도에 직접 걸린다.** 같은 모델·같은 운영점으로
@1FP 민감도가 CBIS 57.9% → VinDr 43.2% 로 떨어졌고, VinDr 을 1.42배로
키우자 54.6% 로 78% 가 회복됐다. 종괴는 안 그랬다(41.7% → 37.4%).

즉 **들어온 영상의 mm/px 를 모르면 미세석회 결과를 믿을 근거가 없다.**
그래서 `ImagerPixelSpacing`(0018,1164)을 `PixelSpacing`(0028,0030)보다
우선해 뽑고, 어느 태그에서 왔는지도 함께 보낸다. 없으면 **없다고** 보낸다 —
CBIS-DDSM 처럼 필름 스캔이면 간격이 아예 없는데, 조용히 비워두면 나중에
아무도 모른다. 응답의 `pixel_spacing_mm` 은 그때 명시적으로 `null` 이다.

### 환자 이름은 담지 않는다

`PatientName`(0010,0010)은 파서가 아예 안 읽는다. 가명화 정책이 정해지기
전에는 이름을 콜백 본문에도 Go 로그에도 흘리지 않는다.
**팀 결정이 필요한 항목이다.**

### 실패해도 요청은 성공이다

I-2 나 Orthanc 가 실패해도 201 을 낸다. I-1 이 이미 끝나 객체가 등록됐기
때문이다. 여기서 502 를 내면 클라이언트가 재업로드해서 **같은 파일이 두 벌**
생긴다. 대신 응답에 `metadata_registered: false` / `orthanc: "failed"` 를
담고 로그에 남긴다 — 조용히 삼키지는 않는다.

---

# llm-proxy (19-4)

```
G-L1  POST /svc/v1/llm/report-narrative   리포트 서술 (SSE) → I-4 콜백
G-L2  POST /svc/v1/llm/chat               챗봇 (SSE) — 저장 안 함
G-L3  GET  /svc/v1/llm/models             Ollama 상주 모델
      GET  /svc/v1/llm/health
```

## G-L1 과 G-L2 를 가르는 한 가지

**G-L1 은 리포트에 저장되는 글**이다. 그래서 근거 없는 문장을 버리고 I-4 로
DB 에 남긴다.
**G-L2 는 화면에서 한 번 읽고 마는 대화**다. 여기에 같은 문장 필터를 걸면
"그게 무슨 뜻인가" 같은 질문에 아무 답도 못 한다 — 설명 문장은 근거 표시를
달 자리가 없기 때문이다.

그래서 G-L2 는 문장을 안 버리고, **DB 에 안 남기고**(콜백 없음), 대신 근거를
컨텍스트로 넣고 근거 밖 임상 사실을 단정하지 말라고 못 박는다. 응답 끝에
면책을 함께 내려보내 화면이 그대로 띄우게 한다.

⚠ **팀과 맞출 것** — 대화를 진료 기록으로 남길지. 남기기로 하면 명세 21장에
콜백이 하나 더 필요하고, 그때는 문장 필터도 다시 봐야 한다.

취소 방향도 반대다. G-L1 은 화면이 닫혀도 끝까지 생성한다(저장해야 하니까).
G-L2 는 화면이 닫히면 즉시 멈춘다(저장할 게 없으니 GPU 낭비다).

대화는 24턴 · 메시지당 4000자로 자른다. 안 자르면 컨텍스트 창을 넘기고
**Ollama 가 앞쪽을 조용히 잘라내는데, 그 앞쪽이 근거 목록이다.**

## 근거 표시 형식 (G-L1)

명세는 "근거 좌표가 붙지 않은 문장은 버린다" 까지만 정하고 표시 형식은
안 정했다. 여기서는 문장 끝에 `[[e:<id>]]` 를 붙이게 한다.

검사는 두 단계다. ① 표시가 있는가 ② **그 id 가 우리가 넘긴 근거 목록 안에
있는가.** ②가 핵심이다. ①만 보면 모델이 없는 근거를 지어내도 통과한다.
**지어낸 인용은 근거 없는 문장보다 나쁘다 — 확인된 것처럼 보인다.**

`evidence` 가 비면 400 으로 거부한다. 근거 없는 서술은 어차피 전부 버려지므로
GPU 시간만 쓴다. 멱등키는 리포트당 고정(`narrative:<report_id>`)이다.

---

# notify (19-3)

```
G-N1  GET  /svc/v1/notify/stream    SSE 구독 (티켓)
G-N2  POST /svc/v1/notify/publish   Django → Go 발행 (내부 서명)
G-N3  POST /svc/v1/notify/ack       확인 처리 → I-3 (티켓)
G-N4  GET  /svc/v1/notify/health
G-N5  GET  /svc/v1/notify/stats     구독 현황 (내부 서명)
```

⚠⚠ **경로 이름은 내가 정한 것이다.** 명세 19-3 표의 G-N1~G-N5 정확한 경로를
확인하지 못했다. 나머지 경로 규칙(`/svc/v1/...`)에 맞춘 추정이고,
**팀 확인 뒤 바꿔야 한다.** 바꿀 곳은 `cmd/notify/main.go` 의 `routes()`
한 군데다.

## 느린 화면 하나가 전원을 막으면 안 된다

한 사용자가 창을 여러 개 띄워 놓고 그중 하나가 응답을 안 읽으면 그 연결로
보내는 쓰기가 막힌다. 팬아웃을 순서대로 돌면 그 하나 때문에 나머지 전원이
알림을 못 받는다. 판독 완료 알림이 한 사람 브라우저 탓에 병동 전체에서 안 뜬다.

그래서 구독자마다 버퍼를 두고 **비차단으로** 보낸다.

**버퍼가 차면 어떻게 하는가 — 이게 제일 중요한 결정이다.**
버리고 세기만 하면 그 알림은 조용히 사라지고 사용자는 판독이 끝난 줄 모른다.
알림 체계가 없느니만 못하다. 그래서 버퍼가 차면 그 구독자를 '밀렸다' 로
표시하고 `resync` 이벤트를 보낸다. 화면은 그걸 받으면 Django 에서 목록을
다시 받아 간다. **개별 알림은 잃되 잃었다는 사실은 안 잃는다.**

## 닫힌 채널에 보내기를 설계로 막았다

구독을 닫을 때 이벤트 채널 `C` 를 **아무도 안 닫는다.** 닫는 순간 "닫힌
채널에 보내기" 로 프로세스가 통째로 죽을 수 있고, 그건 잠금을 아무리
조심해도 리뷰로만 지켜지는 규칙이 된다. 대신 아무도 보내지 않는 `done` 을
닫는다 — 닫기와 보내기가 서로 다른 채널이라 그 사고가 **구조적으로
불가능해진다.** 읽는 쪽은 `C` 와 `Done()` 을 함께 select 한다.

(처음엔 잠금 규칙으로 막고 스트레스 시험을 붙였는데, 일부러 망가뜨려
세 번 돌렸더니 세 번 다 통과했다. 겹치는 창이 너무 좁아 시험이 못 잡는다.
그래서 시험으로 지키는 것을 포기하고 설계를 바꿨다.)

## 발행은 티켓이 아니라 서명으로 막는다

티켓은 사용자용이고 발행은 서버 간 호출이다. 콜백과 같은
`HMAC-SHA256(ts + "." + body)` 를 쓰고 5분 지난 타임스탬프는 거부한다 —
안 그러면 가로챈 요청을 언제든 다시 보낼 수 있다.

`delivered` 와 `read` 는 **다른 사건**이라 멱등키에 status 를 넣는다
(`notif:<id>:<user>:<status>`). 같은 키를 쓰면 나중 것이 중복으로 걸러진다.

확인 처리(G-N3)의 I-3 은 **동기로** 보낸다. 200 을 냈는데 Django 가 못 받으면
화면에서는 읽음인데 DB 에서는 미확인이라 그 알림이 계속 다시 뜬다.
전달 보고(delivered)는 반대로 배경으로 보낸다 — 알림 20개 받는 동안 콜백
20번을 기다리면 화면이 그만큼 늦는다.

---

## 팀과 맞춰야 하는 것

**① 티켓 형식** — HS256 JWT. Django 가
`jwt.encode(claims, key, algorithm="HS256")` 하면 그대로 맞는다.
클레임 이름은 명세 19-1 표 그대로다.

⚠ nonce 저장소가 프로세스 메모리다. **인스턴스를 여러 개 띄우면 Redis 로
옮겨야 한다** — 안 옮기면 A 에서 쓴 티켓을 B 가 받아준다.

**② 콜백 서명** — `HMAC-SHA256(timestamp + "." + body)`.
구분자를 넣은 이유는 없으면 `(ts="1", body="23")` 과 `(ts="12", body="3")`
이 같은 서명을 내기 때문이다. Django 도 같은 식으로 계산해야 한다.

**③ `object_key_prefix` 는 Django 가 확정해서 티켓에 실어야 한다.**
Go 는 그 아래에만 쓰고 그 밖은 403 이다. 없으면 요청 자체를 거부한다.

**④ 확인 필요** — 알림 경로명(위 참고) · DICOM 가명화 범위 · 챗봇 저장 여부.

## 내부 콜백 (Go → Django)

| | 경로 | 멱등키 |
|---|---|---|
| I-1 | `POST /internal/v1/storage-objects` | `obj:<object_key>` |
| I-2 | `POST /internal/v1/dicom-instances` | `dcm:<object_key>` |
| I-3 | `POST /internal/v1/notifications/delivery` | `notif:<id>:<user>:<status>` |
| I-4 | `POST /internal/v1/reports/{id}/narrative` | `narrative:<report_id>` |

명세 21장의 순서 보장 — **I-1 이 성공해야 I-2 가 유효하다.** 코드가 그 순서를
지킨다.

## 실행

```bash
cp .env.example .env   # 값을 채운다. .env 는 커밋하지 않는다
docker compose -f compose.server -f compose.gosvc.yml up -d --build
```

개발 중에 Garage 없이 돌리려면 `GW_LOCAL_ROOT` 를 주면 로컬 디스크를 쓴다.
`ORTHANC_URL` 을 비우면 DICOM 을 파싱해 I-2 만 보내고 전송은 건너뛴다.

## 시험

```bash
go test ./... -race
```

시험 함수 89개. 가짜 Ollama · 가짜 Django · 가짜 Orthanc · 임시 디스크
저장소를 세워 전 경로를 태운다. DICOM 은 바이트를 직접 지어서 만든다 —
CBIS-DDSM 은 재배포 금지고 EMBED 는 DUA 로 묶여 있어 표본을 넣을 수 없다.

시험이 잡은 실제 버그 — **소수점에서 문장이 잘리던 것.** `1.2cm` 의 점을
문장 끝으로 봐서 "우상방에 1." 이 근거 없는 문장으로 버려졌다. 판독 서술은
측정값이 도처에 있으므로 그대로 뒀으면 계속 깨졌다.

시험이 실제로 무언가를 잡는지 일부러 코드를 망가뜨려 확인했다.
접두사 경계의 `/` 제거 · `capReader` 를 `LimitReader` 로 · 조각 연속성 검사
제거 — 셋 다 해당 시험이 잡았다.
**잡지 못한 것도 있다** — 허브의 닫힌 채널 경합. 그건 위에 쓴 대로 설계로
바꿔서 막았다.

## 팀 서버(app-host) 에 붙일 때

접속 안내서 기준 확정 사항이다.

| | 값 |
|---|---|
| Garage 버킷 · 원본 | `empatho-original` |
| Garage 버킷 · 파생 | `empatho-derived` (타일·썸네일·마스크) |
| region | `garage` |
| 주소 방식 | **path-style 필수** — 코드에서 강제해 뒀다 |
| Orthanc | 사용자 `empatho`, DICOMweb 켜짐. **맘모도 등록한다** |

**맘모 DICOM 도 Orthanc 에 등록한다.** 원본 파일은 Garage 에, 촬영 정보는
Orthanc 에 들어가고 둘을 I-2 의 `orthanc_instance_id` 로 잇는다.

⚠ 접속 안내서에는 *"MRI 만 여기에 들어가고, 맘모·초음파·병리는 Garage 에
있습니다"* 라고 적혀 있는데 **그 문서가 틀렸다.** 담당자에게 정정을 요청할 것 —
그대로 두면 다른 팀원이 `ORTHANC_URL` 을 비운 채 띄우고, 그러면 업로드는
성공하는데 Orthanc 에 아무것도 안 들어간다. 로그에 한 줄 남을 뿐이라
한참 뒤에야 알게 된다.

**⚠ 터널을 호스트에서 열고 Go 는 컨테이너 안에서 돌 때** — 컨테이너의
`127.0.0.1` 은 컨테이너 자신이라 호스트 터널이 안 보인다. compose 에
`extra_hosts: host.docker.internal:host-gateway` 를 넣어 뒀으니
`GARAGE_ENDPOINT=host.docker.internal:13900` 으로 주면 된다.

| Go 가 도는 곳 | GARAGE_ENDPOINT |
|---|---|
| 호스트에서 직접 | `127.0.0.1:13900` |
| Docker + 호스트 터널 | `host.docker.internal:13900` |
| Garage 와 같은 compose 망 | `garage:3900` |

## Docker 로 올릴 때 반드시 볼 것 셋

**① `GW_LOCAL_ROOT` 는 운영 `.env` 에 있으면 안 된다.**
설정돼 있으면 Garage 를 무시하고 컨테이너 안 디스크에 쓴다. 재시작하면
파일이 사라지는데 **업로드는 201 로 성공하고 로그도 정상이다.** 그래서
`GW_DEV=1` 을 함께 주지 않으면 아예 기동을 거부하게 했다.

**② `CORS_ORIGINS` 를 설정해야 브라우저가 Go 를 부를 수 있다.**
Go 를 따로 둔 목적이 바이트가 Django 를 안 거치는 것이므로, **브라우저가
Go 를 직접 부른다.** 프런트(:5173)와 Go(:8091)는 다른 출처라 사전 요청
(OPTIONS)이 먼저 오는데, 답을 안 하면 업로드가 시작조차 안 되고 화면에는
애매한 network error 만 뜬다.

```
CORS_ORIGINS=http://localhost:5173,https://cdss.example.org
```

nginx 하나로 프런트와 Go 를 같은 출처에 묶었다면 비워 두면 된다.
`*` 도 받지만 개발용이다 — 티켓을 헤더로 보내므로 아무 사이트나 우리 API 를
부를 수 있게 된다.

**③ 인스턴스는 하나여야 한다.** 티켓 nonce 저장소가 프로세스 메모리다.
`deploy.replicas` 를 2 이상으로 올리면 A 에서 쓴 티켓을 B 가 받아준다.
늘리려면 Redis 로 옮기는 작업이 먼저다.

세 서비스 모두 `/svc/v1/.../health` 를 제공하고 compose 에 healthcheck 가
걸려 있다. Django 쪽에서 `depends_on: {file-gateway: {condition: service_healthy}}`
로 기동 순서를 잡을 수 있다.

## Docker 만으로 전 경로 태우기

Garage·Django·Orthanc 없이, 파이썬 설치도 없이 확인할 수 있다.
**두 compose 파일 모두 저장소 루트에 두고 실행한다** (build context 가
`./gosvc` 라서 그렇다).

```bash
docker compose -f compose.gosvc.yml -f compose.dev.yml up --build -d
docker compose -f compose.gosvc.yml -f compose.dev.yml logs -f fake-django
```

점검 — 시험용 DICOM 을 컨테이너 안에서 만들어 단일·청크 두 경로를 태운다.

```bash
docker compose -f compose.gosvc.yml -f compose.dev.yml run --rm devkit
```

**실제 의료영상을 안 쓴다.** CBIS 는 재배포 금지, VinDr·EMBED 는 인증·DUA 로
묶여 있어 개인 컴퓨터나 CI 로 옮기면 안 된다. `tools/make_test_dicom.py` 가
바이트를 직접 쌓아 만든다 — 파서가 보는 것은 바이트 배치라 이쪽이 오히려
정확한 시험이 된다.

## tools/ — 진짜 Django 없이 전 경로를 태우는 도구

`go test` 는 내가 지어낸 바이트로 돈다. 이건 **실제 촬영 파일**로 같은 경로를
태워서 시험이 못 보는 것을 잡는다. 의존성 없음(표준 라이브러리만).

| | |
|---|---|
| `tools/fake_django.py` | I-1~I-4 를 받아 화면에 찍는다. **서명·멱등키·순서를 검증한다** |
| `tools/mint_ticket.py` | 티켓 발급. Django 가 할 일을 시험 동안 대신한다 |
| `tools/smoke.py` | DICOM 한 장으로 업로드 → G-F7 → 다운로드 → 권한까지 12가지 확인 |
| `tools/smoke_chunked.py` | 청크 업로드(G-F1~F3). 조각을 **거꾸로** 보내 순서를 확인한다 |
| `tools/make_test_dicom.py` | 시험용 DICOM 생성. 실제 자료를 안 써도 되게 한다 |

```bash
# 창 1 — 가짜 Django
python3 tools/fake_django.py --port 9999 --secret dev-secret

# 창 2 — file-gateway (개발용 로컬 디스크)
TICKET_KEY=dev-key CALLBACK_BASE=http://127.0.0.1:9999 \
CALLBACK_SECRET=dev-secret GW_LOCAL_ROOT=/tmp/gw-store \
GW_ADDR=127.0.0.1:8091 go run ./cmd/file-gateway

# 창 3 — 점검
python3 tools/smoke.py --file <진짜.dcm>
```

**Django 팀에게 유용한 지점** — `fake_django.py` 의 `sign()` 이 우리가 쓰는
서명 계산을 그대로 담고 있다. Django 쪽 검증 코드를 이것과 맞추면 된다.
`mint_ticket.py` 는 반대로 발급 쪽이고, PyJWT 로 바꿔도
`jwt.encode(claims, key, algorithm="HS256")` 이 그대로 맞는다.

## 아직 안 한 것 · 왜 못 했나

| | 사유 |
|---|---|
| **G-F6 썸네일** | 압축 DICOM(JPEG2000·JPEG-LS) 디코딩이 순수 Go 로 안 된다. C 라이브러리가 필요하다. 비압축만 하면 CBIS 가 안 되므로 반쪽이다. **파이썬 쪽이나 Orthanc 미리보기로 넘기는 편이 낫다** |
| **G-F8~F12 피라미드** | libvips/openslide 필요. 게다가 WSI 는 병리 담당 자료라 표본이 없다 |
| **Orthanc 연동 검증** | 인스턴스가 없어 **떠 있는 Orthanc 로 안 돌려봤다.** REST 규격에 맞춰 짜고 가짜 서버로만 시험했다. 실물에 붙일 때 인증 방식과 409 처리부터 확인할 것 |
| **mTLS** | 인증서 미발급. 비어 있으면 기동 시 경고를 내고 평문으로 간다 |
| **Redis nonce** | 인스턴스 다중화 여부가 팀 미결정 |
