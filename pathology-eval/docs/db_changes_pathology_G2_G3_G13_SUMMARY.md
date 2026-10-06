# [공유] DB 스키마 공백 3건 변경안 — 병리 소켓 (G2 / G3 / G13)

정다희 · 2026-09-01 · **변경안만. 마이그레이션·ERD 반영 안 함.** 상세: `docs/db_changes_pathology_G2_G3_G13.md`

## 왜 필요한가

`CDSS_DB_설계문서_v3` 가 병리 소켓을 **절반만** 반영함 — AI 테이블에 병리 *값*(`socket_name` 에 `pathology_tissue/cell`, `mask_type` 에 `tumor/stroma/immune`)은 들어갔는데, 그 결과가 **어느 병리 슬라이드에 대한 것인지 가리킬 컬럼**이 없음. 그리고 WSI 확대 뷰어가 쓸 타일 피라미드 테이블이 아예 없음.

| 공백 | 지금 | 문제 |
|---|---|---|
| **G2** | `ai_result` 에 `study_id`(영상 검사)만 | 병리 분석은 슬라이드 단위인데 가리킬 방법이 없음 → 병리 `ai_result` 행의 대상이 붕 뜸 |
| **G3** | `ai_mask` 에 `image_instance_id`(DICOM 낱장)만 | tumor/stroma/immune 마스크가 어느 슬라이드 건지 못 적음 → 병리 마스크 저장 불가 |
| **G13** | `image_pyramid` 테이블 없음 | WSI(수만×수만 px)를 확대·이동하며 볼 수 없음 |

## 무엇이 바뀌나

1. **G2** — `ai_result.pathology_slide_id` 컬럼 추가 (nullable, FK → `pathology_slide`)
2. **G3** — `ai_mask.pathology_slide_id` 컬럼 추가 (nullable, FK → `pathology_slide`)
3. **G13** — `image_pyramid` 신규 테이블 (슬라이드 1:1). DZI/OpenSlide 표준 기반 — 타일 크기·레벨 수·level-0 크기·mpp·대물배율 + 층별 메타(jsonb). 서빙은 **원본 피라미드 TIFF 를 타일 서버가 잘라 주는 방식(`openslide_dynamic`)** 권장 → 추가 스토리지 0.

**1차 마이그레이션은 100% additive** — nullable 컬럼 2개 + 새 테이블 1개. 기존 데이터 변경 없음, 백필 없음, 영상 소켓(맘모/초음파/MRI) 코드·쿼리 영향 없음.
무결성 CHECK 제약(소켓별 대상 강제)은 병리 코드가 새 컬럼을 채우기 시작한 뒤 **2차**로 분리.

## 담당자별 확인 사항

| 담당 | 확인할 것 |
|---|---|
| **최일운** (DB/Django) | ① 문서 불일치 정리: `pathology_slide` 상위 FK 가 `specimen_id`냐 `pathology_result_id`냐 (개정이력 vs 상세표 불일치), 스캔배율·mpp 컬럼 실제 추가 여부 ② `ai_mask.image_instance_id` 가 현재 NOT NULL 인지 (2차 CHECK 설계가 의존) ③ FK `ON DELETE` 정책 (RESTRICT 권장) ④ `image_pyramid` PK 생성 방식을 베이스 스키마 관례에 맞추기 ⑤ 마이그레이션 실행 |
| **윤수용** (FastAPI/백엔드) | ① 컬럼 미지정 `INSERT INTO ai_result/ai_mask` 있는지 (있으면 깨짐) ② `SELECT *` 위치기반 매핑·DTO strict 검증 ③ AI 응답 스키마에 `pathology_slide_id` optional 필드 ④ WSI 타일 엔드포인트 신규 구현(`openslide_dynamic`) |
| **박검모** (맘모) | 맘모 AI 가 `ai_result` INSERT 시 항상 `study_id` 를 채우는지 (2차 CHECK 대비). 맘모 뷰어는 `image_pyramid` 무관 |
| **서정은** (MRI) | MRI AI 도 동일 — `study_id` 항상 채우는지. MRI 3D 뷰어 무관 |
| **정다희** (병리) | 병리 소켓이 새 두 컬럼을 채우도록 수정, 인제스트가 `image_pyramid` 생성. `pathology_result.stil_*` 는 이미 존재 → 서빙 출력 매핑. `tsr_percent`(단수, "정의 확인 필요")는 Q6 결정 후 별도 변경안 |
| **ERD 담당** | `cdss_erd.excalidraw` 에 테이블 1 + 엣지 3 추가 |

## 다음 단계

최일운 확인 회신 → 1차 마이그레이션(아무 때나) → 병리 코드 반영 → 2차 CHECK → ERD 갱신.
마이그레이션 SQL 초안은 상세 문서 §4 에 있음 (1차 additive / 2차 CHECK / 롤백).
