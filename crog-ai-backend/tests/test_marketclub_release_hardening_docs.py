from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SQL = ROOT / "deploy" / "sql" / "marketclub_release_hardening_verification.sql"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_production_runbook_locks_release_hardening_scope() -> None:
    text = _read(DOCS / "MARKETCLUB-SIGNALS-PRODUCTION-RUNBOOK.md")

    assert "release hardening only; no new product mechanics" in text
    assert "Environment And Config Verification" in text
    assert "Hosted DB Migration Verification" in text
    assert "RLS And Policy Verification" in text
    assert "Staging Smoke Test" in text
    assert "Do not expand product behavior" in text
    assert "automatic rollback" in text
    assert "automatic trade or signal changes" in text
    assert "DATABASE_URL" in text
    assert "fortress_db" in text
    assert "fortress_prod" in text
    assert "marketclub_release_hardening_verification.sql" in text


def test_incident_response_requires_audited_ids_and_no_auto_heal() -> None:
    text = _read(DOCS / "MARKETCLUB-SIGNALS-INCIDENT-RESPONSE-CHECKLIST.md")

    assert "Freeze new operator mutations" in text
    assert "decision -> execution -> outcome -> rollback" in text
    assert "Do not auto-heal" in text
    assert "Do not backfill from the cockpit" in text
    assert "Do not roll back by ticker/date" in text
    assert "execution_id" in text
    assert "market_signal_id" in text
    assert "SEV1" in text
    assert "SEV2" in text
    assert "SEV3" in text


def test_rollback_drill_is_scoped_to_execution_id_only() -> None:
    text = _read(DOCS / "MARKETCLUB-SIGNALS-ROLLBACK-DRILL-CHECKLIST.md")

    assert "Allowed target:** `execution_id` only" in text
    assert "Never roll back by ticker, date, action, score, or parameter set" in text
    assert "audited_market_signal_ids" in text
    assert "rollback_preview_market_signal_ids" in text
    assert "Repeat Rollback Test" in text
    assert "No unaudited" in text


def test_staging_smoke_is_read_only_and_covers_required_panels() -> None:
    text = _read(DOCS / "MARKETCLUB-SIGNALS-STAGING-SMOKE-TEST.md")

    assert "do not create decisions, acceptances, executions, acknowledgements, or rollbacks" in text
    assert "/financial/hedge-fund" in text
    assert "Signal Health Dashboard" in text
    assert "Dry-Run Verification Gate" in text
    assert "Lifecycle Timeline" in text
    assert "Reconciliation" in text
    assert "Post-Execution Monitoring" in text
    assert "Post-Execution Alerts" in text
    assert "Rollback Drill" in text
    assert "no POST requests are made" in text
    assert "no `market_signals` row count changes" in text


def test_operator_audit_playbook_links_release_hardening_pack() -> None:
    text = _read(DOCS / "OPERATOR-AUDIT-PLAYBOOK.md")

    assert "Release Hardening Lock" in text
    assert "MARKETCLUB-SIGNALS-PRODUCTION-RUNBOOK.md" in text
    assert "MARKETCLUB-SIGNALS-INCIDENT-RESPONSE-CHECKLIST.md" in text
    assert "MARKETCLUB-SIGNALS-ROLLBACK-DRILL-CHECKLIST.md" in text
    assert "MARKETCLUB-SIGNALS-STAGING-SMOKE-TEST.md" in text
    assert "marketclub_release_hardening_verification.sql" in text


def test_release_hardening_sql_is_read_only_and_covers_release_checks() -> None:
    sql = _read(SQL)

    assert "SELECT version_num" in sql
    assert "hedge_fund.alembic_version_crog_ai" in sql
    assert "to_regprocedure('hedge_fund.verify_promotion_dry_run" in sql
    assert "to_regprocedure('hedge_fund.execute_guarded_signal_promotion" in sql
    assert "to_regprocedure('hedge_fund.rollback_guarded_signal_promotion" in sql
    assert "to_regclass('hedge_fund.v_signal_health_active_promotions')" in sql
    assert "relrowsecurity" in sql
    assert "information_schema.table_privileges" in sql
    assert "has_function_privilege('crog_ai_app'" in sql
    assert "GROUP BY acceptance_id, idempotency_key" in sql
    assert "v_signal_promotion_reconciliation" in sql
    assert "v_signal_health_active_promotions" in sql
    forbidden = [
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "TRUNCATE ",
        "ALTER ",
        "DROP ",
        "CREATE ",
        "GRANT ",
        "REVOKE ",
        "SECURITY DEFINER",
    ]
    upper_sql = sql.upper()
    for token in forbidden:
        assert token not in upper_sql
