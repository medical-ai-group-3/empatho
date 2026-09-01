# DB 스키마 공백 3건 변경안 — G2 / G3 / G13 (병리 소켓)

작성 2026-09-01 · 정다희 · **변경안만. 실제 마이그레이션·ERD 반영은 아직 안 함.**
기준 문서: Google Drive `CDSS_DB_설계문서_v3.docx` (2026-08-19 팀 합의 반영본).

팀 공유용 짧은 요약은 `db_changes_pathology_G2_G3_G13_SUMMARY.md` 참고.

---

## 0. 배경 — v3 가 병리 소켓을 절반만 반영함

v3 개정에서 AI 테이블에 병리 **값**은 들어갔는데 **참조(FK)** 가 빠졌다:

| v3 에서 추가된 것 | v3 에서 빠진 것 |
|---|---|
| `ai_result.socket_name` 에 `pathology_tissue` / `pathology_cell` | `ai_result` 가 어느 **병리 슬라이드**를 분석했는지 가리킬 컬럼 → **G2** |
| `ai_mask.mask_type` 에 `tumor` / `stroma` / `immune` | 그 마스크가 어느 **병리 슬라이드**에 속하는지 가리킬 컬럼 (`image_instance_id` 만 있음) → **G3** |
| `pathology_slide` 에 스캔 배율·mpp (문서상 언급) | WSI 뷰어(확대 보기)가 쓸 **타일 피라미드** 테이블 자체 → **G13** |

즉 G2·G3 는 "v3 가 의도한 병리 통합의 완성", G13 은 신규 뷰어 기능.

### 0-1. 기준 문서에서 확인된 불일치 (최일운 확인 필요)

`CDSS_DB_설계문서_v3.docx` 자체에 아직 안 맞은 부분이 있음. 아래 변경안은 **`pathology_slide.pathology_slide_id` (PK)** 만 참조하므로 영향은 없지만, 베이스 스키마 확정 시 정리 필요:

1. `pathology_slide` 의 상위 FK — 개정 이력·요약표는 `specimen_id` 로 전환한다고 했는데, 상세표(§6-20)는 여전히 `pathology_result_id` 로 되어 있음.
2. `pathology_slide` 스캔 배율·`mpp` 컬럼 — 개정 이력엔 "추가"라고 썼지만 상세표 컬럼 목록엔 없음 (`stain_type` 설명에만 언급).
3. `pathology_result.tsr_percent` — "정의 확인 필요" 주석. → 아래 §4-4 참고 (별건 Q6 와 연결).

---

## 1. 현재 구조 (기준 문서 §6 발췌)

### 1-1. `ai_result` (AI · 필수 · §6-12)

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| ai_result_id | bigint | PK | |
| patient_id | bigint | FK | 조회용 |
| study_id | bigint | FK | **영상 검사 1건. 병리엔 대응물 없음 ← G2 원인** |
| socket_name | varchar | | mammo / ultrasound / mri / **pathology_tissue / pathology_cell** [v3] |
| model_name | varchar | | |
| model_version | varchar | | |
| lora_version | varchar | | 모달리티별 어댑터 |
| threshold_version | varchar | | thresholds.yaml 버전 |
| abstained | boolean | | 기권 여부 |
| abstain_signals | varchar | | path_disagree / ood [v3] |
| analyzed_at | timestamp | | |
| run_status | varchar | | queued / running / done / failed |
| requested_by_staff_id | bigint | FK | 분석 요청자 |

\+ 공통 감사 컬럼 4개(`created_by` `created_at` `updated_by` `updated_at`, §2 공통 규칙).
`study_id` 는 NOT NULL 표기 없음 (nullable 로 추정 — 최일운 확인).

### 1-2. `ai_mask` (AI · 필수 · §6-15)

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| ai_mask_id | bigint | PK | |
| ai_result_id | bigint | FK | 부모 AI 실행 |
| lesion_id | bigint | FK | 병변 마스크면 연결 (nullable) |
| image_instance_id | bigint | FK | **어느 DICOM 낱장인지. 병리 슬라이드엔 대응물 없음 ← G3 원인** |
| mask_type | varchar | | lesion / dense_tissue / breast_area / **tumor / stroma / immune** |
| storage_object_id | bigint | FK | 마스크 파일 |

\+ 공통 감사 컬럼 4개.
`image_instance_id` 의 NOT NULL 여부 = **최일운 확인 필요** (§3 영향분석의 CHECK 제약이 여기 의존).

### 1-3. `image_instance` (영상 · 필수 · §6-9) — 변경 없음, 참조용

| 컬럼 | 타입 | 키 |
|---|---|---|
| image_instance_id | bigint | PK |
| image_series_id | bigint | FK → image_series → study |
| instance_number | int | |
| storage_object_id | bigint | FK (원본) |
| thumbnail_object_id | bigint | FK (썸네일) |
| width_pixel | int | |
| height_pixel | int | |

DICOM 계층( study → image_series → image_instance )의 잎. **병리 슬라이드는 이 계층에 없음** — `specimen → pathology_result → pathology_slide` 라는 별도 계층.

### 1-4. `pathology_slide` (병리 · 필수 · §6-20)

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| pathology_slide_id | bigint | PK | **G2·G3·G13 이 참조할 대상** |
| pathology_result_id | bigint | FK | (개정 이력은 specimen_id 라고 함 — §0-1) |
| storage_object_id | bigint | FK | 원본 WSI 파일 주소 |
| thumbnail_object_id | bigint | FK | 썸네일 |
| stain_type | varchar | | he / ihc (+ 개정 이력상 스캔배율·mpp 예정) |

`patient_id` 없음 (다른 테이블 대부분 "조회용"으로 가지고 있는데 여기엔 없음), `study_id` 없음.

### 1-5. `study` (영상 · 필수 · §6-7) — 변경 없음, 참조용

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| study_id | bigint | PK | |
| patient_id | bigint | FK | 조회용·비정규화 |
| exam_order_id | bigint | FK | |
| modality | varchar | | **맘모 / 초음파 / MRI (병리 값 없음)** |
| study_uid | varchar | UK | DICOM Study UID (병리 WSI 엔 보통 없음) |
| laterality | varchar | | left / right / both |
| view_position | varchar | | 맘모 CC / MLO |
| mri_purpose | varchar | | problem_solving / staging |
| is_screen_capture | boolean | | |
| device_name | varchar | | |
| quality_status | varchar | | accepted / rejected |
| rejected_reason | varchar | | |
| performed_at | timestamp | | |

→ 병리를 `study` 로 우겨넣으면 `modality` enum·`study_uid` UK·`exam_order` 의존이 다 깨짐. 그래서 G2 는 새 컬럼이 맞다.

---

## 2. 변경안

### G2 — `ai_result.pathology_slide_id` 추가

- **컬럼**: `pathology_slide_id bigint NULL REFERENCES pathology_slide(pathology_slide_id)`
- **의미**: 병리 소켓(`pathology_tissue` / `pathology_cell`) 실행의 대상 슬라이드. 영상 소켓은 항상 NULL 이고 `study_id` 를 씀.
- **grain**: AI 실행 1건 = 슬라이드 1장. (조직분할·세포검출은 같은 슬라이드에 대해 `socket_name` 만 다른 별도 `ai_result` 행.) 검체(`specimen`)가 아니라 슬라이드 grain 이 맞다 — sTIL·TSR 은 슬라이드 이미지 위에서 계산되고, 한 검체가 여러 슬라이드(H&E + IHC)를 낼 수 있음.
- **인덱스**: `ix_ai_result_pathology_slide_id`
- **(2단계, 선택) 무결성 CHECK**: 소켓별로 `study_id` xor `pathology_slide_id`. 아래 §3 참고 — **1차 마이그레이션엔 넣지 않음.**

### G3 — `ai_mask.pathology_slide_id` 추가

- **컬럼**: `pathology_slide_id bigint NULL REFERENCES pathology_slide(pathology_slide_id)`
- **의미**: `mask_type ∈ {tumor, stroma, immune, ...}` 인 병리 마스크가 속한 슬라이드. 영상 마스크는 NULL, `image_instance_id` 를 씀.
- **인덱스**: `ix_ai_mask_pathology_slide_id`
- **(2단계, 선택) CHECK**: `num_nonnulls(image_instance_id, pathology_slide_id) >= 1` (최소 한쪽). 엄격히 `= 1` 로 갈지는 `breast_area` 마스크가 낱장에 안 묶이는 경우가 있는지 확인 후 결정.
- 마스크 픽셀 좌표계는 **해당 슬라이드 피라미드의 level-0 기준** 으로 통일 (G13 과 맞물림). 저장 포맷(PNG/전용)은 이 변경 범위 밖.

### G13 — `image_pyramid` 신규 테이블

WSI 뷰어(OpenSeadragon 등)의 확대·이동을 위해 다해상도 타일 피라미드 메타데이터를 보관. **DZI(Deep Zoom Image) 디스크립터 + OpenSlide 레벨 모델**을 참고.

서빙 방식 3가지를 한 테이블로 지원:

| serving_mode | 설명 | 프로토타입 적합도 |
|---|---|---|
| `openslide_dynamic` | 원본 피라미드 TIFF/SVS 를 그대로 두고, 타일 서버(openslide-python + deepzoom 엔드포인트)가 요청 시 잘라 줌 | **★ MVP 권장** — 추가 스토리지 0, TIGER WSI 가 이미 피라미드 tif |
| `dzi_static` | 인제스트 시 `vips dzsave` 로 전체 타일을 미리 생성해 오브젝트 스토리지에 적재, 정적 서빙/CDN | 스토리지 큼(원본의 30~100%), 서빙은 단순 |
| `iiif` | IIIF Image API 서버 경유 | 표준이지만 별도 서버 필요 |

**테이블 정의**

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| image_pyramid_id | bigint | PK | |
| pathology_slide_id | bigint | NN FK **UNIQUE** | 슬라이드 1장 : 피라미드 1개 (MVP) |
| source_object_id | bigint | FK → storage_object | 원본 WSI (조회 편의상 복제 — `pathology_slide.storage_object_id` 와 동일) |
| serving_mode | varchar(20) | NN | `openslide_dynamic` / `dzi_static` / `iiif` · 기본 `openslide_dynamic` |
| tile_format | varchar(10) | | `jpeg` / `png` / `webp` (dynamic 이면 서버 설정, 참고값) |
| tile_size | int | NN | DZI TileSize. 기본 256 (OpenSeadragon 관례), 512 도 가능 |
| tile_overlap | int | NN | DZI Overlap. 기본 0 (1 이면 경계 이음매 감소) |
| level_count | int | NN | OpenSlide `level_count` — 피라미드 층 수 (보통 8~12) |
| level0_width | bigint | NN | 최대 해상도 가로 px (`level_dimensions[0]`) |
| level0_height | bigint | NN | 최대 해상도 세로 px |
| mpp_x | decimal(8,4) | | µm/px (OpenSlide `openslide.mpp-x`). **뷰어 스케일바용.** 임상값은 `pathology_slide` 가 주인(§0-1) — 여기 값은 "파일에서 읽은 값" |
| mpp_y | decimal(8,4) | | |
| objective_power | decimal(5,1) | | 스캔 대물배율 20 / 40 (`openslide.objective-power`) |
| background_color | varchar(7) | | 여백 색 hex (`openslide.background-color`, 없으면 `#FFFFFF`) |
| levels | jsonb | NN | 층별 메타 배열: `[{ "level":0, "width":98304, "height":75776, "downsample":1.0 }, ...]`. 타일 격자(col/row 수)는 `ceil(width/tile_size)` 로 유도 |
| tile_root_key | varchar(255) | | `serving_mode=dzi_static` 일 때 타일 프리픽스. 실제 타일 = `{tile_root_key}/{level}/{col}_{row}.{tile_format}` |
| dzi_descriptor_object_id | bigint | FK → storage_object | `.dzi` XML 파일 (선택, static 서빙 시) |
| generator | varchar(50) | | `openslide+deepzoom` / `libvips dzsave` 등 — 재생성 추적 |
| status | varchar(10) | NN | `pending` / `ready` / `failed` · 기본 `pending` |
| built_at | timestamp | | 피라미드 준비 완료 시각 |
| created_by / created_at / updated_by / updated_at | | | 공통 감사 4 |

**설계 판단**

- **1:1** (`pathology_slide_id` UNIQUE). 슬라이드당 뷰어용 피라미드는 하나면 충분. 나중에 라벨/매크로 이미지까지 피라미드로 넣게 되면 UNIQUE 를 풀고 `pyramid_role` 컬럼 추가.
- **`levels` 는 jsonb** — 층 수가 8~12 로 적고, 뷰어가 부트스트랩 시 한 번에 읽음. 정규화(`image_pyramid_level` 자식 테이블)도 가능하나 조인 이득이 없음. 기준 문서도 뷰어 표시용 반구조 데이터는 text/json 을 씀(`report.content_json`, `report.evidence_links`).
- **영상(맘모/초음파/MRI)은 대상 아님** — 맘모는 ~5k×4k 라 뷰어가 DZI 없이 처리, MRI 는 3D 슬라이스. 나중에 필요하면 `image_instance_id bigint NULL` 을 추가하고 `CHECK (num_nonnulls(pathology_slide_id, image_instance_id) = 1)` 로 확장.
- **`ai_result` 와 무관** — 피라미드는 사람이 보는 뷰어용, 슬라이드 인제스트 시점에 생성. AI 실행과 생명주기가 다름.

---

## 3. 다른 소켓(맘모 / 초음파 / MRI)에 대한 영향

### 3-1. 결론: 1차 마이그레이션은 완전 additive — 기존 데이터·쿼리 영향 없음

- G2·G3 = **nullable 컬럼 추가**. 기본값 불필요, 기존 행은 NULL 로 채워짐. 기존 행 UPDATE 없음.
- G13 = **신규 테이블**. 영상 소켓은 이 테이블을 건드리지 않음.
- 데이터 마이그레이션(백필) 없음.

### 3-2. 그래도 확인할 것

| # | 항목 | 위험 | 확인 담당 |
|---|---|---|---|
| 1 | **컬럼 미지정 INSERT** — `INSERT INTO ai_result VALUES (...)` (컬럼 목록 없이) | 있으면 컬럼 수 안 맞아 깨짐. 컬럼 목록 명시 INSERT 는 무관 | 윤수용 / 박검모 (백엔드·맘모) |
| 2 | **`SELECT *` → 위치 기반 매핑** | 결과에 컬럼 1개 추가. ORM(Django) 은 무관, raw 커서 인덱스 접근·DTO strict 검증은 영향 | 윤수용 |
| 3 | **`ai_result` / `ai_mask` 위에 만든 VIEW** | `SELECT *` 뷰면 새 컬럼 자동 미포함(동작엔 무관). 명시적 뷰면 무관 | 최일운 |
| 4 | **`ai_result.study_id` NOT NULL 가정 코드** | G2 후 병리 행은 `study_id` NULL 가능. 영상 행은 여전히 채워야 함. 영상 AI 코드가 항상 `study_id` 를 넣는지 확인(넣어야 정상) | 박검모(맘모) / 서정은(MRI) |
| 5 | **`ai_mask.image_instance_id` 현재 NOT NULL 인가** | §2 의 선택 CHECK `num_nonnulls(...) >= 1` 설계가 여기 의존. 기존 마스크 중 `image_instance_id` NULL 인 행(예: breast_area)이 있으면 엄격 CHECK 불가 | 최일운 |
| 6 | **FK ON DELETE 정책** | `pathology_slide` 삭제가 `ai_result`/`ai_mask`/`image_pyramid` 참조로 차단됨. `RESTRICT`(권장) vs `SET NULL` vs `CASCADE` 결정 | 최일운 |
| 7 | **AI 응답 스키마(Pydantic/DTO)** | 병리 결과가 API 로 흐르면 `pathology_slide_id` optional 필드 추가 필요. 영상 페이로드는 optional 이라 무영향 | 윤수용 |
| 8 | **PK 생성 방식** | `image_pyramid` PK 를 베이스 스키마 관례(`bigserial` / `GENERATED ... IDENTITY` / 앱생성)에 맞출 것. 아래 SQL 은 `GENERATED ALWAYS AS IDENTITY` 로 작성 | 최일운 |
| 9 | **ERD** (`cdss_erd.excalidraw`) | 테이블 1개 + 엣지 3개(`image_pyramid→pathology_slide`, `ai_result→pathology_slide`, `ai_mask→pathology_slide`) 추가 | ERD 담당 |
| 10 | **Django 마이그레이션 순서** | `pathology_slide`·`storage_object` 가 먼저 존재해야 함(이미 존재). 마이그레이션은 해당 app 에 추가 | 최일운 |

### 3-3. 선택 CHECK 제약은 2차 마이그레이션으로

`ck_ai_result_target`, `ck_ai_mask_target` 은 **1차(컬럼 추가)와 분리**해서, 병리 소켓 코드가 새 컬럼을 실제로 채우기 시작한 뒤에 `NOT VALID` 로 추가하고 데이터 정리 후 `VALIDATE CONSTRAINT`. 1차에 넣으면 신규 영상 INSERT 가 즉시 제약을 받아 회귀 위험.

---

## 4. 마이그레이션 SQL 초안

> PostgreSQL 17. **아직 적용하지 말 것.** 최일운의 베이스 스키마와 PK 생성 방식·FK ON DELETE·`ai_mask.image_instance_id` NN 여부 확정 후 조정.

### 4-1. 1차 — 컬럼·테이블 추가 (완전 additive)

```sql
BEGIN;

-- ── G2: ai_result → 병리 슬라이드 참조 ──────────────────────────────
ALTER TABLE ai_result
    ADD COLUMN pathology_slide_id bigint NULL
        REFERENCES pathology_slide (pathology_slide_id) ON DELETE RESTRICT;

CREATE INDEX ix_ai_result_pathology_slide_id
    ON ai_result (pathology_slide_id);

COMMENT ON COLUMN ai_result.pathology_slide_id IS
    '병리 소켓(pathology_tissue/pathology_cell) 분석 대상 슬라이드. '
    '영상 소켓은 NULL 이고 study_id 사용.';

-- ── G3: ai_mask → 병리 슬라이드 참조 ───────────────────────────────
ALTER TABLE ai_mask
    ADD COLUMN pathology_slide_id bigint NULL
        REFERENCES pathology_slide (pathology_slide_id) ON DELETE RESTRICT;

CREATE INDEX ix_ai_mask_pathology_slide_id
    ON ai_mask (pathology_slide_id);

COMMENT ON COLUMN ai_mask.pathology_slide_id IS
    '병리 마스크(tumor/stroma/immune 등)가 속한 슬라이드. '
    '영상 마스크는 NULL 이고 image_instance_id 사용. '
    '마스크 픽셀 좌표계는 해당 슬라이드 피라미드 level-0 기준.';

-- ── G13: image_pyramid 신규 ───────────────────────────────────────
CREATE TABLE image_pyramid (
    image_pyramid_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    pathology_slide_id       bigint NOT NULL UNIQUE
                             REFERENCES pathology_slide (pathology_slide_id) ON DELETE CASCADE,
    source_object_id         bigint
                             REFERENCES storage_object (storage_object_id) ON DELETE RESTRICT,

    serving_mode             varchar(20)  NOT NULL DEFAULT 'openslide_dynamic',
    tile_format              varchar(10),
    tile_size                int          NOT NULL DEFAULT 256,
    tile_overlap             int          NOT NULL DEFAULT 0,

    level_count              int          NOT NULL,
    level0_width             bigint       NOT NULL,
    level0_height            bigint       NOT NULL,
    mpp_x                    decimal(8,4),
    mpp_y                    decimal(8,4),
    objective_power          decimal(5,1),
    background_color         varchar(7),
    levels                   jsonb        NOT NULL,

    tile_root_key            varchar(255),
    dzi_descriptor_object_id bigint
                             REFERENCES storage_object (storage_object_id) ON DELETE SET NULL,
    generator                varchar(50),
    status                   varchar(10)  NOT NULL DEFAULT 'pending',
    built_at                 timestamp,

    created_by               bigint,
    created_at               timestamp    NOT NULL DEFAULT now(),
    updated_by               bigint,
    updated_at               timestamp    NOT NULL DEFAULT now(),

    CONSTRAINT ck_image_pyramid_serving_mode
        CHECK (serving_mode IN ('openslide_dynamic', 'dzi_static', 'iiif')),
    CONSTRAINT ck_image_pyramid_status
        CHECK (status IN ('pending', 'ready', 'failed')),
    CONSTRAINT ck_image_pyramid_positive_dims
        CHECK (level_count > 0 AND level0_width > 0 AND level0_height > 0
               AND tile_size > 0 AND tile_overlap >= 0)
);

COMMENT ON TABLE image_pyramid IS
    'WSI 뷰어(OpenSeadragon 등) 확대 보기용 다해상도 타일 피라미드 메타데이터. '
    'DZI 디스크립터 + OpenSlide 레벨 모델. 슬라이드 인제스트 시 생성.';
COMMENT ON COLUMN image_pyramid.levels IS
    '층별 메타 배열 [{level,width,height,downsample}, ...]. level 0 = 최대 해상도.';
COMMENT ON COLUMN image_pyramid.mpp_x IS
    '파일에서 읽은 µm/px (뷰어 스케일바용). 임상 기준값의 주인은 pathology_slide.';

COMMIT;
```

### 4-2. 2차 — 무결성 CHECK (병리 소켓 코드 반영 + 데이터 정리 후)

```sql
BEGIN;

-- ai_result: 소켓 종류에 맞는 대상만 참조
ALTER TABLE ai_result
    ADD CONSTRAINT ck_ai_result_target CHECK (
        (socket_name IN ('pathology_tissue', 'pathology_cell')
            AND pathology_slide_id IS NOT NULL AND study_id IS NULL)
        OR
        (socket_name IN ('mammo', 'ultrasound', 'mri')
            AND study_id IS NOT NULL AND pathology_slide_id IS NULL)
    ) NOT VALID;

-- ai_mask: 최소 한쪽 대상 지정 (엄격히 = 1 로 갈지는 최일운·정다희 협의)
ALTER TABLE ai_mask
    ADD CONSTRAINT ck_ai_mask_target CHECK (
        num_nonnulls(image_instance_id, pathology_slide_id) >= 1
    ) NOT VALID;

COMMIT;

-- 기존 데이터 확인·정리 후:
-- ALTER TABLE ai_result VALIDATE CONSTRAINT ck_ai_result_target;
-- ALTER TABLE ai_mask   VALIDATE CONSTRAINT ck_ai_mask_target;
```

### 4-3. 롤백

```sql
-- 1차 롤백
BEGIN;
DROP TABLE IF EXISTS image_pyramid;
DROP INDEX IF EXISTS ix_ai_mask_pathology_slide_id;
ALTER TABLE ai_mask   DROP COLUMN IF EXISTS pathology_slide_id;
DROP INDEX IF EXISTS ix_ai_result_pathology_slide_id;
ALTER TABLE ai_result DROP COLUMN IF EXISTS pathology_slide_id;
COMMIT;
```

### 4-4. (별건) `pathology_result.tsr_percent` — Q6 미확정과 연결

이번 3건 범위는 아니지만 병리 서빙 연결 시 부딪힘. 서빙 파이프라인(`code/serving/`)의 `predict()` 는 `tsr_tumor_percent` 와 `tsr_stroma_percent` **둘 다** 반환하는데 DB 컬럼은 `tsr_percent` 하나(“정의 확인 필요” 주석). 선택지:

```sql
-- 안 A: 관점을 컬럼명에 고정 (권장 — 문서 §4-4 근거)
ALTER TABLE pathology_result RENAME COLUMN tsr_percent TO tsr_stroma_percent;
ALTER TABLE pathology_result ADD COLUMN tsr_tumor_percent decimal;
-- 안 B: 하나만 저장 + 어느 관점인지 별도 컬럼
ALTER TABLE pathology_result ADD COLUMN tsr_basis varchar;  -- 'tumor' | 'stroma'
```

팀 Q6 결정 나면 별도 변경안으로. (`stil_percent` / `stil_interval_low` / `stil_interval_high` / `stil_source` 는 이미 `pathology_result` 에 존재 → 서빙 출력 그대로 매핑 가능.)

---

## 5. 적용 순서 (실제 마이그레이션 시)

1. 최일운: §0-1 불일치 정리 + §3-2 확인 항목 회신
2. 1차 마이그레이션(§4-1) — 완전 additive, 아무 때나
3. 정다희: 병리 소켓이 `ai_result.pathology_slide_id` / `ai_mask.pathology_slide_id` 채우도록 수정, 인제스트가 `image_pyramid` 생성
4. 윤수용: WSI 타일 엔드포인트(`openslide_dynamic`) + AI 응답 스키마 optional 필드
5. 2차 마이그레이션(§4-2) — CHECK, 데이터 정리 후 `VALIDATE`
6. ERD 갱신
