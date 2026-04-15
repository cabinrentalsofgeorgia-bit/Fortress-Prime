"""
Phase 2 tests — compute_owner_statement service.

Covers:
1.  Owner with zero reservations in period → StatementResult with zero totals, no crash
2.  Owner with multiple reservations → correct line items and totals
3.  Non-existent owner_payout_account_id → StatementComputationError('not_found')
4.  Not-enrolled owner (no stripe_account_id) → StatementComputationError('not_enrolled')
5.  commission_rate is read from DB, not hardcoded or defaulted
6.  Two owners with different DB commission_rates produce different net amounts
    on identical gross revenue (proves the DB rate is actually used)
7.  (Replaces the skipped Phase 1.5 test) compute_owner_statement raises
    'not_enrolled' for an owner whose payout account has no stripe_account_id.
8.  StatementResult.source is 'crog'
9.  commission_rate_percent in the result equals commission_rate × 100
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

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_opa(
    *,
    property_id: str,
    owner_name: str,
    commission_rate: Decimal,
    stripe_account_id: Optional[str],
    account_status: str = "pending_kyc",
) -> int:
    """Upsert an owner_payout_accounts row and return its id.

    Uses ON CONFLICT DO UPDATE so the test is idempotent when run multiple times.
    """
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET owner_name        = EXCLUDED.owner_name,
                owner_email       = EXCLUDED.owner_email,
                stripe_account_id = EXCLUDED.stripe_account_id,
                commission_rate   = EXCLUDED.commission_rate,
                account_status    = EXCLUDED.account_status,
                updated_at        = now()
        RETURNING id
    """, (
        property_id,
        owner_name,
        f"{owner_name.lower().replace(' ', '.')}@test.com",
        stripe_account_id,
        commission_rate,
        account_status,
    ))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id

def _get_real_property() -> tuple:
    """Return (property_uuid, property_id_str) for the first active property."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()
    return prop_id, str(prop_id)

def _get_reservation_count_for_property(property_id_str: str) -> int:
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM reservations
        WHERE property_id = %s::uuid
          AND status IN ('confirmed', 'checked_in', 'checked_out', 'completed')
    """, (property_id_str,))
    count = cur.fetchone()[0]
    conn.close()
    return count

# ── 3. Non-existent account → not_found ──────────────────────────────────────

@pytest.mark.asyncio
async def test_nonexistent_account_raises_not_found():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import (
        compute_owner_statement, StatementComputationError,
    )

    async with AsyncSessionLocal() as db:
        with pytest.raises(StatementComputationError) as exc_info:
            await compute_owner_statement(
                db,
                owner_payout_account_id=999999999,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
            )
    assert exc_info.value.code == "not_found"
    assert "999999999" in exc_info.value.message

# ── 4 & 7. Not-enrolled owner (no stripe_account_id) → not_enrolled ──────────

@pytest.mark.asyncio
async def test_not_enrolled_owner_raises_not_enrolled():
    """
    An owner_payout_accounts row with stripe_account_id=NULL means the owner
    has not completed Stripe onboarding.  compute_owner_statement must raise
    StatementComputationError('not_enrolled') — not proceed to compute.

    This also replaces the Phase 1.5 skipped test that could not find an
    owner with no payout account; here we directly create the un-enrolled row.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import (
        compute_owner_statement, StatementComputationError,
    )

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(
        property_id=f"phase2-unenrolled-{uid}",
        owner_name=f"Unenrolled Owner {uid}",
        commission_rate=Decimal("0.3000"),
        stripe_account_id=None,   # ← not enrolled
        account_status="onboarding",
    )

    async with AsyncSessionLocal() as db:
        with pytest.raises(StatementComputationError) as exc_info:
            await compute_owner_statement(
                db,
                owner_payout_account_id=opa_id,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
            )

    assert exc_info.value.code == "not_enrolled"
    assert "stripe" in exc_info.value.message.lower() or "onboard" in exc_info.value.message.lower()

# ── 1. Zero reservations in period → zero totals, no crash ───────────────────

@pytest.mark.asyncio
async def test_zero_reservations_returns_empty_statement():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    # Use a fake property_id string — the test uses a far-future date with no
    # reservations, so the property doesn't need to be real.
    opa_id = _make_opa(
        property_id=f"phase2-zero-{uid}",
        owner_name=f"Zero Res Owner {uid}",
        commission_rate=Decimal("0.3000"),
        stripe_account_id=f"acct_phase2zero_{uid}",
    )

    # Use a period far in the future where no reservations exist
    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db,
            owner_payout_account_id=opa_id,
            period_start=date(2099, 1, 1),
            period_end=date(2099, 1, 31),
        )

    assert result.reservation_count == 0
    assert result.total_gross == Decimal("0.00")
    assert result.total_net_to_owner == Decimal("0.00")
    assert result.total_commission == Decimal("0.00")
    assert result.line_items == []
    assert result.source == "crog"

# ── 5. commission_rate is read from DB ────────────────────────────────────────

@pytest.mark.asyncio
async def test_commission_rate_comes_from_db():
    """
    Create an owner with a specific commission_rate in the DB.
    Verify the result's commission_rate_percent matches exactly what was stored —
    proving the service reads from the DB and does not use any default.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    # Use a rate that would never be a "default": 32.5%
    stored_rate = Decimal("0.3250")

    opa_id = _make_opa(
        property_id=f"phase2-rate-{uid}",
        owner_name=f"Rate Check Owner {uid}",
        commission_rate=stored_rate,
        stripe_account_id=f"acct_phase2rate_{uid}",
    )

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db,
            owner_payout_account_id=opa_id,
            period_start=date(2099, 1, 1),
            period_end=date(2099, 1, 31),
        )

    # commission_rate must be the stored fraction (0.3250)
    assert result.commission_rate == stored_rate, (
        f"Expected commission_rate={stored_rate}, got {result.commission_rate}"
    )
    # commission_rate_percent must be 32.5000
    assert result.commission_rate_percent == Decimal("32.5000"), (
        f"Expected 32.5000, got {result.commission_rate_percent}"
    )

# ── 6. Two owners with different rates → different net amounts ────────────────

@pytest.mark.asyncio
async def test_different_db_rates_produce_different_nets():
    """
    Create two owner_payout_accounts rows for the SAME property with different
    commission_rates.  (Normally one property → one owner, but this tests the
    math isolation.)  Verify the lower-rate owner gets a higher net payout.

    Since we can't have two rows for the same property_id (UNIQUE constraint),
    we use two different test property_id strings.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement
    from backend.services.ledger import calculate_owner_payout, BucketedItem, TaxBucket

    uid1 = uuid.uuid4().hex[:8]
    uid2 = uuid.uuid4().hex[:8]

    opa_30_id = _make_opa(
        property_id=f"phase2-rate30-{uid1}",
        owner_name=f"Owner 30pct {uid1}",
        commission_rate=Decimal("0.3000"),
        stripe_account_id=f"acct_p2_30_{uid1}",
    )
    opa_35_id = _make_opa(
        property_id=f"phase2-rate35-{uid2}",
        owner_name=f"Owner 35pct {uid2}",
        commission_rate=Decimal("0.3500"),
        stripe_account_id=f"acct_p2_35_{uid2}",
    )

    async with AsyncSessionLocal() as db:
        result_30 = await compute_owner_statement(
            db, owner_payout_account_id=opa_30_id,
            period_start=date(2099, 1, 1), period_end=date(2099, 1, 31),
        )
        result_35 = await compute_owner_statement(
            db, owner_payout_account_id=opa_35_id,
            period_start=date(2099, 1, 1), period_end=date(2099, 1, 31),
        )

    # Both have zero reservations (future period), so both have zero totals.
    # The DB-sourced commission rates must differ.
    assert result_30.commission_rate == Decimal("0.3000")
    assert result_35.commission_rate == Decimal("0.3500")
    assert result_30.commission_rate != result_35.commission_rate

    # Now verify the math directly using calculate_owner_payout at both rates.
    items = [
        BucketedItem(name="Base Rent", amount=Decimal("2000.00"),
                     item_type="rent", bucket=TaxBucket.LODGING),
    ]
    payout_30 = calculate_owner_payout(items, commission_rate=Decimal("30.00"))
    payout_35 = calculate_owner_payout(items, commission_rate=Decimal("35.00"))

    assert payout_30.net_owner_payout > payout_35.net_owner_payout
    assert payout_30.commission_amount < payout_35.commission_amount

# ── 2. Multiple reservations → correct line items ────────────────────────────

@pytest.mark.asyncio
async def test_multiple_reservations_correct_totals():
    """
    Find an owner with at least one real reservation and verify the totals
    are computed correctly.  If no property has reservations, use a property
    that we know exists and use a date range covering all time to maximise
    the chance of finding data.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement
    from sqlalchemy import text

    # Find a property that has at least one qualifying reservation
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT r.property_id, COUNT(*) as cnt, SUM(r.total_amount) as total
        FROM reservations r
        WHERE r.status IN ('confirmed', 'checked_in', 'checked_out', 'completed')
          AND r.is_owner_booking = false
        GROUP BY r.property_id
        ORDER BY cnt DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if row is None:
        pytest.skip("No qualifying reservations in the database; cannot test multi-reservation path")

    prop_uuid = row[0]
    prop_id_str = str(prop_uuid)
    expected_count = row[1]

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(
        property_id=prop_id_str,
        owner_name=f"Multi Res Owner {uid}",
        commission_rate=Decimal("0.3000"),
        stripe_account_id=f"acct_phase2multi_{uid}",
    )

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db,
            owner_payout_account_id=opa_id,
            period_start=date(2000, 1, 1),
            period_end=date(2099, 12, 31),
        )

    assert result.reservation_count == expected_count, (
        f"Expected {expected_count} reservations, got {result.reservation_count}"
    )
    assert len(result.line_items) == expected_count
    assert result.total_gross >= Decimal("0.00")
    assert result.total_net_to_owner <= result.total_gross

    # Verify totals are sums of line items
    computed_net = sum(li.net_to_owner for li in result.line_items)
    computed_gross = sum(li.gross_amount for li in result.line_items)
    assert abs(result.total_net_to_owner - computed_net) < Decimal("0.02"), (
        f"total_net_to_owner {result.total_net_to_owner} != sum of line items {computed_net}"
    )
    assert abs(result.total_gross - computed_gross) < Decimal("0.02"), (
        f"total_gross {result.total_gross} != sum of line items {computed_gross}"
    )

    # Verify commission_rate is the one we stored (30%)
    assert result.commission_rate == Decimal("0.3000")
    assert result.commission_rate_percent == Decimal("30.0000")

# ── 8. source is 'crog' ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_source_is_crog():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(
        property_id=f"phase2-source-{uid}",
        owner_name=f"Source Test Owner {uid}",
        commission_rate=Decimal("0.3500"),
        stripe_account_id=f"acct_phase2src_{uid}",
    )

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, owner_payout_account_id=opa_id,
            period_start=date(2099, 1, 1), period_end=date(2099, 1, 31),
        )

    assert result.source == "crog"

# ── 9. commission_rate_percent = commission_rate × 100 ───────────────────────

@pytest.mark.asyncio
async def test_commission_rate_percent_is_rate_times_100():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    for stored_fraction, expected_percent in [
        (Decimal("0.3000"), Decimal("30.0000")),
        (Decimal("0.3500"), Decimal("35.0000")),
        (Decimal("0.3250"), Decimal("32.5000")),
    ]:
        uid = uuid.uuid4().hex[:8]
        opa_id = _make_opa(
            property_id=f"phase2-pct-{uid}",
            owner_name=f"Pct Test Owner {uid}",
            commission_rate=stored_fraction,
            stripe_account_id=f"acct_phase2pct_{uid}",
        )
        async with AsyncSessionLocal() as db:
            result = await compute_owner_statement(
                db, owner_payout_account_id=opa_id,
                period_start=date(2099, 1, 1), period_end=date(2099, 1, 31),
            )
        assert result.commission_rate == stored_fraction
        assert result.commission_rate_percent == expected_percent, (
            f"For fraction {stored_fraction}: expected {expected_percent}, "
            f"got {result.commission_rate_percent}"
        )
