CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_rollback_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL
        REFERENCES hedge_fund.signal_promotion_executions(id)
        ON DELETE RESTRICT,
    operator_membership_id UUID NOT NULL
        REFERENCES hedge_fund.signal_operator_memberships(id)
        ON DELETE RESTRICT,
    rollback_by VARCHAR(120) NOT NULL,
    rollback_reason TEXT NOT NULL,
    rollback_status TEXT NOT NULL,
    deleted_market_signal_ids INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    deleted_market_signal_ids_hash TEXT,
    rollback_marker_count INTEGER NOT NULL DEFAULT 0,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_signal_promotion_rollback_audits_status
        CHECK (rollback_status IN ('rolled_back', 'already_rolled_back')),
    CONSTRAINT ck_signal_promotion_rollback_audits_nonempty_reason
        CHECK (length(trim(rollback_reason)) >= 12)
);

CREATE INDEX IF NOT EXISTS ix_signal_promotion_rollback_audits_execution_attempted
ON hedge_fund.signal_promotion_rollback_audits (
    execution_id,
    attempted_at DESC
);

CREATE OR REPLACE FUNCTION hedge_fund.rollback_guarded_signal_promotion(
    p_execution_id UUID,
    p_operator_token_sha256 TEXT,
    p_rollback_reason TEXT
)
RETURNS hedge_fund.signal_promotion_executions
LANGUAGE plpgsql
-- Rollback is scoped exclusively to execution-row audit IDs.
-- It never deletes by ticker, date, action, rollback marker, or parameter set.
SECURITY DEFINER
SET search_path = pg_catalog, hedge_fund
AS $$
DECLARE
    v_operator RECORD;
    v_execution hedge_fund.signal_promotion_executions%ROWTYPE;
    v_audited_market_signal_ids INTEGER[] := ARRAY[]::INTEGER[];
    v_deleted_market_signal_ids INTEGER[] := ARRAY[]::INTEGER[];
BEGIN
    IF length(trim(COALESCE(p_rollback_reason, ''))) < 12 THEN
        RAISE EXCEPTION 'rollback_reason is required for guarded promotion rollback';
    END IF;

    SELECT id, operator_label, role
    INTO v_operator
    FROM hedge_fund.signal_operator_memberships
    WHERE token_sha256 = lower(trim(COALESCE(p_operator_token_sha256, '')))
      AND is_active = TRUE
      AND role = 'signal_admin'
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Active signal admin membership is required for guarded promotion rollback';
    END IF;

    SELECT *
    INTO v_execution
    FROM hedge_fund.signal_promotion_executions
    WHERE id = p_execution_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No guarded promotion execution found for rollback';
    END IF;

    SELECT COALESCE(array_agg(r.market_signal_id ORDER BY r.market_signal_id), ARRAY[]::INTEGER[])
    INTO v_audited_market_signal_ids
    FROM hedge_fund.signal_promotion_execution_rows r
    WHERE r.execution_id = v_execution.id;

    IF cardinality(v_audited_market_signal_ids) = 0 THEN
        RAISE EXCEPTION 'Guarded rollback requires audited market_signal rows for execution_id';
    END IF;

    IF v_execution.rollback_status = 'rolled_back' THEN
        INSERT INTO hedge_fund.signal_promotion_rollback_audits (
            execution_id,
            operator_membership_id,
            rollback_by,
            rollback_reason,
            rollback_status,
            deleted_market_signal_ids,
            deleted_market_signal_ids_hash,
            rollback_marker_count,
            completed_at
        ) VALUES (
            v_execution.id,
            v_operator.id,
            v_operator.operator_label,
            trim(p_rollback_reason),
            'already_rolled_back',
            ARRAY[]::INTEGER[],
            md5(''),
            cardinality(v_execution.rollback_markers),
            now()
        );
        RETURN v_execution;
    END IF;

    WITH deleted AS (
        DELETE FROM hedge_fund.market_signals ms
        USING hedge_fund.signal_promotion_execution_rows r
        WHERE r.execution_id = v_execution.id
          AND ms.id = r.market_signal_id
        RETURNING ms.id
    )
    SELECT COALESCE(array_agg(id ORDER BY id), ARRAY[]::INTEGER[])
    INTO v_deleted_market_signal_ids
    FROM deleted;

    IF cardinality(v_deleted_market_signal_ids) <> cardinality(v_audited_market_signal_ids) THEN
        RAISE EXCEPTION 'Guarded rollback requires all audited market_signal rows to still be live';
    END IF;

    UPDATE hedge_fund.signal_promotion_executions
    SET rollback_status = 'rolled_back',
        rollback_operator_membership_id = v_operator.id,
        rollback_by = v_operator.operator_label,
        rollback_reason = trim(p_rollback_reason),
        rolled_back_at = now()
    WHERE id = p_execution_id
    RETURNING * INTO v_execution;

    INSERT INTO hedge_fund.signal_promotion_rollback_audits (
        execution_id,
        operator_membership_id,
        rollback_by,
        rollback_reason,
        rollback_status,
        deleted_market_signal_ids,
        deleted_market_signal_ids_hash,
        rollback_marker_count,
        completed_at
    ) VALUES (
        v_execution.id,
        v_operator.id,
        v_operator.operator_label,
        trim(p_rollback_reason),
        'rolled_back',
        v_deleted_market_signal_ids,
        md5(array_to_string(v_deleted_market_signal_ids, ',')),
        cardinality(v_execution.rollback_markers),
        v_execution.rolled_back_at
    );

    RETURN v_execution;
END;
$$;

CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_rollback_drill
WITH (security_invoker = true) AS
WITH latest_rollback_audit AS (
    SELECT DISTINCT ON (a.execution_id)
        a.execution_id,
        a.rollback_status AS audit_rollback_status,
        a.attempted_at,
        a.completed_at
    FROM hedge_fund.signal_promotion_rollback_audits a
    ORDER BY a.execution_id, a.attempted_at DESC
),
audited_rows AS (
    SELECT
        e.id AS execution_id,
        e.acceptance_id AS dry_run_acceptance_id,
        e.candidate_parameter_set,
        e.baseline_parameter_set,
        e.executed_by,
        e.rollback_status,
        e.rollback_by,
        e.rolled_back_at,
        e.created_at AS executed_at,
        e.inserted_market_signal_ids,
        e.rollback_markers,
        a.attempted_at AS audit_attempted_at,
        a.completed_at AS audit_completed_at,
        r.market_signal_id AS audited_market_signal_id,
        ms.id AS live_market_signal_id
    FROM hedge_fund.signal_promotion_executions e
    LEFT JOIN latest_rollback_audit a
      ON a.execution_id = e.id
    LEFT JOIN hedge_fund.signal_promotion_execution_rows r
      ON r.execution_id = e.id
    LEFT JOIN hedge_fund.market_signals ms
      ON ms.id = r.market_signal_id
),
rollup AS (
    SELECT
        execution_id,
        dry_run_acceptance_id,
        candidate_parameter_set,
        baseline_parameter_set,
        executed_by,
        rollback_status,
        rollback_by,
        rolled_back_at,
        executed_at,
        inserted_market_signal_ids,
        rollback_markers,
        audit_attempted_at,
        audit_completed_at,
        COALESCE(
            array_agg(audited_market_signal_id ORDER BY audited_market_signal_id)
                FILTER (WHERE audited_market_signal_id IS NOT NULL),
            ARRAY[]::INTEGER[]
        ) AS audited_market_signal_ids,
        COALESCE(
            array_agg(live_market_signal_id ORDER BY live_market_signal_id)
                FILTER (WHERE live_market_signal_id IS NOT NULL),
            ARRAY[]::INTEGER[]
        ) AS rollback_preview_market_signal_ids
    FROM audited_rows
    GROUP BY
        execution_id,
        dry_run_acceptance_id,
        candidate_parameter_set,
        baseline_parameter_set,
        executed_by,
        rollback_status,
        rollback_by,
        rolled_back_at,
        executed_at,
        inserted_market_signal_ids,
        rollback_markers,
        audit_attempted_at,
        audit_completed_at
),
eligibility AS (
    SELECT
        *,
        CASE
            WHEN rollback_status = 'rolled_back' THEN 'ALREADY_ROLLED_BACK'
            WHEN cardinality(audited_market_signal_ids) = 0 THEN 'NOT_ELIGIBLE_NO_AUDITED_ROWS'
            WHEN cardinality(rollback_preview_market_signal_ids) = 0 THEN 'NOT_ELIGIBLE_NO_LIVE_AUDITED_ROWS'
            WHEN cardinality(rollback_preview_market_signal_ids) < cardinality(audited_market_signal_ids)
                THEN 'ELIGIBLE_PARTIAL_AUDITED_ROWS'
            ELSE 'ELIGIBLE'
        END AS rollback_eligibility
    FROM rollup
)
SELECT
    execution_id,
    dry_run_acceptance_id,
    candidate_parameter_set,
    baseline_parameter_set,
    executed_by,
    executed_at,
    inserted_market_signal_ids,
    rollback_markers,
    audited_market_signal_ids,
    rollback_preview_market_signal_ids,
    cardinality(rollback_preview_market_signal_ids)::INTEGER AS rollback_preview_count,
    rollback_eligibility,
    rollback_eligibility = 'ELIGIBLE' AS rollback_eligible,
    rollback_status = 'rolled_back' AS already_rolled_back,
    rollback_status,
    rollback_by,
    audit_attempted_at AS rollback_attempted_at,
    COALESCE(audit_completed_at, rolled_back_at) AS rolled_back_at
FROM eligibility;

REVOKE ALL ON FUNCTION hedge_fund.rollback_guarded_signal_promotion(UUID, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON TABLE hedge_fund.signal_promotion_rollback_audits FROM PUBLIC;
REVOKE ALL ON TABLE hedge_fund.v_signal_promotion_rollback_drill FROM PUBLIC;

GRANT SELECT ON TABLE
    hedge_fund.signal_promotion_rollback_audits,
    hedge_fund.v_signal_promotion_rollback_drill
TO crog_ai_app;
GRANT EXECUTE ON FUNCTION hedge_fund.rollback_guarded_signal_promotion(UUID, TEXT, TEXT) TO crog_ai_app;
