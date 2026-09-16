# nginx 앞단

앱 서버의 HTTP 서비스 넷을 nginx 뒤로 모았다. 밖에서 들어오는 문이 하나다.

```
http://app-host/
```

2026-09-09 배포. 「앱 서버 nginx 작업 요청서」(2026-09-09) 구현.

---

## 1. 경로

| 경로 | 대상 |
|---|---|
| `/api/…` | Django |
| `/admin/` | Django 관리자 |
| `/svc/v1/upload/…` · `/svc/v1/files/…` | file-gateway |
| `/svc/v1/llm/…` | llm-proxy |
| `/svc/v1/notify/…` | notify (`/stream` 은 SSE) |
| `/internal/…` | **404 로 막는다.** Go → Django 콜백 전용이라 밖에 열릴 이유가 없다 |
| `/` | 프런트 빌드 결과. **아직 비어 있다**(4절) |

`/svc/v1/health` 는 file-gateway 것이다. llm-proxy 와 notify 는
`/svc/v1/llm/health` · `/svc/v1/notify/health` 를 각자 갖고 있다.

---

## 2. 프런트에서 부르는 법

**주소를 코드에 박지 않는다. 상대 경로로 부른다.**

```js
fetch("/svc/v1/files")                              // ○
fetch("http://app-host:8091/svc/v1/files")      // ✗
```

이유는 두 가지다.

**CORS 가 필요 없어진다.** 같은 출처에서 부르면 브라우저가 preflight 를
보내지 않는다. 절대 주소를 쓰면 nginx 를 앞에 둬도 브라우저는 여전히 다른
출처로 보고, `CORS_ORIGINS` 에 그 출처가 정확히 적혀 있어야 한다.

이 목록은 IP 로 되어 있어 자리를 옮기거나 다른 기기로 열면 그대로 막힌다.
그리고 **막힐 때 화면에는 「네트워크 오류」로만 뜨고 서버 로그에도 안
남는다.** 원인을 찾는 데 시간이 많이 든다.

**주소가 바뀌어도 앱을 다시 안 만들어도 된다.** 서버를 옮기거나 포트를
바꿔도 프런트는 자기가 열린 주소를 그대로 쓴다.

---

## 3. 확인

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://app-host/svc/v1/health
```

`200` 이면 정상이다. 브라우저로 `http://app-host/admin/` 을 열면 Django
로그인 화면이 나온다.

`/admin/` 이 **400** 이면 러너 홈 `~/empatho-conf/web.env` 의
`DJANGO_ALLOWED_HOSTS` 에 접속한 주소가 없는 것이다. nginx 는 브라우저가 친
Host 를 그대로 Django 에 넘긴다.

> `settings.py` 는 이 값을 `strip` 하지 않는다. **쉼표 뒤 공백 하나로 계속
> 400 이 난다.** 따옴표도 쓰지 않는다 — `env_file` 이 값의 일부로 읽는다.

---

## 4. 아직 안 되는 것

`http://app-host/` 을 그냥 열면 **404** 다. 프런트 빌드 결과를 넣을
자리(`web-dist/`)만 만들어 뒀고 비어 있다.

프런트 레포 위치와 담당이 정해지면 `deploy.yml` 에 빌드 단계를 붙인다.
API 경로는 지금도 전부 동작한다.

---

## 5. 바뀌지 않은 것

기존 `127.0.0.1` 바인딩은 **그대로 살려 뒀다.**

```
127.0.0.1:8000   web            127.0.0.1:8091   file-gateway
127.0.0.1:8090   llm-proxy      127.0.0.1:8092   notify
```

SSH 터널을 쓰던 사람은 그대로 쓰면 된다. 요청서 5절의 2차(호스트 포트
제거)는 **프런트 연결과 시연 경로 확인이 끝난 뒤**에 한다. 지금 걷어내면
문제가 생겼을 때 되돌아갈 길이 없어지고, 그 포트들은 `127.0.0.1` 바인딩이라
지금도 밖에서는 안 보인다.

postgres · garage · orthanc 는 nginx 대상이 아니다. postgres 는 HTTP 가
아니고, 나머지 둘은 열면 객체 저장소와 환자 DICOM 이 통째로 노출된다.
계속 터널로만 붙는다.

---

## 6. HTTP 다 — TLS 가 아니다

사내망 IP 로는 공인 인증서를 받을 수 없다. 도메인이 있어야 한다. 자체 서명
인증서를 쓰면 접속할 때마다 브라우저 경고 화면을 넘겨야 해서, 시연 첫 화면이
경고문이 된다. 그래서 시연까지는 HTTP 로 간다.

**운영 병원 배포에서는 TLS 가 필수다.** 환자 이름·전화번호, 판독 결과,
영상, 티켓(`Authorization` 헤더)이 지나가는 경로다.

`conf/nginx/default.conf` 하단에 TLS 설정과 인증서 생성 명령을 주석으로 넣어 뒀다.
주석만 풀면 된다.

브라우저의 카메라·위치·서비스워커·웹푸시는 HTTPS 에서만 동작한다. 알림은
SSE 라 HTTP 로 되지만, 그런 기능을 쓸 계획이 생기면 그때는 인증서가 필요하다.

---

## 7. 설정을 손댈 때

`conf/nginx/default.conf` 의 값은 짐작이 아니라 `services/gosvc` 소스에서 나왔다.
바꾸기 전에 왜 그 값인지 확인할 것.

### `resolver` — 지우면 배포마다 502 가 난다

```nginx
resolver 127.0.0.11 valid=10s ipv6=off;
```

`proxy_pass` 에 서비스 이름을 그대로 쓰면 nginx 는 기동할 때 한 번만 이름을
풀고 그 IP 를 계속 쓴다. `up -d --build` 로 web·gosvc 가 새로 뜨면 IP 가
바뀌는데 nginx 는 안 바뀌니 재생성되지 않는다. 옛 IP 를 계속 두드린다.

그래서 업스트림을 변수(`set $up_llm llm-proxy;`)로 두고 10초마다 다시 풀게
한다. 변수를 쓰면 nginx 가 경로를 안 이어 주므로 `$request_uri` 를 직접 붙인다.

### 타임아웃

| 경로 | 값 | 근거 |
|---|---|---|
| `/svc/v1/llm/` | 660초 | llm-proxy 의 `genCtx` 가 10분이다 |
| `/svc/v1/notify/stream` | 24시간 | 계속 열어 두는 통로다 |
| 업로드 · 파일 | 600초 | 큰 DICOM·WSI |

nginx 기본값은 **60초**다. 그대로 두면 서술 생성이 1분을 넘길 때 nginx 가
먼저 끊는다. Go 는 요청 컨텍스트에 안 묶여 있어 끝까지 돌고 콜백까지 하므로
**화면에서만 실패로 보인다.** 서버 로그는 정상이라 원인을 찾기 어렵다.

### 업로드 크기

`/svc/v1/upload/` 와 `/svc/v1/files` 는 `client_max_body_size 0` 이다.
한도는 **티켓의 `max_bytes`** 가 요청마다 정한다. nginx 에 고정 상한을 두면
티켓이 허용해도 nginx 가 먼저 413 을 낸다.

`proxy_request_buffering off` 도 같이 필요하다. 켜 두면 nginx 가 본문을 전부
디스크에 받은 뒤에야 Go 에 넘긴다.

### CORS 헤더를 nginx 에서 붙이지 않는다

Go(`internal/httpx/cors.go`)와 Django(`corsheaders`)가 이미 붙인다. 두 번
붙으면 헤더가 중복되고 **브라우저가 그것을 거부한다.** 오류가 「헤더가 없다」가
아니라 「중복이다」로 나와서 원인을 찾기 어렵다.

### SSE

`llm/report-narrative` · `llm/chat` · `notify/stream` 셋이 SSE 다. Go 쪽이
`X-Accel-Buffering: no` 를 보내고 nginx 도 `proxy_buffering off` 를 건다.
`proxy_set_header Connection ""` 도 필요하다 — 기본값(`close`)이면 스트림이
매번 끊긴다.

---

## 8. 배포

`main` 에 푸시하면 러너가 배포한다. `deploy.yml` 이 요청서 6절의 인수 조건을
curl 로 확인하고, 하나라도 어긋나면 배포를 실패로 만든다.

nginx 는 설정이 틀려도 컨테이너가 살아 있는 채로 502 만 뱉는 경우가 있어,
기존의 「재시작 반복 확인」으로는 안 잡힌다. 그래서 따로 본다.

**푸시 전에 문법 검사를 한다.** 서버에 로컬 시험 환경이 없어서 설정 오류가
그대로 운영 중단이 된다. 이 검사는 컨테이너 하나면 되고 다른 서비스가
필요 없다.

```bash
docker run --rm -v "$PWD/conf/nginx:/etc/nginx/conf.d:ro" \
  nginx:1.27-alpine nginx -t
```

`syntax is ok` 와 `test is successful` 두 줄이 나와야 한다.
