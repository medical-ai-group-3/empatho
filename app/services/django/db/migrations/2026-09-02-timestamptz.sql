-- 2026-09-02 · 업무 테이블의 시각 컬럼을 timestamptz 로 바꾼다
--
-- 왜
--   DB 는 timestamp without time zone 인데 Django 는 USE_TZ = True 다.
--   DEFAULT now() 가 UTC 를 timezone 없이 넣으면 Django 는 그것을 naive 로 읽고
--   TIME_ZONE(Asia/Seoul)으로 간주한다. 다시 저장할 때 UTC 로 변환하므로
--   save() 를 부를 때마다 9시간씩 뒤로 밀린다. 검사·처방 시각을 다루는
--   시스템에서 그대로 둘 수 없다.
--
--   Django 가 직접 만든 django_* · auth_* 테이블은 처음부터 timestamptz 다.
--   업무 테이블만 어긋나 있었다.
--
-- 변환
--   USING col AT TIME ZONE 'UTC' — 저장된 naive 값을 UTC 로 해석한다.
--   DEFAULT now() 는 그대로 둔다. now() 는 timestamptz 라 새 타입에 맞는다.
--   실행 시점에 업무 테이블 35개가 모두 0행이라 변환 위험이 없다.
--
-- 근거는 docs/api_summary.md · db/README.md 「타임존」 참조.

BEGIN;


-- ai_mask
ALTER TABLE public.ai_mask ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.ai_mask ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- ai_result
ALTER TABLE public.ai_result ALTER COLUMN analyzed_at TYPE timestamp with time zone
    USING analyzed_at AT TIME ZONE 'UTC';
ALTER TABLE public.ai_result ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.ai_result ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- assessment
ALTER TABLE public.assessment ALTER COLUMN finalized_at TYPE timestamp with time zone
    USING finalized_at AT TIME ZONE 'UTC';
ALTER TABLE public.assessment ALTER COLUMN ai_revealed_at TYPE timestamp with time zone
    USING ai_revealed_at AT TIME ZONE 'UTC';
ALTER TABLE public.assessment ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.assessment ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- audit_metric
ALTER TABLE public.audit_metric ALTER COLUMN computed_at TYPE timestamp with time zone
    USING computed_at AT TIME ZONE 'UTC';
ALTER TABLE public.audit_metric ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.audit_metric ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- breast_density
ALTER TABLE public.breast_density ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.breast_density ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- chat_message
ALTER TABLE public.chat_message ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.chat_message ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- chat_session
ALTER TABLE public.chat_session ALTER COLUMN started_at TYPE timestamp with time zone
    USING started_at AT TIME ZONE 'UTC';
ALTER TABLE public.chat_session ALTER COLUMN ended_at TYPE timestamp with time zone
    USING ended_at AT TIME ZONE 'UTC';
ALTER TABLE public.chat_session ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.chat_session ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- clinical_decision
ALTER TABLE public.clinical_decision ALTER COLUMN decided_at TYPE timestamp with time zone
    USING decided_at AT TIME ZONE 'UTC';
ALTER TABLE public.clinical_decision ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.clinical_decision ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- discordance_flag
ALTER TABLE public.discordance_flag ALTER COLUMN flagged_at TYPE timestamp with time zone
    USING flagged_at AT TIME ZONE 'UTC';
ALTER TABLE public.discordance_flag ALTER COLUMN closed_at TYPE timestamp with time zone
    USING closed_at AT TIME ZONE 'UTC';
ALTER TABLE public.discordance_flag ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.discordance_flag ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- exam_order
ALTER TABLE public.exam_order ALTER COLUMN ordered_at TYPE timestamp with time zone
    USING ordered_at AT TIME ZONE 'UTC';
ALTER TABLE public.exam_order ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.exam_order ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- followup_round
ALTER TABLE public.followup_round ALTER COLUMN scheduled_at TYPE timestamp with time zone
    USING scheduled_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_round ALTER COLUMN visited_at TYPE timestamp with time zone
    USING visited_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_round ALTER COLUMN contacted_at TYPE timestamp with time zone
    USING contacted_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_round ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_round ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- followup_track
ALTER TABLE public.followup_track ALTER COLUMN opened_at TYPE timestamp with time zone
    USING opened_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_track ALTER COLUMN next_due_at TYPE timestamp with time zone
    USING next_due_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_track ALTER COLUMN closed_at TYPE timestamp with time zone
    USING closed_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_track ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.followup_track ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- image_instance
ALTER TABLE public.image_instance ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.image_instance ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- image_pyramid
ALTER TABLE public.image_pyramid ALTER COLUMN built_at TYPE timestamp with time zone
    USING built_at AT TIME ZONE 'UTC';
ALTER TABLE public.image_pyramid ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.image_pyramid ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- image_series
ALTER TABLE public.image_series ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.image_series ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- lesion
ALTER TABLE public.lesion ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.lesion ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- lesion_descriptor
ALTER TABLE public.lesion_descriptor ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.lesion_descriptor ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- notification
ALTER TABLE public.notification ALTER COLUMN sent_at TYPE timestamp with time zone
    USING sent_at AT TIME ZONE 'UTC';
ALTER TABLE public.notification ALTER COLUMN acknowledged_at TYPE timestamp with time zone
    USING acknowledged_at AT TIME ZONE 'UTC';
ALTER TABLE public.notification ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.notification ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- pathology_result
ALTER TABLE public.pathology_result ALTER COLUMN finalized_at TYPE timestamp with time zone
    USING finalized_at AT TIME ZONE 'UTC';
ALTER TABLE public.pathology_result ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.pathology_result ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- pathology_slide
ALTER TABLE public.pathology_slide ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.pathology_slide ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- patient
ALTER TABLE public.patient ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.patient ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- patient_account
ALTER TABLE public.patient_account ALTER COLUMN last_login_at TYPE timestamp with time zone
    USING last_login_at AT TIME ZONE 'UTC';
ALTER TABLE public.patient_account ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.patient_account ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- pharmacy
ALTER TABLE public.pharmacy ALTER COLUMN synced_at TYPE timestamp with time zone
    USING synced_at AT TIME ZONE 'UTC';
ALTER TABLE public.pharmacy ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.pharmacy ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- prescription
ALTER TABLE public.prescription ALTER COLUMN prescribed_at TYPE timestamp with time zone
    USING prescribed_at AT TIME ZONE 'UTC';
ALTER TABLE public.prescription ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.prescription ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- prescription_item
ALTER TABLE public.prescription_item ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.prescription_item ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- prescription_pharmacy
ALTER TABLE public.prescription_pharmacy ALTER COLUMN occurred_at TYPE timestamp with time zone
    USING occurred_at AT TIME ZONE 'UTC';
ALTER TABLE public.prescription_pharmacy ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.prescription_pharmacy ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- questionnaire
ALTER TABLE public.questionnaire ALTER COLUMN answered_at TYPE timestamp with time zone
    USING answered_at AT TIME ZONE 'UTC';
ALTER TABLE public.questionnaire ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.questionnaire ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- report
ALTER TABLE public.report ALTER COLUMN unlocked_at TYPE timestamp with time zone
    USING unlocked_at AT TIME ZONE 'UTC';
ALTER TABLE public.report ALTER COLUMN generated_at TYPE timestamp with time zone
    USING generated_at AT TIME ZONE 'UTC';
ALTER TABLE public.report ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.report ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- report_access_log
ALTER TABLE public.report_access_log ALTER COLUMN accessed_at TYPE timestamp with time zone
    USING accessed_at AT TIME ZONE 'UTC';
ALTER TABLE public.report_access_log ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.report_access_log ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- reservation
ALTER TABLE public.reservation ALTER COLUMN scheduled_at TYPE timestamp with time zone
    USING scheduled_at AT TIME ZONE 'UTC';
ALTER TABLE public.reservation ALTER COLUMN visited_at TYPE timestamp with time zone
    USING visited_at AT TIME ZONE 'UTC';
ALTER TABLE public.reservation ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.reservation ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- result_explanation
ALTER TABLE public.result_explanation ALTER COLUMN explained_at TYPE timestamp with time zone
    USING explained_at AT TIME ZONE 'UTC';
ALTER TABLE public.result_explanation ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.result_explanation ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- specimen
ALTER TABLE public.specimen ALTER COLUMN collected_at TYPE timestamp with time zone
    USING collected_at AT TIME ZONE 'UTC';
ALTER TABLE public.specimen ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.specimen ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';
ALTER TABLE public.specimen ALTER COLUMN accessioned_at TYPE timestamp with time zone
    USING accessioned_at AT TIME ZONE 'UTC';

-- staff
ALTER TABLE public.staff ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.staff ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- storage_object
ALTER TABLE public.storage_object ALTER COLUMN uploaded_at TYPE timestamp with time zone
    USING uploaded_at AT TIME ZONE 'UTC';
ALTER TABLE public.storage_object ALTER COLUMN deleted_at TYPE timestamp with time zone
    USING deleted_at AT TIME ZONE 'UTC';
ALTER TABLE public.storage_object ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.storage_object ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';

-- study
ALTER TABLE public.study ALTER COLUMN performed_at TYPE timestamp with time zone
    USING performed_at AT TIME ZONE 'UTC';
ALTER TABLE public.study ALTER COLUMN created_at TYPE timestamp with time zone
    USING created_at AT TIME ZONE 'UTC';
ALTER TABLE public.study ALTER COLUMN updated_at TYPE timestamp with time zone
    USING updated_at AT TIME ZONE 'UTC';


COMMIT;
