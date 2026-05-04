from pathlib import Path


def _alerts_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_post_execution_alerts.sql"
    ).read_text(encoding="utf-8")


def test_post_execution_alerts_view_is_read_only_and_audited() -> None:
    sql = _alerts_sql()

    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_post_execution_alerts" in sql
    assert "WITH (security_invoker = true) AS" in sql
    assert "FROM hedge_fund.v_signal_promotion_post_execution_monitoring" in sql
    assert "market_signal_id" in sql
    assert "rollback_marker" in sql
    assert "GRANT SELECT ON TABLE hedge_fund.v_signal_promotion_post_execution_alerts" in sql
    assert "INSERT INTO hedge_fund.market_signals" not in sql
    assert "DELETE FROM hedge_fund.market_signals" not in sql
    assert "UPDATE hedge_fund" not in sql
    assert "FROM hedge_fund.rollback_guarded_signal_promotion(" not in sql
    assert "SELECT * FROM hedge_fund.rollback_guarded_signal_promotion" not in sql


def test_post_execution_alerts_emit_required_alert_types() -> None:
    sql = _alerts_sql()

    assert "'SIGNAL_DECAY'::TEXT AS alert_type" in sql
    assert "'WHIPSAW_AFTER_PROMOTION'::TEXT AS alert_type" in sql
    assert "'DRIFT'::TEXT AS alert_type" in sql
    assert "'STALE_EXECUTION_MONITORING'::TEXT AS alert_type" in sql
    assert "'ROLLBACK_RECOMMENDATION'::TEXT AS alert_type" in sql
    assert "UNION ALL" in sql


def test_post_execution_alerts_are_warning_only() -> None:
    sql = _alerts_sql()

    assert "Warning only" in sql
    assert "no automated rollback is performed" in sql
    assert "no automatic trade or signal change is made" in sql
    assert "no automatic trade, signal, or rollback action is made" in sql
    assert "rollback_guarded_signal_promotion" in sql


def test_post_execution_alerts_track_requested_conditions() -> None:
    sql = _alerts_sql()

    assert "WHERE signal_decay_flag" in sql
    assert "WHERE whipsaw_after_promotion_flag" in sql
    assert "drift_status IN ('PRICE_DRIFT', 'SCORE_DRIFT', 'PRICE_AND_SCORE_DRIFT')" in sql
    assert "monitoring_status = 'PENDING'" in sql
    assert "executed_at < now() - INTERVAL '2 days'" in sql
    assert "rollback_recommendation IN ('WATCH_WARNING', 'REVIEW_ROLLBACK_WARNING')" in sql
    assert "rollback_status = 'active'" in sql
