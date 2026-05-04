import datetime as dt
import inspect
from pathlib import Path
from uuid import UUID

from app.signals import repository

ACCEPTANCE_ID = UUID("44444444-4444-4444-4444-444444444444")
DECISION_ID = UUID("33333333-3333-3333-3333-333333333333")
EXECUTION_ID = UUID("55555555-5555-5555-5555-555555555555")
OPERATOR_MEMBERSHIP_ID = UUID("66666666-6666-6666-6666-666666666666")
OPERATOR_TOKEN_SHA256 = "a" * 64


def _execution_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": EXECUTION_ID,
        "acceptance_id": ACCEPTANCE_ID,
        "decision_record_id": DECISION_ID,
        "candidate_parameter_set": "dochia_v0_2_range_daily",
        "baseline_parameter_set": "dochia_v0_estimated",
        "operator_membership_id": OPERATOR_MEMBERSHIP_ID,
        "executed_by": "Gary Knight",
        "execution_rationale": "Operator accepted the verified dry-run output.",
        "idempotency_key": f"acceptance:{ACCEPTANCE_ID}",
        "dry_run_generated_at": dt.datetime(2026, 5, 4, 12, 0, tzinfo=dt.UTC),
        "dry_run_proposed_insert_count": 2,
        "verification_status": "PASS",
        "inserted_market_signal_ids": [1201, 1202],
        "rollback_markers": [
            "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
            "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
        ],
        "rollback_status": "active",
        "rollback_operator_membership_id": None,
        "rollback_by": None,
        "rollback_reason": None,
        "rolled_back_at": None,
        "created_at": dt.datetime(2026, 5, 4, 12, 5, tzinfo=dt.UTC),
    }
    row.update(overrides)
    return row


class FakeCursor:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.sql = ""
        self.params: dict[str, object] = {}

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.sql = sql
        self.params = params

    def fetchone(self) -> dict[str, object]:
        return self.row

    def fetchall(self) -> list[dict[str, object]]:
        return [self.row]


class FakeConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self.cursor_instance = FakeCursor(row)

    def cursor(self, *args: object, **kwargs: object) -> FakeCursor:
        return self.cursor_instance


def _guarded_execution_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_guarded_promotion_execution.sql"
    ).read_text(encoding="utf-8")


def _rollback_drill_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_rollback_drill_observability.sql"
    ).read_text(encoding="utf-8")


def _operator_rollback_sql() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "sql"
        / "marketclub_operator_rollback_action.sql"
    ).read_text(encoding="utf-8")


def _rollback_drill_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "execution_id": EXECUTION_ID,
        "dry_run_acceptance_id": ACCEPTANCE_ID,
        "candidate_parameter_set": "dochia_v0_2_range_daily",
        "baseline_parameter_set": "dochia_v0_estimated",
        "executed_by": "Gary Knight",
        "executed_at": dt.datetime(2026, 5, 4, 12, 5, tzinfo=dt.UTC),
        "inserted_market_signal_ids": [1201, 1202],
        "rollback_markers": [
            "dochia-dry-run:dochia_v0_2_range_daily:AA:2026-04-24",
            "dochia-dry-run:dochia_v0_2_range_daily:AGIO:2026-04-24",
        ],
        "audited_market_signal_ids": [1201, 1202],
        "rollback_preview_market_signal_ids": [1201],
        "rollback_preview_count": 1,
        "rollback_eligibility": "ELIGIBLE_PARTIAL_AUDITED_ROWS",
        "rollback_eligible": False,
        "already_rolled_back": False,
        "rollback_status": "active",
        "rollback_by": None,
        "rollback_attempted_at": None,
        "rolled_back_at": None,
    }
    row.update(overrides)
    return row


def test_repository_executes_locked_database_function_not_raw_market_signal_insert() -> None:
    conn = FakeConnection(_execution_row())

    result = repository.execute_guarded_promotion(
        conn,  # type: ignore[arg-type]
        acceptance_id=str(ACCEPTANCE_ID),
        operator_token_sha256=OPERATOR_TOKEN_SHA256,
        execution_rationale="Operator accepted the verified dry-run output.",
        idempotency_key="operator-accepted-dry-run-20260504",
    )

    assert result["id"] == EXECUTION_ID
    assert "hedge_fund.execute_guarded_signal_promotion" in conn.cursor_instance.sql
    assert "INSERT INTO hedge_fund.market_signals" not in conn.cursor_instance.sql
    assert conn.cursor_instance.params["acceptance_id"] == str(ACCEPTANCE_ID)
    assert conn.cursor_instance.params["operator_token_sha256"] == OPERATOR_TOKEN_SHA256
    assert conn.cursor_instance.params["idempotency_key"] == "operator-accepted-dry-run-20260504"


def test_repository_rollback_uses_locked_database_function() -> None:
    conn = FakeConnection(
        _execution_row(
            rollback_status="rolled_back",
            rollback_operator_membership_id=OPERATOR_MEMBERSHIP_ID,
            rollback_by="Gary Knight",
            rollback_reason="Operator rollback after review.",
            rolled_back_at=dt.datetime(2026, 5, 4, 12, 30, tzinfo=dt.UTC),
        )
    )

    result = repository.rollback_promotion_execution(
        conn,  # type: ignore[arg-type]
        execution_id=str(EXECUTION_ID),
        operator_token_sha256=OPERATOR_TOKEN_SHA256,
        rollback_reason="Operator rollback after review.",
    )

    assert result["rollback_status"] == "rolled_back"
    assert "hedge_fund.rollback_guarded_signal_promotion" in conn.cursor_instance.sql
    assert conn.cursor_instance.params["execution_id"] == str(EXECUTION_ID)
    assert conn.cursor_instance.params["operator_token_sha256"] == OPERATOR_TOKEN_SHA256


def test_repository_fetches_read_only_rollback_drill_view() -> None:
    conn = FakeConnection(_rollback_drill_row())

    result = repository.fetch_promotion_rollback_drills(
        conn,  # type: ignore[arg-type]
        candidate_parameter_set="dochia_v0_2_range_daily",
        limit=3,
    )

    assert result[0]["execution_id"] == EXECUTION_ID
    assert result[0]["dry_run_acceptance_id"] == ACCEPTANCE_ID
    assert result[0]["rollback_preview_count"] == 1
    assert result[0]["rollback_preview_market_signal_ids"] == [1201]
    assert "hedge_fund.v_signal_promotion_rollback_drill" in conn.cursor_instance.sql
    assert "DELETE FROM hedge_fund.market_signals" not in conn.cursor_instance.sql
    assert conn.cursor_instance.params["candidate_parameter_set"] == "dochia_v0_2_range_daily"


def test_python_execution_path_contains_no_direct_market_signals_write() -> None:
    source = "\n".join(
        [
            inspect.getsource(repository.execute_guarded_promotion),
            inspect.getsource(repository.PostgresSignalDataStore.execute_guarded_promotion),
        ]
    )

    assert "INSERT INTO hedge_fund.market_signals" not in source
    assert "hedge_fund.execute_guarded_signal_promotion" in source


def test_sql_contract_enforces_full_guarded_execution_flow() -> None:
    sql = _guarded_execution_sql()

    assert "No dry-run acceptance exists for guarded promotion execution" in sql
    assert "signal_operator_memberships" in sql
    assert "Active signal operator membership is required" in sql
    assert "JOIN hedge_fund.signal_shadow_review_decisions" in sql
    assert "signal_promotion_dry_run_acceptances" in sql
    assert "promote_to_market_signals" in sql
    assert "hedge_fund.verify_promotion_dry_run" in sql
    assert "v_verification_status IS DISTINCT FROM 'PASS'" in sql
    assert "Promotion verification gate blocked execution" in sql
    assert "INSERT INTO hedge_fund.market_signals" in sql
    assert "INSERT INTO hedge_fund.signal_promotion_executions" in sql
    assert "INSERT INTO hedge_fund.signal_promotion_execution_rows" in sql
    assert "rollback_marker" in sql


def test_sql_contract_keeps_signal_and_audit_writes_transactional() -> None:
    sql = _guarded_execution_sql()

    market_signal_insert = sql.index("INSERT INTO hedge_fund.market_signals")
    execution_audit_insert = sql.index("INSERT INTO hedge_fund.signal_promotion_executions")
    row_audit_insert = sql.index("INSERT INTO hedge_fund.signal_promotion_execution_rows")

    assert market_signal_insert < execution_audit_insert < row_audit_insert
    assert "No exception handler is used in this function" in sql
    assert "production rows cannot commit without the execution audit rows" in sql
    assert "\nEXCEPTION\n" not in sql


def test_sql_contract_has_idempotency_and_rollback_support() -> None:
    sql = _guarded_execution_sql()

    assert "uq_signal_promotion_executions_acceptance UNIQUE (acceptance_id)" in sql
    assert "uq_signal_promotion_executions_idempotency UNIQUE (idempotency_key)" in sql
    assert "RETURN v_existing" in sql
    assert "Dry-run acceptance has already been executed" in sql
    assert "CREATE OR REPLACE FUNCTION hedge_fund.rollback_guarded_signal_promotion" in sql
    assert "DELETE FROM hedge_fund.market_signals" in sql
    assert "rollback_status = 'rolled_back'" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql


def test_sql_contract_requires_operator_roles_for_execution_and_rollback() -> None:
    sql = _guarded_execution_sql()

    assert "role IN ('signal_operator', 'signal_admin')" in sql
    assert "role = 'signal_admin'" in sql
    assert "Active signal admin membership is required for guarded promotion rollback" in sql
    assert "operator_membership_id UUID NOT NULL" in sql
    assert "rollback_operator_membership_id UUID" in sql
    assert "GRANT SELECT ON TABLE\n    hedge_fund.signal_operator_memberships" not in sql
    assert "GRANT INSERT ON TABLE\n    hedge_fund.signal_operator_memberships" not in sql


def test_sql_contract_scopes_rollback_to_audited_market_signal_ids_only() -> None:
    sql = _operator_rollback_sql()

    delete_block = sql.split("DELETE FROM hedge_fund.market_signals", 1)[1].split(
        "UPDATE hedge_fund.signal_promotion_executions", 1
    )[0]
    assert "USING hedge_fund.signal_promotion_execution_rows r" in delete_block
    assert "WHERE r.execution_id = v_execution.id" in delete_block
    assert "AND ms.id = r.market_signal_id" in delete_block
    assert "ticker" not in delete_block.lower()
    assert "candidate_bar_date" not in delete_block.lower()
    assert "candidate_parameter_set" not in delete_block.lower()


def test_sql_contract_makes_second_rollback_safe_noop() -> None:
    sql = _operator_rollback_sql()

    assert "IF v_execution.rollback_status = 'rolled_back' THEN" in sql
    assert "'already_rolled_back'" in sql
    assert "INSERT INTO hedge_fund.signal_promotion_rollback_audits" in sql
    assert "RETURN v_execution;" in sql


def test_operator_rollback_writes_audit_record_and_status() -> None:
    sql = _operator_rollback_sql()

    assert "CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_rollback_audits" in sql
    assert "INSERT INTO hedge_fund.signal_promotion_rollback_audits" in sql
    assert "rollback_status = 'rolled_back'" in sql
    assert "deleted_market_signal_ids" in sql
    assert "completed_at" in sql
    assert "UPDATE hedge_fund.signal_promotion_executions" in sql


def test_operator_rollback_requires_authorized_admin_before_execution_lookup() -> None:
    sql = _operator_rollback_sql()

    operator_lookup = sql.index("FROM hedge_fund.signal_operator_memberships")
    execution_lookup = sql.index("FROM hedge_fund.signal_promotion_executions")
    assert operator_lookup < execution_lookup
    assert "role = 'signal_admin'" in sql
    assert "Active signal admin membership is required for guarded promotion rollback" in sql


def test_operator_rollback_refuses_nonexistent_execution() -> None:
    sql = _operator_rollback_sql()

    assert "WHERE id = p_execution_id" in sql
    assert "No guarded promotion execution found for rollback" in sql


def test_operator_rollback_refuses_unaudited_execution_rows() -> None:
    sql = _operator_rollback_sql()

    assert "FROM hedge_fund.signal_promotion_execution_rows r" in sql
    assert "WHERE r.execution_id = v_execution.id" in sql
    assert "Guarded rollback requires audited market_signal rows for execution_id" in sql


def test_operator_rollback_refuses_partial_live_audit_set() -> None:
    sql = _operator_rollback_sql()

    assert "cardinality(v_deleted_market_signal_ids) <> cardinality(v_audited_market_signal_ids)" in sql
    assert "Guarded rollback requires all audited market_signal rows to still be live" in sql


def test_operator_rollback_preserves_unaudited_market_signals() -> None:
    sql = _operator_rollback_sql()
    delete_block = sql.split("DELETE FROM hedge_fund.market_signals", 1)[1].split(
        "RETURNING ms.id", 1
    )[0]

    assert "USING hedge_fund.signal_promotion_execution_rows r" in delete_block
    assert "ms.id = r.market_signal_id" in delete_block
    assert "ticker" not in delete_block.lower()
    assert "candidate_bar_date" not in delete_block.lower()
    assert "rollback_marker" not in delete_block.lower()


def test_operator_rollback_drill_exposes_boolean_action_eligibility() -> None:
    sql = _operator_rollback_sql()

    assert "rollback_eligibility = 'ELIGIBLE' AS rollback_eligible" in sql
    assert "audit_attempted_at AS rollback_attempted_at" in sql


def test_rollback_drill_preview_only_includes_audited_market_signal_ids() -> None:
    sql = _rollback_drill_sql()

    assert "CREATE OR REPLACE VIEW hedge_fund.v_signal_promotion_rollback_drill" in sql
    assert "LEFT JOIN hedge_fund.signal_promotion_execution_rows r" in sql
    assert "LEFT JOIN hedge_fund.market_signals ms" in sql
    assert "ON ms.id = r.market_signal_id" in sql
    assert "rollback_preview_market_signal_ids" in sql
    assert "cardinality(rollback_preview_market_signal_ids)::INTEGER" in sql


def test_rollback_drill_preview_does_not_match_by_ticker_or_date() -> None:
    sql = _rollback_drill_sql()
    live_signal_join = sql.split("LEFT JOIN hedge_fund.market_signals ms", 1)[1].split(
        "),\nrollup AS", 1
    )[0]

    assert "ms.id = r.market_signal_id" in live_signal_join
    assert "ticker" not in live_signal_join.lower()
    assert "candidate_bar_date" not in live_signal_join.lower()
    assert "bar_date" not in live_signal_join.lower()


def test_rollback_drill_exposes_rolled_back_visibility() -> None:
    sql = _rollback_drill_sql()
    conn = FakeConnection(
        _rollback_drill_row(
            rollback_preview_market_signal_ids=[],
            rollback_preview_count=0,
            rollback_eligibility="ALREADY_ROLLED_BACK",
            already_rolled_back=True,
            rollback_status="rolled_back",
            rollback_by="Gary Knight",
            rollback_attempted_at=dt.datetime(2026, 5, 4, 12, 30, tzinfo=dt.UTC),
            rolled_back_at=dt.datetime(2026, 5, 4, 12, 30, tzinfo=dt.UTC),
        )
    )

    result = repository.fetch_promotion_rollback_drills(conn)  # type: ignore[arg-type]

    assert "rollback_status = 'rolled_back' AS already_rolled_back" in sql
    assert "rolled_back_at AS rollback_attempted_at" in sql
    assert result[0]["already_rolled_back"] is True
    assert result[0]["rollback_eligibility"] == "ALREADY_ROLLED_BACK"
    assert result[0]["rolled_back_at"] == dt.datetime(2026, 5, 4, 12, 30, tzinfo=dt.UTC)


def test_rollback_drill_is_read_only_and_cannot_affect_unaudited_rows() -> None:
    sql = _rollback_drill_sql()
    normalized = sql.upper()

    assert " DELETE " not in normalized
    assert " UPDATE " not in normalized
    assert " INSERT " not in normalized
    assert "GRANT SELECT ON TABLE hedge_fund.v_signal_promotion_rollback_drill" in sql
    assert "GRANT EXECUTE" not in sql


def test_sql_contract_keeps_security_definer_narrow() -> None:
    sql = _guarded_execution_sql()

    assert "SECURITY DEFINER" in sql
    assert "SET search_path = pg_catalog, hedge_fund" in sql
    assert "REVOKE ALL ON FUNCTION hedge_fund.execute_guarded_signal_promotion" in sql
    assert "REVOKE ALL ON FUNCTION hedge_fund.rollback_guarded_signal_promotion" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "GRANT INSERT ON TABLE\n    hedge_fund.market_signals" not in sql
