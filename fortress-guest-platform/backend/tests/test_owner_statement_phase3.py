"""
Phase 3 tests — statement comparison infrastructure.

Tests compare_statements() with mocked StatementResult objects.
fetch_streamline_statement_normalized() is tested only as a stub that
returns None (the current state, pending product owner decision on how
to extract financial data from Streamline's PDF-only response).

Tests:
1.  match_case: identical totals → status='match', winner='crog', diff_cents=0
2.  mismatch_case: totals differ by > $0.01 → status='mismatch',
    winner='streamline', diff_cents correct
3.  tolerance_exact_penny: diff == $0.01 → status='match'
4.  tolerance_two_cents: diff == $0.02 → status='mismatch'
5.  streamline_unavailable: streamline=None → status='streamline_unavailable',
    winner='crog', diff_cents=0
6.  malformed_streamline: StatementResult with all zeros (Streamline returned
    no useful data) → status='mismatch' (compared against non-zero crog total)
7.  mismatched_fields_populated: mismatch reports crog and streamline amounts
8.  gross_comparison_included: if streamline has gross data, it's compared too
9.  property_not_found_fix: compute_owner_statement raises 'property_not_found'
    for a valid UUID that doesn't exist in properties table
10. fetch_streamline_statement_normalized_returns_none (stub test)

Phase 3 does NOT include an integration test against real Streamline because
GetMonthEndStatement returns no financial data in JSON (see Phase 3 report).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

_PERIOD = (date(2026, 3, 1), date(2026, 3, 31))


# ── Factory: build a StatementResult for testing ──────────────────────────────

def _make_statement_result(
    *,
    owner_payout_account_id: int = 1,
    total_net_to_owner: Decimal,
    total_gross: Decimal = Decimal("0.00"),
    total_commission: Decimal = Decimal("0.00"),
    total_cc_processing: Decimal = Decimal("0.00"),
    total_pass_through: Decimal = Decimal("0.00"),
    source: str = "crog",
):
    from backend.services.statement_computation import StatementResult
    return StatementResult(
        owner_payout_account_id=owner_payout_account_id,
        owner_name="Test Owner",
        owner_email=None,
        property_id="test-prop",
        property_name="Test Property",
        period_start=_PERIOD[0],
        period_end=_PERIOD[1],
        commission_rate=Decimal("0.3000"),
        commission_rate_percent=Decimal("30.0000"),
        line_items=[],
        total_gross=total_gross,
        total_pass_through=total_pass_through,
        total_commission=total_commission,
        total_cc_processing=total_cc_processing,
        total_net_to_owner=total_net_to_owner,
        reservation_count=0,
        source=source,
    )


# ── 1. Match case ─────────────────────────────────────────────────────────────

def test_match_identical_totals():
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("5000.00"))
    sl = _make_statement_result(total_net_to_owner=Decimal("5000.00"), source="streamline")

    result = compare_statements(crog, sl)

    assert result.status == "match"
    assert result.winner == "crog"
    assert result.diff_cents == 0
    assert result.crog_total_cents == 500000
    assert result.streamline_total_cents == 500000
    assert result.mismatched_fields == []


# ── 2. Mismatch case ──────────────────────────────────────────────────────────

def test_mismatch_totals_differ():
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("5000.00"))
    sl = _make_statement_result(total_net_to_owner=Decimal("4850.00"), source="streamline")

    result = compare_statements(crog, sl)

    assert result.status == "mismatch"
    assert result.winner == "streamline"
    assert result.diff_cents == 15000  # $150.00 difference
    assert result.crog_total_cents == 500000
    assert result.streamline_total_cents == 485000
    assert len(result.mismatched_fields) >= 1
    assert "net_to_owner" in result.mismatched_fields[0]
    assert "150.00" in result.mismatched_fields[0]


# ── 3. Tolerance: $0.01 diff = match ─────────────────────────────────────────

def test_tolerance_one_cent_is_match():
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("5000.00"))
    sl = _make_statement_result(total_net_to_owner=Decimal("4999.99"), source="streamline")

    result = compare_statements(crog, sl)

    assert result.status == "match", (
        f"Expected match within $0.01 tolerance, got {result.status} diff={result.diff_cents}"
    )
    assert result.diff_cents == 1  # exactly 1 cent
    assert result.winner == "crog"


# ── 4. Tolerance: $0.02 diff = mismatch ──────────────────────────────────────

def test_tolerance_two_cents_is_mismatch():
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("5000.00"))
    sl = _make_statement_result(total_net_to_owner=Decimal("4999.98"), source="streamline")

    result = compare_statements(crog, sl)

    assert result.status == "mismatch"
    assert result.diff_cents == 2
    assert result.winner == "streamline"


# ── 5. Streamline unavailable ─────────────────────────────────────────────────

def test_streamline_unavailable():
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("5000.00"))

    result = compare_statements(crog, None)

    assert result.status == "streamline_unavailable"
    assert result.winner == "crog"
    assert result.diff_cents == 0
    assert result.crog_total_cents == 500000
    assert result.streamline_total_cents is None
    assert result.mismatched_fields == []


# ── 6. Malformed streamline (all zeros) ──────────────────────────────────────

def test_streamline_all_zeros_treated_as_mismatch():
    """
    If Streamline returns a result that parsed to all zeros (e.g., PDF extraction
    failed and we filled zeros), it will differ from a non-zero Crog total.
    This should show as mismatch, not match.
    """
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("5000.00"))
    sl_zeros = _make_statement_result(
        total_net_to_owner=Decimal("0.00"), source="streamline"
    )

    result = compare_statements(crog, sl_zeros)

    assert result.status == "mismatch"
    assert result.winner == "streamline"
    assert result.diff_cents == 500000


# ── 7. mismatched_fields content ──────────────────────────────────────────────

def test_mismatched_fields_human_readable():
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(total_net_to_owner=Decimal("3500.00"))
    sl = _make_statement_result(
        total_net_to_owner=Decimal("3200.00"), source="streamline"
    )

    result = compare_statements(crog, sl)

    assert result.status == "mismatch"
    assert len(result.mismatched_fields) == 1
    field_desc = result.mismatched_fields[0]
    assert "net_to_owner" in field_desc
    assert "$3,500.00" in field_desc or "3500" in field_desc
    assert "$3,200.00" in field_desc or "3200" in field_desc
    assert "300.00" in field_desc or "30000" in field_desc  # diff


# ── 8. Gross comparison included when streamline has gross data ───────────────

def test_gross_comparison_included_when_available():
    """
    When the streamline result has a non-zero total_gross (i.e., if/when
    financial data extraction is implemented), gross differences are also
    reported in mismatched_fields.
    """
    from backend.services.statement_comparison import compare_statements

    crog = _make_statement_result(
        total_net_to_owner=Decimal("5000.00"),
        total_gross=Decimal("7000.00"),
        total_commission=Decimal("2100.00"),
    )
    sl = _make_statement_result(
        total_net_to_owner=Decimal("4950.00"),  # different net
        total_gross=Decimal("6900.00"),          # different gross
        total_commission=Decimal("2100.00"),     # same commission
        source="streamline",
    )

    result = compare_statements(crog, sl)

    assert result.status == "mismatch"
    field_names = [f.split(":")[0] for f in result.mismatched_fields]
    assert "net_to_owner" in field_names
    assert "gross" in field_names
    # Commission matches, so it should NOT be in mismatched_fields
    assert "commission" not in field_names


# ── 9. property_not_found fix (Phase 3 bug fix) ───────────────────────────────

@pytest.mark.asyncio
async def test_property_not_found_raises_error():
    """
    compute_owner_statement must raise StatementComputationError('property_not_found')
    when the owner_payout_accounts.property_id is a valid UUID that does not
    exist in the properties table.  (Fixed in Phase 3 as part of Clarification 2.)
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import (
        compute_owner_statement, StatementComputationError,
    )

    # Create an OPA row with a valid-format UUID that doesn't exist in properties
    non_existent_uuid = str(uuid.uuid4())
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id = EXCLUDED.stripe_account_id,
                commission_rate   = EXCLUDED.commission_rate,
                updated_at        = now()
        RETURNING id
    """, (
        non_existent_uuid,
        "Phantom Owner",
        "phantom@test.com",
        f"acct_phantom_{uuid.uuid4().hex[:8]}",
        Decimal("0.3000"),
        "active",
    ))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        with pytest.raises(StatementComputationError) as exc_info:
            await compute_owner_statement(
                db,
                owner_payout_account_id=opa_id,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
            )

    assert exc_info.value.code == "property_not_found"
    assert non_existent_uuid in exc_info.value.message


# ── 10. fetch_streamline_statement_normalized stub ───────────────────────────

@pytest.mark.asyncio
async def test_streamline_normalized_returns_none():
    """
    fetch_streamline_statement_normalized currently always returns None because
    GetMonthEndStatement returns no financial data in JSON.
    The stub must not raise and must return None.
    """
    from backend.services.statement_comparison import fetch_streamline_statement_normalized

    result = await fetch_streamline_statement_normalized(
        streamline_owner_id=503499,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )
    assert result is None


# ── ComparisonResult model validation ─────────────────────────────────────────

def test_comparison_result_model():
    from backend.services.statement_comparison import ComparisonResult

    cr = ComparisonResult(
        status="match",
        winner="crog",
        diff_cents=0,
        crog_total_cents=500000,
        streamline_total_cents=500000,
        mismatched_fields=[],
    )
    assert cr.status == "match"
    assert cr.winner == "crog"
    assert cr.diff_cents == 0
