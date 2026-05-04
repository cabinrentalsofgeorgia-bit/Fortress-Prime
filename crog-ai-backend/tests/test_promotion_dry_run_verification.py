import datetime as dt
import inspect

import pytest

from app.signals import repository


def _dry_run_row(
    *,
    ticker: str = "ACLX",
    score: int = 80,
    action: str = "BUY",
    bar_date: dt.date = dt.date(2026, 4, 24),
    parameter_set: str = "dochia_v0_2_range_daily",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "composite_score": score,
        "candidate_bar_date": bar_date,
        "lineage": {
            "parameter_set": parameter_set,
            "rollback_marker": f"dochia-dry-run:{parameter_set}:{ticker}:{bar_date}",
        },
    }


def _dry_run(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "candidate_parameter_set": "dochia_v0_2_range_daily",
        "baseline_parameter_set": "dochia_v0_estimated",
        "proposed_rows": rows,
    }


def _source_row(
    *,
    ticker: str = "ACLX",
    score: int = 80,
    monthly: int = 1,
    weekly: int = 1,
    daily: int = 1,
    bar_date: dt.date = dt.date(2026, 4, 24),
    parameter_set: str = "dochia_v0_2_range_daily",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "bar_date": bar_date,
        "parameter_set_name": parameter_set,
        "monthly_state": monthly,
        "weekly_state": weekly,
        "daily_state": daily,
        "momentum_state": 0,
        "composite_score": score,
    }


def _transition(
    *,
    ticker: str = "ACLX",
    transition_type: str = "breakout_bullish",
    from_score: int = 50,
    to_score: int = 80,
    daily: int = 1,
    to_bar_date: dt.date = dt.date(2026, 4, 24),
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "transition_type": transition_type,
        "from_score": from_score,
        "to_score": to_score,
        "from_bar_date": dt.date(2026, 4, 21),
        "to_bar_date": to_bar_date,
        "from_states": {"monthly": 1, "weekly": 1, "daily": -daily, "momentum": 0},
        "to_states": {"monthly": daily, "weekly": daily, "daily": daily, "momentum": 0},
        "detected_at": dt.datetime(2026, 5, 2, 12, 0, tzinfo=dt.UTC),
        "notes": "candidate resolved state",
    }


def _verify(
    *,
    dry_run_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
    production_rows: list[dict[str, object]] | None = None,
    transitions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return repository.verify_promotion_dry_run_payload(
        dry_run=_dry_run(dry_run_rows),
        candidate_source_rows=candidate_rows,
        production_source_rows=production_rows or [],
        candidate_transition_rows=transitions or [],
        candidate_parameter_set="dochia_v0_2_range_daily",
        production_parameter_set="dochia_v0_estimated",
    )


def test_verification_code_path_has_no_acceptance_or_market_signal_insert() -> None:
    verification_source = "\n".join(
        [
            inspect.getsource(repository._fetch_source_rows_for_dry_run),
            inspect.getsource(repository._fetch_candidate_transitions_for_dry_run),
            inspect.getsource(repository._verify_promotion_dry_run_from_payload),
            inspect.getsource(repository.fetch_promotion_dry_run_verification),
            inspect.getsource(repository.PostgresSignalDataStore.promotion_dry_run_verification),
        ]
    )

    assert "INSERT INTO hedge_fund.market_signals" not in verification_source
    assert (
        "INSERT INTO hedge_fund.signal_promotion_dry_run_acceptances"
        not in verification_source
    )
    assert "SET default_transaction_read_only = on" in verification_source


def test_store_verification_runs_in_read_only_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str, *args: object, **kwargs: object) -> None:
            executed.append(sql)

    monkeypatch.setattr(repository, "connect", lambda: FakeConnection())

    def fake_fetch_verification(*args: object, **kwargs: object) -> dict[str, object]:
        assert executed == ["SET default_transaction_read_only = on"]
        return {
            "overall_status": "PASS",
            "proposed_rows_checked": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "inconclusive_rows": 0,
            "cross_model_diagnostic_only_rows": 0,
            "rows": [],
        }

    monkeypatch.setattr(
        repository,
        "fetch_promotion_dry_run_verification",
        fake_fetch_verification,
    )

    result = repository.PostgresSignalDataStore().promotion_dry_run_verification(
        candidate_parameter_set="dochia_v0_2_range_daily"
    )

    assert result["overall_status"] == "PASS"
    assert executed == ["SET default_transaction_read_only = on"]


def test_verification_passes_cross_model_diagnostic_only_aclx_case() -> None:
    result = _verify(
        dry_run_rows=[_dry_run_row()],
        candidate_rows=[_source_row(score=80, daily=1)],
        production_rows=[
            _source_row(
                score=50,
                daily=-1,
                parameter_set="dochia_v0_estimated",
            )
        ],
        transitions=[_transition()],
    )

    assert result["overall_status"] == "PASS"
    assert result["cross_model_diagnostic_only_rows"] == 1
    assert result["rows"][0]["conflict_type"] == "CROSS_MODEL_DIAGNOSTIC_ONLY"
    assert result["rows"][0]["candidate_daily_triangle"] == 1
    assert result["rows"][0]["production_daily_triangle"] == -1


def test_verification_fails_candidate_buy_with_bearish_daily() -> None:
    result = _verify(
        dry_run_rows=[_dry_run_row(score=80, action="BUY")],
        candidate_rows=[_source_row(score=80, daily=-1)],
        transitions=[],
    )

    assert result["overall_status"] == "FAIL"
    assert result["failed_rows"] == 1
    assert result["rows"][0]["conflict_type"] == "CANDIDATE_INTERNAL_CONFLICT"
    assert "BUY while candidate daily triangle is bearish" in result["rows"][0]["explanation"]


def test_verification_fails_duplicate_same_bar_different_actions() -> None:
    result = _verify(
        dry_run_rows=[_dry_run_row(score=80, action="BUY")],
        candidate_rows=[
            _source_row(score=80, daily=1),
            _source_row(score=-80, monthly=-1, weekly=-1, daily=-1),
        ],
    )

    assert result["overall_status"] == "FAIL"
    assert result["failed_rows"] == 1
    assert result["rows"][0]["conflict_type"] == "SOURCE_LINEAGE_DUPLICATE"


def test_verification_is_inconclusive_without_traceable_candidate_source() -> None:
    result = _verify(
        dry_run_rows=[_dry_run_row()],
        candidate_rows=[],
    )

    assert result["overall_status"] == "INCONCLUSIVE"
    assert result["inconclusive_rows"] == 1
    assert result["rows"][0]["conflict_type"] == "SOURCE_LINEAGE_MISSING"


def test_verification_passes_clean_buy_with_full_alignment() -> None:
    result = _verify(
        dry_run_rows=[_dry_run_row(ticker="AEP")],
        candidate_rows=[_source_row(ticker="AEP", score=80, monthly=1, weekly=1, daily=1)],
        transitions=[],
    )

    assert result["overall_status"] == "PASS"
    assert result["passed_rows"] == 1
    assert result["rows"][0]["conflict_type"] == "NONE"


def test_acceptance_creation_blocks_failed_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository,
        "fetch_promotion_dry_run",
        lambda *args, **kwargs: {
            "generated_at": dt.datetime(2026, 5, 4, 12, 0, tzinfo=dt.UTC),
            "candidate_parameter_set": "dochia_v0_2_range_daily",
            "baseline_parameter_set": "dochia_v0_estimated",
            "approval": {
                "status": "ready_for_dry_run",
                "decision_id": "33333333-3333-3333-3333-333333333333",
                "rollback_criteria": "Rollback if verification fails.",
            },
            "summary": {
                "candidate_signal_count": 1,
                "proposed_insert_count": 1,
                "bullish_count": 1,
                "risk_count": 0,
                "skipped_neutral_count": 0,
                "target_table": "hedge_fund.market_signals",
                "target_columns": [],
            },
            "proposed_rows": [_dry_run_row()],
        },
    )
    monkeypatch.setattr(
        repository,
        "_verify_promotion_dry_run_from_payload",
        lambda *args, **kwargs: {"overall_status": "FAIL"},
    )

    with pytest.raises(ValueError, match="Dry-run verification gate blocked acceptance"):
        repository.create_promotion_dry_run_acceptance(
            object(),  # type: ignore[arg-type]
            candidate_parameter_set="dochia_v0_2_range_daily",
            accepted_by="Gary Knight",
            acceptance_rationale="Operator reviewed the dry-run.",
        )
