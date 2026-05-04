CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_post_execution_monitoring
WITH (security_invoker = true) AS
WITH audited_promotions AS (
    SELECT
        e.id AS execution_id,
        e.acceptance_id,
        e.decision_record_id,
        e.candidate_parameter_set AS candidate_id,
        e.baseline_parameter_set,
        e.executed_by,
        e.created_at AS executed_at,
        e.rollback_status,
        r.market_signal_id,
        r.ticker,
        r.action,
        r.confidence_score,
        r.candidate_bar_date,
        r.rollback_marker,
        r.row_payload,
        (r.row_payload ->> 'composite_score')::INTEGER AS candidate_score,
        (r.row_payload #>> '{lineage,explanation_payload,states,monthly}')::INTEGER
            AS candidate_monthly_triangle,
        (r.row_payload #>> '{lineage,explanation_payload,states,weekly}')::INTEGER
            AS candidate_weekly_triangle,
        (r.row_payload #>> '{lineage,explanation_payload,states,daily}')::INTEGER
            AS candidate_daily_triangle,
        ms.id IS NOT NULL AS market_signal_live
    FROM hedge_fund.signal_promotion_executions e
    JOIN hedge_fund.signal_promotion_execution_rows r
      ON r.execution_id = e.id
    LEFT JOIN hedge_fund.market_signals ms
      ON ms.id = r.market_signal_id
),
future_bars AS (
    SELECT
        a.execution_id,
        a.market_signal_id,
        b.bar_date,
        b.close,
        row_number() OVER (
            PARTITION BY a.execution_id, a.market_signal_id
            ORDER BY b.bar_date
        ) AS sessions_after_promotion
    FROM audited_promotions a
    JOIN hedge_fund.eod_bars b
      ON b.ticker = a.ticker
     AND b.bar_date > a.candidate_bar_date
),
bar_rollup AS (
    SELECT
        a.execution_id,
        a.market_signal_id,
        entry.close AS entry_close,
        MAX(f.bar_date) FILTER (WHERE f.sessions_after_promotion = 1) AS outcome_1d_bar_date,
        MAX(f.close) FILTER (WHERE f.sessions_after_promotion = 1) AS outcome_1d_close,
        MAX(f.bar_date) FILTER (WHERE f.sessions_after_promotion = 5) AS outcome_5d_bar_date,
        MAX(f.close) FILTER (WHERE f.sessions_after_promotion = 5) AS outcome_5d_close,
        MAX(f.bar_date) FILTER (WHERE f.sessions_after_promotion = 20) AS outcome_20d_bar_date,
        MAX(f.close) FILTER (WHERE f.sessions_after_promotion = 20) AS outcome_20d_close
    FROM audited_promotions a
    LEFT JOIN hedge_fund.eod_bars entry
      ON entry.ticker = a.ticker
     AND entry.bar_date = a.candidate_bar_date
    LEFT JOIN future_bars f
      ON f.execution_id = a.execution_id
     AND f.market_signal_id = a.market_signal_id
    GROUP BY a.execution_id, a.market_signal_id, entry.close
),
latest_candidate_state AS (
    SELECT DISTINCT ON (a.execution_id, a.market_signal_id)
        a.execution_id,
        a.market_signal_id,
        v.bar_date AS latest_candidate_bar_date,
        v.composite_score AS latest_candidate_score,
        v.monthly_state AS latest_monthly_triangle,
        v.weekly_state AS latest_weekly_triangle,
        v.daily_state AS latest_daily_triangle
    FROM audited_promotions a
    JOIN hedge_fund.v_signal_scores_composite v
      ON v.ticker = a.ticker
     AND v.parameter_set_name = a.candidate_id
     AND v.bar_date >= a.candidate_bar_date
    ORDER BY a.execution_id, a.market_signal_id, v.bar_date DESC, v.computed_at DESC
),
first_decay AS (
    SELECT DISTINCT ON (a.execution_id, a.market_signal_id)
        a.execution_id,
        a.market_signal_id,
        v.bar_date AS signal_decay_date,
        v.composite_score AS signal_decay_score,
        v.daily_state AS signal_decay_daily_triangle
    FROM audited_promotions a
    JOIN hedge_fund.v_signal_scores_composite v
      ON v.ticker = a.ticker
     AND v.parameter_set_name = a.candidate_id
     AND v.bar_date > a.candidate_bar_date
    WHERE (
        a.action = 'BUY'
        AND (v.composite_score < 50 OR v.daily_state <> 1)
    ) OR (
        a.action = 'SELL'
        AND (v.composite_score > -50 OR v.daily_state <> -1)
    )
    ORDER BY a.execution_id, a.market_signal_id, v.bar_date ASC, v.computed_at ASC
),
first_whipsaw AS (
    SELECT DISTINCT ON (a.execution_id, a.market_signal_id)
        a.execution_id,
        a.market_signal_id,
        t.to_bar_date AS whipsaw_transition_date,
        t.transition_type AS whipsaw_transition_type,
        t.to_score AS whipsaw_to_score
    FROM audited_promotions a
    JOIN hedge_fund.scoring_parameters p
      ON p.name = a.candidate_id
    JOIN hedge_fund.signal_transitions t
      ON t.ticker = a.ticker
     AND t.parameter_set_id = p.id
     AND t.to_bar_date > a.candidate_bar_date
    LEFT JOIN bar_rollup b
      ON b.execution_id = a.execution_id
     AND b.market_signal_id = a.market_signal_id
    WHERE t.to_bar_date <= COALESCE(b.outcome_5d_bar_date, a.candidate_bar_date + 10)
      AND (
        (a.action = 'BUY' AND (t.to_score < 0 OR (t.to_states ->> 'daily')::INTEGER = -1))
        OR
        (a.action = 'SELL' AND (t.to_score > 0 OR (t.to_states ->> 'daily')::INTEGER = 1))
      )
    ORDER BY a.execution_id, a.market_signal_id, t.to_bar_date ASC, t.detected_at ASC
),
monitored AS (
    SELECT
        a.*,
        b.entry_close,
        b.outcome_1d_bar_date,
        b.outcome_1d_close,
        CASE
            WHEN b.entry_close IS NULL OR b.entry_close = 0 OR b.outcome_1d_close IS NULL THEN NULL
            WHEN a.action = 'BUY' THEN (b.outcome_1d_close - b.entry_close) / b.entry_close
            ELSE (b.entry_close - b.outcome_1d_close) / b.entry_close
        END AS outcome_1d_directional_return,
        b.outcome_5d_bar_date,
        b.outcome_5d_close,
        CASE
            WHEN b.entry_close IS NULL OR b.entry_close = 0 OR b.outcome_5d_close IS NULL THEN NULL
            WHEN a.action = 'BUY' THEN (b.outcome_5d_close - b.entry_close) / b.entry_close
            ELSE (b.entry_close - b.outcome_5d_close) / b.entry_close
        END AS outcome_5d_directional_return,
        b.outcome_20d_bar_date,
        b.outcome_20d_close,
        CASE
            WHEN b.entry_close IS NULL OR b.entry_close = 0 OR b.outcome_20d_close IS NULL THEN NULL
            WHEN a.action = 'BUY' THEN (b.outcome_20d_close - b.entry_close) / b.entry_close
            ELSE (b.entry_close - b.outcome_20d_close) / b.entry_close
        END AS outcome_20d_directional_return,
        s.latest_candidate_bar_date,
        s.latest_candidate_score,
        s.latest_monthly_triangle,
        s.latest_weekly_triangle,
        s.latest_daily_triangle,
        s.latest_candidate_score - a.candidate_score AS score_delta,
        d.signal_decay_date,
        d.signal_decay_score,
        d.signal_decay_daily_triangle,
        d.signal_decay_date IS NOT NULL AS signal_decay_flag,
        w.whipsaw_transition_date,
        w.whipsaw_transition_type,
        w.whipsaw_to_score,
        w.whipsaw_transition_date IS NOT NULL AS whipsaw_after_promotion_flag
    FROM audited_promotions a
    LEFT JOIN bar_rollup b
      ON b.execution_id = a.execution_id
     AND b.market_signal_id = a.market_signal_id
    LEFT JOIN latest_candidate_state s
      ON s.execution_id = a.execution_id
     AND s.market_signal_id = a.market_signal_id
    LEFT JOIN first_decay d
      ON d.execution_id = a.execution_id
     AND d.market_signal_id = a.market_signal_id
    LEFT JOIN first_whipsaw w
      ON w.execution_id = a.execution_id
     AND w.market_signal_id = a.market_signal_id
)
SELECT
    execution_id,
    acceptance_id,
    decision_record_id,
    candidate_id,
    baseline_parameter_set,
    executed_by,
    executed_at,
    rollback_status,
    market_signal_id,
    market_signal_live,
    ticker,
    action,
    confidence_score,
    candidate_bar_date,
    rollback_marker,
    candidate_score,
    candidate_monthly_triangle,
    candidate_weekly_triangle,
    candidate_daily_triangle,
    entry_close,
    outcome_1d_bar_date,
    outcome_1d_close,
    outcome_1d_directional_return,
    outcome_5d_bar_date,
    outcome_5d_close,
    outcome_5d_directional_return,
    outcome_20d_bar_date,
    outcome_20d_close,
    outcome_20d_directional_return,
    latest_candidate_bar_date,
    latest_candidate_score,
    latest_monthly_triangle,
    latest_weekly_triangle,
    latest_daily_triangle,
    score_delta,
    signal_decay_flag,
    signal_decay_date,
    signal_decay_score,
    signal_decay_daily_triangle,
    whipsaw_after_promotion_flag,
    whipsaw_transition_date,
    whipsaw_transition_type,
    whipsaw_to_score,
    CASE
        WHEN outcome_5d_directional_return IS NULL
         AND outcome_20d_directional_return IS NULL THEN 'PENDING'
        WHEN signal_decay_flag
         AND (
            outcome_20d_directional_return < -0.03
            OR (outcome_20d_directional_return IS NULL AND outcome_5d_directional_return < -0.02)
         ) THEN 'PRICE_AND_SCORE_DRIFT'
        WHEN signal_decay_flag THEN 'SCORE_DRIFT'
        WHEN outcome_20d_directional_return < -0.03
          OR (outcome_20d_directional_return IS NULL AND outcome_5d_directional_return < -0.02)
            THEN 'PRICE_DRIFT'
        ELSE 'IN_LINE'
    END AS drift_status,
    CASE
        WHEN rollback_status = 'rolled_back' THEN 'NO_ACTION_ROLLED_BACK'
        WHEN whipsaw_after_promotion_flag
         AND signal_decay_flag
         AND (
            outcome_20d_directional_return < -0.03
            OR outcome_5d_directional_return < -0.02
         ) THEN 'REVIEW_ROLLBACK_WARNING'
        WHEN whipsaw_after_promotion_flag
          OR signal_decay_flag
          OR outcome_20d_directional_return < -0.03
          OR (outcome_20d_directional_return IS NULL AND outcome_5d_directional_return < -0.02)
            THEN 'WATCH_WARNING'
        ELSE 'NO_WARNING'
    END AS rollback_recommendation,
    CASE
        WHEN rollback_status = 'rolled_back' THEN 'ROLLED_BACK'
        WHEN outcome_1d_directional_return IS NULL
         AND outcome_5d_directional_return IS NULL
         AND outcome_20d_directional_return IS NULL THEN 'PENDING'
        WHEN whipsaw_after_promotion_flag
          OR signal_decay_flag
          OR outcome_20d_directional_return < -0.03
          OR (outcome_20d_directional_return IS NULL AND outcome_5d_directional_return < -0.02)
            THEN 'WARNING'
        ELSE 'HEALTHY'
    END AS monitoring_status,
    CASE
        WHEN rollback_status = 'rolled_back'
            THEN 'Promotion has already been rolled back; monitoring remains read-only.'
        WHEN whipsaw_after_promotion_flag AND signal_decay_flag
            THEN 'Candidate state whipsawed after promotion and score support decayed; rollback review warning only.'
        WHEN whipsaw_after_promotion_flag
            THEN 'Opposite candidate transition appeared after promotion; rollback review warning only.'
        WHEN signal_decay_flag
            THEN 'Candidate score or daily triangle no longer supports the promoted state; rollback review warning only.'
        WHEN outcome_20d_directional_return < -0.03
          OR (outcome_20d_directional_return IS NULL AND outcome_5d_directional_return < -0.02)
            THEN 'Observed return is drifting against candidate expectation; rollback review warning only.'
        WHEN outcome_1d_directional_return IS NULL
         AND outcome_5d_directional_return IS NULL
         AND outcome_20d_directional_return IS NULL
            THEN 'Outcome windows are still pending.'
        ELSE 'Promoted signal remains in line with monitored candidate expectations.'
    END AS explanation
FROM monitored;

GRANT SELECT ON TABLE hedge_fund.v_signal_promotion_post_execution_monitoring TO crog_ai_app;
