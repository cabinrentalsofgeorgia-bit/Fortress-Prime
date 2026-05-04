from pathlib import Path


def _health_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_signal_health_dashboard.sql"
    ).read_text(encoding="utf-8")


def test_signal_health_dashboard_is_read_only() -> None:
    sql = _health_sql()

    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_health_active_promotions" in sql
    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_health_at_risk_signals" in sql
    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_health_execution_outcomes" in sql
    assert "CREATE OR REPLACE FUNCTION hedge_fund.signal_health_model_divergence" in sql
    assert "WITH (security_invoker = true) AS" in sql
    assert "FROM hedge_fund.v_signal_promotion_post_execution_monitoring" in sql
    assert "FROM hedge_fund.v_signal_scores_composite" in sql
    assert "INSERT INTO hedge_fund.market_signals" not in sql
    assert "DELETE FROM hedge_fund.market_signals" not in sql
    assert "UPDATE hedge_fund.market_signals" not in sql
    assert "rollback_guarded_signal_promotion" not in sql


def test_signal_health_dashboard_tracks_requested_health_flags() -> None:
    sql = _health_sql()

    assert "'drift', drift_signal_count > 0" in sql
    assert "'whipsaw', whipsaw_signal_count > 0" in sql
    assert "'decay', decay_signal_count > 0" in sql
    assert "'HEALTHY'" in sql
    assert "'WARNING'" in sql
    assert "'DEGRADED'" in sql
    assert "outcome_1d_directional_return" in sql
    assert "outcome_5d_directional_return" in sql
    assert "outcome_20d_directional_return" in sql
    assert "positive_5d_pct" in sql
    assert "whipsaw_pct" in sql


def test_signal_health_dashboard_surfaces_only_actionable_at_risk_conditions() -> None:
    sql = _health_sql()

    assert "WHERE rollback_status = 'active'" in sql
    assert "AND market_signal_live" in sql
    assert "whipsaw_after_promotion_flag" in sql
    assert "outcome_5d_directional_return < -0.02" in sql
    assert "drift_status IN ('PRICE_DRIFT', 'SCORE_DRIFT', 'PRICE_AND_SCORE_DRIFT')" in sql
    assert "'whipsaw-after-promotion'" in sql
    assert "'5d return below threshold'" in sql
    assert "'drift vs expected range'" in sql


def test_signal_health_model_divergence_compares_candidate_80_to_production() -> None:
    sql = _health_sql()

    assert "candidate_parameter_set TEXT DEFAULT 'dochia_v0_2_range_daily'" in sql
    assert "production_parameter_set TEXT DEFAULT 'dochia_v0_estimated'" in sql
    assert "v.composite_score = 80" in sql
    assert "p.parameter_set_name = production_parameter_set" in sql
    assert "j.production_score IS DISTINCT FROM 80" in sql
    assert "divergence_rate" in sql
    assert "divergent_tickers" in sql


def test_signal_health_dashboard_grants_are_read_only() -> None:
    sql = _health_sql()

    assert "REVOKE ALL ON TABLE hedge_fund.v_signal_health_active_promotions" in sql
    assert "REVOKE ALL ON TABLE hedge_fund.v_signal_health_at_risk_signals" in sql
    assert "REVOKE ALL ON TABLE hedge_fund.v_signal_health_execution_outcomes" in sql
    assert "REVOKE ALL ON FUNCTION hedge_fund.signal_health_model_divergence" in sql
    assert "GRANT SELECT ON TABLE" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql
