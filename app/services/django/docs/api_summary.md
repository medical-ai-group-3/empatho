# CDSS API 요약

사양서 3종(API 명세서 v3 · API-테이블 매핑표 v3 · DB 설계문서 v3)에서
개발에 필요한 것만 뽑아 합쳤다. **원본 docx 는 저장소에 두지 않는다.**

- 공개 API **100개** (2~14장) · Django + DRF 가 단독으로 DB 를 쓴다
- 테이블 **34개** (필수 25 · 선택 9) · 컬럼 345개

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
