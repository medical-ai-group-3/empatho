# EMPATHO 백엔드 API 전체 정리

작성: 2026-09-16 · 담당: 다희(reception·nursing·radiology·pathology·surgery·admin·인증)
Base URL: `/api/v1` · 브랜치: `feature/dahee`

이 문서는 다른 세션에서 프론트 연동 작업을 이어가기 위한 통합 참고자료입니다.
Swagger(`/api/docs/`)는 대부분 정확하지만, 함수 기반 뷰(login/signup/me 등)와
`Response(dict)`를 직접 리턴하는 일부 뷰는 스키마가 부정확하거나 비어 보일 수
있습니다 — 이 문서를 기준으로 삼으세요.

---

## 0. 공통 규약

### 응답 봉투 (전체 공통)

성공:

```json
{"success": true, "data": { ... }, "error": null, "trace_id": "01JB2K..."}
```

실패:

```json
{"success": false, "data": null, "error": {"code": "...", "message": "...", "details": null}, "trace_id": "01JB2K..."}
```

`trace_id`는 응답 헤더 `X-Trace-Id`에도 옵니다.

### 인증

`Authorization: Bearer <access_token>` 헤더 필요 (health/login/signup/token/refresh/logout 제외).

### 페이지네이션 (목록 조회 다수)

```json
{"count": 123, "next": "...", "previous": "...", "results": [...]}
```

이 구조가 `data` 안에 들어갑니다. `?page=`, `?page_size=` 지원.

---

## 1. 인증·계정 (`core/api/`)

| 메서드 | 경로 | 설명 | 인증 필요 |
|---|---|---|---|
| POST | `/login` | `{login_id, password}` → `{access}` (본문), `refresh_token` 쿠키(httpOnly, Secure, SameSite=None) | ✗ |
| POST | `/token/refresh` | 쿠키의 `refresh_token` 읽어서 `{access}` 재발급 | ✗ (쿠키 필요) |
| POST | `/logout` | `refresh_token` 쿠키 삭제. 서버 쪽 토큰 무효화는 안 됨(Redis 미도입) | ✗ |
| POST | `/signup/staff` | `{login_id, password, role, full_name, staff_number}` → `account_status='pending'`, `is_active=False`. role은 reception/nursing/radiology/surgery/pathology만(admin/patient 불가) | ✗ |
| POST | `/signup/patient` | `{login_id, password}` → `account_status='active'`, `is_active=True`, 즉시 토큰 발급(access 본문 + refresh 쿠키) | ✗ |
| GET | `/me` | 로그인 계정 정보 + 권한 배열 | ✓ |
| GET | `/health` | 상태 확인 (DB 죽어도 200) | ✗ |
| POST | `/tickets` | 파일 업로드용 티켓 발급 (Go file-gateway 연동) | ✓ |

`GET /me` 응답:

```json
{
  "name": "박민재", "role": "pathology", "dept": "pathology",
  "dept_name": "병리과",
  "perms": ["pathology.queue.view", "pathology.queue.assign", "..."]
}
```

현재 `perms` 카탈로그는 병리과·영상의학과 24개만 정의됨(`core/api/perms.py`).
원무·간호·유방외과·관리자 화면에서 필요해지면 추가 요청 필요.

**쿠키 관련 주의**: `SameSite=None` + `Secure=True`. 로컬 개발 시 프론트/백엔드
둘 다 `localhost`(또는 둘 다 `127.0.0.1`)로 통일해서 접속해야 함 — 하나만
다르면 브라우저가 별개 origin으로 취급해 쿠키가 거부될 수 있음. 프론트에서
fetch는 `credentials: "include"`, axios는 `withCredentials: true` 필수.

---

## 2. 원무과 (reception)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/patients/?q=` | 환자 검색 (환자번호 정확일치, 이름/전화/생년월일 부분일치) |
| GET | `/patients/?primary_staff=me` | 로그인한 유방외과 의사의 담당 환자 목록 |
| POST | `/patients/` | 환자 등록 (기존, patient+patient_pii 필드 전부) |
| POST | `/patients/register` | §1 간소화 등록 — name/birth_date/phone만, 중복이면 기존 환자 반환 |
| GET | `/patients/{id}/` | 환자 상세 |
| PATCH | `/patients/{id}/` | 환자 정보 수정 (primary_staff 지정 포함) |
| GET | `/patients/today-status` | §1 오늘 방문 환자 모니터링(단계별 상태) |
| PATCH | `/patients/{id}/questionnaire/` | 문진 저장(JSONB 덮어쓰기, 검증 포함) |
| GET | `/exam-orders` | 검사오더 목록 — `?status=&visited=yes/none&scheduled_on=today/YYYY-MM-DD&scheduled_from=&scheduled_to=&patient=&ordering=` |
| GET | `/exam-orders/{id}` | 검사오더 단건 |
| POST | `/exam-orders/checkin` | §1 접수하기 — `{patient_id}` → requested + visited_at |
| POST | `/exam-orders/schedule` | §3 예약 — `{patient_id, scheduled_at}`, 검사종류는 미정 상태 |
| PATCH | `/exam-orders/{id}/confirm` | §7 원무 확정 — `{modalities:[...], exam_purpose, ordered_by}`. 여러 modality면 첫 번째는 기존 행 확정, 나머지는 `parent_order_id`로 묶어 신규 생성. 이미 확정된 건 재요청시 409 `ALREADY_CONFIRMED` |
| POST | `/reservations/` | (기존) 원무가 검사종류까지 정해서 exam_order N건 생성 |
| GET | `/reservation-requests` | 원무 큐 — `order_status='requested'`만 |
| POST | `/me/reservation-requests/` | 환자 본인이 날짜만 신청(모달리티 없음) |
| GET | `/staff?role=` | 부서별 직원 목록(배정 팝업용) |

---

## 3. 간호과 (nursing)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/visits/today/` | 오늘 방문 목록 |
| POST | `/visits/today/` | `{exam_order_id}` → 내원 확인(visited_at) |
| GET | `/followups/` | 추적 목록. `?include_candidates=1`이면 아직 followup 행 없는 category=3 확정 환자도 후보로 포함 |
| POST | `/followups/new` | `{patient_id, round_no, due_at}` 회차 생성 |
| PATCH | `/followups/{id}/call` | `{call_result, call_note}` 통화 기록 |
| PATCH | `/followups/{id}/` | (기존) 통화기록 또는 회차종료 — body에 `closed_reason` 있으면 종료, 없으면 통화기록 분기 |

검체 바인딩은 §5(유방외과) 참고 — 같은 컴포넌트 재사용.

---

## 4. 영상의학과 (radiology)

주의: 같은 기능에 경로 별칭(alias)이 여러 개 있습니다.

| 메서드 | 경로 | 권장 | 설명 |
|---|---|---|---|
| GET | `/exam-orders/queue` | ✅ | 대기 큐. `?status=ordered&assigned=none` 프론트에서 붙여야 함 |
| GET | `/radiology/queue` | (별칭) | |
| POST | `/exam-orders/{id}/start-study` | ✅ | 촬영 시작 → Study 생성 |
| POST | `/radiology/queue/{id}/start-study` | (별칭) | |
| PATCH | `/exam-orders/{id}/assign` | | 집기. 이미 집혔으면 409 `ALREADY_ASSIGNED` |
| PATCH | `/exam-orders/{id}/complete` | | 영상 품질 승인 → AI 분석 시작 트리거 |
| GET/PATCH | `/studies/{id}/upload` | ✅ | 업로드 조회/품질승인 |
| GET/PATCH | `/radiology/studies/{id}/upload` | (별칭) | |
| GET | `/studies/{id}/read` | ✅ | 판독 통합조회. 업로드 파일 없으면 409 `STUDY_NOT_READ_READY` |
| GET | `/radiology/studies/{id}/read` | (별칭) | |
| POST | `/studies/{id}/ai-results` | | AI 분석 시작(202, `run_status='queued'`) |
| GET | `/ai-results?study={id}` or `?specimen={id}` | | 통합 진행상태. `{"status": "...", "pct": 0~100}` |
| PUT | `/studies/{id}/assessment/draft` | | 판독 임시저장 |
| PATCH | `/studies/{id}/finalize` | | 판독 확정 |
| GET/POST | `/lesions/` | | 병변 조회/생성 |
| PATCH | `/lesions/{id}/` | | 오탐 표시 |
| GET | `/studies/` `/studies/{id}/` | | 검사 목록/상세 |
| GET | `/assessments?study={id}` | | 판정 이력 |
| POST | `/assessments/{id}/amend` | | 판독 정정(새 행+`superseded_by`) |

AI 콜백(완료 후 병변 자동 생성)은 미구현.

---

## 5. 유방외과 (surgery)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/patients/?primary_staff=me` | 내 환자 목록 |
| POST | `/exam-orders` | 촬영 요청. GET/POST가 같은 경로에서 메서드로 분기됨 |
| GET | `/patients/{id}/timeline` | 환자 통합 타임라인 |
| GET | `/reports/?patient=&type=final` | 종합 리포트 조회 |
| PUT | `/reports/{id}/` | `content_json` 수정. 최초 조회 시 열람기록 자동 |
| PATCH | `/assessments/{id}/decision` | 수술 결정. 단독권한(유방외과만), 403은 `DECISION_ROLE_ONLY_SURGERY` |
| PATCH | `/reports/{id}/explain` | 대면 설명 기록 |
| GET | `/reports/{id}/unlock-status` | 잠금해제 조건 판단 |
| PATCH | `/reports/{id}/unlock` | 잠금 해제 |
| GET/POST | `/specimens/` | 목록/바인딩. POST는 단독권한(간호·유방외과) |
| GET | `/discordances?patient=&status=open` | 불일치 목록 |
| GET/PATCH | `/discordances/{id}` | 상세/처분(PATCH는 유방외과만) |

---

## 6. 병리과 (pathology)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/specimens/queue` | 접수 대기 큐 |
| PATCH | `/specimens/{id}/assign` | 집기 |
| GET | `/specimens/{id}` | 검체 상세 |
| GET | `/specimens/{id}/upload` | 업로드된 크롭 목록 |
| POST | `/specimens/{id}/ai-results` | AI 분석 시작 |
| PUT | `/specimens/{id}/draft` | 판독 임시저장 |
| PATCH | `/specimens/{id}/finalize` | 판독 확정 |
| POST | `/specimens/{id}/amend` | 판독 정정(`amend_history` JSONB) |

병리 결과가 검사(study) 직접 참조 못 하는 구조 문제는 팀 결정 대기 중.

---

## 7. 관리자 (admin)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/admin/approvals` | 승인 대기/완료 목록 |
| PATCH | `/admin/approvals/{id}` | 승인 — `is_active`/`account_status` 활성화 |
| PATCH | `/admin/accounts/{id}/role` | 부서 재지정 |

---

## 8. 에러 코드 (자주 마주칠 것)

| 코드 | 상태 | 의미 |
|---|---|---|
| `VALIDATION_ERROR` | 400 | 입력값 문제 |
| `UNAUTHENTICATED` | 401 | 토큰 없음/만료 |
| `ROLE_FORBIDDEN` | 403 | 권한 매트릭스 |
| `NOT_FOUND` | 404 | 대상 없음 |
| `ALREADY_CONFIRMED` | 409 | 이미 확정된 오더 |
| `ALREADY_ASSIGNED` | 409 | 이미 집힌 건 |
| `BINDING_ROLE_FORBIDDEN` | 403 | 검체바인딩 권한 |
| `DISPOSITION_ROLE_ONLY_SURGERY` | 403 | 불일치처분 권한 |
| `UNLOCK_ROLE_ONLY_SURGERY` | 403 | 잠금해제 권한 |
| `DECISION_ROLE_ONLY_SURGERY` | 403 | 수술결정 권한 |
| `STUDY_NOT_READ_READY` | 409 | 업로드 없이 판독시도 |
| `UNLOCK_CONDITION_NOT_MET` | 409 | 잠금해제 조건 미충족 |

전체 목록은 `core/api/errors.py` 참고.

---

## 9. 알려진 미해결/보류 사항

- 병리 결과가 검사(study) 직접 참조 못 하는 구조 — 팀 결정 대기
- AI 분석 완료 후 병변 자동 생성 콜백 — 미구현
- 영상의학과 §5 정정(amend) — 만들어짐, 프론트 실연동 미확인
- 서버 쪽 refresh 토큰 완전 무효화 — Redis 도입 전까지 불가
- perms 카탈로그 — 병리과·영상의학과만, 나머지 부서 추가 필요
