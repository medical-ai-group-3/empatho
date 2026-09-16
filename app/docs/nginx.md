# nginx 앞단

앱 서버의 HTTP 서비스 넷을 nginx 뒤로 모았다. 밖에서 들어오는 문이 하나다.

```
https://empatho.example.com/
```

2026-09-09 배포. 「앱 서버 nginx 작업 요청서」(2026-09-09) 구현.

---

## 1. 경로

| 경로 | 대상 |
|---|---|
| `/api/…` | Django |
| `/admin/` | Django 관리자 |
| `/svc/v1/upload/…` · `/svc/v1/files/…` | file-gateway |
| `/svc/v1/derived/…` | file-gateway (읽기 전용) |
| `/svc/v1/dicom/…` | file-gateway → **Orthanc** (읽기 전용) |
| `/svc/v1/llm/…` | llm-proxy |
| `/svc/v1/notify/…` | notify (`/stream` 은 SSE) |
| `/internal/…` | **404 로 막는다.** Go → Django 콜백 전용이라 밖에 열릴 이유가 없다 |
| `/` | 프런트 빌드 결과. **아직 비어 있다**(4절) |

`/svc/v1/health` 는 file-gateway 것이다. llm-proxy 와 notify 는
`/svc/v1/llm/health` · `/svc/v1/notify/health` 를 각자 갖고 있다.

### DICOM 은 Garage 가 아니라 Orthanc 에 있다

맘모와 MRI 만 DICOM 이다. 초음파와 병리는 PNG 로 Garage 에 있다.

```
GET /svc/v1/dicom/instances/{sop}   맘모 한 장 (원본 DICOM)
GET /svc/v1/dicom/series/{id}       MRI 시리즈 (zip)
```

브라우저가 Orthanc 에 직접 가지 않는다. Go 가 감싸서 흘려보낸다 — Orthanc 는
nginx 밖에 안 열려 있고, 계정도 Go 만 들고 있다.

⚠ **티켓 규칙이 파일과 다르다.** 일반 파일은 티켓의 `ObjectKeyPrefix` 로
**시작만** 보지만, DICOM 은 **정확히 일치**해야 한다
(`file-gateway/main.go` 의 `fromOrthanc`).

```
파일    티켓 하나로 그 검체의 여러 장을 받는다
DICOM   영상 한 건에 티켓 하나다 — 맘모 4장이면 티켓 4개
```

`dicom/series/ab` 티켓으로 `ab12` 를 여는 것을 막으려고 그렇게 돼 있다.
화면에서 티켓을 재사용하려다 403 `TICKET_SCOPE_MISMATCH` 를 만나면 이것이다.

---

## 2. 프런트에서 부르는 법

**주소를 코드에 박지 않는다. 상대 경로로 부른다.**

```js
fetch("/svc/v1/files")                              // ○
fetch("https://empatho.example.com:8091/svc/v1/files")      // ✗
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
curl -s -o /dev/null -w "%{http_code}\n" https://empatho.example.com/svc/v1/health
```

`200` 이면 정상이다. 브라우저로 `https://empatho.example.com/admin/` 을 열면 Django
로그인 화면이 나온다.

`/admin/` 이 **400** 이면 러너 홈 `~/empatho-conf/web.env` 의
`DJANGO_ALLOWED_HOSTS` 에 접속한 주소가 없는 것이다. nginx 는 브라우저가 친
Host 를 그대로 Django 에 넘긴다.

> `settings.py` 는 이 값을 `strip` 하지 않는다. **쉼표 뒤 공백 하나로 계속
> 400 이 난다.** 따옴표도 쓰지 않는다 — `env_file` 이 값의 일부로 읽는다.

---

## 4. 아직 안 되는 것

`https://empatho.example.com/` 을 그냥 열면 **404** 다. 프런트 빌드 결과를 넣을
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

## 6. TLS (HTTPS)

**HTTPS 로 간다.** 예전에는 HTTP 였다 — 사내망 IP 로는 공인 인증서를 못 받고,
자체 서명은 접속할 때마다 경고 화면이라 시연 첫 인상이 경고문이 되기 때문이었다.
도메인이 생기면서 그 이유가 없어졌다.

### 왜 필요한가 — 취향이 아니라 막힘의 문제다

환자 이름·전화번호, 판독 결과, 영상, `Authorization` 헤더가 지나가는 경로다.
그것만으로도 이유가 되지만, **지금은 HTTP 면 로그인 자체가 안 된다.**

refresh 토큰이 이렇게 내려온다 (`core/api/views.py`).

```python
response.set_cookie("refresh_token", ...,
    httponly=True, secure=True, samesite="None")
```

`secure=True` 는 「HTTPS 일 때만 이 쿠키를 보내라」는 뜻이고, `SameSite=None`
은 규격상 `Secure` 가 필수라 뗄 수도 없다. HTTP 로 올리면:

```
로그인은 된다 → refresh 쿠키가 저장되지 않는다
→ 30분 뒤 access 만료 → 갱신 실패 → 판독 중에 통째로 로그아웃
```

화면 쪽 401 자동 갱신(`empatho-view` 의 `hospital/api.js`)도 같이 무용지물이 된다.

> 개발자 PC 에서 멀쩡한 이유는 브라우저가 `localhost` 만 예외로 봐주기
> 때문이다. **서버에 올리는 순간 조용히 안 된다.**

### Django 쪽에 짝이 필요하다

```python
# settings.py
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

Django 는 nginx 뒤에 있어서 자기에게 오는 요청을 http 로 본다. 그러면
**Secure 쿠키를 「https 가 아니니」 하며 안 내려보낸다.** nginx 가
`X-Forwarded-Proto` 를 붙이고(설정에 있다) Django 가 그것을 믿게 하는 줄이
이것이다. **둘 중 하나만 있으면 로그인이 안 된다.**

### 처음 한 번 — 인증서 발급

도메인이 이 서버를 가리키고 80 이 밖에서 닿아야 한다. 확인:

```bash
dig +short empatho.example.com          # 서버 IP 가 나와야 한다
curl -I http://empatho.example.com/nginx-health
```

**닭과 달걀 문제가 하나 있다.** nginx 는 인증서 파일이 없으면 뜨지 않고,
certbot 은 확인 파일을 받아 줄 nginx 가 있어야 한다. 그래서 임시 인증서로
한 번 띄운 뒤 진짜 것으로 바꾼다.

```bash
# 1) 자리를 만들고 임시 인증서를 넣는다 (진짜가 오기 전까지만 쓴다)
mkdir -p conf/certbot/etc/live/empatho conf/certbot/www
openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
  -keyout conf/certbot/etc/live/empatho/privkey.pem \
  -out    conf/certbot/etc/live/empatho/fullchain.pem \
  -subj "/CN=temp"

# 2) nginx 를 띄운다 — 이제 80 이 열려 확인 파일을 받을 수 있다
docker compose up -d nginx

# 3) 진짜 인증서를 받는다
docker compose run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  --cert-name empatho \
  -d empatho.example.com \
  --agree-tos -m 담당자@메일 --no-eff-email

# 4) nginx 가 새 인증서를 읽게 한다
docker compose exec nginx nginx -s reload
```

> **`--cert-name empatho` 를 빠뜨리지 말 것.** 이것 때문에 인증서 경로가
> `/etc/letsencrypt/live/empatho/` 로 고정된다. 안 주면 도메인 이름으로
> 폴더가 생겨서, 도메인이 바뀔 때마다 `default.conf` 를 고쳐야 한다.

확인:

```bash
curl -I https://empatho.example.com/nginx-health        # 200
curl -I http://empatho.example.com/                     # 301 → https
echo | openssl s_client -connect empatho.example.com:443 2>/dev/null \
  | openssl x509 -noout -dates                      # 만료일
```

### 갱신은 자동이다

Let's Encrypt 인증서는 **90일**이다. 시연이 끝나도 계속 돈다.

* `certbot` 컨테이너가 12시간마다 깨어나 만료 30일 전인지 본다. 아니면 아무
  일도 안 하고 다시 잔다.
* `nginx` 컨테이너는 6시간마다 스스로 `reload` 한다. 갱신된 파일을 읽으려면
  필요하다 — **이게 없으면 갱신은 됐는데 브라우저에는 만료된 인증서가
  내려간다.** 90일 뒤 조용히 터지고, 그때는 아무도 이 문서를 안 보고 있다.

갱신이 실제로 되는지 미리 확인:

```bash
docker compose run --rm --entrypoint certbot certbot renew --dry-run
```

### 인증서는 git 에 없다

`conf/certbot/` 은 `.gitignore` 에 있다 — **개인키가 들어 있다.** 서버에서
certbot 이 직접 만들고, 배포가 지우지도 않는다(checkout 은 추적되는 파일만
건드린다).

> 서버를 새로 세우면 위 「처음 한 번」을 다시 밟는다.

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
