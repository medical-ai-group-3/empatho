-- 2026-09-02 · 사양서 v3 결정 4건 반영
--
-- core 모델은 전부 managed = False 다. Django 마이그레이션은 DDL 을 내지
-- 않으므로 스키마를 실제로 바꾼 것은 이 파일이다.
--
--   1. pathology_slide 의 상위를 pathology_result → specimen 으로
--      v3 개정이력의 결정인데 상세표 컬럼 행이 v2 그대로라 반영이 안 됐었다
--   2. G2  ai_result.pathology_slide_id   (study 와 배타)
--   3. G3  ai_mask.pathology_slide_id
--   4. G13 image_pyramid 신설            (배타 FK 2개 — 원문의 다형 참조 대신)
--
-- 근거와 배경은 docs/api_summary.md §0-1 개정이력 · §0-2 갭 목록에 있다.
-- 실행 시점에 관련 테이블 전부 0행이었다.

BEGIN;


-- ── 1. pathology_slide 의 상위를 specimen 으로 ─────────────────────────

ALTER TABLE public.pathology_slide ADD COLUMN specimen_id bigint;

UPDATE public.pathology_slide s
   SET specimen_id = r.specimen_id
  FROM public.pathology_result r
 WHERE s.pathology_result_id = r.pathology_result_id;

ALTER TABLE ONLY public.pathology_slide
    ADD CONSTRAINT pathology_slide_specimen_id_fkey
    FOREIGN KEY (specimen_id) REFERENCES public.specimen(specimen_id);

ALTER TABLE ONLY public.pathology_slide
    DROP CONSTRAINT pathology_slide_pathology_result_id_fkey;

ALTER TABLE public.pathology_slide DROP COLUMN pathology_result_id;

CREATE INDEX pathology_slide_specimen_id_idx
    ON public.pathology_slide USING btree (specimen_id);


-- ── 2. G2 — ai_result ─────────────────────────────────────────────────

ALTER TABLE public.ai_result ADD COLUMN pathology_slide_id bigint;

ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_pathology_slide_id_fkey
    FOREIGN KEY (pathology_slide_id) REFERENCES public.pathology_slide(pathology_slide_id);

CREATE INDEX ai_result_pathology_slide_id_idx
    ON public.ai_result USING btree (pathology_slide_id);

-- 둘 다 비는 것은 허용한다 — study_id 가 원래 nullable 이다.
ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_target_ck
    CHECK (num_nonnulls(study_id, pathology_slide_id) <= 1);


-- ── 3. G3 — ai_mask ───────────────────────────────────────────────────

ALTER TABLE public.ai_mask ADD COLUMN pathology_slide_id bigint;

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_pathology_slide_id_fkey
    FOREIGN KEY (pathology_slide_id) REFERENCES public.pathology_slide(pathology_slide_id);

CREATE INDEX ai_mask_pathology_slide_id_idx
    ON public.ai_mask USING btree (pathology_slide_id);


-- ── 4. G13 — image_pyramid ────────────────────────────────────────────

CREATE TABLE public.image_pyramid (
    image_pyramid_id bigint NOT NULL,
    pathology_slide_id bigint,
    image_instance_id bigint,
    tile_size integer,
    tile_format character varying(10),
    level_count integer,
    max_width integer,
    max_height integer,
    mpp_x numeric(6,4),
    mpp_y numeric(6,4),
    object_key_prefix character varying(255),
    build_status character varying(20),
    built_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp without time zone DEFAULT now(),
    updated_by bigint
);

CREATE SEQUENCE public.image_pyramid_image_pyramid_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.image_pyramid_image_pyramid_id_seq
    OWNED BY public.image_pyramid.image_pyramid_id;

ALTER TABLE ONLY public.image_pyramid
    ALTER COLUMN image_pyramid_id
    SET DEFAULT nextval('public.image_pyramid_image_pyramid_id_seq'::regclass);

ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_pkey PRIMARY KEY (image_pyramid_id);

ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_pathology_slide_id_fkey
    FOREIGN KEY (pathology_slide_id) REFERENCES public.pathology_slide(pathology_slide_id);

ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_image_instance_id_fkey
    FOREIGN KEY (image_instance_id) REFERENCES public.image_instance(image_instance_id);

-- 소스는 병리 WSI 아니면 영상 인스턴스, 정확히 하나다.
ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_source_ck
    CHECK (num_nonnulls(pathology_slide_id, image_instance_id) = 1);

-- 소스 1개당 피라미드 1개. 부분 유니크라 null 은 서로 충돌하지 않는다.
CREATE UNIQUE INDEX image_pyramid_slide_idx
    ON public.image_pyramid USING btree (pathology_slide_id)
    WHERE (pathology_slide_id IS NOT NULL);

CREATE UNIQUE INDEX image_pyramid_instance_idx
    ON public.image_pyramid USING btree (image_instance_id)
    WHERE (image_instance_id IS NOT NULL);


COMMIT;
