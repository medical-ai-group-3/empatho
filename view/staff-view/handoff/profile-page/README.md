# 내 정보(/me) 페이지 — 다른 과 화면 이식용

유방외과(staff-view) 프로젝트에서 "내 정보 · 설정" 페이지(`/me`) 관련 파일만 모았습니다.

## 핵심 파일 (반드시 필요)

- `src/screens/Profile.jsx` — 페이지 전체. 이 파일 하나에 다 들어있음(서브컴포넌트도 별도 파일 아님).
- `src/lib/useApi.js` — API 로딩/에러 상태 훅.
- `src/lib/Screen.jsx` — `Head`/`Body` 공용 레이아웃 컴포넌트.
- `src/api.js` — 공용 API 모듈. `Profile.jsx`는 이 중 `api.me()`, `api.updateMe()`, `api.logout()`만 씀. 다른 과 프로젝트에 이미 자체 api.js가 있다면, 이 세 메서드만 옮겨 붙이면 됨(파일 하단 참고).
- `mock-data-snippet.json` — 위 세 API의 mock 응답. 각 과 프로젝트의 `mock/db.json`에 키 그대로 병합하면 됨.

## 주의: CSS는 전역 파일에서 가져온 것 (페이지 전용 아님)

`Profile.jsx`는 자체 `<style>` 태그가 없고, 프로젝트 전역 `src/index.css`의 클래스에 전부 의존합니다:

```
.pane .cols2 .card .pt-head .avatar(.sm) .name .sub
.field(.err) .card-foot .split .note .btn(.ghost) .check-row
```

`Head`/`Body`가 쓰는 것도 추가로 필요:
```
.shead .back-btn .tx .empty .ic
```

`index.css` 전체를 참고용으로 같이 넣었지만(`src/index.css`), 그대로 통째로 가져다 쓰면 다른 화면 스타일까지 다 딸려옵니다 — 위 클래스만 뽑아서 옮기거나, 이미 비슷한 디자인 시스템이 있다면 그쪽 토큰(`--ink`, `--muted`, `--line`, `--accent` 등 CSS 변수)에 맞춰 다시 매핑하는 걸 추천합니다.

## 참고용 (페이지 자체엔 불필요, 동작 이해용으로만 포함)

- `src/App.jsx` — 상단 네비게이션바(로고/다크모드/알림/시계) + `/me` 링크가 있는 곳. 이건 페이지가 아니라 앱 셸이라, "내 정보 페이지"만 재사용할 거면 안 가져와도 됨. 다만 상단바의 `/me` 진입 링크 UX까지 그대로 재현하고 싶다면 참고.
- `src/lib/theme.js` — 다크/라이트 테마 전환 로직 (App.jsx가 씀).
- `src/main.jsx` — 라우트 정의 참고용. `{ path: "/me", element: <Profile /> }` 한 줄이 전부.

## 이식 체크리스트

1. `Profile.jsx` + `useApi.js` + `Screen.jsx` 복사
2. 대상 프로젝트 `api.js`에 `me`/`updateMe`/`logout` 세 메서드 추가 (엔드포인트: `GET/PUT /api/v1/me`, `POST /api/v1/auth/logout`)
   - ⚠ `/api/v1/staff/me` 에서 `/api/v1/me` 로 바뀌었습니다. 서버에 직원용 접두
     경로가 없습니다(최일운님 회신 · 다희님 병리 경로표에도 `GET /me`).
   - ⚠ 로그아웃 경로는 아직 명세에 없습니다. 확정되면 다시 맞춰야 합니다.
3. mock 서버 쓰면 `mock-data-snippet.json` 내용을 그쪽 `mock/db.json`에 병합
4. 라우트에 `{ path: "/me", element: <Profile /> }` 추가
5. 위에 적은 CSS 클래스들을 대상 프로젝트 전역 CSS에 옮기거나 매핑
