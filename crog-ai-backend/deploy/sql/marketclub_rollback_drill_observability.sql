CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_rollback_drill
WITH (security_invoker = true) AS
WITH audited_rows AS (
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
        r.market_signal_id AS audited_market_signal_id,
        ms.id AS live_market_signal_id
    FROM hedge_fund.signal_promotion_executions e
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
        rollback_markers
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
    CASE
        WHEN rollback_status = 'rolled_back' THEN 'ALREADY_ROLLED_BACK'
        WHEN cardinality(audited_market_signal_ids) = 0 THEN 'NOT_ELIGIBLE_NO_AUDITED_ROWS'
        WHEN cardinality(rollback_preview_market_signal_ids) = 0 THEN 'NOT_ELIGIBLE_NO_LIVE_AUDITED_ROWS'
        WHEN cardinality(rollback_preview_market_signal_ids) < cardinality(audited_market_signal_ids)
            THEN 'ELIGIBLE_PARTIAL_AUDITED_ROWS'
        ELSE 'ELIGIBLE'
    END AS rollback_eligibility,
    rollback_status = 'rolled_back' AS already_rolled_back,
    rollback_status,
    rollback_by,
    rolled_back_at AS rollback_attempted_at,
    rolled_back_at
FROM rollup;

REVOKE ALL ON TABLE hedge_fund.v_signal_promotion_rollback_drill FROM PUBLIC;
GRANT SELECT ON TABLE hedge_fund.v_signal_promotion_rollback_drill TO crog_ai_app;
