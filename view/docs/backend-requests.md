# 백엔드에 요청할 것

`empatho-view`(화면)가 `empatho-app`(서버)에 요청하는 목록.

**대조 기준** — `empatho-app@c5215db` 의 `core/urls.py` · `core/api/urls.py` ·
`core/models.py` 를 직접 읽고 맞춘 것이다. 들은 말이 아니라 코드다.
서버가 움직이면 이 표도 다시 맞춰야 한다.

**마지막 대조** 2026-09-17

---

## 0. 먼저 — 지난번 요청 중 **해결된 것**

다시 요청하지 않도록 적어 둔다. 예전 목록을 그대로 들고 가면 이미 만들어
주신 것을 또 달라고 하는 셈이 된다.

| 항목 | 상태 |
|---|---|
| `GET /me` | ✅ `core/urls.py:154` |
| `GET /specimens/{id}` · `/upload` · `/assign` · `/draft` · `/finalize` · `/amend` | ✅ 전부 있음 |
| `POST /token/refresh` · `POST /logout` | ✅ `api/urls.py:26-27` |
| `GET /assessments?study=` (영상 정정 이력) | ✅ `urls.py:124` |
| 영상 대기 큐 경로가 두 가지 | ✅ **둘 다** 만들어 주셨다 — `/exam-orders/queue` 와 `/radiology/queue`(alias) |
| 슬래시 규칙 | ✅ 문제 아님. `api/urls.py` 맨 끝 catch-all 때문에 APPEND_SLASH 리다이렉트가 일어나지 않는다. 슬래시를 빠뜨리면 깔끔한 404 다 |
| 로그인 경로·필드 | ✅ 화면 쪽을 `POST /login { login_id, password }` 로 맞췄다 |

---

## 1. 🔴 표(table)가 없는 것 — 새로 만들어야 한다

### 1-1. 복약 관리 — 표 3개

화면은 **처방전을 원천으로** 만들어 두었다(`src/screens/Meds.jsx`).
약 목록을 따로 들지 않고 처방전 안의 약을 꺼내 쓴다 — 약이 왜 거기
있는지(누가·언제·며칠분)를 같이 말할 수 있어야 해서다.

| 표 | 주요 칸 |
|---|---|
| `prescription` | `prescription_id` · `patient`(FK) · `issued_by`(staff FK) · `dept` · `issued_on` · `days` · `status`(`active`\|`ended`) |
| `prescription_drug` | `drug_id` · `prescription`(FK) · `name` · `ingredient` · `dose` · `times`(jsonb `["09:00","19:00"]`) · `per_day` · `purpose` · `how` · `watch` |
| `medication_log` | `log_id` · `drug`(FK) · `patient`(FK) · `slot_time` · `taken_at` |

> ⚠ `core/api/tickets.py` 에 **「처방 표가 MVP 밖이라…」** 로 적혀 있다
> (`prescription_pdf` 가 `UNSUPPORTED_PURPOSES`). **범위를 다시 여는
> 결정이 먼저** 필요하다.

> ⚠ `purpose` · `how` · `watch` 는 **설명 문구**다. 화면은 이 세 칸을
> 그대로 옮겨 적을 뿐, 약 이름으로 약전을 뒤져 지어내지 않는다 — 같은
> 성분도 환자마다 쓰는 이유가 다르고, 앱이 지어내는 순간 그것은
> **의학적 조언**이 된다. 누가 이 문구를 쓰는지(처방의/약국)를 정해야 한다.

### 1-2. 병원 찾기 — 표 1개

| 표 | 주요 칸 |
|---|---|
| `hospital` | `hospital_id` · `name` · `dept` · `address` · `phone` · `hours` · `region` · `is_partner` · **`lat`·`lng`(필수)** |

> ⚠ `lat`·`lng` 는 **선택이 아니라 필수**다. 화면이 「가까운 순」과 거리
> 표시를 그 값으로 만든다. 지도 앱으로 넘기는 링크도 좌표를 쓴다.

> ⚠ 지금 스키마는 **단일 병원 전제**다. 어느 표에도 병원을 가리키는 칸이
> 없다. 협력 병원 목록을 두려면 표가 새로 있어야 한다.

### 1-3. 직원 신원 칸 — `staff` 표에 없다

| 필요한 칸 | 지금 |
|---|---|
| `email` · `phone` · `hospital` | **없음**. `staff` 에는 `staff_number` · `full_name` · `extra_permissions` · `approved_*` 뿐 |
| `notify_*` (직원 알림 설정) | **없음** |
| 세부 분과 | **없음**. `account.role` 로는 「외과」까지만 갈리고 **유방외과가 안 나온다** — 환자 앱의 「담당 주치의 ○○○ · 유방외과」가 「외과」로 뜬다 |

> 화면은 **값이 오는 칸만 그린다**(`hospital/screens/Me.jsx`). 칸이 생기면
> 코드를 안 고쳐도 자리가 생긴다.

---

## 2. 🔴 경로(route)가 없는 것

### 2-1. 복약 · 병원 — 새 기능

| 메서드 · 경로 | 응답 | 비고 |
|---|---|---|
| `GET /api/v1/me/prescriptions` | `{ items[], note }` | 처방전 + 약 중첩. **본인 것만** |
| `POST /api/v1/me/medications/{drugId}/log` | `{ log_id, taken_at }` | 본문 `{ time }` — 회차만 보낸다 |
| `DELETE /api/v1/me/medications/{drugId}/log/{logId}` | `{ ok }` | 잘못 누른 것 되돌리기 |
| `GET /api/v1/hospitals?q=&region=` | `{ items[], regions[], note }` | 로그인 없이 열지 여부 확인 필요 |

응답 모양은 `mock/db.json` 의 같은 열쇠를 그대로 보면 된다 — 화면이
지금 그 모양으로 돌고 있다.

### 2-2. 환자 앱 — 아직 없는 것

`core/urls.py` 에 직원용은 오십여 개가 들어왔는데 **환자 앱이 쓰는 것은
대부분 아직 없다.**

| 화면 | 경로 | 상태 |
|---|---|---|
| 홈 | `GET /home` | ❌ |
| 문진 | `GET`·`PUT /questionnaire` | ❌ |
| 알림 | `GET /notifications` · `POST /notifications/{id}/read` | ❌ |
| 알림 설정 | `PUT /notifications/settings/{kind}` | ❌ |
| 동의 | `GET /consents` · `POST /consents/{kind}/withdraw` | ❌ |
| 챗봇 | `POST /chat` | ❌ |
| 예약 | `GET /me/reservations` · `POST /me/reservations/{id}/cancel` | 🟡 `reservations` · `me/reservation-requests` 뷰셋은 있음 — 본인 조회·취소가 되는지 확인 필요 |
| 결과 | `GET /reports` · `GET /reports/{id}` | 🟡 `reports` 뷰셋이 있으나 **유방외과용**(`SurgeryReportViewSet`)이다. 환자가 같은 경로로 자기 것만 보는지 확인 필요 |

### 2-3. 🔴 환자 가입이 **병원 기록과 안 이어진다**

지금 `POST /signup/patient` 는 `login_id` · `password` 만 받아 계정을
만든다(`core/api/views.py:175`). **환자 표와 잇는 자리가 없다.**

그러면 가입한 사람은 자기 검사도 결과도 못 본다 — 서버가 그 계정이
어느 환자인지 모른다.

화면은 세 걸음으로 만들어져 있다(`src/screens/Signup.jsx`).

| 걸음 | 경로 | 하는 일 |
|---|---|---|
| ① | `POST /signup/verify-phone` | 이름 · 주민등록번호 · 휴대폰 → 인증번호 발송 |
| ② | `POST /signup/verify-code` | 인증번호 확인 → `verify_token` |
| ③ | `POST /signup/link` | `verify_token` + 아이디 · 비밀번호 → 가입 완료 |
| — | `GET /signup/check-id?value=` | 아이디 중복 확인 |

**병원 기록과 잇는 열쇠는 주민등록번호다.** 병원이 그 번호로 이미 있는
환자를 찾아 계정에 붙여 준다. 환자는 병원코드도 환자번호도 모른다.

> ⚠ 주민등록번호는 앱이 **저장하지 않는다.** ①의 본문에 한 번 실릴 뿐이고
> 화면은 보내자마자 상태에서 지운다. 서버도 로그에 남기면 안 된다.

---

## 3. 🟡 확인이 필요한 것

| 항목 | 물어볼 내용 |
|---|---|
| `taken_at` 을 누가 찍나 | **서버가 찍어야 한다.** 앱이 보낸 시각을 믿으면 기기 시계가 틀어진 만큼 기록이 어긋난다. 앱은 「어느 회차」(`time`)만 보낸다 |
| 같은 회차 중복 기록 | 두 번 POST 하면? 409 로 막을지, 덮어쓸지 |
| `times` 자료형 | jsonb 배열로 둘지, 행으로 뺄지 |
| `hospitals` 인증 | 로그인 전에도 보여야 하나 |
| ~~위치 기반 거리~~ | ✅ **서버에 안 물어도 된다.** 화면이 브라우저 위치로 직접 잰다(`src/lib/near.js`). 서버에는 **병원 좌표(`lat`·`lng`)만** 주면 된다 — 좌표를 서버로 보내면 「어디 살고 어느 병원 다니는지」가 기록에 남아서, 거리 하나 때문에 치를 값이 아니다 |
| `status_label` 류 한글 칸 | 응답에 넣을 것인지. **안 넣어도 화면은 돈다** — 코드로 한글을 만든다(`hospital/codes.js`). 넣는다면 칸 이름만 알려 주면 된다 |
| `followup.status` 의 `candidate` | 간호과 화면이 쓰는데 `FOLLOWUP_STATUS` enum(`open`·`resolved`·`escalated`·`declined`·`overdue`)에 **없는 값**이다 |
| `patient_pii.sex` | `CharField(20)` 에 CHECK 이 없다. 무엇이 오는지 정해 주면 화면의 별칭 표를 줄일 수 있다 |

---

## 4. 🟡 DICOM 을 브라우저에서 못 받는다

Go 관문은 DICOM 에 대해 티켓 범위를 **정확히 일치**로 본다.

```
fromOrthanc:  cl.ObjectKeyPrefix != "dicom/instances/<UID>"  → 403
```

그런데 `POST /tickets` 는 그 모양의 범위를 **낼 수가 없다.** `scope_kind`
로 받는 값이 `study`·`specimen`·`report`·`account` 넷뿐이라 접두사가 늘
`study/201` 꼴로 나온다. 둘이 영영 안 맞는다.

지금 그 접두사를 만들 수 있는 것은 **Celery 뿐**이다 — 추론에 파일을
넘길 때 `issue("download", "dicom/instances", uid)` 를 직접 부른다
(`core/tasks.py`). 사람이 지나가는 길이 아니다.

→ **맘모 원본 한 장과 MRI 시리즈를 판독 화면에서 받을 길이 없다.**
화면은 지금 빈 뷰어 대신 이유를 띄운다(`hospital/lib/files.js`).

---

## 5. ⚪ 서버가 아니라 우리 쪽 — 같이 적어 둔다

| 항목 | 내용 |
|---|---|
| ~~`public/dicom/…` 자료가 없을 때 「Unexpected token '<'」~~ | **처리함.** 자료는 여전히 저장소에 없다(용량 때문에 `.gitignore`). 다만 Vite 가 404 에 `index.html` 을 돌려주는 것을 `lib/dicom/manifest.js` 가 가려내고 「샘플 DICOM 자료가 없습니다」로 바꾼다. 맘모·MRI 뷰어 둘 다 적용 |
| 로고 SVG | 지금 것은 자동 추적본(path 23개)이다. 워드마크가 들어간 원본이 오면 소개 화면의 글자 두 줄을 그림 하나로 바꾼다 |
| 캐릭터 영문 표기 | 시트는 `Tily`(L 하나), 코드는 `Tilly` 다 |

---

## 부록 — 응답 모양은 목업이 규격이다

새 경로의 응답 모양은 **`mock/db.json` · `mock/hospital.json` 을 그대로
보면 된다.** 화면이 지금 그 모양으로 돌고 있어서, 서버가 같은 모양으로
주면 화면은 한 줄도 안 고쳐도 된다.

```bash
npm run dev:mock     # 환자 앱   http://localhost:5173/
npm run dev:hos      # 병원 웹   http://localhost:5173/hospital
```

두 곳이 어긋나면 화면이 조용히 빈다 — 경로를 늘릴 때 `src/api.js`
(또는 `hospital/api.js`)와 목업을 같이 고치는 것이 이 저장소의 규칙이다.
