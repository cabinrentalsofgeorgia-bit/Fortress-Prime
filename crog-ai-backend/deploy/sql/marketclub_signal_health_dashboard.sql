CREATE OR REPLACE VIEW hedge_fund.v_signal_health_active_promotions
WITH (security_invoker = true) AS
WITH execution_rollup AS (
    SELECT
        execution_id,
        acceptance_id,
        candidate_id,
        baseline_parameter_set,
        executed_by,
        executed_at,
        rollback_status,
        count(*)::INTEGER AS inserted_count,
        count(*) FILTER (WHERE market_signal_live)::INTEGER AS live_signal_count,
        count(*) FILTER (WHERE monitoring_status = 'WARNING')::INTEGER AS warning_signal_count,
        count(*) FILTER (
            WHERE drift_status IN ('PRICE_DRIFT', 'SCORE_DRIFT', 'PRICE_AND_SCORE_DRIFT')
        )::INTEGER AS drift_signal_count,
        count(*) FILTER (WHERE whipsaw_after_promotion_flag)::INTEGER AS whipsaw_signal_count,
        count(*) FILTER (WHERE signal_decay_flag)::INTEGER AS decay_signal_count,
        count(*) FILTER (
            WHERE rollback_recommendation = 'REVIEW_ROLLBACK_WARNING'
        )::INTEGER AS rollback_review_count,
        avg(outcome_1d_directional_return) AS avg_1d_return,
        avg(outcome_5d_directional_return) AS avg_5d_return,
        avg(outcome_20d_directional_return) AS avg_20d_return,
        (
            count(*) FILTER (WHERE outcome_1d_directional_return > 0)::NUMERIC
            / NULLIF(count(*) FILTER (WHERE outcome_1d_directional_return IS NOT NULL), 0)
        ) AS positive_1d_pct,
        (
            count(*) FILTER (WHERE outcome_5d_directional_return > 0)::NUMERIC
            / NULLIF(count(*) FILTER (WHERE outcome_5d_directional_return IS NOT NULL), 0)
        ) AS positive_5d_pct,
        (
            count(*) FILTER (WHERE outcome_20d_directional_return > 0)::NUMERIC
            / NULLIF(count(*) FILTER (WHERE outcome_20d_directional_return IS NOT NULL), 0)
        ) AS positive_20d_pct,
        (
            count(*) FILTER (WHERE whipsaw_after_promotion_flag)::NUMERIC
            / NULLIF(count(*), 0)
        ) AS whipsaw_pct
    FROM hedge_fund.v_signal_promotion_post_execution_monitoring
    GROUP BY
        execution_id,
        acceptance_id,
        candidate_id,
        baseline_parameter_set,
        executed_by,
        executed_at,
        rollback_status
)
SELECT
    *,
    CASE
        WHEN rollback_review_count > 0 THEN 'DEGRADED'
        WHEN rollback_status = 'active'
         AND (
            (whipsaw_signal_count > 0 AND decay_signal_count > 0)
            OR avg_5d_return < -0.02
            OR avg_20d_return < -0.03
         ) THEN 'DEGRADED'
        WHEN warning_signal_count > 0
          OR drift_signal_count > 0
          OR whipsaw_signal_count > 0
          OR decay_signal_count > 0 THEN 'WARNING'
        ELSE 'HEALTHY'
    END AS health_status,
    jsonb_build_object(
        'drift', drift_signal_count > 0,
        'whipsaw', whipsaw_signal_count > 0,
        'decay', decay_signal_count > 0
    ) AS key_flags,
    CASE
        WHEN rollback_review_count > 0
            THEN 'Rollback review warning is present; operator review only.'
        WHEN whipsaw_signal_count > 0 AND decay_signal_count > 0
            THEN 'Promotion has both whipsaw and signal decay flags; watch closely.'
        WHEN avg_5d_return < -0.02 OR avg_20d_return < -0.03
            THEN 'Outcome returns are below the monitored expected band.'
        WHEN warning_signal_count > 0
            THEN 'Promotion has warning rows in post-execution monitoring.'
        ELSE 'Latest audited promotion outcome is in line with monitored expectations.'
    END AS explanation
FROM execution_rollup;

CREATE OR REPLACE VIEW hedge_fund.v_signal_health_at_risk_signals
WITH (security_invoker = true) AS
SELECT
    execution_id,
    acceptance_id,
    decision_record_id,
    candidate_id,
    market_signal_id,
    ticker,
    action,
    candidate_bar_date,
    candidate_score,
    rollback_marker,
    outcome_5d_directional_return,
    outcome_20d_directional_return,
    drift_status,
    whipsaw_after_promotion_flag,
    signal_decay_flag,
    rollback_recommendation,
    monitoring_status,
    (
        CASE WHEN whipsaw_after_promotion_flag THEN 50 ELSE 0 END
        + CASE WHEN outcome_5d_directional_return < -0.02 THEN 30 ELSE 0 END
        + CASE
            WHEN drift_status = 'PRICE_AND_SCORE_DRIFT' THEN 25
            WHEN drift_status IN ('PRICE_DRIFT', 'SCORE_DRIFT') THEN 15
            ELSE 0
          END
    )::INTEGER AS risk_score,
    CASE
        WHEN whipsaw_after_promotion_flag
            THEN 'whipsaw-after-promotion'
        WHEN outcome_5d_directional_return < -0.02
            THEN '5d return below threshold'
        ELSE 'drift vs expected range'
    END AS risk_reason,
    explanation
FROM hedge_fund.v_signal_promotion_post_execution_monitoring
WHERE rollback_status = 'active'
  AND market_signal_live
  AND (
    whipsaw_after_promotion_flag
    OR outcome_5d_directional_return < -0.02
    OR drift_status IN ('PRICE_DRIFT', 'SCORE_DRIFT', 'PRICE_AND_SCORE_DRIFT')
  );

CREATE OR REPLACE VIEW hedge_fund.v_signal_health_execution_outcomes
WITH (security_invoker = true) AS
SELECT
    execution_id,
    acceptance_id,
    candidate_id,
    baseline_parameter_set,
    executed_by,
    executed_at,
    rollback_status,
    inserted_count,
    avg_1d_return,
    avg_5d_return,
    avg_20d_return,
    positive_1d_pct,
    positive_5d_pct,
    positive_20d_pct,
    whipsaw_pct,
    health_status,
    key_flags
FROM hedge_fund.v_signal_health_active_promotions;

CREATE OR REPLACE FUNCTION hedge_fund.signal_health_model_divergence(
    candidate_parameter_set TEXT DEFAULT 'dochia_v0_2_range_daily',
    production_parameter_set TEXT DEFAULT 'dochia_v0_estimated',
    lookback_bars INTEGER DEFAULT 30
)
RETURNS TABLE (
    bar_date DATE,
    candidate_80_count INTEGER,
    production_matching_80_count INTEGER,
    divergence_count INTEGER,
    divergence_rate NUMERIC,
    divergent_tickers TEXT[]
)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, hedge_fund
AS $$
WITH candidate_bar_dates AS (
    SELECT DISTINCT v.bar_date
    FROM hedge_fund.v_signal_scores_composite v
    WHERE v.parameter_set_name = candidate_parameter_set
    ORDER BY v.bar_date DESC
    LIMIT GREATEST(1, COALESCE(lookback_bars, 30))
),
candidate AS (
    SELECT
        v.ticker,
        v.bar_date,
        v.composite_score
    FROM hedge_fund.v_signal_scores_composite v
    JOIN candidate_bar_dates b
      ON b.bar_date = v.bar_date
    WHERE v.parameter_set_name = candidate_parameter_set
      AND v.composite_score = 80
),
joined AS (
    SELECT
        c.ticker,
        c.bar_date,
        p.composite_score AS production_score
    FROM candidate c
    LEFT JOIN hedge_fund.v_signal_scores_composite p
      ON p.ticker = c.ticker
     AND p.bar_date = c.bar_date
     AND p.parameter_set_name = production_parameter_set
)
SELECT
    j.bar_date,
    count(*)::INTEGER AS candidate_80_count,
    count(*) FILTER (WHERE j.production_score = 80)::INTEGER
        AS production_matching_80_count,
    count(*) FILTER (WHERE j.production_score IS DISTINCT FROM 80)::INTEGER
        AS divergence_count,
    (
        count(*) FILTER (WHERE j.production_score IS DISTINCT FROM 80)::NUMERIC
        / NULLIF(count(*), 0)
    ) AS divergence_rate,
    COALESCE(
        array_agg(j.ticker ORDER BY j.ticker)
            FILTER (WHERE j.production_score IS DISTINCT FROM 80),
        ARRAY[]::TEXT[]
    ) AS divergent_tickers
FROM joined j
GROUP BY j.bar_date
ORDER BY j.bar_date DESC;
$$;

REVOKE ALL ON TABLE hedge_fund.v_signal_health_active_promotions FROM PUBLIC;
REVOKE ALL ON TABLE hedge_fund.v_signal_health_at_risk_signals FROM PUBLIC;
REVOKE ALL ON TABLE hedge_fund.v_signal_health_execution_outcomes FROM PUBLIC;
REVOKE ALL ON FUNCTION hedge_fund.signal_health_model_divergence(TEXT, TEXT, INTEGER)
FROM PUBLIC;

GRANT SELECT ON TABLE
    hedge_fund.v_signal_health_active_promotions,
    hedge_fund.v_signal_health_at_risk_signals,
    hedge_fund.v_signal_health_execution_outcomes
TO crog_ai_app;

GRANT EXECUTE ON FUNCTION
    hedge_fund.signal_health_model_divergence(TEXT, TEXT, INTEGER)
TO crog_ai_app;
