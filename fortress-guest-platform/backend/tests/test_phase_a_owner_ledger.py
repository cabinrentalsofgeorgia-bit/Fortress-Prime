"""
Phase A tests — owner ledger foundation.

Tests:
1.  renting_state migration: exactly 1 property is pre_launch
2.  renting_state migration: exactly 13 active properties (among our 14 known ones)
3.  renting_state column is NOT NULL
4.  Restoration Luxury is pre_launch
5.  owner_balance_periods table exists with all columns and constraints
6.  The ledger CHECK constraint rejects a row that violates the equation
7.  get_or_create_balance_period creates a new period with 0 opening balance
    when no prior period exists
8.  get_or_create_balance_period creates a new period with the prior period's
    closing balance when a prior period exists
9.  get_or_create_balance_period is idempotent (calling twice returns same row)
10. compute_owner_statement raises 'property_not_renting' for Restoration Luxury
11. compute_owner_statement still succeeds for an active property (zero reservations)
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# The 14 known CROG properties by name (used for the active count test)
KNOWN_PROPERTIES = {
    "Above the Timberline", "Aska Escape Lodge", "Blue Ridge Lake Sanctuary",
    "Chase Mountain Dreams", "Cherokee Sunrise on Noontootla Creek",
    "Cohutta Sunset", "Creekside Green", "Fallen Timber Lodge", "High Hopes",
    "Restoration Luxury", "Riverview Lodge", "Serendipity on Noontootla Creek",
    "Skyfall", "The Rivers Edge",
}

# ── A1: renting_state migration ───────────────────────────────────────────────

def test_exactly_one_pre_launch_among_known_properties():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM properties
        WHERE renting_state = 'pre_launch'
          AND name = ANY(%s)
    """, ([list(KNOWN_PROPERTIES)],))
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1, f"Expected exactly 1 pre_launch among known properties, got {count}"

def test_thirteen_active_among_known_properties():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM properties
        WHERE renting_state = 'active'
          AND name = ANY(%s)
    """, ([list(KNOWN_PROPERTIES)],))
    count = cur.fetchone()[0]
    conn.close()
    assert count == 13, f"Expected 13 active known properties, got {count}"

def test_renting_state_is_not_nullable():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT is_nullable FROM information_schema.columns
        WHERE table_name = 'properties' AND column_name = 'renting_state'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "renting_state column missing"
    assert row[0] == "NO", "renting_state must be NOT NULL"

def test_restoration_luxury_is_pre_launch():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT renting_state FROM properties WHERE name = 'Restoration Luxury'")
    row = cur.fetchone()
    conn.close()
    assert row is not None, "Restoration Luxury not found"
    assert row[0] == "pre_launch", f"Expected pre_launch, got {row[0]}"

# ── A2: owner_balance_periods table ──────────────────────────────────────────

def test_owner_balance_periods_columns():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'owner_balance_periods'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    required = {
        "id", "owner_payout_account_id", "period_start", "period_end",
        "opening_balance", "closing_balance",
        "total_revenue", "total_commission", "total_charges",
        "total_payments", "total_owner_income",
        "status", "created_at", "updated_at",
        "approved_at", "approved_by", "paid_at", "emailed_at", "notes",
    }
    missing = required - cols
    assert not missing, f"Missing columns: {missing}"

def test_ledger_equation_constraint_rejects_invalid_row():
    """
    Inserting a row where closing_balance doesn't match the formula must fail.
    closing = opening + revenue - commission - charges - payments + income
    """
    import psycopg2.errors

    # First we need a valid owner_payout_account row
    uid = uuid.uuid4().hex[:8]
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (f"ledger-test-{uid}", f"Ledger Test {uid}", Decimal("0.3000"), "active"))
    opa_id = cur.fetchone()[0]
    conn.commit()

    # Now try to insert a row with a wrong closing_balance (should be 100, we say 999)
    with pytest.raises(Exception) as exc_info:
        cur.execute("""
            INSERT INTO owner_balance_periods
                (owner_payout_account_id, period_start, period_end,
                 opening_balance, closing_balance,
                 total_revenue, total_commission, total_charges, total_payments, total_owner_income)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (opa_id, date(2026, 3, 1), date(2026, 3, 31),
              100.00, 999.00,  # wrong: should be 100+0-0-0-0+0=100
              0.00, 0.00, 0.00, 0.00, 0.00))
        conn.commit()
    conn.rollback()
    conn.close()
    assert "chk_obp_ledger_equation" in str(exc_info.value) or "check" in str(exc_info.value).lower()

# ── A3: get_or_create_balance_period ─────────────────────────────────────────

def _make_opa_for_period_tests(uid: str) -> int:
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status,
             stripe_account_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET commission_rate = EXCLUDED.commission_rate,
                stripe_account_id = EXCLUDED.stripe_account_id,
                updated_at = now()
        RETURNING id
    """, (f"period-test-{uid}", f"Period Test {uid}", Decimal("0.3000"), "active",
          f"acct_period_{uid}"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id

@pytest.mark.asyncio
async def test_get_or_create_new_period_zero_opening():
    from backend.core.database import AsyncSessionLocal
    from backend.services.balance_period import get_or_create_balance_period

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa_for_period_tests(uid)

    async with AsyncSessionLocal() as db:
        period = await get_or_create_balance_period(
            db, opa_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
        )
        await db.commit()

    assert Decimal(str(period.opening_balance)) == Decimal("0.00"), (
        f"Expected 0.00 opening balance for first period, got {period.opening_balance}"
    )
    assert Decimal(str(period.closing_balance)) == Decimal("0.00")
    assert period.status == "draft"

@pytest.mark.asyncio
async def test_get_or_create_carries_prior_closing_balance():
    from backend.core.database import AsyncSessionLocal
    from backend.services.balance_period import get_or_create_balance_period
    from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa_for_period_tests(uid)

    async with AsyncSessionLocal() as db:
        # Create a prior period with a non-zero closing balance
        prior = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("1250.50"),
            total_revenue=Decimal("1785.00"),
            total_commission=Decimal("535.50"),
            total_charges=Decimal("0.00"),
            total_payments=Decimal("0.00"),
            total_owner_income=Decimal("1.00"),
            # 0 + 1785 - 535.50 - 0 - 0 + 1 = 1250.50 ✓
            status=StatementPeriodStatus.APPROVED.value,
        )
        db.add(prior)
        await db.flush()

        # Create March: should carry 1250.50 as opening balance
        march = await get_or_create_balance_period(
            db, opa_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
        )
        await db.commit()

    assert Decimal(str(march.opening_balance)) == Decimal("1250.50"), (
        f"Expected opening_balance=1250.50, got {march.opening_balance}"
    )
    assert Decimal(str(march.closing_balance)) == Decimal("1250.50")

@pytest.mark.asyncio
async def test_get_or_create_idempotent():
    from backend.core.database import AsyncSessionLocal
    from backend.services.balance_period import get_or_create_balance_period

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa_for_period_tests(uid)

    async with AsyncSessionLocal() as db:
        first = await get_or_create_balance_period(
            db, opa_id,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
        await db.commit()
        first_id = first.id

    async with AsyncSessionLocal() as db:
        second = await get_or_create_balance_period(
            db, opa_id,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )

    assert second.id == first_id, (
        f"Expected same row id={first_id}, got id={second.id}"
    )

# ── A4: compute_owner_statement renting_state check ──────────────────────────

@pytest.mark.asyncio
async def test_compute_owner_statement_raises_property_not_renting():
    """
    compute_owner_statement must raise StatementComputationError('property_not_renting')
    for Restoration Luxury (renting_state = 'pre_launch').
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import (
        compute_owner_statement, StatementComputationError,
    )

    # Create an enrolled owner_payout_account pointing at Restoration Luxury
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE name = 'Restoration Luxury'")
    prop_id = str(cur.fetchone()[0])
    conn.close()

    uid = uuid.uuid4().hex[:8]
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status, stripe_account_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id = EXCLUDED.stripe_account_id,
                commission_rate = EXCLUDED.commission_rate,
                updated_at = now()
        RETURNING id
    """, (prop_id, f"Restoration Owner {uid}", Decimal("0.3000"), "active",
          f"acct_restoration_{uid}"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        with pytest.raises(StatementComputationError) as exc_info:
            await compute_owner_statement(
                db, opa_id,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
            )

    assert exc_info.value.code == "property_not_renting"
    assert "Restoration Luxury" in exc_info.value.message or "pre_launch" in exc_info.value.message

@pytest.mark.asyncio
async def test_compute_owner_statement_works_for_active_property():
    """
    An active property with no reservations in the period returns a StatementResult
    with zero totals (not an error).
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]

    # Use a real active property
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM properties WHERE is_active=true AND name != 'Restoration Luxury' LIMIT 1"
    )
    prop_id = str(cur.fetchone()[0])
    conn.close()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status, stripe_account_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id = EXCLUDED.stripe_account_id,
                commission_rate = EXCLUDED.commission_rate,
                updated_at = now()
        RETURNING id
    """, (prop_id, f"Active Owner {uid}", Decimal("0.3000"), "active",
          f"acct_active_{uid}"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 1, 1),  # far future — no reservations
            period_end=date(2099, 1, 31),
        )

    assert result.total_net_to_owner == Decimal("0.00")
    assert result.reservation_count == 0
    assert result.source == "crog"

# ── Phase A.5: offboarding counts and compute guard ──────────────────────────

def test_post_offboarding_counts():
    """Post A.5 migration: exactly 13 active, 1 pre_launch, 44 offboarded, 58 total."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE renting_state = 'active')     AS n_active,
            COUNT(*) FILTER (WHERE renting_state = 'pre_launch') AS n_pre_launch,
            COUNT(*) FILTER (WHERE renting_state = 'offboarded') AS n_offboarded,
            COUNT(*)                                             AS n_total
        FROM properties
    """)
    row = cur.fetchone()
    conn.close()
    n_active, n_pre_launch, n_offboarded, n_total = row

    assert n_active == 13,     f"Expected 13 active, got {n_active}"
    assert n_pre_launch == 1,  f"Expected 1 pre_launch, got {n_pre_launch}"
    assert n_offboarded == 44, f"Expected 44 offboarded, got {n_offboarded}"
    assert n_total == 58,      f"Expected 58 total, got {n_total}"
    assert n_active + n_pre_launch + n_offboarded == n_total

def test_14_preserved_properties_have_correct_states():
    """Each of the 14 Streamline-active properties has the correct renting_state."""
    EXPECTED = {
        "50f8e859-c30c-4d4c-a32e-8c8189eebb6c": ("Above the Timberline",                 "active"),
        "8302f1c9-40d8-4d4d-99ae-f83647a15cc6": ("Aska Escape Lodge",                    "active"),
        "ba440208-cfcf-4b47-b687-0f07f0436c21": ("Blue Ridge Lake Sanctuary",             "active"),
        "ed6a2ba8-6cca-4f69-b822-4b825e44d4af": ("Chase Mountain Dreams",                "active"),
        "50a9066d-fc2e-44c4-a716-25adb8fbad3e": ("Cherokee Sunrise on Noontootla Creek", "active"),
        "53d047f9-2ba4-4ef4-bb29-22f34df279d3": ("Cohutta Sunset",                       "active"),
        "72e278a3-1dc1-4bd8-9373-ce8f234f8ea0": ("Creekside Green",                      "active"),
        "93b2253d-7ae4-4d6f-8be2-125d33799c88": ("Fallen Timber Lodge",                  "active"),
        "25e397f9-ce07-4924-9fb6-c09759aff357": ("High Hopes",                           "active"),
        "d7f4a8d3-7947-4d56-9c46-1cb37b96fd85": ("Restoration Luxury",                   "pre_launch"),
        "200780d1-2d26-494f-ae7a-5214ac0dd9e7": ("Riverview Lodge",                      "active"),
        "63bf8847-9990-4a36-9943-b6c160ce1ec4": ("Serendipity on Noontootla Creek",      "active"),
        "e22e6ef2-1d8e-4310-ad73-0a105eda0583": ("Skyfall",                              "active"),
        "7a263caf-6b0f-46cd-af22-6d1a0bfe486e": ("The Rivers Edge",                     "active"),
    }
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT id::text, name, renting_state FROM properties WHERE id::text = ANY(%s)",
        ([list(EXPECTED.keys())],),
    )
    rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()

    assert len(rows) == 14, f"Expected 14 rows, found {len(rows)}"
    for prop_id, (expected_name, expected_state) in EXPECTED.items():
        assert prop_id in rows, f"Property {expected_name} ({prop_id}) not found"
        actual_name, actual_state = rows[prop_id]
        assert actual_state == expected_state, (
            f"{actual_name}: expected renting_state={expected_state!r}, got {actual_state!r}"
        )

@pytest.mark.asyncio
async def test_compute_raises_for_offboarded_property():
    """
    compute_owner_statement must raise 'property_not_renting' for an offboarded
    property (same guard as pre_launch, but now tested with a real offboarded row).
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import (
        compute_owner_statement, StatementComputationError,
    )

    # Pick any offboarded property
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM properties WHERE renting_state='offboarded' LIMIT 1"
    )
    offboarded_prop_id = str(cur.fetchone()[0])
    conn.close()

    uid = uuid.uuid4().hex[:8]
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status, stripe_account_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id = EXCLUDED.stripe_account_id,
                commission_rate = EXCLUDED.commission_rate,
                updated_at = now()
        RETURNING id
    """, (offboarded_prop_id, f"Offboarded Owner {uid}", Decimal("0.3000"),
          "active", f"acct_offboarded_{uid}"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        with pytest.raises(StatementComputationError) as exc_info:
            await compute_owner_statement(
                db, opa_id,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
            )

    assert exc_info.value.code == "property_not_renting"
    assert "offboarded" in exc_info.value.message

@pytest.mark.asyncio
async def test_all_13_active_properties_can_compute():
    """
    Every one of the 13 actively-renting properties can produce a statement
    (zero reservations in the far future — but no error).
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    ACTIVE_IDS = [
        "50f8e859-c30c-4d4c-a32e-8c8189eebb6c",  # Above the Timberline
        "8302f1c9-40d8-4d4d-99ae-f83647a15cc6",  # Aska Escape Lodge
        "ba440208-cfcf-4b47-b687-0f07f0436c21",  # Blue Ridge Lake Sanctuary
        "ed6a2ba8-6cca-4f69-b822-4b825e44d4af",  # Chase Mountain Dreams
        "50a9066d-fc2e-44c4-a716-25adb8fbad3e",  # Cherokee Sunrise on Noontootla Creek
        "53d047f9-2ba4-4ef4-bb29-22f34df279d3",  # Cohutta Sunset
        "72e278a3-1dc1-4bd8-9373-ce8f234f8ea0",  # Creekside Green
        "93b2253d-7ae4-4d6f-8be2-125d33799c88",  # Fallen Timber Lodge
        "25e397f9-ce07-4924-9fb6-c09759aff357",  # High Hopes
        "200780d1-2d26-494f-ae7a-5214ac0dd9e7",  # Riverview Lodge
        "63bf8847-9990-4a36-9943-b6c160ce1ec4",  # Serendipity on Noontootla Creek
        "e22e6ef2-1d8e-4310-ad73-0a105eda0583",  # Skyfall
        "7a263caf-6b0f-46cd-af22-6d1a0bfe486e",  # The Rivers Edge
    ]

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    errors = []
    opa_ids = []
    uid = uuid.uuid4().hex[:8]

    for prop_id in ACTIVE_IDS:
        cur.execute("""
            INSERT INTO owner_payout_accounts
                (property_id, owner_name, commission_rate, account_status, stripe_account_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (property_id) DO UPDATE
                SET stripe_account_id = EXCLUDED.stripe_account_id,
                    commission_rate = EXCLUDED.commission_rate,
                    updated_at = now()
            RETURNING id
        """, (prop_id, f"AllActive Test {uid}", Decimal("0.3000"), "active",
              f"acct_allactive_{prop_id[:8]}_{uid}"))
        opa_ids.append(cur.fetchone()[0])
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        for opa_id, prop_id in zip(opa_ids, ACTIVE_IDS):
            try:
                result = await compute_owner_statement(
                    db, opa_id,
                    period_start=date(2099, 1, 1),
                    period_end=date(2099, 1, 31),
                )
                assert result.reservation_count == 0
            except Exception as exc:
                errors.append(f"opa_id={opa_id} prop_id={prop_id}: {exc}")

    assert not errors, "Some active properties raised during compute:\n" + "\n".join(errors)
