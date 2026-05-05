from pathlib import Path


def _audit_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_promotion_audit_observability.sql"
    ).read_text(encoding="utf-8")


def test_audit_observability_adds_stable_snapshots() -> None:
    sql = _audit_sql()

    assert "verification_status_snapshot" in sql
    assert "verification_payload_snapshot" in sql
    assert "candidate_set_hash" in sql
    assert "inserted_market_signal_ids_hash" in sql
    assert "deleted_market_signal_ids_hash" in sql
    assert "trg_signal_promotion_execution_snapshot_hash" in sql
    assert "trg_signal_promotion_rollback_snapshot_hash" in sql
    assert "ALTER VIEW IF EXISTS hedge_fund.v_signal_promotion_rollback_drill" in sql
    assert "hedge_fund.signal_promotion_rollback_audits" in sql


def test_lifecycle_timeline_uses_audited_sources_only() -> None:
    sql = _audit_sql()

    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_lifecycle_timeline" in sql
    assert "WITH (security_invoker = true) AS" in sql
    assert "DECISION_CREATED" in sql
    assert "DRY_RUN_GENERATED" in sql
    assert "VERIFICATION_RESULT" in sql
    assert "ACCEPTANCE_CREATED" in sql
    assert "EXECUTION_COMPLETED" in sql
    assert "ROLLBACK_ELIGIBLE" in sql
    assert "ROLLBACK_COMPLETED" in sql
    assert "signal_shadow_review_decisions" in sql
    assert "signal_promotion_dry_run_acceptances" in sql
    assert "signal_promotion_executions" in sql
    assert "signal_promotion_rollback_audits" in sql


def test_reconciliation_healthy_path_requires_all_checks_pass() -> None:
    sql = _audit_sql()

    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_reconciliation" in sql
    assert sql.count("WITH (security_invoker = true) AS") >= 2
    assert "decision_link" in sql
    assert "verification_gate" in sql
    assert "execution_count_match" in sql
    assert "write_integrity" in sql
    assert "extraneous_writes" in sql
    assert "rollback_integrity" in sql
    assert "idempotency" in sql
    assert "ELSE 'HEALTHY'" in sql


def test_reconciliation_missing_verification_returns_error() -> None:
    sql = _audit_sql()

    assert "FROM hedge_fund.signal_promotion_dry_run_acceptances a" in sql
    assert "LEFT JOIN execution_base e ON e.acceptance_id = a.id" in sql
    assert "a.verification_status_snapshot = 'PASS'" in sql
    assert "a.verification_payload_snapshot IS NOT NULL" in sql
    assert "ELSE 'FAIL'\n        END AS verification_gate" in sql
    assert "WHEN 'FAIL' = ANY(check_values) THEN 'ERROR'" in sql
    assert "WHEN e.id IS NULL THEN 'NA'" in sql


def test_reconciliation_count_mismatch_returns_error() -> None:
    sql = _audit_sql()

    assert "e.dry_run_proposed_insert_count = r.audited_count" in sql
    assert "e.dry_run_proposed_insert_count = cardinality(e.inserted_market_signal_ids)" in sql
    assert "END AS execution_count_match" in sql


def test_reconciliation_extraneous_write_check_uses_audited_ids_not_ticker_date() -> None:
    sql = _audit_sql()
    extraneous_block = sql.split("END AS write_integrity", 1)[1].split(
        "END AS rollback_integrity", 1
    )[0]

    assert "e.inserted_ids_sorted = r.audited_ids" in extraneous_block
    assert "r.audited_count = r.distinct_audited_count" in extraneous_block
    assert "ticker" not in extraneous_block.lower()
    assert "candidate_bar_date" not in extraneous_block.lower()


def test_reconciliation_partial_rollback_returns_error() -> None:
    sql = _audit_sql()

    assert "WHEN e.rollback_status <> 'rolled_back' THEN 'NA'" in sql
    assert "r.live_audited_count = 0" in sql
    assert "cardinality(COALESCE(ra.deleted_market_signal_ids" in sql
    assert "END AS rollback_integrity" in sql


def test_reconciliation_uses_successful_rollback_audit_after_repeat_noop() -> None:
    sql = _audit_sql()

    assert "successful_rollback_audit AS" in sql
    assert "latest_rollback_audit" not in sql
    assert "WHERE a.rollback_status = 'rolled_back'" in sql
    assert (
        "ORDER BY a.execution_id, COALESCE(a.completed_at, a.attempted_at) DESC"
        in sql
    )
    assert "FROM successful_rollback_audit a" in sql
    assert "LEFT JOIN successful_rollback_audit ra ON ra.execution_id = e.id" in sql


def test_reconciliation_double_execute_attempt_keeps_idempotency_explicit() -> None:
    sql = _audit_sql()

    assert "COUNT(*) OVER (PARTITION BY e.acceptance_id) AS executions_for_acceptance" in sql
    assert (
        "COUNT(*) OVER (PARTITION BY e.acceptance_id, e.idempotency_key) "
        "AS executions_for_acceptance_key"
    ) in sql
    assert "e.executions_for_acceptance = 1" in sql
    assert "e.executions_for_acceptance_key = 1" in sql


def test_reconciliation_cross_model_only_returns_warning_not_error() -> None:
    sql = _audit_sql()

    assert "cross_model_diagnostic_only" in sql
    assert "cross_model_diagnostic_only > 0 OR high_churn_flag OR whipsaw_flag" in sql
    assert "WHEN has_warning THEN 'WARNING'" in sql
