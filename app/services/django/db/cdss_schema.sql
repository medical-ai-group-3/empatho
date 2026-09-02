--
-- PostgreSQL database dump
--


-- Dumped from database version 17.11 (Debian 17.11-0+deb13u1)
-- Dumped by pg_dump version 17.11 (Debian 17.11-0+deb13u1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_mask; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_mask (
    ai_mask_id bigint NOT NULL,
    ai_result_id bigint,
    lesion_id bigint,
    image_instance_id bigint,
    mask_type character varying(30),
    storage_object_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    pathology_slide_id bigint
);


--
-- Name: ai_mask_ai_mask_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_mask_ai_mask_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_mask_ai_mask_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_mask_ai_mask_id_seq OWNED BY public.ai_mask.ai_mask_id;


--
-- Name: ai_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_result (
    ai_result_id bigint NOT NULL,
    patient_id bigint,
    study_id bigint,
    socket_name character varying(30),
    model_name character varying(50),
    model_version character varying(50),
    lora_version character varying(50),
    threshold_version character varying(50),
    abstained boolean,
    abstain_signals character varying(100),
    analyzed_at timestamp with time zone,
    run_status character varying(20),
    requested_by_staff_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    pathology_slide_id bigint,
    CONSTRAINT ai_result_target_ck CHECK ((num_nonnulls(study_id, pathology_slide_id) <= 1))
);


--
-- Name: ai_result_ai_result_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_result_ai_result_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_result_ai_result_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_result_ai_result_id_seq OWNED BY public.ai_result.ai_result_id;


--
-- Name: assessment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assessment (
    assessment_id bigint NOT NULL,
    patient_id bigint,
    study_id bigint,
    lesion_id bigint,
    assessment_scope character varying(20),
    read_stage character varying(20),
    category character varying(10),
    category_rule character varying(10),
    category_model character varying(10),
    path_agreement character varying(20),
    suspicion_total_score integer,
    recommendation character varying(100),
    recommendation_reason character varying(250),
    rule_table_version character varying(30),
    assessed_by_staff_id bigint,
    finalized_at timestamp with time zone,
    superseded_by_id bigint,
    finding_note text,
    ai_revealed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: assessment_assessment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.assessment_assessment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: assessment_assessment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.assessment_assessment_id_seq OWNED BY public.assessment.assessment_id;


--
-- Name: audit_metric; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_metric (
    audit_metric_id bigint NOT NULL,
    metric_name character varying(50),
    exam_purpose character varying(20),
    period_start date,
    period_end date,
    metric_value numeric(10,4),
    computed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: audit_metric_audit_metric_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_metric_audit_metric_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_metric_audit_metric_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_metric_audit_metric_id_seq OWNED BY public.audit_metric.audit_metric_id;


--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user (
    id integer NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL
);


--
-- Name: auth_user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_groups (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: auth_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_user_permissions (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: breast_density; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.breast_density (
    breast_density_id bigint NOT NULL,
    study_id bigint,
    density_percent numeric(5,2),
    density_category character varying(10),
    is_near_boundary boolean,
    measured_by character varying(20),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: breast_density_breast_density_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.breast_density_breast_density_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: breast_density_breast_density_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.breast_density_breast_density_id_seq OWNED BY public.breast_density.breast_density_id;


--
-- Name: chat_message; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_message (
    chat_message_id bigint NOT NULL,
    chat_session_id bigint,
    sender_type character varying(20),
    content text,
    cited_report_id bigint,
    needs_human boolean,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: chat_message_chat_message_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.chat_message_chat_message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chat_message_chat_message_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.chat_message_chat_message_id_seq OWNED BY public.chat_message.chat_message_id;


--
-- Name: chat_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_session (
    chat_session_id bigint NOT NULL,
    patient_id bigint,
    channel character varying(20),
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    escalated_to_staff_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: chat_session_chat_session_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.chat_session_chat_session_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chat_session_chat_session_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.chat_session_chat_session_id_seq OWNED BY public.chat_session.chat_session_id;


--
-- Name: clinical_decision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.clinical_decision (
    clinical_decision_id bigint NOT NULL,
    patient_id bigint,
    lesion_id bigint,
    decision_type character varying(20) NOT NULL,
    decision_value character varying(20) NOT NULL,
    decision_reason character varying(250),
    source_assessment_id bigint,
    source_discordance_id bigint,
    decided_by_staff_id bigint,
    decided_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: clinical_decision_clinical_decision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.clinical_decision_clinical_decision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: clinical_decision_clinical_decision_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.clinical_decision_clinical_decision_id_seq OWNED BY public.clinical_decision.clinical_decision_id;


--
-- Name: discordance_flag; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discordance_flag (
    discordance_flag_id bigint NOT NULL,
    patient_id bigint,
    lesion_id bigint,
    specimen_id bigint,
    pathology_result_id bigint,
    assessment_id bigint,
    violated_rule character varying(20),
    flag_status character varying(20),
    rule_table_version character varying(30),
    flagged_at timestamp with time zone,
    reviewed_by_staff_id bigint,
    review_opinion character varying(20),
    review_note character varying(250),
    disposition_type character varying(20),
    disposition_reason character varying(250),
    disposed_by_staff_id bigint,
    closed_at timestamp with time zone,
    superseded_by_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: discordance_flag_discordance_flag_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.discordance_flag_discordance_flag_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: discordance_flag_discordance_flag_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.discordance_flag_discordance_flag_id_seq OWNED BY public.discordance_flag.discordance_flag_id;


--
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


--
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_admin_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_admin_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: exam_order; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exam_order (
    exam_order_id bigint NOT NULL,
    patient_id bigint NOT NULL,
    exam_purpose character varying(20) NOT NULL,
    modality character varying(20),
    order_source character varying(20),
    followup_round_no integer,
    parent_order_id bigint,
    billing_class character varying(20),
    ordered_by_staff_id bigint,
    ordered_at timestamp with time zone,
    reservation_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    order_status character varying(20) DEFAULT 'ordered'::character varying NOT NULL,
    CONSTRAINT exam_order_order_status_ck CHECK (((order_status)::text = ANY ((ARRAY['ordered'::character varying, 'accepted'::character varying, 'in_progress'::character varying, 'completed'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: exam_order_exam_order_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exam_order_exam_order_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exam_order_exam_order_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exam_order_exam_order_id_seq OWNED BY public.exam_order.exam_order_id;


--
-- Name: followup_round; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.followup_round (
    followup_round_id bigint NOT NULL,
    followup_track_id bigint,
    round_no integer,
    scheduled_at timestamp with time zone,
    visited_at timestamp with time zone,
    study_id bigint,
    round_result character varying(20),
    contact_method character varying(20),
    contacted_at timestamp with time zone,
    contacted_by_staff_id bigint,
    patient_response character varying(20),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: followup_round_followup_round_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.followup_round_followup_round_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: followup_round_followup_round_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.followup_round_followup_round_id_seq OWNED BY public.followup_round.followup_round_id;


--
-- Name: followup_track; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.followup_track (
    followup_track_id bigint NOT NULL,
    patient_id bigint,
    assessment_id bigint,
    track_status character varying(20),
    current_round_no integer,
    opened_at timestamp with time zone,
    next_due_at timestamp with time zone,
    closed_at timestamp with time zone,
    close_reason character varying(250),
    assigned_staff_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: followup_track_followup_track_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.followup_track_followup_track_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: followup_track_followup_track_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.followup_track_followup_track_id_seq OWNED BY public.followup_track.followup_track_id;


--
-- Name: image_instance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.image_instance (
    image_instance_id bigint NOT NULL,
    image_series_id bigint,
    instance_number integer,
    storage_object_id bigint,
    thumbnail_object_id bigint,
    width_pixel integer,
    height_pixel integer,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: image_instance_image_instance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.image_instance_image_instance_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: image_instance_image_instance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.image_instance_image_instance_id_seq OWNED BY public.image_instance.image_instance_id;


--
-- Name: image_pyramid; Type: TABLE; Schema: public; Owner: -
--

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
    built_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    CONSTRAINT image_pyramid_source_ck CHECK ((num_nonnulls(pathology_slide_id, image_instance_id) = 1))
);


--
-- Name: image_pyramid_image_pyramid_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.image_pyramid_image_pyramid_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: image_pyramid_image_pyramid_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.image_pyramid_image_pyramid_id_seq OWNED BY public.image_pyramid.image_pyramid_id;


--
-- Name: image_series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.image_series (
    image_series_id bigint NOT NULL,
    study_id bigint,
    series_uid character varying(100) NOT NULL,
    pixel_spacing_mm numeric(6,4),
    slice_count integer,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: image_series_image_series_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.image_series_image_series_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: image_series_image_series_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.image_series_image_series_id_seq OWNED BY public.image_series.image_series_id;


--
-- Name: lesion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lesion (
    lesion_id bigint NOT NULL,
    patient_id bigint,
    study_id bigint,
    ai_result_id bigint,
    laterality character varying(10),
    clock_position character varying(20),
    distance_from_nipple_mm numeric(6,2),
    size_mm numeric(6,2),
    size_measurable boolean,
    aspect_ratio numeric(5,3),
    area_pixel integer,
    lesion_source character varying(20),
    lesion_type character varying(30),
    needs_additional_view boolean,
    additional_view_reason character varying(250),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: lesion_descriptor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lesion_descriptor (
    lesion_descriptor_id bigint NOT NULL,
    lesion_id bigint,
    descriptor_name character varying(50),
    descriptor_value character varying(50),
    confidence numeric(4,3),
    suspicion_score integer,
    descriptor_source character varying(20),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: lesion_descriptor_lesion_descriptor_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.lesion_descriptor_lesion_descriptor_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: lesion_descriptor_lesion_descriptor_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.lesion_descriptor_lesion_descriptor_id_seq OWNED BY public.lesion_descriptor.lesion_descriptor_id;


--
-- Name: lesion_lesion_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.lesion_lesion_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: lesion_lesion_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.lesion_lesion_id_seq OWNED BY public.lesion.lesion_id;


--
-- Name: notification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification (
    notification_id bigint NOT NULL,
    patient_id bigint,
    staff_id bigint,
    notification_type character varying(30),
    severity character varying(20),
    channel character varying(20),
    sent_at timestamp with time zone,
    acknowledged_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: notification_notification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notification_notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notification_notification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notification_notification_id_seq OWNED BY public.notification.notification_id;


--
-- Name: pathology_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pathology_result (
    pathology_result_id bigint NOT NULL,
    patient_id bigint,
    specimen_id bigint,
    diagnosis character varying(20),
    b_category character varying(10),
    diagnosis_code character varying(30),
    histologic_type character varying(100),
    nottingham_grade integer,
    er_status character varying(20),
    pr_status character varying(20),
    her2_status character varying(20),
    ki67_percent numeric(5,2),
    stil_percent numeric(5,2),
    stil_interval_low numeric(5,2),
    stil_interval_high numeric(5,2),
    tsr_percent numeric(5,2),
    stil_source character varying(20),
    has_calcification boolean,
    reported_by_staff_id bigint,
    finalized_at timestamp with time zone,
    finding_note text,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: pathology_result_pathology_result_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pathology_result_pathology_result_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pathology_result_pathology_result_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pathology_result_pathology_result_id_seq OWNED BY public.pathology_result.pathology_result_id;


--
-- Name: pathology_slide; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pathology_slide (
    pathology_slide_id bigint NOT NULL,
    storage_object_id bigint,
    thumbnail_object_id bigint,
    stain_type character varying(20),
    scan_magnification character varying(20),
    mpp numeric(6,4),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    specimen_id bigint
);


--
-- Name: pathology_slide_pathology_slide_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pathology_slide_pathology_slide_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pathology_slide_pathology_slide_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pathology_slide_pathology_slide_id_seq OWNED BY public.pathology_slide.pathology_slide_id;


--
-- Name: patient; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.patient (
    patient_id bigint NOT NULL,
    patient_number character varying(50) NOT NULL,
    birth_year integer,
    sex character varying(20),
    has_allergy boolean DEFAULT false,
    allergy_note character varying(250),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: patient_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.patient_account (
    patient_account_id bigint NOT NULL,
    patient_id bigint NOT NULL,
    login_id character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    phone_verified boolean,
    push_token character varying(255),
    account_status character varying(20) DEFAULT 'active'::character varying,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: patient_account_patient_account_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.patient_account_patient_account_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: patient_account_patient_account_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.patient_account_patient_account_id_seq OWNED BY public.patient_account.patient_account_id;


--
-- Name: patient_patient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.patient_patient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: patient_patient_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.patient_patient_id_seq OWNED BY public.patient.patient_id;


--
-- Name: pharmacy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pharmacy (
    pharmacy_id bigint NOT NULL,
    external_key character varying(100),
    pharmacy_name character varying(100) NOT NULL,
    address character varying(250),
    phone character varying(30),
    latitude numeric(10,7),
    longitude numeric(10,7),
    business_hours text,
    is_holiday_open boolean,
    synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: pharmacy_pharmacy_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pharmacy_pharmacy_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pharmacy_pharmacy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pharmacy_pharmacy_id_seq OWNED BY public.pharmacy.pharmacy_id;


--
-- Name: prescription; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prescription (
    prescription_id bigint NOT NULL,
    patient_id bigint,
    prescribed_by_staff_id bigint,
    prescribed_at timestamp with time zone NOT NULL,
    valid_until date,
    diagnosis_code character varying(30),
    prescription_status character varying(20),
    storage_object_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: prescription_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prescription_item (
    prescription_item_id bigint NOT NULL,
    prescription_id bigint,
    line_no integer,
    drug_code character varying(50) NOT NULL,
    drug_name character varying(100) NOT NULL,
    dose_amount numeric(8,3),
    dose_unit character varying(20),
    times_per_day integer,
    duration_days integer,
    route character varying(20),
    instruction character varying(250),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: prescription_item_prescription_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prescription_item_prescription_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prescription_item_prescription_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prescription_item_prescription_item_id_seq OWNED BY public.prescription_item.prescription_item_id;


--
-- Name: prescription_pharmacy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prescription_pharmacy (
    prescription_pharmacy_id bigint NOT NULL,
    prescription_id bigint,
    pharmacy_id bigint,
    relation_type character varying(20),
    distance_meter integer,
    occurred_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: prescription_pharmacy_prescription_pharmacy_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prescription_pharmacy_prescription_pharmacy_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prescription_pharmacy_prescription_pharmacy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prescription_pharmacy_prescription_pharmacy_id_seq OWNED BY public.prescription_pharmacy.prescription_pharmacy_id;


--
-- Name: prescription_prescription_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prescription_prescription_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prescription_prescription_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prescription_prescription_id_seq OWNED BY public.prescription.prescription_id;


--
-- Name: questionnaire; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.questionnaire (
    questionnaire_id bigint NOT NULL,
    patient_id bigint NOT NULL,
    has_symptom boolean,
    symptom_detail character varying(250),
    family_history character varying(250),
    past_history character varying(250),
    menopause_status character varying(50),
    risk_model character varying(50),
    risk_lifetime_percent numeric(5,2),
    risk_tier character varying(50),
    guideline_source character varying(100),
    answered_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: questionnaire_questionnaire_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.questionnaire_questionnaire_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: questionnaire_questionnaire_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.questionnaire_questionnaire_id_seq OWNED BY public.questionnaire.questionnaire_id;


--
-- Name: report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report (
    report_id bigint NOT NULL,
    patient_id bigint,
    report_type character varying(20),
    audience character varying(20),
    content_json text,
    narrative_text text,
    evidence_links text,
    dropped_sentence_log text,
    lock_status character varying(20) DEFAULT 'locked'::character varying,
    unlocked_by_staff_id bigint,
    unlocked_at timestamp with time zone,
    generated_at timestamp with time zone,
    doc_type character varying(20),
    issued_by_staff_id bigint,
    storage_object_id bigint,
    unlock_reason character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: report_access_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_access_log (
    report_access_log_id bigint NOT NULL,
    report_id bigint,
    patient_id bigint,
    actor_type character varying(20),
    actor_id bigint,
    action character varying(20),
    accessed_at timestamp with time zone,
    client_channel character varying(20),
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: report_access_log_report_access_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.report_access_log_report_access_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: report_access_log_report_access_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.report_access_log_report_access_log_id_seq OWNED BY public.report_access_log.report_access_log_id;


--
-- Name: report_report_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.report_report_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: report_report_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.report_report_id_seq OWNED BY public.report.report_id;


--
-- Name: reservation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reservation (
    reservation_id bigint NOT NULL,
    patient_id bigint NOT NULL,
    scheduled_at timestamp with time zone NOT NULL,
    visited_at timestamp with time zone,
    reservation_status character varying(20),
    requested_by character varying(20),
    cancel_reason character varying(250),
    created_by_staff_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: reservation_reservation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reservation_reservation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reservation_reservation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reservation_reservation_id_seq OWNED BY public.reservation.reservation_id;


--
-- Name: result_explanation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.result_explanation (
    result_explanation_id bigint NOT NULL,
    report_id bigint,
    patient_id bigint,
    explained_by_staff_id bigint,
    explained_at timestamp with time zone,
    explain_method character varying(20),
    summary_text text,
    patient_confirmed boolean,
    storage_object_id bigint,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: result_explanation_result_explanation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.result_explanation_result_explanation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: result_explanation_result_explanation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.result_explanation_result_explanation_id_seq OWNED BY public.result_explanation.result_explanation_id;


--
-- Name: specimen; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.specimen (
    specimen_id bigint NOT NULL,
    patient_id bigint,
    lesion_id bigint NOT NULL,
    specimen_label character varying(50),
    specimen_type character varying(30),
    guidance_route character varying(30),
    target_snapshot character varying(250),
    bound_by_staff_id bigint,
    collected_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    accession_status character varying(20) DEFAULT 'unbound'::character varying NOT NULL,
    accessioned_at timestamp with time zone,
    CONSTRAINT specimen_accession_status_ck CHECK (((accession_status)::text = ANY ((ARRAY['unbound'::character varying, 'bound'::character varying, 'accessioned'::character varying])::text[])))
);


--
-- Name: specimen_specimen_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.specimen_specimen_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: specimen_specimen_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.specimen_specimen_id_seq OWNED BY public.specimen.specimen_id;


--
-- Name: staff; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff (
    staff_id bigint NOT NULL,
    login_name character varying(50) NOT NULL,
    display_name character varying(50),
    department character varying(20),
    is_active boolean DEFAULT true,
    email character varying(100),
    password_hash character varying(255) NOT NULL,
    staff_position character varying(30),
    account_status character varying(20) DEFAULT 'pending'::character varying,
    created_by bigint,
    created_at timestamp with time zone DEFAULT now(),
    updated_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT staff_department_ck CHECK (((department)::text = ANY ((ARRAY['admin'::character varying, 'reception'::character varying, 'nursing'::character varying, 'radiology'::character varying, 'surgery'::character varying, 'pathology'::character varying])::text[])))
);


--
-- Name: staff_staff_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staff_staff_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staff_staff_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staff_staff_id_seq OWNED BY public.staff.staff_id;


--
-- Name: storage_object; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storage_object (
    storage_object_id bigint NOT NULL,
    bucket character varying(100),
    object_key character varying(255) NOT NULL,
    content_type character varying(100),
    byte_size bigint,
    checksum_sha256 character varying(64),
    storage_class character varying(20),
    uploaded_at timestamp with time zone DEFAULT now(),
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: storage_object_storage_object_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.storage_object_storage_object_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: storage_object_storage_object_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.storage_object_storage_object_id_seq OWNED BY public.storage_object.storage_object_id;


--
-- Name: study; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.study (
    study_id bigint NOT NULL,
    patient_id bigint NOT NULL,
    exam_order_id bigint,
    modality character varying(20),
    study_uid character varying(100) NOT NULL,
    laterality character varying(10),
    view_position character varying(20),
    mri_purpose character varying(30),
    is_screen_capture boolean,
    device_name character varying(100),
    quality_status character varying(20),
    rejected_reason character varying(250),
    performed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    created_by bigint,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by bigint
);


--
-- Name: study_study_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.study_study_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: study_study_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.study_study_id_seq OWNED BY public.study.study_id;


--
-- Name: ai_mask ai_mask_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask ALTER COLUMN ai_mask_id SET DEFAULT nextval('public.ai_mask_ai_mask_id_seq'::regclass);


--
-- Name: ai_result ai_result_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_result ALTER COLUMN ai_result_id SET DEFAULT nextval('public.ai_result_ai_result_id_seq'::regclass);


--
-- Name: assessment assessment_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment ALTER COLUMN assessment_id SET DEFAULT nextval('public.assessment_assessment_id_seq'::regclass);


--
-- Name: audit_metric audit_metric_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_metric ALTER COLUMN audit_metric_id SET DEFAULT nextval('public.audit_metric_audit_metric_id_seq'::regclass);


--
-- Name: breast_density breast_density_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.breast_density ALTER COLUMN breast_density_id SET DEFAULT nextval('public.breast_density_breast_density_id_seq'::regclass);


--
-- Name: chat_message chat_message_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message ALTER COLUMN chat_message_id SET DEFAULT nextval('public.chat_message_chat_message_id_seq'::regclass);


--
-- Name: chat_session chat_session_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session ALTER COLUMN chat_session_id SET DEFAULT nextval('public.chat_session_chat_session_id_seq'::regclass);


--
-- Name: clinical_decision clinical_decision_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision ALTER COLUMN clinical_decision_id SET DEFAULT nextval('public.clinical_decision_clinical_decision_id_seq'::regclass);


--
-- Name: discordance_flag discordance_flag_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag ALTER COLUMN discordance_flag_id SET DEFAULT nextval('public.discordance_flag_discordance_flag_id_seq'::regclass);


--
-- Name: exam_order exam_order_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_order ALTER COLUMN exam_order_id SET DEFAULT nextval('public.exam_order_exam_order_id_seq'::regclass);


--
-- Name: followup_round followup_round_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_round ALTER COLUMN followup_round_id SET DEFAULT nextval('public.followup_round_followup_round_id_seq'::regclass);


--
-- Name: followup_track followup_track_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_track ALTER COLUMN followup_track_id SET DEFAULT nextval('public.followup_track_followup_track_id_seq'::regclass);


--
-- Name: image_instance image_instance_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_instance ALTER COLUMN image_instance_id SET DEFAULT nextval('public.image_instance_image_instance_id_seq'::regclass);


--
-- Name: image_series image_series_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_pyramid ALTER COLUMN image_pyramid_id SET DEFAULT nextval('public.image_pyramid_image_pyramid_id_seq'::regclass);


--
-- Name: image_series image_series_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_series ALTER COLUMN image_series_id SET DEFAULT nextval('public.image_series_image_series_id_seq'::regclass);


--
-- Name: lesion lesion_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion ALTER COLUMN lesion_id SET DEFAULT nextval('public.lesion_lesion_id_seq'::regclass);


--
-- Name: lesion_descriptor lesion_descriptor_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion_descriptor ALTER COLUMN lesion_descriptor_id SET DEFAULT nextval('public.lesion_descriptor_lesion_descriptor_id_seq'::regclass);


--
-- Name: notification notification_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification ALTER COLUMN notification_id SET DEFAULT nextval('public.notification_notification_id_seq'::regclass);


--
-- Name: pathology_result pathology_result_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_result ALTER COLUMN pathology_result_id SET DEFAULT nextval('public.pathology_result_pathology_result_id_seq'::regclass);


--
-- Name: pathology_slide pathology_slide_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_slide ALTER COLUMN pathology_slide_id SET DEFAULT nextval('public.pathology_slide_pathology_slide_id_seq'::regclass);


--
-- Name: patient patient_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient ALTER COLUMN patient_id SET DEFAULT nextval('public.patient_patient_id_seq'::regclass);


--
-- Name: patient_account patient_account_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_account ALTER COLUMN patient_account_id SET DEFAULT nextval('public.patient_account_patient_account_id_seq'::regclass);


--
-- Name: pharmacy pharmacy_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pharmacy ALTER COLUMN pharmacy_id SET DEFAULT nextval('public.pharmacy_pharmacy_id_seq'::regclass);


--
-- Name: prescription prescription_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription ALTER COLUMN prescription_id SET DEFAULT nextval('public.prescription_prescription_id_seq'::regclass);


--
-- Name: prescription_item prescription_item_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_item ALTER COLUMN prescription_item_id SET DEFAULT nextval('public.prescription_item_prescription_item_id_seq'::regclass);


--
-- Name: prescription_pharmacy prescription_pharmacy_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_pharmacy ALTER COLUMN prescription_pharmacy_id SET DEFAULT nextval('public.prescription_pharmacy_prescription_pharmacy_id_seq'::regclass);


--
-- Name: questionnaire questionnaire_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questionnaire ALTER COLUMN questionnaire_id SET DEFAULT nextval('public.questionnaire_questionnaire_id_seq'::regclass);


--
-- Name: report report_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report ALTER COLUMN report_id SET DEFAULT nextval('public.report_report_id_seq'::regclass);


--
-- Name: report_access_log report_access_log_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_access_log ALTER COLUMN report_access_log_id SET DEFAULT nextval('public.report_access_log_report_access_log_id_seq'::regclass);


--
-- Name: reservation reservation_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation ALTER COLUMN reservation_id SET DEFAULT nextval('public.reservation_reservation_id_seq'::regclass);


--
-- Name: result_explanation result_explanation_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.result_explanation ALTER COLUMN result_explanation_id SET DEFAULT nextval('public.result_explanation_result_explanation_id_seq'::regclass);


--
-- Name: specimen specimen_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specimen ALTER COLUMN specimen_id SET DEFAULT nextval('public.specimen_specimen_id_seq'::regclass);


--
-- Name: staff staff_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff ALTER COLUMN staff_id SET DEFAULT nextval('public.staff_staff_id_seq'::regclass);


--
-- Name: storage_object storage_object_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_object ALTER COLUMN storage_object_id SET DEFAULT nextval('public.storage_object_storage_object_id_seq'::regclass);


--
-- Name: study study_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study ALTER COLUMN study_id SET DEFAULT nextval('public.study_study_id_seq'::regclass);


--
-- Name: ai_mask ai_mask_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_pkey PRIMARY KEY (ai_mask_id);


--
-- Name: ai_result ai_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_pkey PRIMARY KEY (ai_result_id);


--
-- Name: assessment assessment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment
    ADD CONSTRAINT assessment_pkey PRIMARY KEY (assessment_id);


--
-- Name: audit_metric audit_metric_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_metric
    ADD CONSTRAINT audit_metric_pkey PRIMARY KEY (audit_metric_id);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_user_id_group_id_94350c0c_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_group_id_94350c0c_uniq UNIQUE (user_id, group_id);


--
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_permission_id_14a6b632_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_permission_id_14a6b632_uniq UNIQUE (user_id, permission_id);


--
-- Name: auth_user auth_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_username_key UNIQUE (username);


--
-- Name: breast_density breast_density_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.breast_density
    ADD CONSTRAINT breast_density_pkey PRIMARY KEY (breast_density_id);


--
-- Name: chat_message chat_message_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_message_pkey PRIMARY KEY (chat_message_id);


--
-- Name: chat_session chat_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session
    ADD CONSTRAINT chat_session_pkey PRIMARY KEY (chat_session_id);


--
-- Name: clinical_decision clinical_decision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision
    ADD CONSTRAINT clinical_decision_pkey PRIMARY KEY (clinical_decision_id);


--
-- Name: discordance_flag discordance_flag_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_pkey PRIMARY KEY (discordance_flag_id);


--
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: exam_order exam_order_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_order
    ADD CONSTRAINT exam_order_pkey PRIMARY KEY (exam_order_id);


--
-- Name: followup_round followup_round_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_round
    ADD CONSTRAINT followup_round_pkey PRIMARY KEY (followup_round_id);


--
-- Name: followup_track followup_track_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_track
    ADD CONSTRAINT followup_track_pkey PRIMARY KEY (followup_track_id);


--
-- Name: image_instance image_instance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_instance
    ADD CONSTRAINT image_instance_pkey PRIMARY KEY (image_instance_id);


--
-- Name: image_pyramid image_pyramid_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_pkey PRIMARY KEY (image_pyramid_id);


--
-- Name: image_series image_series_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_series
    ADD CONSTRAINT image_series_pkey PRIMARY KEY (image_series_id);


--
-- Name: image_series image_series_series_uid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_series
    ADD CONSTRAINT image_series_series_uid_key UNIQUE (series_uid);


--
-- Name: lesion_descriptor lesion_descriptor_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion_descriptor
    ADD CONSTRAINT lesion_descriptor_pkey PRIMARY KEY (lesion_descriptor_id);


--
-- Name: lesion lesion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion
    ADD CONSTRAINT lesion_pkey PRIMARY KEY (lesion_id);


--
-- Name: notification notification_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (notification_id);


--
-- Name: pathology_result pathology_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_result
    ADD CONSTRAINT pathology_result_pkey PRIMARY KEY (pathology_result_id);


--
-- Name: pathology_result pathology_result_specimen_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_result
    ADD CONSTRAINT pathology_result_specimen_id_key UNIQUE (specimen_id);


--
-- Name: pathology_slide pathology_slide_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_slide
    ADD CONSTRAINT pathology_slide_pkey PRIMARY KEY (pathology_slide_id);


--
-- Name: patient_account patient_account_login_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_account
    ADD CONSTRAINT patient_account_login_id_key UNIQUE (login_id);


--
-- Name: patient_account patient_account_patient_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_account
    ADD CONSTRAINT patient_account_patient_id_key UNIQUE (patient_id);


--
-- Name: patient_account patient_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_account
    ADD CONSTRAINT patient_account_pkey PRIMARY KEY (patient_account_id);


--
-- Name: patient patient_patient_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient
    ADD CONSTRAINT patient_patient_number_key UNIQUE (patient_number);


--
-- Name: patient patient_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient
    ADD CONSTRAINT patient_pkey PRIMARY KEY (patient_id);


--
-- Name: pharmacy pharmacy_external_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pharmacy
    ADD CONSTRAINT pharmacy_external_key_key UNIQUE (external_key);


--
-- Name: pharmacy pharmacy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pharmacy
    ADD CONSTRAINT pharmacy_pkey PRIMARY KEY (pharmacy_id);


--
-- Name: prescription_item prescription_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_item
    ADD CONSTRAINT prescription_item_pkey PRIMARY KEY (prescription_item_id);


--
-- Name: prescription_pharmacy prescription_pharmacy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_pharmacy
    ADD CONSTRAINT prescription_pharmacy_pkey PRIMARY KEY (prescription_pharmacy_id);


--
-- Name: prescription prescription_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription
    ADD CONSTRAINT prescription_pkey PRIMARY KEY (prescription_id);


--
-- Name: questionnaire questionnaire_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questionnaire
    ADD CONSTRAINT questionnaire_pkey PRIMARY KEY (questionnaire_id);


--
-- Name: report_access_log report_access_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_access_log
    ADD CONSTRAINT report_access_log_pkey PRIMARY KEY (report_access_log_id);


--
-- Name: report report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report
    ADD CONSTRAINT report_pkey PRIMARY KEY (report_id);


--
-- Name: reservation reservation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_pkey PRIMARY KEY (reservation_id);


--
-- Name: result_explanation result_explanation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.result_explanation
    ADD CONSTRAINT result_explanation_pkey PRIMARY KEY (result_explanation_id);


--
-- Name: specimen specimen_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specimen
    ADD CONSTRAINT specimen_pkey PRIMARY KEY (specimen_id);


--
-- Name: specimen specimen_specimen_label_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specimen
    ADD CONSTRAINT specimen_specimen_label_key UNIQUE (specimen_label);


--
-- Name: staff staff_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_email_key UNIQUE (email);


--
-- Name: staff staff_login_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_login_name_key UNIQUE (login_name);


--
-- Name: staff staff_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_pkey PRIMARY KEY (staff_id);


--
-- Name: storage_object storage_object_object_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_object
    ADD CONSTRAINT storage_object_object_key_key UNIQUE (object_key);


--
-- Name: storage_object storage_object_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_object
    ADD CONSTRAINT storage_object_pkey PRIMARY KEY (storage_object_id);


--
-- Name: study study_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study
    ADD CONSTRAINT study_pkey PRIMARY KEY (study_id);


--
-- Name: study study_study_uid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study
    ADD CONSTRAINT study_study_uid_key UNIQUE (study_uid);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: auth_user_groups_group_id_97559544; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id);


--
-- Name: auth_user_groups_user_id_6a12ed8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_user_id_6a12ed8b ON public.auth_user_groups USING btree (user_id);


--
-- Name: auth_user_user_permissions_permission_id_1fbb5f2c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id);


--
-- Name: auth_user_user_permissions_user_id_a95ead1b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON public.auth_user_user_permissions USING btree (user_id);


--
-- Name: auth_user_username_6821ab7c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops);


--
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: ai_mask_pathology_slide_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ai_mask_pathology_slide_id_idx ON public.ai_mask USING btree (pathology_slide_id);


--
-- Name: ai_result_pathology_slide_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ai_result_pathology_slide_id_idx ON public.ai_result USING btree (pathology_slide_id);


--
-- Name: image_pyramid_instance_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX image_pyramid_instance_idx ON public.image_pyramid USING btree (image_instance_id) WHERE (image_instance_id IS NOT NULL);


--
-- Name: image_pyramid_slide_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX image_pyramid_slide_idx ON public.image_pyramid USING btree (pathology_slide_id) WHERE (pathology_slide_id IS NOT NULL);


--
-- Name: pathology_slide_specimen_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX pathology_slide_specimen_id_idx ON public.pathology_slide USING btree (specimen_id);


--
-- Name: ai_mask ai_mask_ai_result_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_ai_result_id_fkey FOREIGN KEY (ai_result_id) REFERENCES public.ai_result(ai_result_id);


--
-- Name: ai_mask ai_mask_image_instance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_image_instance_id_fkey FOREIGN KEY (image_instance_id) REFERENCES public.image_instance(image_instance_id);


--
-- Name: ai_mask ai_mask_lesion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_lesion_id_fkey FOREIGN KEY (lesion_id) REFERENCES public.lesion(lesion_id);


--
-- Name: ai_mask ai_mask_storage_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_storage_object_id_fkey FOREIGN KEY (storage_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: ai_result ai_result_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: ai_result ai_result_requested_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_requested_by_staff_id_fkey FOREIGN KEY (requested_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: ai_result ai_result_study_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_study_id_fkey FOREIGN KEY (study_id) REFERENCES public.study(study_id);


--
-- Name: assessment assessment_assessed_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment
    ADD CONSTRAINT assessment_assessed_by_staff_id_fkey FOREIGN KEY (assessed_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: assessment assessment_lesion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment
    ADD CONSTRAINT assessment_lesion_id_fkey FOREIGN KEY (lesion_id) REFERENCES public.lesion(lesion_id);


--
-- Name: assessment assessment_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment
    ADD CONSTRAINT assessment_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: assessment assessment_study_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment
    ADD CONSTRAINT assessment_study_id_fkey FOREIGN KEY (study_id) REFERENCES public.study(study_id);


--
-- Name: assessment assessment_superseded_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessment
    ADD CONSTRAINT assessment_superseded_by_id_fkey FOREIGN KEY (superseded_by_id) REFERENCES public.assessment(assessment_id);


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_group_id_97559544_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_user_id_6a12ed8b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_6a12ed8b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: breast_density breast_density_study_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.breast_density
    ADD CONSTRAINT breast_density_study_id_fkey FOREIGN KEY (study_id) REFERENCES public.study(study_id);


--
-- Name: chat_message chat_message_chat_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_message_chat_session_id_fkey FOREIGN KEY (chat_session_id) REFERENCES public.chat_session(chat_session_id);


--
-- Name: chat_message chat_message_cited_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_message_cited_report_id_fkey FOREIGN KEY (cited_report_id) REFERENCES public.report(report_id);


--
-- Name: chat_session chat_session_escalated_to_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session
    ADD CONSTRAINT chat_session_escalated_to_staff_id_fkey FOREIGN KEY (escalated_to_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: chat_session chat_session_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_session
    ADD CONSTRAINT chat_session_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: clinical_decision clinical_decision_decided_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision
    ADD CONSTRAINT clinical_decision_decided_by_staff_id_fkey FOREIGN KEY (decided_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: clinical_decision clinical_decision_lesion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision
    ADD CONSTRAINT clinical_decision_lesion_id_fkey FOREIGN KEY (lesion_id) REFERENCES public.lesion(lesion_id);


--
-- Name: clinical_decision clinical_decision_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision
    ADD CONSTRAINT clinical_decision_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: clinical_decision clinical_decision_source_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision
    ADD CONSTRAINT clinical_decision_source_assessment_id_fkey FOREIGN KEY (source_assessment_id) REFERENCES public.assessment(assessment_id);


--
-- Name: clinical_decision clinical_decision_source_discordance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clinical_decision
    ADD CONSTRAINT clinical_decision_source_discordance_id_fkey FOREIGN KEY (source_discordance_id) REFERENCES public.discordance_flag(discordance_flag_id);


--
-- Name: discordance_flag discordance_flag_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_assessment_id_fkey FOREIGN KEY (assessment_id) REFERENCES public.assessment(assessment_id);


--
-- Name: discordance_flag discordance_flag_disposed_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_disposed_by_staff_id_fkey FOREIGN KEY (disposed_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: discordance_flag discordance_flag_lesion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_lesion_id_fkey FOREIGN KEY (lesion_id) REFERENCES public.lesion(lesion_id);


--
-- Name: discordance_flag discordance_flag_pathology_result_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_pathology_result_id_fkey FOREIGN KEY (pathology_result_id) REFERENCES public.pathology_result(pathology_result_id);


--
-- Name: discordance_flag discordance_flag_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: discordance_flag discordance_flag_reviewed_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_reviewed_by_staff_id_fkey FOREIGN KEY (reviewed_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: discordance_flag discordance_flag_specimen_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_specimen_id_fkey FOREIGN KEY (specimen_id) REFERENCES public.specimen(specimen_id);


--
-- Name: discordance_flag discordance_flag_superseded_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discordance_flag
    ADD CONSTRAINT discordance_flag_superseded_by_id_fkey FOREIGN KEY (superseded_by_id) REFERENCES public.discordance_flag(discordance_flag_id);


--
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: exam_order exam_order_ordered_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_order
    ADD CONSTRAINT exam_order_ordered_by_staff_id_fkey FOREIGN KEY (ordered_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: exam_order exam_order_parent_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_order
    ADD CONSTRAINT exam_order_parent_order_id_fkey FOREIGN KEY (parent_order_id) REFERENCES public.exam_order(exam_order_id);


--
-- Name: exam_order exam_order_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_order
    ADD CONSTRAINT exam_order_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: exam_order exam_order_reservation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exam_order
    ADD CONSTRAINT exam_order_reservation_id_fkey FOREIGN KEY (reservation_id) REFERENCES public.reservation(reservation_id);


--
-- Name: followup_round followup_round_contacted_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_round
    ADD CONSTRAINT followup_round_contacted_by_staff_id_fkey FOREIGN KEY (contacted_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: followup_round followup_round_followup_track_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_round
    ADD CONSTRAINT followup_round_followup_track_id_fkey FOREIGN KEY (followup_track_id) REFERENCES public.followup_track(followup_track_id);


--
-- Name: followup_round followup_round_study_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_round
    ADD CONSTRAINT followup_round_study_id_fkey FOREIGN KEY (study_id) REFERENCES public.study(study_id);


--
-- Name: followup_track followup_track_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_track
    ADD CONSTRAINT followup_track_assessment_id_fkey FOREIGN KEY (assessment_id) REFERENCES public.assessment(assessment_id);


--
-- Name: followup_track followup_track_assigned_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_track
    ADD CONSTRAINT followup_track_assigned_staff_id_fkey FOREIGN KEY (assigned_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: followup_track followup_track_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.followup_track
    ADD CONSTRAINT followup_track_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: image_instance image_instance_image_series_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_instance
    ADD CONSTRAINT image_instance_image_series_id_fkey FOREIGN KEY (image_series_id) REFERENCES public.image_series(image_series_id);


--
-- Name: image_instance image_instance_storage_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_instance
    ADD CONSTRAINT image_instance_storage_object_id_fkey FOREIGN KEY (storage_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: image_instance image_instance_thumbnail_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_instance
    ADD CONSTRAINT image_instance_thumbnail_object_id_fkey FOREIGN KEY (thumbnail_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: image_series image_series_study_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_series
    ADD CONSTRAINT image_series_study_id_fkey FOREIGN KEY (study_id) REFERENCES public.study(study_id);


--
-- Name: lesion lesion_ai_result_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion
    ADD CONSTRAINT lesion_ai_result_id_fkey FOREIGN KEY (ai_result_id) REFERENCES public.ai_result(ai_result_id);


--
-- Name: lesion_descriptor lesion_descriptor_lesion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion_descriptor
    ADD CONSTRAINT lesion_descriptor_lesion_id_fkey FOREIGN KEY (lesion_id) REFERENCES public.lesion(lesion_id);


--
-- Name: lesion lesion_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion
    ADD CONSTRAINT lesion_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: lesion lesion_study_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lesion
    ADD CONSTRAINT lesion_study_id_fkey FOREIGN KEY (study_id) REFERENCES public.study(study_id);


--
-- Name: notification notification_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: notification notification_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES public.staff(staff_id);


--
-- Name: pathology_result pathology_result_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_result
    ADD CONSTRAINT pathology_result_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: pathology_result pathology_result_reported_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_result
    ADD CONSTRAINT pathology_result_reported_by_staff_id_fkey FOREIGN KEY (reported_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: pathology_result pathology_result_specimen_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_result
    ADD CONSTRAINT pathology_result_specimen_id_fkey FOREIGN KEY (specimen_id) REFERENCES public.specimen(specimen_id);


--
-- Name: pathology_slide pathology_slide_specimen_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_slide
    ADD CONSTRAINT pathology_slide_specimen_id_fkey FOREIGN KEY (specimen_id) REFERENCES public.specimen(specimen_id);


--
-- Name: pathology_slide pathology_slide_storage_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_slide
    ADD CONSTRAINT pathology_slide_storage_object_id_fkey FOREIGN KEY (storage_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: pathology_slide pathology_slide_thumbnail_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pathology_slide
    ADD CONSTRAINT pathology_slide_thumbnail_object_id_fkey FOREIGN KEY (thumbnail_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: ai_mask ai_mask_pathology_slide_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_mask
    ADD CONSTRAINT ai_mask_pathology_slide_id_fkey FOREIGN KEY (pathology_slide_id) REFERENCES public.pathology_slide(pathology_slide_id);


--
-- Name: ai_result ai_result_pathology_slide_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_result
    ADD CONSTRAINT ai_result_pathology_slide_id_fkey FOREIGN KEY (pathology_slide_id) REFERENCES public.pathology_slide(pathology_slide_id);


--
-- Name: image_pyramid image_pyramid_image_instance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_image_instance_id_fkey FOREIGN KEY (image_instance_id) REFERENCES public.image_instance(image_instance_id);


--
-- Name: image_pyramid image_pyramid_pathology_slide_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.image_pyramid
    ADD CONSTRAINT image_pyramid_pathology_slide_id_fkey FOREIGN KEY (pathology_slide_id) REFERENCES public.pathology_slide(pathology_slide_id);


--
-- Name: patient_account patient_account_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.patient_account
    ADD CONSTRAINT patient_account_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: prescription_item prescription_item_prescription_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_item
    ADD CONSTRAINT prescription_item_prescription_id_fkey FOREIGN KEY (prescription_id) REFERENCES public.prescription(prescription_id);


--
-- Name: prescription prescription_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription
    ADD CONSTRAINT prescription_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: prescription_pharmacy prescription_pharmacy_pharmacy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_pharmacy
    ADD CONSTRAINT prescription_pharmacy_pharmacy_id_fkey FOREIGN KEY (pharmacy_id) REFERENCES public.pharmacy(pharmacy_id);


--
-- Name: prescription_pharmacy prescription_pharmacy_prescription_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription_pharmacy
    ADD CONSTRAINT prescription_pharmacy_prescription_id_fkey FOREIGN KEY (prescription_id) REFERENCES public.prescription(prescription_id);


--
-- Name: prescription prescription_prescribed_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription
    ADD CONSTRAINT prescription_prescribed_by_staff_id_fkey FOREIGN KEY (prescribed_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: prescription prescription_storage_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescription
    ADD CONSTRAINT prescription_storage_object_id_fkey FOREIGN KEY (storage_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: questionnaire questionnaire_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questionnaire
    ADD CONSTRAINT questionnaire_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: report_access_log report_access_log_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_access_log
    ADD CONSTRAINT report_access_log_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: report_access_log report_access_log_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_access_log
    ADD CONSTRAINT report_access_log_report_id_fkey FOREIGN KEY (report_id) REFERENCES public.report(report_id);


--
-- Name: report report_issued_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report
    ADD CONSTRAINT report_issued_by_staff_id_fkey FOREIGN KEY (issued_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: report report_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report
    ADD CONSTRAINT report_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: report report_storage_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report
    ADD CONSTRAINT report_storage_object_id_fkey FOREIGN KEY (storage_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: report report_unlocked_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report
    ADD CONSTRAINT report_unlocked_by_staff_id_fkey FOREIGN KEY (unlocked_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: reservation reservation_created_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_created_by_staff_id_fkey FOREIGN KEY (created_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: reservation reservation_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation
    ADD CONSTRAINT reservation_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: result_explanation result_explanation_explained_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.result_explanation
    ADD CONSTRAINT result_explanation_explained_by_staff_id_fkey FOREIGN KEY (explained_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: result_explanation result_explanation_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.result_explanation
    ADD CONSTRAINT result_explanation_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: result_explanation result_explanation_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.result_explanation
    ADD CONSTRAINT result_explanation_report_id_fkey FOREIGN KEY (report_id) REFERENCES public.report(report_id);


--
-- Name: result_explanation result_explanation_storage_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.result_explanation
    ADD CONSTRAINT result_explanation_storage_object_id_fkey FOREIGN KEY (storage_object_id) REFERENCES public.storage_object(storage_object_id);


--
-- Name: specimen specimen_bound_by_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specimen
    ADD CONSTRAINT specimen_bound_by_staff_id_fkey FOREIGN KEY (bound_by_staff_id) REFERENCES public.staff(staff_id);


--
-- Name: specimen specimen_lesion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specimen
    ADD CONSTRAINT specimen_lesion_id_fkey FOREIGN KEY (lesion_id) REFERENCES public.lesion(lesion_id);


--
-- Name: specimen specimen_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specimen
    ADD CONSTRAINT specimen_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- Name: study study_exam_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study
    ADD CONSTRAINT study_exam_order_id_fkey FOREIGN KEY (exam_order_id) REFERENCES public.exam_order(exam_order_id);


--
-- Name: study study_patient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.study
    ADD CONSTRAINT study_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patient(patient_id);


--
-- PostgreSQL database dump complete
--


