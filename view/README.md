# empatho-view

EMPATHO 유방암 임상의사결정지원 시스템의 **화면** 저장소.

앱이 **둘** 들어 있다. 하나는 환자가 쓰는 앱, 하나는 병원 직원이 쓰는 웹이다.
서로 색도 글꼴도 규칙도 다르므로 **입구부터 갈라 두었다.**

| | 환자 앱 | 병원 웹 |
|---|---|---|
| 누가 | 검진받는 사람 | 병원 직원 |
| 어디로 들어가나 | `/` | `/hospital` |
| 입구 파일 | `index.html` | `hospital.html` |
| 코드 | `src/` | `hospital/` |
| 무엇으로 보나 | 휴대폰 | 데스크톱 |
| 분위기 | 따뜻한 분홍, 둥근 모서리 | 차분한 회색·시안, 표와 뷰어 |

> **왜 갈랐나** — 두 앱의 CSS 변수 이름이 겹친다. `--ink` 가 양쪽에 다 있고
> 값이 서로 정반대다. 한 입구에 둘을 넣으면 나중 것이 앞 것을 덮어 화면이
> 무너진다. 그래서 `index.html` 과 `hospital.html` 을 따로 두고, 각자 자기
> 토큰만 읽게 했다. **둘을 한 파일에서 import 하지 말 것.**

---

## 시작하기

```bash
npm install
```

| 명령 | 하는 일 |
|---|---|
| `npm run dev:hos` | **병원 웹.** 목업으로 돌고 `/hospital` 을 바로 연다 |
| `npm run dev:mock` | 목업으로 돌린다. 브라우저는 `/` — **환자 앱이 열린다** |
| `npm run dev` | 진짜 서버에 붙는다 |
| `npm run build` | `dist/` 로 내보낸다 (두 입구가 같이 빌드된다) |
| `npm run preview` | 빌드 결과를 그대로 띄워 본다 |
| `npm run lint` | oxlint |

> **병원 웹을 보려는데 휴대폰 화면이 뜬다면** `dev:mock` 을 친 것이다.
> 그 명령은 `/` 를 열고, 거기는 환자 앱 자리다. `dev:hos` 를 쓰거나
> 주소창에 `/hospital` 을 직접 치면 된다. 둘 다 같은 서버라 한쪽을
> 띄워 놓고 다른 주소로 옮겨 가도 된다.

열 주소

```
http://localhost:5173/            환자 앱
http://localhost:5173/hospital    병원 웹
```

`/hospital` 을 열었는데 **환자 앱이 나온다면** `vite.config.js` 의
`hospitalRoutes()` 미들웨어가 빠진 것이다. Vite 의 SPA 되돌림이 주소를
전부 `index.html` 로 보내기 때문에, 이 미들웨어가 `/hospital…` 만
`hospital.html` 로 되돌려 준다.

---

## 목업으로 도는 방식

`npm run dev:mock` 은 서버 없이 돈다. `mock/` 안의 파일이 API 를 흉내 낸다.

* `mock/hospital.js` — `/api/v1/hospital/**` 만 맡는다.
  `mock/hospital.json` 에 적힌 응답을 주소·질의로 골라 돌려준다.
  질의까지 본다. 예를 들어 `?status=bound&assigned=none` 은 접수 대기 큐,
  질의가 없는 `GET /specimens` 는 전체 목록으로 갈린다.
* 환자 앱 쪽 목업은 `mock/` 의 나머지 파일이 맡는다.

로그인 쿠키도 갈라 두었다.

```
환자 앱   empatho_mock_session
병원 웹   empatho_mock_staff
```

한 브라우저에서 둘을 같이 열어도 서로 로그아웃시키지 않는다.

목업으로 돌 때는 화면 맨 아래에 회색 띠가 뜬다.

```
목업 자료 — 지어낸 값입니다 · /api/v1/hospital
```

**띠가 없으면 진짜 서버에 붙어 있는 것이다.** 시연 중에 이 띠를 보고
어느 쪽인지 판단한다.

---

## 병원 웹

### 지금 만들어진 것

**병리과만** 만들어져 있다. 다른 과(유방외과·영상의학과·간호과·원무과·
관리부)는 각 담당자가 맡는다. 이 저장소의 `hospital/` 은 병리과 화면
다섯 장과 그것이 쓰는 부품·토큰만 들고 있다.

| 주소 | 화면 |
|---|---|
| `/hospital/pathology` | 검체 접수 — 대기 큐, 「다음 환자 받기」 |
| `/hospital/pathology/specimens` | 환자 목록 |
| `/hospital/pathology/specimens/:id/upload` | 크롭 조직 이미지 올리기 |
| `/hospital/pathology/read/:id` | 판독 — 뷰어 · AI 소견 · 의사 소견 |
| `/hospital/pathology/read/:id/amend` | 판독 정정 |

`/hospital` 로 들어오면 `/hospital/pathology` 로 넘긴다.
**`/` 는 건드리지 않는다** — 환자 앱 자리다.

주소를 바꿀 일이 생기면 `hospital/nav.js` **한 곳만** 고친다. 화면들은
`go.upload(id)` 처럼 그 파일의 함수를 통해서만 주소를 만든다.

### 화면이 서버를 부르는 자리

전부 `hospital/api.js` 를 지난다. 화면 안에서 `fetch` 를 직접 쓰지 않는다.

```js
api.queue()          GET  /specimens?status=bound&assigned=none
api.specimen(id)     GET  /specimens/{id}
api.assign(id)       PATCH /specimens/{id}/assign
api.uploadInfo(id)   GET  /specimens/{id}/upload
api.ticket(body)     POST /tickets
api.analyze(id)      POST /specimens/{id}/ai-results
api.aiResults(id)    GET  /ai-results?specimen={id}
api.read(id)         GET  /specimens/{id}/read
api.draft(id, body)  PUT  /specimens/{id}/draft
api.finalize(id, b)  PATCH /specimens/{id}/finalize
api.list(opts)       GET  /specimens?…
api.amend(id, body)  POST /specimens/{id}/amend
```

**목업에서 진짜 서버로 갈아탈 때 고칠 곳은 셋뿐이다.** `api.js` 안에
`⚠` 로 표시해 두었다.

1. `BASE` — 주소 앞머리. `.env.local` 의 `VITE_API_BASE` 로 덮을 수 있어
   보통은 코드를 안 고쳐도 된다.
2. `unwrap()` — 응답이 `{ data: … }` 로 싸여 오는지 벗겨서 오는지.
3. `setToken()` — 로그인 뒤 받은 토큰을 넣는 자리.
   **토큰은 메모리에만 둔다. localStorage 에 넣지 않는다.**

오류는 모양을 맞춰 던진다.

```js
{ status, code, detail, fields }
```

네트워크가 끊기면 `status: 0`, `code: "NETWORK"` 다. 예전처럼
"Failed to fetch" 가 화면에 그대로 뜨지 않는다.

### 아직 안 채워진 자리

* **업로드** — 파일 선택 창은 열리지만 실제로 보내지 않는다.
  티켓 발급 → Go 관문 업로드 규격이 아직 없다. 고른 파일은 「전송 준비 중」
  칩으로만 보인다. **올라간 것처럼 그리지 않는다.** 규격이 오면
  `Upload.jsx` 에서 `api.ticket()` 부르는 자리만 채우면 된다.
* **쪽 넘김** — 환자 목록에 나누는 규격(page / cursor)이 명세에 없어
  넣지 않았다. 지금은 `{total}건 중 {n}건 표시` 만 보여 준다.

### 병리 화면이 쓰는 값

등급은 **`b_category` (b1~b5)** 다. BI-RADS 가 아니다. 맘모 쪽과 헷갈리지 말 것.

AI 지표는 이렇게 낸다.

| 값 | 화면에 |
|---|---|
| `stil_calibrated` | 퍼센트로 낸다 |
| `stil_level` | low→낮음 · mid→중등도 · high→높음 |
| `tsr_percent` | 퍼센트로 낸다 |
| `cell_counts` | 총 / TIL / 간질내 TIL |
| `stil_nucleus` | **안 낸다.** 보정 전 값이라 임상 기준의 1/12 로 나온다. 화면에도 소견문에도 넣지 않는다. |

`stroma_status` 가 `absent` 면 sTIL 이 없다. **0% 가 아니라 「평가 불가 —
간질 없음」으로 적는다.** 0% 로 적으면 면역 반응이 없다는 뜻이 되어
정반대로 읽힌다.

크롭이 여러 장이면 **평균을 내지 않는다.** 장마다 나란히 보여 준다.

정정은 새 판독 행을 만들지 않는다. `specimen.amend_history` (JSONB) 에
쌓는다. `specimen_label` 이 유일 키이고 `discordance_flag` 가 붙어 있어
새 행을 만들면 둘 다 깨진다.

---

## 환자 앱

`src/` 에 있다. 화면은 홈 · 예약 · 검사 결과 · 안내문 · 문진 · 내 정보 ·
설정 · 챗봇 · 알림.

* 안내문 PDF 는 따로 만들지 않는다. 브라우저 인쇄(`window.print()`)와
  `@media print` 규칙으로 뽑는다.
* 색은 `src/tokens.css` 에 있다. **분홍은 상태 색으로 쓰지 않는다.**
  성공·주의·오류는 `--ok` / `--warn` / `--error` 를 쓴다.
  화면의 70~80% 는 무채색, 분홍은 10~15% 만.

### 지켜야 할 것

* **주민등록번호는 어디에도 저장하지 않는다.** 확인 요청 한 번에만 실려
  가고 화면 상태에서 곧바로 지운다. localStorage · sessionStorage 금지.
  뒷자리 입력칸은 `type="password"`.
* **JWT 토큰은 localStorage 에 두지 않는다.** 메모리에만 둔다.

---

## 폴더

```
index.html          환자 앱 입구
hospital.html       병원 웹 입구
vite.config.js      두 입구를 같이 빌드한다 + /hospital 되돌림 + 프록시
env.example         .env.local 견본

src/                환자 앱
  lib/              부품 · 날짜 · 부서 이름 · 오류 그물
  screens/          화면
  tokens.css        색과 치수
  index.css

hospital/           병원 웹
  hospital.html 이 여기를 읽는다
  main.jsx          라우트
  nav.js            주소는 여기 한 곳에서만 만든다
  api.js            서버를 부르는 자리는 여기만
  tokens.css        색과 치수 (환자 앱과 이름이 겹친다 — 섞지 말 것)
  hospital.css
  lib/              Page · Top · Body · Parts · useApi
  screens/path/     병리과 화면 다섯 장

mock/               목업 응답
  hospital.js       /api/v1/hospital/** 만 맡는다
  hospital.json     응답 본문
```

---

## 환경 설정

`env.example` 을 `.env.local` 로 복사해서 쓴다. `.env.local` 은 git 에
올라가지 않는다.

```bash
cp env.example .env.local
```

| 이름 | 무엇 |
|---|---|
| `VITE_API_BASE` | 병원 웹이 부를 API 주소 앞머리 |
| `EMPATHO_SERVER` | 프록시가 넘길 서버 주소 |

값을 안 주면 `dev:mock` 은 목업으로, `dev` 는 nginx 를 거쳐 Django 로 간다.

---

## 브랜치

작업은 `geommo` 에서 한다.
