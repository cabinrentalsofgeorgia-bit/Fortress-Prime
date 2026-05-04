CREATE OR REPLACE FUNCTION hedge_fund.verify_promotion_dry_run(
    candidate_parameter_set TEXT,
    production_parameter_set TEXT DEFAULT 'dochia_v0_estimated'
)
RETURNS TABLE (
    overall_status TEXT,
    ticker TEXT,
    candidate_bar_date DATE,
    candidate_score INTEGER,
    candidate_action TEXT,
    candidate_monthly_triangle INTEGER,
    candidate_weekly_triangle INTEGER,
    candidate_daily_triangle INTEGER,
    latest_candidate_transition_date DATE,
    latest_candidate_transition_type TEXT,
    prior_score INTEGER,
    new_score INTEGER,
    production_score INTEGER,
    production_daily_triangle INTEGER,
    conflict_type TEXT,
    explanation TEXT
)
LANGUAGE sql
STABLE
AS $$
    WITH candidate_ranked AS (
        SELECT
            v.*,
            ROW_NUMBER() OVER (
                PARTITION BY v.ticker
                ORDER BY v.bar_date DESC, v.computed_at DESC
            ) AS rn
        FROM hedge_fund.v_signal_scores_composite v
        WHERE v.parameter_set_name = candidate_parameter_set
    ),
    proposed AS (
        SELECT *
        FROM candidate_ranked
        WHERE rn = 1
          AND abs(composite_score) >= 50
    ),
    candidate_counts AS (
        SELECT
            v.ticker,
            v.bar_date,
            COUNT(*) AS source_count,
            COUNT(DISTINCT CASE WHEN v.composite_score >= 0 THEN 'BUY' ELSE 'SELL' END)
                AS action_count,
            COUNT(DISTINCT v.monthly_state) AS monthly_state_count,
            COUNT(DISTINCT v.weekly_state) AS weekly_state_count,
            COUNT(DISTINCT v.daily_state) AS daily_state_count,
            COUNT(DISTINCT v.composite_score) AS score_count
        FROM hedge_fund.v_signal_scores_composite v
        JOIN proposed p
          ON p.ticker = v.ticker
         AND p.bar_date = v.bar_date
        WHERE v.parameter_set_name = candidate_parameter_set
        GROUP BY v.ticker, v.bar_date
    ),
    production_same_bar AS (
        SELECT DISTINCT ON (v.ticker, v.bar_date)
            v.ticker,
            v.bar_date,
            v.composite_score,
            v.daily_state
        FROM hedge_fund.v_signal_scores_composite v
        JOIN proposed p
          ON p.ticker = v.ticker
         AND p.bar_date = v.bar_date
        WHERE v.parameter_set_name = production_parameter_set
        ORDER BY v.ticker, v.bar_date, v.computed_at DESC
    ),
    latest_transition AS (
        SELECT DISTINCT ON (t.ticker)
            t.ticker,
            t.transition_type,
            t.from_score,
            t.to_score,
            t.to_bar_date,
            t.to_states,
            t.notes
        FROM hedge_fund.signal_transitions t
        JOIN hedge_fund.scoring_parameters sp ON sp.id = t.parameter_set_id
        JOIN proposed p ON p.ticker = t.ticker
        WHERE sp.name = candidate_parameter_set
          AND t.to_bar_date <= p.bar_date
        ORDER BY t.ticker, t.to_bar_date DESC, t.detected_at DESC
    ),
    row_eval AS (
        SELECT
            p.ticker,
            p.bar_date AS candidate_bar_date,
            p.composite_score::INTEGER AS candidate_score,
            CASE WHEN p.composite_score >= 0 THEN 'BUY' ELSE 'SELL' END AS candidate_action,
            p.monthly_state::INTEGER AS candidate_monthly_triangle,
            p.weekly_state::INTEGER AS candidate_weekly_triangle,
            p.daily_state::INTEGER AS candidate_daily_triangle,
            lt.to_bar_date AS latest_candidate_transition_date,
            lt.transition_type AS latest_candidate_transition_type,
            lt.from_score::INTEGER AS prior_score,
            lt.to_score::INTEGER AS new_score,
            prod.composite_score::INTEGER AS production_score,
            prod.daily_state::INTEGER AS production_daily_triangle,
            CASE
                WHEN cc.source_count IS NULL THEN 'INCONCLUSIVE'
                WHEN cc.source_count > 1 THEN 'FAIL'
                WHEN cc.action_count > 1
                  OR cc.monthly_state_count > 1
                  OR cc.weekly_state_count > 1
                  OR cc.daily_state_count > 1
                  OR cc.score_count > 1 THEN 'FAIL'
                WHEN p.composite_score >= 50 AND p.daily_state < 0 THEN 'FAIL'
                WHEN p.composite_score <= -50 AND p.daily_state > 0 THEN 'FAIL'
                WHEN p.composite_score >= 50
                  AND NOT (p.monthly_state = 1 AND p.weekly_state = 1 AND p.daily_state = 1)
                  AND NOT (
                    lt.transition_type IN ('breakout_bullish', 'exit_to_reentry', 'full_reversal')
                    AND lt.to_score = p.composite_score
                    AND COALESCE((lt.to_states ->> 'daily')::INTEGER, 0) = 1
                  ) THEN 'INCONCLUSIVE'
                WHEN p.composite_score <= -50
                  AND NOT (p.monthly_state = -1 AND p.weekly_state = -1 AND p.daily_state = -1)
                  AND NOT (
                    lt.transition_type IN ('breakout_bearish', 'peak_to_exit', 'full_reversal')
                    AND lt.to_score = p.composite_score
                    AND COALESCE((lt.to_states ->> 'daily')::INTEGER, 0) = -1
                  ) THEN 'INCONCLUSIVE'
                ELSE 'PASS'
            END AS row_status,
            CASE
                WHEN cc.source_count IS NULL THEN 'SOURCE_LINEAGE_MISSING'
                WHEN cc.source_count > 1 THEN 'SOURCE_LINEAGE_DUPLICATE'
                WHEN cc.action_count > 1
                  OR cc.monthly_state_count > 1
                  OR cc.weekly_state_count > 1
                  OR cc.daily_state_count > 1
                  OR cc.score_count > 1 THEN 'CANDIDATE_INTERNAL_CONFLICT'
                WHEN p.composite_score >= 50 AND p.daily_state < 0 THEN 'CANDIDATE_INTERNAL_CONFLICT'
                WHEN p.composite_score <= -50 AND p.daily_state > 0 THEN 'CANDIDATE_INTERNAL_CONFLICT'
                WHEN p.composite_score >= 50
                  AND NOT (p.monthly_state = 1 AND p.weekly_state = 1 AND p.daily_state = 1)
                  AND NOT (
                    lt.transition_type IN ('breakout_bullish', 'exit_to_reentry', 'full_reversal')
                    AND lt.to_score = p.composite_score
                    AND COALESCE((lt.to_states ->> 'daily')::INTEGER, 0) = 1
                  ) THEN 'TRANSITION_UNSUPPORTED'
                WHEN p.composite_score <= -50
                  AND NOT (p.monthly_state = -1 AND p.weekly_state = -1 AND p.daily_state = -1)
                  AND NOT (
                    lt.transition_type IN ('breakout_bearish', 'peak_to_exit', 'full_reversal')
                    AND lt.to_score = p.composite_score
                    AND COALESCE((lt.to_states ->> 'daily')::INTEGER, 0) = -1
                  ) THEN 'TRANSITION_UNSUPPORTED'
                WHEN prod.composite_score IS NOT NULL
                  AND (prod.composite_score <> p.composite_score OR prod.daily_state <> p.daily_state)
                  THEN 'CROSS_MODEL_DIAGNOSTIC_ONLY'
                ELSE 'NONE'
            END AS conflict_type,
            CASE
                WHEN cc.source_count IS NULL THEN
                    'No candidate source row traces to the dry-run ticker/bar.'
                WHEN cc.source_count > 1 THEN
                    'More than one candidate source row exists for the dry-run ticker/bar.'
                WHEN p.composite_score >= 50 AND p.daily_state < 0 THEN
                    'Candidate proposes BUY while candidate daily triangle is bearish.'
                WHEN p.composite_score <= -50 AND p.daily_state > 0 THEN
                    'Candidate proposes SELL while candidate daily triangle is bullish.'
                WHEN prod.composite_score IS NOT NULL
                  AND (prod.composite_score <> p.composite_score OR prod.daily_state <> p.daily_state)
                  THEN 'Production baseline differs from candidate, but candidate lineage is clean.'
                ELSE 'Candidate dry-run lineage is clean.'
            END AS explanation
        FROM proposed p
        LEFT JOIN candidate_counts cc
          ON cc.ticker = p.ticker
         AND cc.bar_date = p.bar_date
        LEFT JOIN production_same_bar prod
          ON prod.ticker = p.ticker
         AND prod.bar_date = p.bar_date
        LEFT JOIN latest_transition lt ON lt.ticker = p.ticker
    )
    SELECT
        CASE
            WHEN EXISTS (SELECT 1 FROM row_eval WHERE row_status = 'FAIL') THEN 'FAIL'
            WHEN EXISTS (SELECT 1 FROM row_eval WHERE row_status = 'INCONCLUSIVE') THEN 'INCONCLUSIVE'
            ELSE 'PASS'
        END AS overall_status,
        ticker,
        candidate_bar_date,
        candidate_score,
        candidate_action,
        candidate_monthly_triangle,
        candidate_weekly_triangle,
        candidate_daily_triangle,
        latest_candidate_transition_date,
        latest_candidate_transition_type,
        prior_score,
        new_score,
        production_score,
        production_daily_triangle,
        conflict_type,
        explanation
    FROM row_eval
    ORDER BY
        CASE row_status WHEN 'FAIL' THEN 0 WHEN 'INCONCLUSIVE' THEN 1 ELSE 2 END,
        ticker;
$$;

GRANT EXECUTE ON FUNCTION hedge_fund.verify_promotion_dry_run(TEXT, TEXT) TO crog_ai_app;
