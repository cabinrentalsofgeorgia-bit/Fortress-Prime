CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS hedge_fund.signal_operator_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_label VARCHAR(120) NOT NULL,
    role TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_signal_operator_memberships_role
        CHECK (role IN ('signal_viewer', 'signal_operator', 'signal_admin')),
    CONSTRAINT ck_signal_operator_memberships_token_sha256
        CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_signal_operator_memberships_active_revoked
        CHECK (
            (is_active = TRUE AND revoked_at IS NULL)
            OR (is_active = FALSE)
        )
);

CREATE INDEX IF NOT EXISTS ix_signal_operator_memberships_role_active
ON hedge_fund.signal_operator_memberships (
    role,
    is_active
);

CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acceptance_id UUID NOT NULL
        REFERENCES hedge_fund.signal_promotion_dry_run_acceptances(id)
        ON DELETE RESTRICT,
    decision_record_id UUID NOT NULL
        REFERENCES hedge_fund.signal_shadow_review_decisions(id)
        ON DELETE RESTRICT,
    candidate_parameter_set VARCHAR(100) NOT NULL,
    baseline_parameter_set VARCHAR(100) NOT NULL,
    operator_membership_id UUID NOT NULL
        REFERENCES hedge_fund.signal_operator_memberships(id)
        ON DELETE RESTRICT,
    executed_by VARCHAR(120) NOT NULL,
    execution_rationale TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    dry_run_generated_at TIMESTAMPTZ NOT NULL,
    dry_run_proposed_insert_count INTEGER NOT NULL,
    verification_status TEXT NOT NULL,
    verification_payload JSONB NOT NULL,
    dry_run_payload JSONB NOT NULL,
    inserted_market_signal_ids INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    rollback_markers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    rollback_status TEXT NOT NULL DEFAULT 'active',
    rollback_operator_membership_id UUID
        REFERENCES hedge_fund.signal_operator_memberships(id)
        ON DELETE RESTRICT,
    rollback_by VARCHAR(120),
    rollback_reason TEXT,
    rolled_back_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_signal_promotion_executions_acceptance UNIQUE (acceptance_id),
    CONSTRAINT uq_signal_promotion_executions_idempotency UNIQUE (idempotency_key),
    CONSTRAINT ck_signal_promotion_executions_verification_status
        CHECK (verification_status IN ('PASS')),
    CONSTRAINT ck_signal_promotion_executions_rollback_status
        CHECK (rollback_status IN ('active', 'rolled_back')),
    CONSTRAINT ck_signal_promotion_executions_nonempty_rationale
        CHECK (length(trim(execution_rationale)) >= 12)
);

CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_execution_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL
        REFERENCES hedge_fund.signal_promotion_executions(id)
        ON DELETE CASCADE,
    market_signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence_score INTEGER NOT NULL,
    candidate_bar_date DATE NOT NULL,
    rollback_marker TEXT NOT NULL,
    row_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_signal_promotion_execution_rows_signal UNIQUE (market_signal_id),
    CONSTRAINT uq_signal_promotion_execution_rows_marker UNIQUE (execution_id, rollback_marker)
);

CREATE INDEX IF NOT EXISTS ix_signal_promotion_executions_candidate_created
ON hedge_fund.signal_promotion_executions (
    candidate_parameter_set,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS ix_signal_promotion_executions_rollback_status
ON hedge_fund.signal_promotion_executions (
    rollback_status,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS ix_signal_promotion_execution_rows_execution
ON hedge_fund.signal_promotion_execution_rows (execution_id);

CREATE OR REPLACE FUNCTION hedge_fund.execute_guarded_signal_promotion(
    p_acceptance_id UUID,
    p_operator_token_sha256 TEXT,
    p_execution_rationale TEXT,
    p_idempotency_key TEXT DEFAULT NULL
)
RETURNS hedge_fund.signal_promotion_executions
LANGUAGE plpgsql
-- SECURITY DEFINER is intentionally narrow here: crog_ai_app gets EXECUTE on
-- this function, not direct INSERT/DELETE on hedge_fund.market_signals. The
-- function re-checks human decision, accepted dry-run, verification PASS,
-- idempotency, audit creation, and rollback markers before any production write.
SECURITY DEFINER
SET search_path = pg_catalog, hedge_fund
AS $$
DECLARE
    v_operator RECORD;
    v_acceptance RECORD;
    v_existing hedge_fund.signal_promotion_executions%ROWTYPE;
    v_execution hedge_fund.signal_promotion_executions%ROWTYPE;
    v_effective_idempotency_key TEXT;
    v_verification_status TEXT;
    v_verification_payload JSONB;
    v_proposed_row_count INTEGER;
    v_inserted_market_signal_id INTEGER;
    v_inserted_market_signal_ids INTEGER[] := ARRAY[]::INTEGER[];
    v_rollback_marker TEXT;
    v_rollback_markers TEXT[] := ARRAY[]::TEXT[];
    v_execution_rows JSONB := '[]'::JSONB;
    v_row JSONB;
BEGIN
    -- No exception handler is used in this function. Any failure after
    -- market_signals insertion aborts the whole statement/transaction, so
    -- production rows cannot commit without the execution audit rows.
    v_effective_idempotency_key := COALESCE(
        NULLIF(trim(p_idempotency_key), ''),
        'acceptance:' || p_acceptance_id::TEXT
    );

    IF length(trim(COALESCE(p_execution_rationale, ''))) < 12 THEN
        RAISE EXCEPTION 'execution_rationale is required for guarded promotion execution';
    END IF;

    SELECT id, operator_label, role
    INTO v_operator
    FROM hedge_fund.signal_operator_memberships
    WHERE token_sha256 = lower(trim(COALESCE(p_operator_token_sha256, '')))
      AND is_active = TRUE
      AND role IN ('signal_operator', 'signal_admin')
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Active signal operator membership is required for guarded promotion execution';
    END IF;

    SELECT
        a.*,
        d.decision AS shadow_decision
    INTO v_acceptance
    FROM hedge_fund.signal_promotion_dry_run_acceptances a
    JOIN hedge_fund.signal_shadow_review_decisions d
      ON d.id = a.decision_record_id
    WHERE a.id = p_acceptance_id
    FOR UPDATE OF a;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No dry-run acceptance exists for guarded promotion execution';
    END IF;

    IF v_acceptance.shadow_decision <> 'promote_to_market_signals' THEN
        RAISE EXCEPTION 'Human promote_to_market_signals decision is required before execution';
    END IF;

    SELECT *
    INTO v_existing
    FROM hedge_fund.signal_promotion_executions
    WHERE idempotency_key = v_effective_idempotency_key
    LIMIT 1;

    IF v_existing.id IS NOT NULL THEN
        IF v_existing.acceptance_id <> p_acceptance_id THEN
            RAISE EXCEPTION 'Idempotency key is already attached to another promotion execution';
        END IF;
        RETURN v_existing;
    END IF;

    SELECT *
    INTO v_existing
    FROM hedge_fund.signal_promotion_executions
    WHERE acceptance_id = p_acceptance_id
    LIMIT 1;

    IF v_existing.id IS NOT NULL THEN
        RAISE EXCEPTION 'Dry-run acceptance has already been executed';
    END IF;

    SELECT
        MAX(v.overall_status),
        COALESCE(jsonb_agg(to_jsonb(v)), '[]'::JSONB)
    INTO v_verification_status, v_verification_payload
    FROM hedge_fund.verify_promotion_dry_run(
        v_acceptance.candidate_parameter_set,
        v_acceptance.baseline_parameter_set
    ) v;

    IF v_verification_status IS DISTINCT FROM 'PASS' THEN
        RAISE EXCEPTION 'Promotion verification gate blocked execution: %',
            COALESCE(v_verification_status, 'INCONCLUSIVE');
    END IF;

    IF v_acceptance.target_table <> 'hedge_fund.market_signals' THEN
        RAISE EXCEPTION 'Dry-run acceptance target table is not hedge_fund.market_signals';
    END IF;

    v_proposed_row_count := jsonb_array_length(
        COALESCE(v_acceptance.dry_run_payload -> 'proposed_rows', '[]'::JSONB)
    );

    IF v_proposed_row_count < 1 THEN
        RAISE EXCEPTION 'Dry-run acceptance has no market_signals rows to execute';
    END IF;

    IF v_proposed_row_count <> v_acceptance.dry_run_proposed_insert_count THEN
        RAISE EXCEPTION 'Dry-run acceptance payload count does not match accepted summary';
    END IF;

    FOR v_row IN
        SELECT value
        FROM jsonb_array_elements(v_acceptance.dry_run_payload -> 'proposed_rows')
    LOOP
        v_rollback_marker := v_row #>> '{lineage,rollback_marker}';
        IF v_rollback_marker IS NULL OR length(trim(v_rollback_marker)) = 0 THEN
            RAISE EXCEPTION 'Every promotion row requires a rollback marker';
        END IF;

        INSERT INTO hedge_fund.market_signals (
            ticker,
            signal_type,
            action,
            confidence_score,
            price_target,
            source_sender,
            source_subject,
            raw_reasoning,
            model_used,
            extracted_at
        ) VALUES (
            v_row ->> 'ticker',
            v_row ->> 'signal_type',
            v_row ->> 'action',
            (v_row ->> 'confidence_score')::INTEGER,
            NULLIF(v_row ->> 'price_target', '')::NUMERIC,
            v_row ->> 'source_sender',
            v_row ->> 'source_subject',
            CONCAT(
                COALESCE(v_row ->> 'raw_reasoning', ''),
                E'\nRollback marker: ',
                v_rollback_marker
            ),
            v_row ->> 'model_used',
            ((v_row ->> 'extracted_at')::TIMESTAMPTZ AT TIME ZONE 'UTC')
        )
        RETURNING id INTO v_inserted_market_signal_id;

        v_inserted_market_signal_ids :=
            array_append(v_inserted_market_signal_ids, v_inserted_market_signal_id);
        v_rollback_markers := array_append(v_rollback_markers, v_rollback_marker);
        v_execution_rows := v_execution_rows || jsonb_build_array(
            jsonb_build_object(
                'market_signal_id', v_inserted_market_signal_id,
                'ticker', v_row ->> 'ticker',
                'action', v_row ->> 'action',
                'confidence_score', (v_row ->> 'confidence_score')::INTEGER,
                'candidate_bar_date', v_row ->> 'candidate_bar_date',
                'rollback_marker', v_rollback_marker,
                'row_payload', v_row
            )
        );
    END LOOP;

    INSERT INTO hedge_fund.signal_promotion_executions (
        acceptance_id,
        decision_record_id,
        candidate_parameter_set,
        baseline_parameter_set,
        operator_membership_id,
        executed_by,
        execution_rationale,
        idempotency_key,
        dry_run_generated_at,
        dry_run_proposed_insert_count,
        verification_status,
        verification_payload,
        dry_run_payload,
        inserted_market_signal_ids,
        rollback_markers
    ) VALUES (
        v_acceptance.id,
        v_acceptance.decision_record_id,
        v_acceptance.candidate_parameter_set,
        v_acceptance.baseline_parameter_set,
        v_operator.id,
        v_operator.operator_label,
        trim(p_execution_rationale),
        v_effective_idempotency_key,
        v_acceptance.dry_run_generated_at,
        v_acceptance.dry_run_proposed_insert_count,
        v_verification_status,
        v_verification_payload,
        v_acceptance.dry_run_payload,
        v_inserted_market_signal_ids,
        v_rollback_markers
    )
    RETURNING * INTO v_execution;

    INSERT INTO hedge_fund.signal_promotion_execution_rows (
        execution_id,
        market_signal_id,
        ticker,
        action,
        confidence_score,
        candidate_bar_date,
        rollback_marker,
        row_payload
    )
    SELECT
        v_execution.id,
        row_data.market_signal_id,
        row_data.ticker,
        row_data.action,
        row_data.confidence_score,
        row_data.candidate_bar_date,
        row_data.rollback_marker,
        row_data.row_payload
    FROM jsonb_to_recordset(v_execution_rows) AS row_data (
        market_signal_id INTEGER,
        ticker TEXT,
        action TEXT,
        confidence_score INTEGER,
        candidate_bar_date DATE,
        rollback_marker TEXT,
        row_payload JSONB
    );

    RETURN v_execution;
END;
$$;

CREATE OR REPLACE FUNCTION hedge_fund.rollback_guarded_signal_promotion(
    p_execution_id UUID,
    p_operator_token_sha256 TEXT,
    p_rollback_reason TEXT
)
RETURNS hedge_fund.signal_promotion_executions
LANGUAGE plpgsql
-- Rollback is scoped exclusively to IDs captured in the execution audit row.
-- It never deletes by ticker, date, action, or candidate parameter set.
SECURITY DEFINER
SET search_path = pg_catalog, hedge_fund
AS $$
DECLARE
    v_operator RECORD;
    v_execution hedge_fund.signal_promotion_executions%ROWTYPE;
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

    IF v_execution.rollback_status = 'rolled_back' THEN
        RETURN v_execution;
    END IF;

    DELETE FROM hedge_fund.market_signals
    WHERE id = ANY(v_execution.inserted_market_signal_ids);

    UPDATE hedge_fund.signal_promotion_executions
    SET rollback_status = 'rolled_back',
        rollback_operator_membership_id = v_operator.id,
        rollback_by = v_operator.operator_label,
        rollback_reason = trim(p_rollback_reason),
        rolled_back_at = now()
    WHERE id = p_execution_id
    RETURNING * INTO v_execution;

    RETURN v_execution;
END;
$$;

REVOKE ALL ON FUNCTION hedge_fund.execute_guarded_signal_promotion(UUID, TEXT, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION hedge_fund.rollback_guarded_signal_promotion(UUID, TEXT, TEXT) FROM PUBLIC;

GRANT SELECT ON TABLE
    hedge_fund.signal_promotion_executions,
    hedge_fund.signal_promotion_execution_rows
TO crog_ai_app;

GRANT EXECUTE ON FUNCTION
    hedge_fund.execute_guarded_signal_promotion(UUID, TEXT, TEXT, TEXT),
    hedge_fund.rollback_guarded_signal_promotion(UUID, TEXT, TEXT)
TO crog_ai_app;
