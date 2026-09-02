-- 2026-09-02 · G1 · G4 상태 컬럼 + department 허용값
--
--   1. G1  exam_order.order_status       (매핑표 6장, 높음)
--   2. G4  specimen.accession_status · accessioned_at   (매핑표 6장, 높음)
--   3. staff.department 허용값 CHECK
--
-- 원본 16장 상태 전이가 두 리소스의 상태를 정의하는데 담을 컬럼이 없었다.
-- 매핑표가 "W0 스키마 잠금 전에 결정해야 하며, 잠긴 뒤에는 과거 레코드를
-- 복원할 수 없다" 고 경고한 항목이다. 지금 두 테이블 모두 0행이다.
--
-- 상태값은 오타 하나로 전이가 깨지므로 CHECK 으로 막는다. NOT NULL DEFAULT
-- 로 두어 "상태 없는 오더" 가 생기지 않게 한다 — NULL 을 허용하면 전이 로직이
-- 매번 NULL 을 검사해야 한다.
--
-- department 는 v3 개정이력이 reception 을 admin 에서 분리하기로 했으나
-- 상세표 6-34 와 API 명세 staff 필드표 양쪽 모두 반영되지 않았다. 여기서는
-- 개정이력 결정을 따른다.
--
-- 근거는 docs/api_summary.md §0-2 갭 목록 · §7 상태 전이 참조.

BEGIN;


-- ── 1. G1 — exam_order.order_status ───────────────────────────────────
-- ordered → accepted → in_progress → completed / cancelled

ALTER TABLE public.exam_order
    ADD COLUMN order_status character varying(20) NOT NULL DEFAULT 'ordered';

ALTER TABLE ONLY public.exam_order
    ADD CONSTRAINT exam_order_order_status_ck
    CHECK (order_status IN ('ordered', 'accepted', 'in_progress', 'completed', 'cancelled'));


-- ── 2. G4 — specimen.accession_status · accessioned_at ────────────────
-- unbound → bound → accessioned · unbound 상태로 접수하면 409

ALTER TABLE public.specimen
    ADD COLUMN accession_status character varying(20) NOT NULL DEFAULT 'unbound';

ALTER TABLE public.specimen
    ADD COLUMN accessioned_at timestamp without time zone;

ALTER TABLE ONLY public.specimen
    ADD CONSTRAINT specimen_accession_status_ck
    CHECK (accession_status IN ('unbound', 'bound', 'accessioned'));


-- ── 3. staff.department 허용값 ────────────────────────────────────────
-- admin / reception / nursing / radiology / surgery / pathology
-- 컬럼이 nullable 이라 NULL 은 통과한다 (IN 은 NULL 에 UNKNOWN 을 낸다).
-- department 가 비면 권한 판정이 불가능하므로 NOT NULL 여부는 별도 결정.

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_department_ck
    CHECK (department IN ('admin', 'reception', 'nursing', 'radiology', 'surgery', 'pathology'));


COMMIT;