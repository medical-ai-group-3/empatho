# CDSS API 요약

사양서 3종(API 명세서 v3 · API-테이블 매핑표 v3 · DB 설계문서 v3)에서
개발에 필요한 것만 뽑아 합쳤다. **원본 docx 는 저장소에 두지 않는다.**

- 공개 API **100개** (2~14장) · Django + DRF 가 단독으로 DB 를 쓴다
- 테이블 **34개** (필수 25 · 선택 9) · 컬럼 345개

---

## 0 · v3 개정 이력 · 스키마 보완 필요 항목

원본 docx 를 저장소에 두지 않으므로, **결정과 미결 항목은 여기로 옮겨 적는다.**
아래는 원본에서 그대로 옮긴 것이고 요약하거나 해석하지 않았다.

### 0-1 · v3 개정 이력 — 2026-08-19 팀 합의 확정

출처: DB 설계문서 v3 「v3 개정 이력」. 스키마에 영향 있는 항목만 옮겼다.

| 항목 | v2 → v3 |
|---|---|
| 테이블 수 | 35 → 34. `hospital` 삭제 (처방전은 유지 — 결제 기능만 만들지 않는다) |
| `staff.department` | 원무(reception)와 시스템 관리자(admin)를 분리한다. 관리자는 임상 액터가 아니므로 사용자 목록(6명)에는 넣지 않고 권한 매트릭스에만 열을 둔다 |
| `lesion` | `lesion_type` 신설 (mass / calcification / asymmetry / architectural_distortion / lymph_node). `needs_additional_view` + 사유 신설 — 등급 0을 등급으로 접지 않기 위한 칸 |
| `lesion_descriptor` | 초음파 전용 → 맘모 + 초음파. 허용값을 (모달리티, 병변유형) 조합으로 제약 |
| `assessment` | `category` 에 6 추가. `path_agreement` 에 not_applicable 추가. `rule_table_version` 은 모달리티 접두사 필수 (mammo-v1.0 / us-v0.3) |
| `pathology_result` | `b_category`(b1~b5) 신설 — AI 는 benign/malignant 만 내고 B분류는 병리의가 직접 고른다. `amend`·`superseded_by_id` 는 만들지 않는다 |
| **`pathology_slide`** | **`pathology_result_id` → `specimen_id` FK 로 전환.** 스캔 배율 · mpp 추가 (세포밀도 sTIL 환산용) |
| `discordance_flag` | `violated_rule` 에 rule5(역불일치 — 영상 3·4a 인데 병리 악성) 추가 |
| 처방 · 결제 | 결제(payment) 테이블을 신설하지 않는다. 서류 발급 화면에 수납 버튼만 두고 발급 조건으로 걸지 않는다. 처방전(prescription)은 그대로 유지 |
| 프로토타입 범위 | `notification` 발송 결과 컬럼 · 내부 콜백 멱등성 키 · `model_registry` 테이블은 만들지 않는다. 소켓 가용 여부는 설정 파일(yaml) |
| 이름 길이 | 30자 → 25~30자 (공통 규약 합의문과 통일) |

매핑표 v3 가 별도로 기록한 결정:

| 항목 | 내용 |
|---|---|
| `conformal_q` 제약 | 삭제 — DB 제약↔에러 매핑에서 제거. `gate_flags` 1건 이상 → `abstained=true` 로 대체 |
| `model_registry` (G5) | 만들지 않는다 — 프로토타입 범위. 소켓 가용 여부는 설정 파일(yaml) |
| G11 · G12 | `notification` 발송 결과 · 콜백 멱등성 키는 만들지 않는다 — 재시도를 하지 않으므로 필요 없다 |
| 신규 반영 대상 | `lesion_type` · `needs_additional_view` · `b_category` · `category` 6 · `path_agreement` not_applicable · **`pathology_slide` 의 `specimen_id` 전환** · 소켓 1·2 테이블 분리 · `GET /me/followups` |

### 0-2 · 스키마 보완 필요 항목 (갭 목록)

출처: 매핑표 v3 「6. 스키마 보완 필요 항목」 전 16건.

> 매핑 과정에서 드러난 공백이다. W0(8.25–8.31) 스키마 잠금 전에 결정해야 하며,
> 잠긴 뒤에는 과거 레코드를 복원할 수 없는 항목이 포함돼 있다.

| # | 항목 | 문제 | 제안 | 시급도 |
|---|---|---|---|---|
| G1 | `exam_order` 진행 상태 | 접수 · 촬영중 · 완료 · 취소를 담을 컬럼이 없어 4.x 상태 전이를 저장할 수 없다 | `order_status` varchar 추가 | 높음 |
| G2 | `ai_result` 의 병리 대상 | `study_id` 만 있어 7.6 슬라이드 분석의 대상을 가리킬 수 없다 | `pathology_slide_id` bigint 추가 (`study_id` 와 배타) | 높음 |
| G3 | `ai_mask` 의 병리 대상 | `image_instance_id` 만 있어 병리 마스크(tumor·stroma·immune)를 붙일 곳이 없다 | `pathology_slide_id` bigint 추가 | 높음 |
| G4 | `specimen` 접수 상태 | 7.3 병리 접수 완료 여부를 저장할 컬럼이 없다 | `accession_status` + `accessioned_at` | 높음 |
| ~~G5~~ | `model_registry` | — | **만들지 않는다** (v3 확정) | — |
| G6 | `patient` 성명 | 컬럼 자체가 없다 — 비식별 의도인지 누락인지 미확인 | 팀 확인 (Q1) | 높음 |
| G7 | `study` MWL 배포 상태 | D2 추가분에 있으나 DBML 에 반영되지 않았다 | MVP 제외 항목이므로 `mwl_status` varchar 필드만 확보 | 보통 |
| G8 | `staff` 로그인 이력 | `patient_account` 에는 `last_login_at` 이 있으나 `staff` 에는 없다 | `last_login_at` 추가 또는 별도 로그 테이블 | 보통 |
| G9 | `report_access_log.actor_id` | `patient_account_id` 와 `staff_id` 를 한 컬럼에 담아 FK 를 걸 수 없다 | 무결성은 애플리케이션 책임으로 명시하거나 컬럼 분리 | 보통 |
| G10 | SEV-1 승격 규칙 | `notification.acknowledged_at` 미기록 시 승격 기준·기한이 정해지지 않았다 | 운영 정책 확정 후 배치 잡 설계 (Q3) | 보통 |
| ~~G11~~ | `notification` 발송 결과 | Go I-3 이 돌려주는 실패 사유 · 재시도 횟수를 담을 컬럼이 없다 | **만들지 않는다** (v3 확정 — 재시도를 하지 않는다) | — |
| ~~G12~~ | 내부 콜백 멱등성 | I-1~I-5 재시도 시 중복 행을 막을 키 저장소가 없다 | **만들지 않는다** (v3 확정 — 재시도를 하지 않는다) | — |
| **G13** | **`image_pyramid` 테이블 부재** | 타일 피라미드 메타(레벨 수 · 타일 크기 · mpp · 경로 prefix · 빌드 상태)를 저장할 테이블이 아예 없다. **이게 없으면 WSI 판독 화면이 열리지 않는다** | `image_pyramid` 신설 — `source_type`(image_instance/pathology_slide) · `source_id` · `tile_size` · `tile_format` · `level_count` · `max_width/height` · `mpp_x/y` · `object_key_prefix` · `build_status` · `built_at` | **최상 (데모 차단)** |
| G14 | `ai_mask.mask_type` 부족 | 현재 6종(lesion·dense_tissue·breast_area·tumor·stroma·immune)뿐이라 히트맵 · 바운딩박스 · 세포검출 마커를 담을 수 없다. bbox·마커는 래스터가 아니라 좌표 데이터라 저장 형식도 다르다 | `mask_type` 에 heatmap·bbox·cell_detection·contour 추가 + `payload_format`(raster/vector_json) 컬럼 신설 | 보통 |
| G15 | MRI Orthanc 직결 설계 미기록 | Cornerstone3D 가 DICOMweb 으로 Orthanc 에 직접 붙고 Django 를 우회하는 경로가 어느 문서에도 없다. 소켓 3 재개 시 인증·권한 설계부터 다시 논의해야 한다 | 명세서 18장 Q9 로 등재 · 재개 시 우회 경로의 토큰 검증 주체를 먼저 확정 | 보통 (소켓 3 재개 시 높음) |
| G16 | `notification.channel` 값 부족 | 실시간 스트림(G-N5)으로 도달한 건을 구분할 값이 없다 | `channel` 에 stream 추가 (기존 app·sms·call_queue) | 보통 |

> **G13 이 가장 급하다.** 7장(검체·병리)이 MVP 필수 경로이고 완성 기준이
> 「병리 판정까지 끊기지 않고 흐르는가」인데, 이 테이블이 없으면 WSI 를 확대해서 보는
> 화면 자체가 성립하지 않는다. G1~G5 는 API 를 구현하면 즉시 막히고, G11·G12 는 Go
> 콜백을 붙이는 순간 필요해진다 — 멱등성 키가 없으면 재시도 한 번에 `storage_object`
> 가 중복 생성된다. G15 는 스키마 문제가 아니라 기록 누락이므로 재발 방지 차원에서
> 목록에 남긴다.

관련 표기가 본문 다른 곳에도 있다 — 스토리지 매핑의 `image_pyramid.object_key_prefix ⚠ G13`,
7.6 의 `⚠ 슬라이드 참조 컬럼 없음`, 7.9 의 `image_pyramid ⚠`.

### 0-3 · 미결 질문(Q) 해소 기록

원본 사양서가 Q 번호로 등재해둔 미결 항목 중 **확정된 것**을 여기에 적는다.
확정 전에는 원본 상세표에 `정의 확인 필요` · `⚠ 정의 미확정` 으로만 남아 있어
저장소만 봐서는 무엇이 미정인지 알 수 없었다.

#### Q6 · TSR 정의 — **확정**

원본이 남긴 질문 (API 명세서 18장):

> **Q6** | TSR 정의 | 암÷사이조직 vs 암÷(암+사이조직) — 값이 크게 달라짐 | 7장 병리

확정 내용:

| 항목 | 확정값 |
|---|---|
| 공식 | **간질 ÷ (종양 + 간질)** |
| 산출 주체 | AI. 기권 시 수기값이 정답 (사양서 규정) |
| 신뢰구간 | **없음** — `tsr_interval_low`/`high` 를 만들지 않는다 |
| 컬럼 | `pathology_result.tsr_percent` `numeric(5,2)` — 변경 없음 |

**왜 TSR 에만 구간이 없는가** — 나중에 반드시 나올 질문이므로 근거를 남긴다.

`stil_percent` 는 `stil_interval_low`/`stil_interval_high` 로 신뢰구간을 남긴다.
그 구간은 **MC Dropout**(추론 시 dropout 을 켠 채 여러 번 돌려 분산을 구하는 방식)으로
산출한다. 그런데 TSR 을 내는 **소켓 1 조직분할 모델(`linear_tand`)에는 dropout 레이어가
없다.** 켤 dropout 이 없으므로 MC Dropout 자체가 성립하지 않고, sTIL 과 같은 방식의
구간을 낼 수 없다.

즉 **"안 만든 것"이 아니라 "그 모델로는 만들 수 없는 것"이다.** 모델이 dropout 을 갖도록
바뀌면 그때 다시 판단한다.

공식이 `간질 ÷ (종양 + 간질)` 이므로 값은 0~100 으로 갇힌다. `numeric(5,2)` 로 충분하다.
(원본 Q6 의 후보였던 `암÷사이조직` 은 비율이라 100 을 넘을 수 있었다.)

---

## 1 · 공통 규약

| 항목 | 값 |
|---|---|
| Base URL | `/api/v1` |
| 식별자 | bigint. DICOM 은 `study_uid`·`series_uid` 등 별도 unique 컬럼으로 조회 |
| 인증 | `Authorization: Bearer {access_token}` (JWT). **직원 토큰과 환자 토큰 스코프를 절대 섞지 않는다** |
| 요청 | `application/json` · 파일 업로드만 `multipart/form-data` |
| 명명 | 소문자 snake_case · 예약어 회피(`order→exam_order`, `user→staff`) · 25~30자 |
| 감사 컬럼 | `created_by`/`created_at`/`updated_by`/`updated_at` 전 테이블 공통 · **응답에 항상 포함** |
| 페이지네이션 | `?page=1&page_size=20` → `{count, next, previous, results}` |
| 버전 고정 | `model_version`·`lora_version`·`threshold_version`·`rule_table_version` 을 응답에 포함 |
| 멱등성 | 생성 계열 POST 는 `Idempotency-Key` 헤더 권장 |

**응답 봉투** — 모든 응답을 이 형태로 감싼다.

```json
{
  "success": true,
  "data": {},
  "error": null,          // {code, message, details}
  "trace_id": "..."       // 감사 로그 대조용
}
```

## 2 · 서비스 계층 분담

| 계층 | 하는 일 | 하지 않는 일 |
|---|---|---|
| **Django + DRF** | 인증 · 권한 판정 · **모든 DB 쓰기** · 비즈니스 규칙 검증(Hard Stop · 범주 3 차단 · 잠금 3조건) · 전송 티켓 발급 | 대용량 바이트 전송 · 외부 발송 · LLM 응답 대기 |
| Celery + Redis | 소켓 1~5 GPU 추론 호출(FastAPI 직결) · 감사지표 배치 · 추적 회차 스케줄 | 동기 응답이 필요한 처리 |
| Go | 파일 바이트 전송 · 타일 피라미드 서빙 · 알림 발송 · Ollama(MedGemma) 호출 | 권한 판정 · DB 직접 쓰기 |
| FastAPI (GPU) | 소켓 1~5 세그멘테이션 · 분류 · 정량 | 저장 · 판정 |

**원칙** — Go 는 Django 가 서명한 단기 티켓만 검증하고 자체 권한 판정을 하지 않는다.
Go 의 결과는 내부 콜백으로 Django 에 넘어와 기록된다. Postgres 에 직접 쓰지 않는다.

## 3 · 엔드포인트 100개

`W` = 쓰기 · `R` = 읽기. 매핑표 기준.


### 2. 병원 · 계정

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 2.2 | POST | `/auth/staff/signup` | 직원 가입 신청 → account_status=pending | 공개 | staff | — |
| 2.3 | POST | `/auth/staff/login` | 직원 로그인 (직원등록번호@고정도메인) | 공개 | — | staff |
| 2.4 | POST | `/auth/token/refresh` | 토큰 재발급 | 인증 | — | — |
| 2.5 | POST | `/auth/logout` | 로그아웃 | 인증 | — | — |
| 2.7 | GET | `/staff` | 직원 목록 (?account_status=pending) | 관리자 | — | staff |
| 2.8 | PATCH | `/staff/{staff_id}` | 가입 승인 · 반려 · 비활성 | 관리자 | staff | — |
| 2.9 | POST | `/auth/patient/signup` | 환자 계정 생성 (patient_account) | 공개 | patient_account | patient |
| 2.10 | POST | `/auth/patient/login` | 환자 로그인 (스코프 분리) | 공개 | patient_account | — |
| 2.11 | POST | `/me/push-token` | push_token 등록 (예약 · 결과 알림) | 환자 | patient_account | — |

### 3. 환자 · 예약 · 문진

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 3.1 | POST | `/patients` | 신규 환자 등록 | 원무 | patient | — |
| 3.2 | GET | `/patients` | 목록 · 검색 (?patient_number=) | 전 직원 | — | patient |
| 3.3 | GET | `/patients/{patient_id}` | 환자 상세 | 전 직원 | — | patient · questionnaire · exam_order |
| 3.4 | PATCH | `/patients/{patient_id}` | 환자 정보 수정 | 원무 | patient | — |
| 3.5 | GET | `/patients/{patient_id}/timeline` | 통합 타임라인 (전 단계 이력) | 전 직원 | — | exam_order · study · assessment · specimen · pathology_result · discordance_flag · followup_track · report |
| 3.6 | POST | `/reservations` | 예약 등록 (예약 1건 : 오더 N건) | 원무 · 환자 | reservation | patient |
| 3.7 | GET | `/reservations` | 예약 목록 (?reservation_status=) | 원무 · 간호 | — | reservation · patient |
| 3.8 | PATCH | `/reservations/{reservation_id}` | 변경 요청 · 취소 (requested_by) | 원무 · 환자 | reservation | — |
| 3.9 | POST | `/reservations/{reservation_id}/visit` | 내원 확인 — 미기록 시 노쇼 | 간호 | reservation | — |
| 3.10 | POST | `/patients/{patient_id}/questionnaires` | 문진 + 위험 계층화 | 간호 | questionnaire | patient |
| 3.11 | GET | `/questionnaires/{questionnaire_id}` | 문진 조회 | 전 직원 | — | questionnaire |
| 3.12 | PATCH | `/questionnaires/{questionnaire_id}` | 추가 확인 정보 보완 | 간호 | questionnaire | — |

### 4. 오더 · 검사 · 영상

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 4.1 | POST | `/exam-orders` | 오더 생성 — exam_purpose 없으면 생성 거부 | 원무 · 의사 | exam_order | patient · reservation |
| 4.2 | GET | `/exam-orders` | 목록 (?modality=, ?exam_purpose=) | 전 직원 | — | exam_order |
| 4.3 | GET | `/exam-orders/{exam_order_id}` | 상세 (재촬영 체인 포함) | 전 직원 | — | exam_order |
| 4.4 | POST | `/exam-orders/{id}/rework` | 재촬영 오더 (parent_order_id + billing_class) | 원무 | exam_order | exam_order |
| 4.5 | GET | `/exam-orders/{id}/mwl-status` | MWL 배포 상태 — MVP 는 필드로만 | 영상의학 | — | exam_order |
| 4.6 | POST | `/studies` | 검사 생성 (DICOM 파일 업로드 기반) | 영상의학 | study | exam_order |
| 4.7 | GET | `/studies/{study_id}` | 검사 상세 | 전 직원 | — | study · image_series · image_instance |
| 4.8 | PATCH | `/studies/{study_id}/quality` | 판독 반려 · 승인 → 반려 시 재촬영 오더 자동 발행 | 영상의학 | study · exam_order · notification | exam_order |
| 4.9 | POST | `/studies/{study_id}/series` | 시리즈 등록 (pixel_spacing_mm) | 영상의학 | image_series | study |
| 4.10 | POST | `/image-series/{id}/instances` | 업로드 티켓 발급 → 전송은 Go G-F4 · G-F7 | 영상의학 | — | image_series |
| 4.11 | GET | `/storage-objects/{id}/download-url` | 조회 티켓 발급 → 스트리밍은 Go G-F5 | 권한별 | — | storage_object |
| 4.12 | POST | `/patients/{id}/external-results` | 외부 결과지 등록 (order_source=external) | 원무 · 간호 | exam_order · study · storage_object | patient |
| 4.13 | POST | `/studies/{study_id}/breast-density` | 유방밀도 등록 | 영상의학 | breast_density | study · ai_result |
| 4.14 | GET | `/studies/{study_id}/viewer` | 뷰어 세션 — 피라미드 메타 + 타일 티켓 + 오버레이 목록 | 영상의학 | — | image_instance · ai_mask |

### 5. AI 분석

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 5.1 | POST | `/studies/{study_id}/ai-results` | AI 분석 요청 (비동기 202) | 영상의학 | ai_result · lesion · lesion_descriptor · ai_mask | study · image_series · image_instance · storage_object |
| 5.2 | GET | `/ai-results/{ai_result_id}` | 분석 결과 — 1차 판정 잠금 전 403 | 영상의학 | — | ai_result · assessment |
| 5.3 | GET | `/ai-results/{id}/lesions` | 검출 병변 목록 | 조건부 | — | lesion |
| 5.4 | GET | `/lesions/{lesion_id}` | 병변 상세 | 조건부 | — | lesion · lesion_descriptor · ai_mask |
| 5.5 | GET | `/lesions/{id}/descriptors` | BI-RADS 서술자 — 맘모 + 초음파  [v3] | 조건부 | — | lesion_descriptor |
| 5.6 | PATCH | `/lesion-descriptors/{id}` | 판독의 수정 → descriptor_source=radiologist + 등급 재계산 | 영상의학 | lesion_descriptor · lesion | — |
| 5.7 | POST | `/lesions` | 수동 병변 추가 (lesion_source=manual) | 영상의학 | lesion | study |
| 5.8 | GET | `/ai-masks/{ai_mask_id}` | 마스크 오버레이 (XAI 1층) | 조건부 | — | ai_mask · storage_object |
| 5.9 | POST | `/studies/{id}/lesion-merge` | 검사 간 동일 병변 병합 후보 | 영상의학 | — | lesion · study |
| 5.10 | GET | `/model-registry` | 소켓별 모델 · 사용 가능 여부 (설정 파일 기반)  [v3] | 전 직원 | — | ai_result |

### 6. 판정 — 1차 잠금 → AI 공개 → FINAL

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 6.1 | POST | `/assessments` | 1차 판정 (read_stage=first) → 즉시 잠금 | 영상의학 | assessment | lesion · study · exam_order · questionnaire |
| 6.2 | POST | `/assessments/{id}/reveal-ai` | AI 결과 공개 — ai_revealed_at 기록 | 영상의학 | assessment | ai_result |
| 6.3 | POST | `/assessments` | 최종 판정 (read_stage=final) | 영상의학 | assessment | ai_result |
| 6.4 | POST | `/studies/{id}/comprehensive-assessment` | 종합 BI-RADS 판정 (assessment_scope=overall) | 영상의학 | assessment | assessment · breast_density |
| 6.5 | POST | `/assessments/{id}/finalize` | 영상 FINAL — finalized_at 기록 · 잠금 | 영상의학 | assessment | — |
| 6.6 | POST | `/assessments/{id}/amend` | 정정 → 신규 행 + superseded_by_id · 대조 재실행 | 영상의학 | assessment · discordance_flag | — |
| 6.7 | GET | `/assessments/{id}/recommendations` | 권고 후보 조회 (등급 ≠ 조치) | 전 직원 | — | assessment · breast_density · questionnaire · exam_order |
| 6.8 | POST | `/assessments/{id}/findings` | 소견서 작성 · 수정 | 영상의학 | assessment | — |

### 7. 검체 · 병리

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 7.1 | POST | `/lesions/{lesion_id}/specimens` | 검체 등록 · 병변 바인딩 | 간호 단독 | specimen | lesion |
| 7.2 | GET | `/specimens` | 목록 (?binding=unbound) | 간호 · 병리 | — | specimen · lesion |
| 7.3 | POST | `/specimens/{id}/accession` | 병리 접수 — 미바인딩이면 409 | 병리 | specimen | specimen · lesion |
| 7.4 | POST | `/specimens/{id}/pathology-results` | 병리 결과 초안 등록 | 병리 | pathology_result | specimen |
| 7.5 | POST | `/pathology-results/{id}/slides` | WSI 업로드 티켓 발급 → Go G-F1~G-F3 청크 전송 | 병리 | pathology_slide · storage_object | pathology_result |
| 7.6 | POST | `/pathology-slides/{id}/ai-results` | sTIL · TSR 정량 분석 요청 | 병리 | ai_result · ai_mask · pathology_result | pathology_slide |
| 7.7 | GET | `/pathology-results/{id}/reference-images` | 영상 참조 패널 데이터 | 병리 | — | lesion · study · image_instance · storage_object · assessment |
| 7.8 | POST | `/pathology-results/{id}/finalize` | 병리 FINAL = 자동 대조 트리거 | 병리 | pathology_result · discordance_flag · notification | assessment · lesion · specimen |
| 7.9 | GET | `/pathology-slides/{id}/viewer` | WSI 뷰어 세션 — DZI 메타 + 타일 티켓 + sTIL 오버레이 | 병리 | — | pathology_slide · ai_mask |

### 8. 영상–병리 자동 대조 (SYS-4)

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 8.1 | GET | `/discordance-flags` | 목록 (?flag_status=sev1) | 의사 | — | discordance_flag |
| 8.2 | GET | `/discordance-flags/{id}` | 상세 (영상 등급 vs 병리 결과) | 의사 | — | discordance_flag · assessment · pathology_result · lesion · specimen |
| 8.3 | POST | `/discordance-flags/{id}/review` | 검토 의견 제출 — 해소가 아니다 | 영상의학 | discordance_flag | — |
| 8.4 | POST | `/discordance-flags/{id}/disposition` | 해소 처분 | 유방외과 단독 | discordance_flag · clinical_decision | — |

### 9. 추적 관리 (BI-RADS 3 트랙)

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 9.1 | POST | `/assessments/{id}/followup-tracks` | 추적 트랙 개설 | 영상의학 | followup_track | assessment |
| 9.2 | GET | `/followup-tracks` | 목록 (?track_status=overdue) | 간호 · 의사 | — | followup_track |
| 9.3 | GET | `/followup-tracks/{id}` | 트랙 상세 + 회차 | 간호 · 의사 | — | followup_track · followup_round |
| 9.4 | POST | `/followup-tracks/{id}/rounds` | 회차 생성 (6 · 12 · 24개월) | 간호 | followup_round | — |
| 9.5 | PATCH | `/followup-rounds/{id}` | 안내 콜 기록 · 회차 결과 입력 | 간호 | followup_round | — |
| 9.6 | POST | `/followup-rounds/{id}/reentry` | [2] 진단영상 재진입 + followup_round_no +1 | 간호 · 의사 | exam_order · followup_round | followup_track |
| 9.7 | POST | `/followup-tracks/{id}/close` | 종결 (close_reason) | 영상의학 | followup_track | followup_round |

### 10. 임상 결정 (유방외과)

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 10.1 | POST | `/clinical-decisions` | 결정 등록 | 유방외과 | clinical_decision | assessment · discordance_flag |
| 10.2 | GET | `/clinical-decisions` | 결정 이력 (?patient_id=) | 의사 | — | clinical_decision |
| 10.3 | GET | `/patients/{id}/summary` | 최종 종합 리포트(의사용) 데이터 | 의사 | — | assessment · pathology_result · lesion · discordance_flag · report |

### 11. 리포트 · 설명 · 열람 잠금 (SYS-5)

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 11.1 | POST | `/reports` | 리포트 생성 — content_json 동기 · narrative_text 는 Go G-L1 비동기 | 의사 | report | assessment · pathology_result · lesion · ai_result |
| 11.2 | GET | `/reports/{report_id}` | 조회 (잠금 시 409) | 권한별 | report_access_log | report |
| 11.3 | GET | `/reports/{id}/lock-conditions` | 해제 3조건 충족 현황 | 의사 | — | assessment · pathology_result · discordance_flag · result_explanation |
| 11.4 | POST | `/result-explanations` | 대면 설명 기록 — 해제 트리거 · PDF 는 Go G-F4 | 유방외과 | result_explanation · storage_object | report |
| 11.5 | POST | `/reports/{id}/unlock` | 열람 잠금 해제 | 유방외과 단독 | report | result_explanation · discordance_flag |
| 11.6 | POST | `/reports/{id}/issue` | 서류 발급 — PDF 전송은 Go G-F4 | 원무 | report · storage_object | — |
| 11.7 | GET | `/report-access-logs` | 열람 이력 (잠금 통제의 증거) | 관리자 | — | report_access_log |

### 12. 처방 · 약국

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 12.1 | POST | `/prescriptions` | 처방전 사본 등록 (+ items[]) · PDF 는 Go G-F4 | 의사 | prescription · prescription_item · storage_object | patient |
| 12.2 | GET | `/prescriptions/{id}` | 처방전 조회 | 의사 · 원무 · 환자 | — | prescription · prescription_item |
| 12.3 | GET | `/pharmacies` | 약국 조회 (외부 API 캐시) | 환자 | pharmacy | pharmacy |
| 12.4 | POST | `/prescriptions/{id}/pharmacy-events` | viewed / selected 기록 | 환자 | prescription_pharmacy | — |

### 13. 알림 · 감사지표

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 13.1 | GET | `/notifications` | 내 알림 목록 | 인증 | — | notification |
| 13.2 | POST | `/notifications/{id}/ack` | 확인 처리 — 승격 발송은 Go G-N3 | 인증 | notification | — |
| 13.3 | GET | `/audit-metrics` | 감사지표 조회 | 관리자 | — | audit_metric |
| 13.4 | POST | `/audit-metrics/recalculate` | 지표 재계산 (배치) | 관리자 | audit_metric | exam_order · assessment · pathology_result · study · followup_track |

### 14. 환자 앱 · 웹

| # | Method | Endpoint | 용도 | 권한 | W | R |
|---|---|---|---|---|---|---|
| 14.1 | GET | `/me/profile` | 내 정보 | 환자 | — | patient · patient_account |
| 14.2 | GET | `/me/reservations` | 예약 확인 | 환자 | — | reservation |
| 14.3 | POST | `/me/reservations` | 예약 추가 (requested_by=patient) | 환자 | reservation | — |
| 14.4 | PATCH | `/me/reservations/{id}` | 변경 요청 · 취소 | 환자 | reservation | — |
| 14.5 | GET | `/me/reports` | 결과 목록 — 잠금 건은 「설명 후 공개」 상태로만 표시 | 환자 | — | report |
| 14.6 | GET | `/me/reports/{id}` | 열람 → report_access_log 기록 · 잠금 시 409 | 환자 | report_access_log | report |
| 14.7 | GET | `/me/notifications` | 예약 · 추적 알림 | 환자 | — | notification |
| 14.8 | POST | `/me/chat/sessions` | 챗봇 세션 시작 (MVP 범위 밖) | 환자 | chat_session | — |
| 14.9 | POST | `/me/chat/messages` | 챗봇 질의 — 응답 생성은 Go G-L2 스트리밍 | 환자 | chat_message | report |

---

## 4 · 테이블 → 엔드포인트 (역방향)

| 테이블 | 구분 | 필수 | 컬럼 | 쓰는 API | 읽는 API |
|---|---|---|---|---|---|
| `ai_mask` | AI | 필수 | 6 | 5.1, 7.6 | 4.14, 5.4, 5.8, 7.9 |
| `ai_result` | AI | 필수 | 15 | 5.1, 7.6 | 4.13, 5.2, 5.10, 6.2, 6.3, 11.1 |
| `lesion` | AI | 필수 | 13 | 5.1, 5.6, 5.7 | 5.3, 5.4, 5.9, 6.1, 7.1, 7.2, 7.3, 7.7, 7.8, 8.2 … |
| `lesion_descriptor` | AI | 필수 | 8 | 5.1, 5.6 | 5.4, 5.5 |
| `patient_account` | 계정 | 필수 | 8 | 2.9, 2.10, 2.11 | 14.1 |
| `audit_metric` | 공통 | 선택 | 7 | 13.4 | 13.3 |
| `staff` | 공통 | 필수 | 10 | 2.2, 2.8 | 2.3, 2.6, 2.7 |
| `discordance_flag` | 대조 | 필수 | 18 | 6.6, 7.8, 8.3, 8.4 | 3.5, 8.1, 8.2, 10.1, 10.3, 11.3, 11.5 |
| `report` | 리포트 | 필수 | 16 | 11.1, 11.5, 11.6 | 3.5, 10.3, 11.2, 11.4, 14.5, 14.6, 14.9 |
| `report_access_log` | 리포트 | 선택 | 8 | 11.2, 14.6 | 11.7 |
| `result_explanation` | 리포트 | 필수 | 9 | 11.4 | 11.3, 11.5 |
| `pathology_result` | 병리 | 필수 | 20 | 7.4, 7.6, 7.8 | 3.5, 7.5, 8.2, 10.3, 11.1, 11.3, 13.4 |
| `pathology_slide` | 병리 | 필수 | 5 | 7.5 | 7.6, 7.9 |
| `specimen` | 병리 | 필수 | 9 | 7.1, 7.3 | 3.5, 7.2, 7.3, 7.4, 7.8, 8.2 |
| `breast_density` | 영상 | 선택 | 6 | 4.13 | 6.4, 6.7 |
| `image_instance` | 영상 | 필수 | 7 | — | 4.7, 4.14, 5.1, 7.7 |
| `image_series` | 영상 | 필수 | 6 | 4.9 | 4.7, 4.10, 5.1 |
| `storage_object` | 영상 | 필수 | 9 | 4.12, 7.5, 11.4, 11.6, 12.1 | 4.11, 5.1, 5.8, 7.7 |
| `study` | 영상 | 필수 | 13 | 4.6, 4.8, 4.12 | 3.5, 4.7, 4.9, 4.13, 5.1, 5.7, 5.9, 6.1, 7.7, 13.4 |
| `reservation` | 예약 | 필수 | 9 | 3.6, 3.8, 3.9, 14.3, 14.4 | 3.7, 4.1, 14.2 |
| `chat_message` | 챗봇 | 선택 | 7 | 14.9 | — |
| `chat_session` | 챗봇 | 선택 | 6 | 14.8 | — |
| `pharmacy` | 처방 | 선택 | 10 | 12.3 | 12.3 |
| `prescription` | 처방 | 필수 | 9 | 12.1 | 12.2 |
| `prescription_item` | 처방 | 필수 | 11 | 12.1 | 12.2 |
| `prescription_pharmacy` | 처방 | 선택 | 6 | 12.4 | — |
| `followup_round` | 추적 | 선택 | 11 | 9.4, 9.5, 9.6 | 9.3, 9.7 |
| `followup_track` | 추적 | 필수 | 10 | 9.1, 9.7 | 3.5, 9.2, 9.3, 9.6, 13.4 |
| `notification` | 통보 | 선택 | 8 | 4.8, 7.8, 13.2 | 13.1, 14.7 |
| `assessment` | 판정 | 필수 | 19 | 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8 | 3.5, 5.2, 6.4, 6.7, 7.7, 7.8, 8.2, 9.1, 10.1, 10.3 … |
| `clinical_decision` | 판정 | 필수 | 10 | 8.4, 10.1 | 10.2 |
| `exam_order` | 환자 | 필수 | 11 | 4.1, 4.4, 4.8, 4.12, 9.6 | 3.3, 3.5, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8, 6.1, 6.7 … |
| `patient` | 환자 | 필수 | 8 | 3.1, 3.4 | 2.9, 3.2, 3.3, 3.6, 3.7, 3.10, 4.1, 4.12, 12.1, 14.1 |
| `questionnaire` | 환자 | 필수 | 12 | 3.10, 3.12 | 3.3, 3.11, 6.1, 6.7 |
---

## 5 · 설계 원칙 8개 — API 가 반드시 강제한다

없으면 이 프로젝트일 이유가 없어지는 항목. 애플리케이션이 실수해도 뚫리지 않도록
API 계층과 DB 제약 양쪽에서 막는다.

| # | 원칙 | 강제 지점 |
|---|---|---|
| 1 | 시스템은 판정하지 않는다 — 모든 AI 산출은 제안 · 후보 · 플래그 | 전 응답 필드명 (*_suggested, *_candidate) |
| 2 | 의사가 먼저, AI는 나중에 — 1차 판정 잠금 후에만 AI 결과 공개 | GET /ai-results/{id} 403 차단 · assessment.ai_revealed_at |
| 3 | 검체 바인딩 Hard Stop — 미바인딩 검체는 병리 접수 불가. 바인딩 주체 = 영상의학 · 유방외과 · 간호  [v3] | specimen.lesion_id NOT NULL · POST /specimens/{id}/accession 409 |
| 4 | exam_purpose 없으면 오더 생성 거부 | POST /exam-orders 422 |
| 5 | 등급 ≠ 조치 분리 — 시스템이 의료진 판단을 덮어쓰지 않음 | assessment.category 와 recommendation 별도 칸 |
| 6 | 자동 대조는 무인 트리거 — 병리 FINAL 상태 변화가 대조를 일으킨다 | 대조 실행 API 를 만들지 않는다 (SYS-4) |
| 7 | 리포트 열람 기본값 잠금 — 3조건 AND 로만 해제 | report.lock_status 기본 locked · POST /reports/{id}/unlock |
| 8 | 확신 없으면 기권 — 게이트 1건이라도 걸리면 기권  [v3] | abstained=true + abstain_signals (HTTP 200) |

## 6 · 에러 코드

| HTTP | code | 발생 조건 |
|---|---|---|
| 422 | `EXAM_PURPOSE_REQUIRED` | exam_purpose 없이 오더 생성 |
| 403 | `AI_LOCKED_BEFORE_FIRST_READ` | 1차 판정 잠금 전 AI 결과 조회 |
| 422 | `BIRADS3_NOT_ALLOWED_IN_SCREENING` | 선별 판독에서 범주 3 입력 |
| 422 | `BIRADS3_CONDITION_FAILED` | 범주 3 부여 조건 3개 미충족 |
| 422 | `BIRADS_SUBCATEGORY_NOT_FOR_MRI` | MRI 판정에 4a/4b/4c 입력 |
| 403 | `BINDING_ROLE_FORBIDDEN` | 영상의학 · 유방외과 · 간호 외 액터의 검체 바인딩  [v3] |
| 409 | `SPECIMEN_NOT_BOUND` | 미바인딩 검체의 병리 접수 |
| 403 | `DISPOSITION_ROLE_ONLY_SURGERY` | 유방외과 외의 불일치 해소 처분 |
| 403 | `UNLOCK_ROLE_ONLY_SURGERY` | 유방외과 외의 열람 잠금 해제 |
| 409 | `UNLOCK_CONDITION_NOT_MET` | 해제 3조건 AND 미충족 |
| 409 | `REPORT_LOCKED` | 잠금 상태 리포트 열람 시도 |
| 409 | `ASSESSMENT_FINALIZED` | FINAL 이후 직접 수정 시도 |
| 409 | `STUDY_REJECTED` | 반려된 검사에 판독 시도 |
| 400 | `VALIDATION_ERROR` | 필수 필드 누락 · 타입 불일치 |
| 401 | `UNAUTHENTICATED` | 토큰 없음 · 만료 |
| 403 | `ROLE_FORBIDDEN` | 역할 권한 밖 요청 |
| 404 | `NOT_FOUND` | 리소스 없음 |
| 429 | `RATE_LIMITED` | 추론 큐 과부하 |
| 500 | `INFERENCE_FAILED` | GPU 추론 서버 오류 |
| 401 | `TICKET_EXPIRED` | Go 전송 티켓 만료 (5분) |
| 403 | `TICKET_SCOPE_MISMATCH` | 티켓 범위 밖 리소스에 전송 시도 |
| 409 | `CHECKSUM_MISMATCH` | 업로드 바이트와 checksum_sha256 불일치 |
| 503 | `UPSTREAM_LLM_UNAVAILABLE` | Ollama · MedGemma 응답 불가 |
| 409 | `PYRAMID_NOT_READY` | 타일 피라미드 생성 전 뷰어 요청 |
| 404 | `TILE_OUT_OF_RANGE` | 존재하지 않는 줌 레벨 · 타일 좌표 |
## 7 · 상태 전이

| 리소스 | 상태 값 | 전이 조건 |
|---|---|---|
| `전이 조건` | exam_order | ordered → accepted → in_progress → completed / cancelled |
| `완료 시 study 생성 필수` | study.quality_status | accepted / rejected |
| `rejected → 재촬영 오더 자동 발행 + 간호 재호출 + 순서 재배치` | ai_result.run_status | queued → running → done / failed |
| `gate_flags 1건 이상 → abstained=true  [v3]` | assessment | first(잠금) → reveal-ai → final → finalized |
| `finalize 후 수정은 amend → superseded_by_id + 대조 재실행` | specimen | unbound → bound → accessioned |
| `unbound 상태로 접수하면 409` | pathology_result | draft → finalized |
| `finalized_at = SYS-4 무인 트리거` | discordance_flag | pass / sev1 · sev2 · review → closed |
| `검토 의견만으로는 종결되지 않고 처분으로만 종결` | followup_track | open → resolved / escalated / declined / overdue |
| `24개월 안정 → 범주 2 재판정 후 종결` | report.lock_status | locked → unlocked |
| `해제 3조건 AND` | reservation | reserved → change_requested / cancelled / done |

## 8 · 역할별 권한 매트릭스

C 생성 · R 조회 · U 수정 · D 삭제. **굵은 항목은 단독 권한** — 다른 역할에 주면
미처리 건이 어느 큐에도 남지 않는다.

| 원무 | 간호 | 영상의학 | 병리 | 유방외과 | 환자 | patient · reservation |
|---|---|---|---|---|---|---|
| CRUD | RU | R | R | R | 본인 CRU | questionnaire |
| R | CRU | R | R | R | — | exam_order |
| CRU | CR | CRU | R | CR | — | study · quality(반려) |
| — | R | CRU | R | R | — | ai_result · lesion |
| — | — | CR (1차 잠금 후) | CR (병리) | R | — | assessment · 영상 FINAL |
| R | R | CRU | R | R | — | specimen (바인딩) |
| — | C 단독 | R | R | R | — | pathology_result · FINAL |
| R | R | R | CRU | R | — | discordance 검토 의견 |
| — | — | CU (의견만) | R | R | — | discordance 해소 처분 |
| — | — | — | — | CU 단독 | — | followup_track · round |
| R | CRU | CRU | — | R | 본인 R | clinical_decision |
| R | R | R | R | CRU | — | report 열람 잠금 해제 |
| — | — | — | — | U 단독 | — | report 생성 · 발급 |
| C (발급) | R | CR | CR | CR | 본인 R | prescription |
| R | R | — | — | C | 본인 R | audit_metric |

## 9 · MVP 구현 우선순위

완성 기준 — **케이스 하나가 [0] 부터 병리 판정까지 끊기지 않고 흐르는가**.

| 등급 | 엔드포인트 |
|---|---|
| **필수** | 4.1 (exam_purpose 거부) · 6.1 · 6.2 · 6.5 (1차 잠금 → AI 공개 → FINAL) · 7.1 · 7.3 (Hard Stop) · 7.8 + SYS-4 · 8.4 (해소 처분) · 11.5 (잠금 해제) · 5.1~5.5 (기권 포함) · 9.x (24개월 종결) · 5.10 (레지스트리) · 7.9 · 4.14 + G-F8~G-F12 타일 피라미드 (없으면 판독·병리 화면 자체가 안 열린다) |
| **우선** | 4.8 (반려 · 재촬영) · 13.1~13.2 (SEV-1 Push) · G-N5 실시간 스트림 · 8.3 (검토 패널) · 4.12 (외부 결과지) · 9.5 (추적 콜) · 3.5 (통합 타임라인) · 13.3 (감사지표 6종) · G-F12 오버레이 타일 |
| **선택** | MRI 계열 전체 (소켓 3 — 데이터셋 미확보) · 12.x (처방 · 약국) · 14.8~14.9 (챗봇) · 11.6 (서류 발급) |
| **제외** | HL7 MWL · DICOM C-STORE 실연동 (4.5 는 필드로만) · 학습형 기권 (CoDoC) · 이중판독 워크플로 |

**절대 버리지 않는 것** — 스키마 잠금 5개 필드(`exam_purpose` · 판정 출처 · 추적 회차 ·
검체 종류 · 등급/조치 분리) · 범주 3 차단과 조건 검증 · 추적 종료 조건 · 1차 판정 잠금 ·
기권 인터페이스 · 검체 바인딩 Hard Stop · 자동 대조 무인 트리거 · 리포트 기본 잠금 ·
WSI 타일 피라미드 서빙.

**컷라인** — 일정이 밀리면 ① 소켓 4·5 성능 목표(「항상 기권」데모) ② 타일 피라미드 레벨 수
③ 대조 규칙 ③④ ④ 리포트 근거 좌표 링크 ⑤ 추적 알림 ⑥ Gail 계산 순으로 버린다.
