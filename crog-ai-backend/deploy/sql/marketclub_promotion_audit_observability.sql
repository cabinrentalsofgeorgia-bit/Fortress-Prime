ALTER TABLE hedge_fund.signal_promotion_dry_run_acceptances
    ADD COLUMN IF NOT EXISTS verification_status_snapshot TEXT,
    ADD COLUMN IF NOT EXISTS verification_payload_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS candidate_set_hash TEXT;

ALTER TABLE hedge_fund.signal_promotion_executions
    ADD COLUMN IF NOT EXISTS inserted_market_signal_ids_hash TEXT;

ALTER TABLE hedge_fund.signal_promotion_rollback_audits
    ADD COLUMN IF NOT EXISTS deleted_market_signal_ids_hash TEXT;

CREATE OR REPLACE FUNCTION hedge_fund.set_signal_promotion_execution_snapshot_hash()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, hedge_fund
AS $$
BEGIN
    NEW.inserted_market_signal_ids_hash :=
        md5(array_to_string(COALESCE(NEW.inserted_market_signal_ids, ARRAY[]::INTEGER[]), ','));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_signal_promotion_execution_snapshot_hash
ON hedge_fund.signal_promotion_executions;

CREATE TRIGGER trg_signal_promotion_execution_snapshot_hash
BEFORE INSERT OR UPDATE OF inserted_market_signal_ids
ON hedge_fund.signal_promotion_executions
FOR EACH ROW
EXECUTE FUNCTION hedge_fund.set_signal_promotion_execution_snapshot_hash();

CREATE OR REPLACE FUNCTION hedge_fund.set_signal_promotion_rollback_snapshot_hash()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, hedge_fund
AS $$
BEGIN
    NEW.deleted_market_signal_ids_hash :=
        md5(array_to_string(COALESCE(NEW.deleted_market_signal_ids, ARRAY[]::INTEGER[]), ','));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_signal_promotion_rollback_snapshot_hash
ON hedge_fund.signal_promotion_rollback_audits;

CREATE TRIGGER trg_signal_promotion_rollback_snapshot_hash
BEFORE INSERT OR UPDATE OF deleted_market_signal_ids
ON hedge_fund.signal_promotion_rollback_audits
FOR EACH ROW
EXECUTE FUNCTION hedge_fund.set_signal_promotion_rollback_snapshot_hash();

ALTER VIEW IF EXISTS hedge_fund.v_signal_promotion_rollback_drill
SET (security_invoker = true);

CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_lifecycle_timeline
WITH (security_invoker = true) AS
WITH successful_rollback_audit AS (
    SELECT DISTINCT ON (a.execution_id)
        a.execution_id,
        a.rollback_status,
        a.deleted_market_signal_ids,
        a.deleted_market_signal_ids_hash,
        a.rollback_marker_count,
        a.attempted_at,
        a.completed_at
    FROM hedge_fund.signal_promotion_rollback_audits a
    WHERE a.rollback_status = 'rolled_back'
    ORDER BY a.execution_id, COALESCE(a.completed_at, a.attempted_at) DESC
),
rollback_eligible AS (
    SELECT
        d.execution_id,
        d.executed_at,
        d.rollback_preview_count,
        d.rollback_markers
    FROM hedge_fund.v_signal_promotion_rollback_drill d
    WHERE d.rollback_eligibility = 'ELIGIBLE'
)
SELECT
    d.created_at AS ts,
    'DECISION_CREATED'::TEXT AS event_type,
    d.id AS decision_id,
    NULL::UUID AS acceptance_id,
    NULL::UUID AS execution_id,
    d.candidate_parameter_set AS candidate_id,
    d.reviewer AS actor,
    jsonb_build_object(
        'decision', d.decision,
        'rationale', d.rationale,
        'rollback_criteria', d.rollback_criteria,
        'reviewed_tickers', d.reviewed_tickers,
        'promotion_gate_status', d.promotion_gate_status,
        'recommendation_status', d.recommendation_status
    ) AS meta
FROM hedge_fund.signal_shadow_review_decisions d

UNION ALL

SELECT
    a.dry_run_generated_at AS ts,
    'DRY_RUN_GENERATED'::TEXT AS event_type,
    a.decision_record_id AS decision_id,
    a.id AS acceptance_id,
    NULL::UUID AS execution_id,
    a.candidate_parameter_set AS candidate_id,
    a.accepted_by AS actor,
    jsonb_build_object(
        'proposed_rows', a.dry_run_proposed_insert_count,
        'bullish', a.dry_run_bullish_count,
        'risk', a.dry_run_risk_count,
        'candidate_signal_count', a.dry_run_candidate_signal_count,
        'skipped_neutral', a.dry_run_skipped_neutral_count,
        'candidate_set_hash', a.candidate_set_hash
    ) AS meta
FROM hedge_fund.signal_promotion_dry_run_acceptances a

UNION ALL

SELECT
    a.created_at AS ts,
    'VERIFICATION_RESULT'::TEXT AS event_type,
    a.decision_record_id AS decision_id,
    a.id AS acceptance_id,
    NULL::UUID AS execution_id,
    a.candidate_parameter_set AS candidate_id,
    a.accepted_by AS actor,
    jsonb_build_object(
        'status', a.verification_status_snapshot,
        'checked', COALESCE((a.verification_payload_snapshot ->> 'proposed_rows_checked')::INTEGER, 0),
        'passed', COALESCE((a.verification_payload_snapshot ->> 'passed_rows')::INTEGER, 0),
        'fail', COALESCE((a.verification_payload_snapshot ->> 'failed_rows')::INTEGER, 0),
        'inconclusive', COALESCE((a.verification_payload_snapshot ->> 'inconclusive_rows')::INTEGER, 0),
        'cross_model_only', COALESCE((a.verification_payload_snapshot ->> 'cross_model_diagnostic_only_rows')::INTEGER, 0)
    ) AS meta
FROM hedge_fund.signal_promotion_dry_run_acceptances a
WHERE a.verification_status_snapshot IS NOT NULL

UNION ALL

SELECT
    a.created_at AS ts,
    'ACCEPTANCE_CREATED'::TEXT AS event_type,
    a.decision_record_id AS decision_id,
    a.id AS acceptance_id,
    NULL::UUID AS execution_id,
    a.candidate_parameter_set AS candidate_id,
    a.accepted_by AS actor,
    jsonb_build_object(
        'rationale', a.acceptance_rationale,
        'rollback_criteria', a.rollback_criteria,
        'target_table', a.target_table,
        'proposed_rows', a.dry_run_proposed_insert_count
    ) AS meta
FROM hedge_fund.signal_promotion_dry_run_acceptances a

UNION ALL

SELECT
    e.created_at AS ts,
    'EXECUTION_COMPLETED'::TEXT AS event_type,
    e.decision_record_id AS decision_id,
    e.acceptance_id,
    e.id AS execution_id,
    e.candidate_parameter_set AS candidate_id,
    e.executed_by AS actor,
    jsonb_build_object(
        'inserted_count', cardinality(e.inserted_market_signal_ids),
        'idempotency_key', e.idempotency_key,
        'inserted_market_signal_ids', e.inserted_market_signal_ids,
        'rollback_markers', e.rollback_markers,
        'ids_hash', e.inserted_market_signal_ids_hash
    ) AS meta
FROM hedge_fund.signal_promotion_executions e

UNION ALL

SELECT
    re.executed_at AS ts,
    'ROLLBACK_ELIGIBLE'::TEXT AS event_type,
    e.decision_record_id AS decision_id,
    e.acceptance_id,
    re.execution_id,
    e.candidate_parameter_set AS candidate_id,
    e.executed_by AS actor,
    jsonb_build_object(
        'rollback_preview_count', re.rollback_preview_count,
        'rollback_markers', re.rollback_markers
    ) AS meta
FROM rollback_eligible re
JOIN hedge_fund.signal_promotion_executions e ON e.id = re.execution_id

UNION ALL

SELECT
    COALESCE(a.completed_at, a.attempted_at) AS ts,
    'ROLLBACK_COMPLETED'::TEXT AS event_type,
    e.decision_record_id AS decision_id,
    e.acceptance_id,
    a.execution_id,
    e.candidate_parameter_set AS candidate_id,
    e.rollback_by AS actor,
    jsonb_build_object(
        'removed_count', cardinality(a.deleted_market_signal_ids),
        'removed_market_signal_ids', a.deleted_market_signal_ids,
        'rollback_marker_count', a.rollback_marker_count,
        'ids_hash', a.deleted_market_signal_ids_hash,
        'rollback_status', a.rollback_status
    ) AS meta
FROM successful_rollback_audit a
JOIN hedge_fund.signal_promotion_executions e ON e.id = a.execution_id;

CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_reconciliation
WITH (security_invoker = true) AS
WITH execution_base AS (
    SELECT
        e.*,
        (
            SELECT COALESCE(array_agg(id ORDER BY id), ARRAY[]::INTEGER[])
            FROM unnest(e.inserted_market_signal_ids) AS id
        ) AS inserted_ids_sorted,
        COUNT(*) OVER (PARTITION BY e.acceptance_id) AS executions_for_acceptance,
        COUNT(*) OVER (PARTITION BY e.acceptance_id, e.idempotency_key) AS executions_for_acceptance_key
    FROM hedge_fund.signal_promotion_executions e
),
successful_rollback_audit AS (
    SELECT DISTINCT ON (a.execution_id)
        a.execution_id,
        a.rollback_status,
        a.deleted_market_signal_ids,
        a.deleted_market_signal_ids_hash,
        a.attempted_at,
        a.completed_at
    FROM hedge_fund.signal_promotion_rollback_audits a
    WHERE a.rollback_status = 'rolled_back'
    ORDER BY a.execution_id, COALESCE(a.completed_at, a.attempted_at) DESC
),
row_rollup AS (
    SELECT
        e.id AS execution_id,
        COALESCE(array_agg(r.market_signal_id ORDER BY r.market_signal_id)
            FILTER (WHERE r.market_signal_id IS NOT NULL), ARRAY[]::INTEGER[]) AS audited_ids,
        COUNT(r.market_signal_id)::INTEGER AS audited_count,
        COALESCE(array_agg(ms.id ORDER BY ms.id)
            FILTER (WHERE ms.id IS NOT NULL), ARRAY[]::INTEGER[]) AS live_audited_ids,
        COUNT(ms.id)::INTEGER AS live_audited_count,
        COUNT(DISTINCT r.market_signal_id)::INTEGER AS distinct_audited_count
    FROM execution_base e
    LEFT JOIN hedge_fund.signal_promotion_execution_rows r ON r.execution_id = e.id
    LEFT JOIN hedge_fund.market_signals ms ON ms.id = r.market_signal_id
    GROUP BY e.id
),
evidence_flags AS (
    SELECT
        d.id AS decision_id,
        EXISTS (
            SELECT 1
            FROM jsonb_array_elements(COALESCE(d.evidence_payload -> 'lane_reviews', '[]'::JSONB)) lane
            WHERE COALESCE((lane ->> 'churn_rate')::NUMERIC, 0) >= 0.50
        ) AS high_churn_flag,
        EXISTS (
            SELECT 1
            FROM jsonb_array_elements(COALESCE(d.evidence_payload -> 'whipsaw_reviews', '[]'::JSONB)) whipsaw
            WHERE whipsaw ->> 'risk_level' IN ('high', 'elevated')
        ) AS whipsaw_flag
    FROM hedge_fund.signal_shadow_review_decisions d
),
checks AS (
    SELECT
        e.id AS execution_id,
        a.id AS acceptance_id,
        a.candidate_parameter_set AS candidate_id,
        CASE
            WHEN d.id IS NOT NULL
             AND a.decision_record_id = d.id
             AND d.candidate_parameter_set = a.candidate_parameter_set
                THEN 'PASS'
            ELSE 'FAIL'
        END AS decision_link,
        CASE
            WHEN a.verification_status_snapshot = 'PASS'
             AND a.verification_payload_snapshot IS NOT NULL
                THEN 'PASS'
            ELSE 'FAIL'
        END AS verification_gate,
        CASE
            WHEN e.id IS NULL THEN 'NA'
            WHEN e.dry_run_proposed_insert_count = r.audited_count
             AND e.dry_run_proposed_insert_count = cardinality(e.inserted_market_signal_ids)
                THEN 'PASS'
            ELSE 'FAIL'
        END AS execution_count_match,
        CASE
            WHEN e.id IS NULL THEN 'NA'
            WHEN e.rollback_status = 'rolled_back' THEN 'PASS'
            WHEN r.live_audited_count = r.audited_count
             AND r.audited_count > 0
                THEN 'PASS'
            ELSE 'FAIL'
        END AS write_integrity,
        CASE
            WHEN e.id IS NULL THEN 'NA'
            WHEN e.inserted_ids_sorted = r.audited_ids
             AND r.audited_count = r.distinct_audited_count
                THEN 'PASS'
            ELSE 'FAIL'
        END AS extraneous_writes,
        CASE
            WHEN e.id IS NULL THEN 'NA'
            WHEN e.rollback_status <> 'rolled_back' THEN 'NA'
            WHEN r.live_audited_count = 0
             AND cardinality(COALESCE(ra.deleted_market_signal_ids, ARRAY[]::INTEGER[])) = r.audited_count
                THEN 'PASS'
            ELSE 'FAIL'
        END AS rollback_integrity,
        CASE
            WHEN e.id IS NULL THEN 'NA'
            WHEN e.executions_for_acceptance = 1
             AND e.executions_for_acceptance_key = 1
             AND r.audited_count = r.distinct_audited_count
                THEN 'PASS'
            ELSE 'FAIL'
        END AS idempotency,
        COALESCE((a.verification_payload_snapshot ->> 'cross_model_diagnostic_only_rows')::INTEGER, 0)
            AS cross_model_diagnostic_only,
        COALESCE(flags.high_churn_flag, FALSE) AS high_churn_flag,
        COALESCE(flags.whipsaw_flag, FALSE) AS whipsaw_flag,
        COALESCE(r.audited_ids, ARRAY[]::INTEGER[]) AS audited_ids,
        COALESCE(r.live_audited_ids, ARRAY[]::INTEGER[]) AS live_audited_ids,
        COALESCE(ra.deleted_market_signal_ids, ARRAY[]::INTEGER[]) AS deleted_market_signal_ids,
        ra.deleted_market_signal_ids_hash
    FROM hedge_fund.signal_promotion_dry_run_acceptances a
    LEFT JOIN execution_base e ON e.acceptance_id = a.id
    LEFT JOIN hedge_fund.signal_shadow_review_decisions d ON d.id = a.decision_record_id
    LEFT JOIN row_rollup r ON r.execution_id = e.id
    LEFT JOIN successful_rollback_audit ra ON ra.execution_id = e.id
    LEFT JOIN evidence_flags flags ON flags.decision_id = d.id
),
classified AS (
    SELECT
        *,
        ARRAY[
            decision_link,
            verification_gate,
            execution_count_match,
            write_integrity,
            extraneous_writes,
            rollback_integrity,
            idempotency
        ] AS check_values,
        (cross_model_diagnostic_only > 0 OR high_churn_flag OR whipsaw_flag) AS has_warning
    FROM checks
)
SELECT
    execution_id,
    acceptance_id,
    candidate_id,
    CASE
        WHEN 'FAIL' = ANY(check_values) THEN 'ERROR'
        WHEN has_warning THEN 'WARNING'
        ELSE 'HEALTHY'
    END AS status,
    jsonb_build_object(
        'decision_link', decision_link,
        'verification_gate', verification_gate,
        'execution_count_match', execution_count_match,
        'write_integrity', write_integrity,
        'extraneous_writes', extraneous_writes,
        'rollback_integrity', rollback_integrity,
        'idempotency', idempotency
    ) AS checks,
    jsonb_build_object(
        'cross_model_diagnostic_only', cross_model_diagnostic_only,
        'high_churn_flag', high_churn_flag,
        'whipsaw_flag', whipsaw_flag
    ) AS warnings,
    jsonb_build_object(
        'audited_market_signal_ids', audited_ids,
        'live_audited_market_signal_ids', live_audited_ids,
        'removed_market_signal_ids', deleted_market_signal_ids,
        'removed_ids_hash', deleted_market_signal_ids_hash
    ) AS drilldown,
    CASE
        WHEN 'FAIL' = ANY(check_values) THEN 'One or more audited promotion invariants failed.'
        WHEN has_warning THEN 'Promotion audit is internally consistent with non-fatal diagnostic warnings.'
        ELSE 'Promotion audit is healthy across decision, acceptance, execution, and rollback invariants.'
    END AS explanation
FROM classified;

GRANT SELECT ON TABLE
    hedge_fund.signal_promotion_rollback_audits,
    hedge_fund.v_signal_promotion_lifecycle_timeline,
    hedge_fund.v_signal_promotion_reconciliation
TO crog_ai_app;
