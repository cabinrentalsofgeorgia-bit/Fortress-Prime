CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_alert_acknowledgements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id TEXT NOT NULL,
    execution_id UUID NOT NULL
        REFERENCES hedge_fund.signal_promotion_executions(id)
        ON DELETE RESTRICT,
    acceptance_id UUID NOT NULL
        REFERENCES hedge_fund.signal_promotion_dry_run_acceptances(id)
        ON DELETE RESTRICT,
    decision_record_id UUID NOT NULL
        REFERENCES hedge_fund.signal_shadow_review_decisions(id)
        ON DELETE RESTRICT,
    market_signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    candidate_bar_date DATE NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    operator_membership_id UUID NOT NULL
        REFERENCES hedge_fund.signal_operator_memberships(id)
        ON DELETE RESTRICT,
    acknowledged_by VARCHAR(120) NOT NULL,
    acknowledgement_status TEXT NOT NULL,
    acknowledgement_note TEXT NOT NULL,
    alert_evidence_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_signal_promotion_alert_ack_action
        CHECK (action IN ('BUY', 'SELL')),
    CONSTRAINT ck_signal_promotion_alert_ack_type
        CHECK (
            alert_type IN (
                'SIGNAL_DECAY',
                'WHIPSAW_AFTER_PROMOTION',
                'DRIFT',
                'STALE_EXECUTION_MONITORING',
                'ROLLBACK_RECOMMENDATION'
            )
        ),
    CONSTRAINT ck_signal_promotion_alert_ack_severity
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    CONSTRAINT ck_signal_promotion_alert_ack_status
        CHECK (acknowledgement_status IN ('ACKNOWLEDGED', 'WATCHING', 'NO_ACTION_NEEDED')),
    CONSTRAINT ck_signal_promotion_alert_ack_note
        CHECK (length(trim(acknowledgement_note)) >= 8)
);

CREATE INDEX IF NOT EXISTS ix_signal_promotion_alert_ack_alert_created
ON hedge_fund.signal_promotion_alert_acknowledgements (
    alert_id,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS ix_signal_promotion_alert_ack_execution_created
ON hedge_fund.signal_promotion_alert_acknowledgements (
    execution_id,
    created_at DESC
);

CREATE OR REPLACE FUNCTION hedge_fund.acknowledge_signal_promotion_alert(
    p_alert_id TEXT,
    p_operator_token_sha256 TEXT,
    p_acknowledgement_note TEXT,
    p_acknowledgement_status TEXT DEFAULT 'ACKNOWLEDGED'
)
RETURNS hedge_fund.signal_promotion_alert_acknowledgements
LANGUAGE plpgsql
-- SECURITY DEFINER is intentionally narrow: crog_ai_app gets EXECUTE on this
-- audit-only function, not direct INSERT on acknowledgement tables. The function
-- checks active operator membership and requires an existing alert_id from the
-- audited post-execution alert view before writing an acknowledgement audit row.
SECURITY DEFINER
SET search_path = pg_catalog, hedge_fund
AS $$
DECLARE
    v_operator RECORD;
    v_alert RECORD;
    v_ack hedge_fund.signal_promotion_alert_acknowledgements%ROWTYPE;
    v_status TEXT;
BEGIN
    v_status := upper(trim(COALESCE(p_acknowledgement_status, 'ACKNOWLEDGED')));

    IF v_status NOT IN ('ACKNOWLEDGED', 'WATCHING', 'NO_ACTION_NEEDED') THEN
        RAISE EXCEPTION 'Unsupported alert acknowledgement status: %', v_status;
    END IF;

    IF length(trim(COALESCE(p_acknowledgement_note, ''))) < 8 THEN
        RAISE EXCEPTION 'acknowledgement_note is required for alert acknowledgement';
    END IF;

    SELECT id, operator_label, role
    INTO v_operator
    FROM hedge_fund.signal_operator_memberships
    WHERE token_sha256 = lower(trim(COALESCE(p_operator_token_sha256, '')))
      AND is_active = TRUE
      AND role IN ('signal_operator', 'signal_admin')
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Active signal operator membership is required for alert acknowledgement';
    END IF;

    SELECT *
    INTO v_alert
    FROM hedge_fund.v_signal_promotion_post_execution_alerts
    WHERE alert_id = trim(COALESCE(p_alert_id, ''))
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No active post-execution alert found for alert_id';
    END IF;

    INSERT INTO hedge_fund.signal_promotion_alert_acknowledgements (
        alert_id,
        execution_id,
        acceptance_id,
        decision_record_id,
        market_signal_id,
        ticker,
        action,
        candidate_bar_date,
        alert_type,
        severity,
        operator_membership_id,
        acknowledged_by,
        acknowledgement_status,
        acknowledgement_note,
        alert_evidence_snapshot
    ) VALUES (
        v_alert.alert_id,
        v_alert.execution_id,
        v_alert.acceptance_id,
        v_alert.decision_record_id,
        v_alert.market_signal_id,
        v_alert.ticker,
        v_alert.action,
        v_alert.candidate_bar_date,
        v_alert.alert_type,
        v_alert.severity,
        v_operator.id,
        v_operator.operator_label,
        v_status,
        trim(p_acknowledgement_note),
        to_jsonb(v_alert)
    )
    RETURNING * INTO v_ack;

    RETURN v_ack;
END;
$$;

CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_post_execution_alerts
WITH (security_invoker = true) AS
WITH monitoring AS (
    SELECT *
    FROM hedge_fund.v_signal_promotion_post_execution_monitoring
),
signal_decay_alerts AS (
    SELECT
        md5(execution_id::TEXT || ':' || market_signal_id::TEXT || ':SIGNAL_DECAY') AS alert_id,
        execution_id,
        acceptance_id,
        decision_record_id,
        candidate_id,
        market_signal_id,
        ticker,
        action,
        candidate_bar_date,
        'SIGNAL_DECAY'::TEXT AS alert_type,
        CASE
            WHEN rollback_recommendation = 'REVIEW_ROLLBACK_WARNING' THEN 'HIGH'
            ELSE 'MEDIUM'
        END AS severity,
        'ACTIVE'::TEXT AS alert_status,
        signal_decay_date AS alert_date,
        signal_decay_score::NUMERIC AS metric_value,
        rollback_recommendation,
        monitoring_status,
        drift_status,
        jsonb_build_object(
            'rollback_marker', rollback_marker,
            'signal_decay_score', signal_decay_score,
            'signal_decay_daily_triangle', signal_decay_daily_triangle,
            'latest_candidate_score', latest_candidate_score,
            'latest_daily_triangle', latest_daily_triangle,
            'score_delta', score_delta
        ) AS evidence,
        'Candidate score or daily triangle decayed after promotion.'::TEXT AS explanation,
        'Warning only: review the audited execution; no automated rollback is performed.'::TEXT
            AS operator_guidance
    FROM monitoring
    WHERE signal_decay_flag
      AND rollback_status = 'active'
),
whipsaw_alerts AS (
    SELECT
        md5(execution_id::TEXT || ':' || market_signal_id::TEXT || ':WHIPSAW_AFTER_PROMOTION')
            AS alert_id,
        execution_id,
        acceptance_id,
        decision_record_id,
        candidate_id,
        market_signal_id,
        ticker,
        action,
        candidate_bar_date,
        'WHIPSAW_AFTER_PROMOTION'::TEXT AS alert_type,
        CASE
            WHEN rollback_recommendation = 'REVIEW_ROLLBACK_WARNING' THEN 'HIGH'
            ELSE 'MEDIUM'
        END AS severity,
        'ACTIVE'::TEXT AS alert_status,
        whipsaw_transition_date AS alert_date,
        whipsaw_to_score::NUMERIC AS metric_value,
        rollback_recommendation,
        monitoring_status,
        drift_status,
        jsonb_build_object(
            'rollback_marker', rollback_marker,
            'whipsaw_transition_date', whipsaw_transition_date,
            'whipsaw_transition_type', whipsaw_transition_type,
            'whipsaw_to_score', whipsaw_to_score
        ) AS evidence,
        'Candidate produced an opposite transition after promotion.'::TEXT AS explanation,
        'Warning only: review whipsaw context; no automatic trade or signal change is made.'::TEXT
            AS operator_guidance
    FROM monitoring
    WHERE whipsaw_after_promotion_flag
      AND rollback_status = 'active'
),
drift_alerts AS (
    SELECT
        md5(execution_id::TEXT || ':' || market_signal_id::TEXT || ':DRIFT') AS alert_id,
        execution_id,
        acceptance_id,
        decision_record_id,
        candidate_id,
        market_signal_id,
        ticker,
        action,
        candidate_bar_date,
        'DRIFT'::TEXT AS alert_type,
        CASE
            WHEN drift_status = 'PRICE_AND_SCORE_DRIFT' THEN 'HIGH'
            ELSE 'MEDIUM'
        END AS severity,
        'ACTIVE'::TEXT AS alert_status,
        COALESCE(outcome_20d_bar_date, outcome_5d_bar_date, latest_candidate_bar_date)
            AS alert_date,
        COALESCE(
            outcome_20d_directional_return,
            outcome_5d_directional_return,
            score_delta::NUMERIC
        ) AS metric_value,
        rollback_recommendation,
        monitoring_status,
        drift_status,
        jsonb_build_object(
            'rollback_marker', rollback_marker,
            'outcome_1d_directional_return', outcome_1d_directional_return,
            'outcome_5d_directional_return', outcome_5d_directional_return,
            'outcome_20d_directional_return', outcome_20d_directional_return,
            'score_delta', score_delta,
            'latest_candidate_score', latest_candidate_score
        ) AS evidence,
        'Promoted signal drifted away from candidate expectation.'::TEXT AS explanation,
        'Warning only: review candidate drift; no automatic trade or signal change is made.'::TEXT
            AS operator_guidance
    FROM monitoring
    WHERE drift_status IN ('PRICE_DRIFT', 'SCORE_DRIFT', 'PRICE_AND_SCORE_DRIFT')
      AND rollback_status = 'active'
),
stale_alerts AS (
    SELECT
        md5(execution_id::TEXT || ':' || market_signal_id::TEXT || ':STALE_EXECUTION_MONITORING')
            AS alert_id,
        execution_id,
        acceptance_id,
        decision_record_id,
        candidate_id,
        market_signal_id,
        ticker,
        action,
        candidate_bar_date,
        'STALE_EXECUTION_MONITORING'::TEXT AS alert_type,
        CASE
            WHEN executed_at < now() - INTERVAL '5 days' THEN 'MEDIUM'
            ELSE 'LOW'
        END AS severity,
        'ACTIVE'::TEXT AS alert_status,
        executed_at::DATE AS alert_date,
        EXTRACT(EPOCH FROM (now() - executed_at)) / 86400.0 AS metric_value,
        rollback_recommendation,
        monitoring_status,
        drift_status,
        jsonb_build_object(
            'rollback_marker', rollback_marker,
            'executed_at', executed_at,
            'latest_candidate_bar_date', latest_candidate_bar_date,
            'outcome_1d_bar_date', outcome_1d_bar_date,
            'market_signal_live', market_signal_live
        ) AS evidence,
        'Execution monitoring is stale: no post-promotion outcome or candidate update has arrived.'::TEXT
            AS explanation,
        'Warning only: verify data freshness; no automatic trade, signal, or rollback action is made.'::TEXT
            AS operator_guidance
    FROM monitoring
    WHERE rollback_status = 'active'
      AND market_signal_live
      AND monitoring_status = 'PENDING'
      AND executed_at < now() - INTERVAL '2 days'
      AND outcome_1d_bar_date IS NULL
      AND (
        latest_candidate_bar_date IS NULL
        OR latest_candidate_bar_date <= candidate_bar_date
      )
),
rollback_recommendation_alerts AS (
    SELECT
        md5(execution_id::TEXT || ':' || market_signal_id::TEXT || ':ROLLBACK_RECOMMENDATION')
            AS alert_id,
        execution_id,
        acceptance_id,
        decision_record_id,
        candidate_id,
        market_signal_id,
        ticker,
        action,
        candidate_bar_date,
        'ROLLBACK_RECOMMENDATION'::TEXT AS alert_type,
        CASE
            WHEN rollback_recommendation = 'REVIEW_ROLLBACK_WARNING' THEN 'HIGH'
            ELSE 'MEDIUM'
        END AS severity,
        'ACTIVE'::TEXT AS alert_status,
        COALESCE(
            whipsaw_transition_date,
            signal_decay_date,
            outcome_20d_bar_date,
            outcome_5d_bar_date,
            latest_candidate_bar_date
        ) AS alert_date,
        COALESCE(outcome_20d_directional_return, outcome_5d_directional_return)
            AS metric_value,
        rollback_recommendation,
        monitoring_status,
        drift_status,
        jsonb_build_object(
            'rollback_marker', rollback_marker,
            'rollback_recommendation', rollback_recommendation,
            'whipsaw_after_promotion_flag', whipsaw_after_promotion_flag,
            'signal_decay_flag', signal_decay_flag,
            'drift_status', drift_status
        ) AS evidence,
        'Monitoring recommends operator rollback review.'::TEXT AS explanation,
        'Warning only: this alert never calls rollback_guarded_signal_promotion and never changes trades or signals automatically.'::TEXT
            AS operator_guidance
    FROM monitoring
    WHERE rollback_recommendation IN ('WATCH_WARNING', 'REVIEW_ROLLBACK_WARNING')
      AND rollback_status = 'active'
),
alert_rows AS (
    SELECT * FROM signal_decay_alerts
    UNION ALL
    SELECT * FROM whipsaw_alerts
    UNION ALL
    SELECT * FROM drift_alerts
    UNION ALL
    SELECT * FROM stale_alerts
    UNION ALL
    SELECT * FROM rollback_recommendation_alerts
),
acknowledgement_rollup AS (
    SELECT DISTINCT ON (a.alert_id)
        a.alert_id,
        count(*) OVER (PARTITION BY a.alert_id)::INTEGER AS acknowledgement_count,
        a.acknowledgement_status AS latest_acknowledgement_status,
        a.acknowledged_by AS latest_acknowledged_by,
        a.acknowledgement_note AS latest_acknowledgement_note,
        a.created_at AS latest_acknowledged_at
    FROM hedge_fund.signal_promotion_alert_acknowledgements a
    ORDER BY a.alert_id, a.created_at DESC
)
SELECT
    r.*,
    COALESCE(a.acknowledgement_count, 0)::INTEGER AS acknowledgement_count,
    COALESCE(a.acknowledgement_count, 0) > 0 AS acknowledged,
    a.latest_acknowledgement_status,
    a.latest_acknowledged_by,
    a.latest_acknowledged_at,
    a.latest_acknowledgement_note,
    COALESCE(a.acknowledgement_count, 0) = 0
        AND r.severity IN ('HIGH', 'MEDIUM') AS acknowledgement_required
FROM alert_rows r
LEFT JOIN acknowledgement_rollup a
  ON a.alert_id = r.alert_id;

REVOKE ALL ON FUNCTION hedge_fund.acknowledge_signal_promotion_alert(TEXT, TEXT, TEXT, TEXT)
FROM PUBLIC;
REVOKE ALL ON TABLE hedge_fund.signal_promotion_alert_acknowledgements FROM PUBLIC;
REVOKE ALL ON TABLE hedge_fund.v_signal_promotion_post_execution_alerts FROM PUBLIC;

GRANT SELECT ON TABLE
    hedge_fund.signal_promotion_alert_acknowledgements,
    hedge_fund.v_signal_promotion_post_execution_alerts
TO crog_ai_app;

GRANT EXECUTE ON FUNCTION
    hedge_fund.acknowledge_signal_promotion_alert(TEXT, TEXT, TEXT, TEXT)
TO crog_ai_app;
