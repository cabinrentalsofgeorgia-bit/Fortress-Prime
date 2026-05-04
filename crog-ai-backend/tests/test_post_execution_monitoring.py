from pathlib import Path


def _monitoring_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_post_execution_monitoring.sql"
    ).read_text(encoding="utf-8")


def test_post_execution_monitoring_view_is_read_only_and_audited() -> None:
    sql = _monitoring_sql()

    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_post_execution_monitoring" in sql
    assert "WITH (security_invoker = true) AS" in sql
    assert "FROM hedge_fund.signal_promotion_executions e" in sql
    assert "JOIN hedge_fund.signal_promotion_execution_rows r" in sql
    assert "r.market_signal_id" in sql
    assert "candidate_bar_date" in sql
    assert "GRANT SELECT ON TABLE hedge_fund.v_signal_promotion_post_execution_monitoring" in sql
    assert "INSERT INTO hedge_fund.market_signals" not in sql
    assert "DELETE FROM hedge_fund.market_signals" not in sql
    assert "UPDATE hedge_fund.signal_promotion_executions" not in sql


def test_post_execution_monitoring_tracks_required_outcome_windows() -> None:
    sql = _monitoring_sql()

    assert "sessions_after_promotion = 1" in sql
    assert "sessions_after_promotion = 5" in sql
    assert "sessions_after_promotion = 20" in sql
    assert "outcome_1d_directional_return" in sql
    assert "outcome_5d_directional_return" in sql
    assert "outcome_20d_directional_return" in sql
    assert "WHEN a.action = 'BUY' THEN (b.outcome_5d_close - b.entry_close)" in sql
    assert "ELSE (b.entry_close - b.outcome_5d_close)" in sql


def test_post_execution_monitoring_flags_whipsaw_after_promotion() -> None:
    sql = _monitoring_sql()

    assert "first_whipsaw AS" in sql
    assert "t.to_bar_date > a.candidate_bar_date" in sql
    assert "t.to_bar_date <= COALESCE(b.outcome_5d_bar_date" in sql
    assert "a.action = 'BUY' AND (t.to_score < 0" in sql
    assert "a.action = 'SELL' AND (t.to_score > 0" in sql
    assert "whipsaw_after_promotion_flag" in sql


def test_post_execution_monitoring_flags_signal_decay_and_drift() -> None:
    sql = _monitoring_sql()

    assert "first_decay AS" in sql
    assert "a.action = 'BUY'" in sql
    assert "v.composite_score < 50 OR v.daily_state <> 1" in sql
    assert "a.action = 'SELL'" in sql
    assert "v.composite_score > -50 OR v.daily_state <> -1" in sql
    assert "signal_decay_flag" in sql
    assert "PRICE_AND_SCORE_DRIFT" in sql
    assert "SCORE_DRIFT" in sql
    assert "PRICE_DRIFT" in sql


def test_post_execution_monitoring_recommends_warning_only() -> None:
    sql = _monitoring_sql()

    assert "REVIEW_ROLLBACK_WARNING" in sql
    assert "WATCH_WARNING" in sql
    assert "NO_WARNING" in sql
    assert "rollback review warning only" in sql
    assert "rollback_guarded_signal_promotion" not in sql
