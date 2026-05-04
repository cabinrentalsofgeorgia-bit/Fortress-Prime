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
)
SELECT * FROM signal_decay_alerts
UNION ALL
SELECT * FROM whipsaw_alerts
UNION ALL
SELECT * FROM drift_alerts
UNION ALL
SELECT * FROM stale_alerts
UNION ALL
SELECT * FROM rollback_recommendation_alerts;

GRANT SELECT ON TABLE hedge_fund.v_signal_promotion_post_execution_alerts TO crog_ai_app;
