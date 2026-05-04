from pathlib import Path


def _ack_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_post_execution_alert_acknowledgements.sql"
    ).read_text(encoding="utf-8")


def test_alert_acknowledgement_sql_is_audit_only() -> None:
    sql = _ack_sql()

    assert "CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_alert_acknowledgements" in sql
    assert "CREATE OR REPLACE FUNCTION hedge_fund.acknowledge_signal_promotion_alert" in sql
    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_post_execution_alerts" in sql
    assert "INSERT INTO hedge_fund.signal_promotion_alert_acknowledgements" in sql
    assert "INSERT INTO hedge_fund.market_signals" not in sql
    assert "DELETE FROM hedge_fund.market_signals" not in sql
    assert "UPDATE hedge_fund.market_signals" not in sql
    assert "rollback_guarded_signal_promotion(" not in sql


def test_alert_acknowledgement_requires_operator_and_alert_id_only() -> None:
    sql = _ack_sql()

    assert "p_alert_id TEXT" in sql
    assert "p_operator_token_sha256 TEXT" in sql
    assert "role IN ('signal_operator', 'signal_admin')" in sql
    assert "WHERE alert_id = trim(COALESCE(p_alert_id, ''))" in sql
    assert "No active post-execution alert found for alert_id" in sql
    assert "p_ticker" not in sql
    assert "p_bar_date" not in sql


def test_alert_acknowledgement_snapshots_evidence_and_surfaces_state() -> None:
    sql = _ack_sql()

    assert "alert_evidence_snapshot JSONB NOT NULL" in sql
    assert "to_jsonb(v_alert)" in sql
    assert "acknowledgement_rollup AS" in sql
    assert "acknowledgement_count" in sql
    assert "acknowledged" in sql
    assert "latest_acknowledgement_status" in sql
    assert "acknowledgement_required" in sql


def test_alert_acknowledgement_grants_are_narrow() -> None:
    sql = _ack_sql()

    assert "REVOKE ALL ON FUNCTION hedge_fund.acknowledge_signal_promotion_alert" in sql
    assert "REVOKE ALL ON TABLE hedge_fund.signal_promotion_alert_acknowledgements" in sql
    assert "GRANT SELECT ON TABLE" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
