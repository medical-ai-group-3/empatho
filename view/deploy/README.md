# 배포

이 폴더에 nginx 설정이 있다. **서버에만 두지 않고 여기 둔다** — 서버에만
있으면 그 기계가 날아갈 때 같이 없어지고, 누가 언제 무엇을 바꿨는지도 안 남는다.

서버에서 고쳤으면 여기에도 반영하고 커밋한다.

---

## 한 대가 셋을 한다

```
브라우저 ──▶ nginx ┬─▶ dist            화면  /  ·  /hospital
                   ├─▶ Django :8000    /api
                   └─▶ Go 관문 :8080   /svc   파일 · 알림 스트림
```

**셋이 같은 주소에서 나온다는 것이 핵심이다.** 화면 코드는 주소를 하나도
박지 않고 상대경로만 쓴다(`src/api.js` 머리말). 같은 출처라 브라우저가
교차 출처로 보지 않고, 그래서 CORS 목록을 관리할 일이 없다.

> 개발 중에는 vite 가 같은 일을 한다(`vite.config.js` 의 proxy).
> 그래서 코드는 개발이든 배포든 그대로다.

---

## 처음 올릴 때

### 1. 빌드해서 옮긴다

```bash
npm install
npm run build          # dist/ 로 나온다 (두 입구가 같이 빌드된다)
```

`dist/` 를 nginx 가 보는 자리로 옮긴다. `nginx.conf` 의 `root` 와 같아야 한다.

```bash
sudo rsync -a --delete dist/ /srv/empatho/web-dist/
```

> ⚠ 빌드 결과가 저장소 안 `dist/` 로 나오는데, nginx 가 보는 자리는 그것이
> 아니다. **옮기는 한 줄을 빠뜨리면 옛 화면이 그대로 뜬다.** 고쳤는데 안
> 바뀐다면 여기부터 본다.

### 2. 설정을 놓는다

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/empatho
sudo ln -sf /etc/nginx/sites-available/empatho /etc/nginx/sites-enabled/empatho
sudo nginx -t          # 문법 검사 — 반드시 통과하고 나서 reload 한다
sudo systemctl reload nginx
```

`nginx.conf` 안에 ⚠ 가 네 군데 있다. 도메인 · 인증서 · `root` · 뒤에 있는
두 서버 주소다. 거기만 채우면 된다.

---

## HTTPS

### 왜 필요한가 — 취향이 아니라 막힘의 문제다

로그인 refresh 토큰이 이렇게 내려온다(백엔드 확인, 2026-09-16).

```python
response.set_cookie("refresh_token", ...,
    httponly=True, secure=True, samesite="None")
```

`secure=True` 는 **「HTTPS 일 때만 이 쿠키를 보내라」** 는 뜻이다. 그리고
`SameSite=None` 은 규격상 `Secure` 가 필수라 뗄 수도 없다.

그래서 HTTP 로 올리면:

```
로그인은 된다 → refresh 쿠키가 저장되지 않는다
→ 30분 뒤 access 만료 → 갱신 실패 → 판독 중에 통째로 로그아웃
```

`hospital/api.js` 의 401 자동 갱신도 **HTTPS 가 아니면 무용지물**이다.

> 로컬(`localhost`)에서 멀쩡한 이유는 브라우저가 localhost 만 예외로
> 봐주기 때문이다. **서버에 올리는 순간 조용히 안 된다.**

### 도메인이 아직 없다면 — 자체서명으로 먼저 세운다

사설 IP(`192.168.x.x`)에는 **어떤 공인 인증기관도 인증서를 발급하지
않는다.** 규정이라 우회할 수 없다. 무료 인증서(Let's Encrypt)도 도메인이
있어야 받는다.

그래서 자체서명으로 구조를 먼저 세워 둔다. 나중에 인증서 파일만 갈아
끼우면 되고, 설정에서 고칠 곳은 두 줄뿐이다.

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/empatho.key \
  -out    /etc/nginx/ssl/empatho.crt \
  -subj "/CN=empatho.local" \
  -addext "subjectAltName=IP:app-host,DNS:empatho.local"
sudo nginx -t && sudo systemctl reload nginx
```

브라우저가 「안전하지 않음」을 띄우지만 **HTTPS 자체는 켜진 것**이라,
Secure 쿠키가 실리는지 · 갱신이 도는지 · SSE 가 끊기지 않는지 전부 지금
확인할 수 있다.

시연 자리에서 경고를 안 보이게 하려면 그 PC 에 위 `.crt` 를 신뢰할 수 있는
루트 인증서로 등록해 둔다.

### 도메인이 나온 뒤

```bash
sudo certbot --nginx -d empatho.example.com
```

certbot 이 `server_name` 과 인증서 두 줄을 알아서 고친다. 설정에
`/.well-known/acme-challenge/` 자리를 리다이렉트보다 **위에** 비워 둔 것이
그 때문이다 — 아래에 있으면 https 로 튕겨서 발급이 실패한다.

갱신은 certbot 이 알아서 돈다. 확인만 한 번:

```bash
sudo certbot renew --dry-run
```

---

## 백엔드 쪽에 같이 필요한 것

**Django `settings.py`**

```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

Django 는 nginx 뒤에 있어서 자기 쪽으로 오는 요청이 http 로 보인다.
그러면 **Secure 쿠키를 「https 가 아니니」 하며 안 내려보낸다.** nginx 가
`X-Forwarded-Proto` 를 붙여 주고(설정에 있다), Django 가 그것을 믿게 하는
줄이 이것이다. **둘 중 하나만 있으면 로그인이 안 된다.**

---

## 자주 걸리는 것

| 증상 | 볼 곳 |
|---|---|
| 고쳤는데 옛 화면이 뜬다 | `dist/` 를 `web-dist/` 로 옮겼는지 |
| `/hospital/...` 주소를 직접 치면 404 | `location /hospital` 의 `try_files` |
| 병원 웹 주소인데 환자 앱이 뜬다 | 입구가 둘이다. `/hospital` 블록이 `/` 보다 먼저 있어야 한다 |
| 로그인은 되는데 30분 뒤 튕긴다 | HTTPS 인지 · `X-Forwarded-Proto` · Django 의 `SECURE_PROXY_SSL_HEADER` |
| 알림이 늦게 몰아서 오거나 1분마다 끊긴다 | `/svc/v1/notify/` 의 `proxy_buffering off` · `proxy_read_timeout` |
| 파일 올리면 413 | `client_max_body_size` |

---

## 참고

* 화면 두 입구와 그 이유 — 최상위 `README.md`
* API 경로와 응답 봉투 — `hospital/api.js` 머리말
* 파일 업로드가 Django 를 거치지 않는 이유 — `hospital/lib/files.js`
