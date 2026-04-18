"""
Phase 1 tests — owner_statement_infrastructure migration.

Verifies:
1.  owner_statement_sends table exists with all required columns.
2.  owner_payout_accounts has the two new columns: commission_rate and
    streamline_owner_id.
3.  The commission_rate check constraint rejects values outside 0–0.5.
4.  OwnerStatementSend: insert a row, read it back, confirm all fields round-trip.
5.  OwnerPayoutAccount: the ORM model can insert and read a row including
    commission_rate and streamline_owner_id.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg2
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── 1. Schema checks ─────────────────────────────────────────────────────────

def test_owner_statement_sends_columns():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'owner_statement_sends'
        ORDER BY ordinal_position
    """)
    cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()

    required = {
        "id", "owner_payout_account_id", "property_id",
        "statement_period_start", "statement_period_end",
        "sent_at", "sent_to_email",
        "crog_total_amount", "streamline_total_amount",
        "source_used", "comparison_status", "comparison_diff_cents",
        "email_message_id", "error_message", "is_test", "created_at",
    }
    missing = required - set(cols.keys())
    assert not missing, f"Missing columns: {missing}"

    # is_test must be NOT NULL
    assert cols["is_test"][1] == "NO", "is_test should be NOT NULL"
    # sent_at should be nullable (filled in after successful send)
    assert cols["sent_at"][1] == "YES", "sent_at should be nullable"


def test_owner_payout_accounts_new_columns():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'owner_payout_accounts'
          AND column_name IN ('commission_rate', 'streamline_owner_id')
    """)
    cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()

    assert "commission_rate" in cols, "commission_rate column missing"
    assert cols["commission_rate"][0] == "numeric", "commission_rate must be numeric"
    assert cols["commission_rate"][1] == "NO", "commission_rate must be NOT NULL"

    assert "streamline_owner_id" in cols, "streamline_owner_id column missing"
    assert cols["streamline_owner_id"][1] == "YES", "streamline_owner_id must be nullable"


def test_commission_rate_check_constraint_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'owner_payout_accounts'
          AND c.contype = 'c'
          AND c.conname = 'chk_opa_commission_rate'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "chk_opa_commission_rate constraint missing"
    assert "0.5000" in row[0], f"Constraint text unexpected: {row[0]}"


# ── 2. OwnerPayoutAccount ORM insert / read ──────────────────────────────────

@pytest.mark.asyncio
async def test_owner_payout_account_insert_reads_back():
    from backend.core.database import AsyncSessionLocal
    from backend.models.owner_payout import OwnerPayoutAccount
    from sqlalchemy import select

    # We need a real property_id to satisfy the FK on owner_statement_sends
    # later, but owner_payout_accounts.property_id is VARCHAR so any string works.
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        opa = OwnerPayoutAccount(
            property_id=f"test-prop-{uid}",
            owner_name=f"Test Owner {uid}",
            owner_email=f"owner-{uid}@example.com",
            commission_rate=Decimal("0.3000"),
            streamline_owner_id=42,
            account_status="pending_kyc",
        )
        db.add(opa)
        await db.commit()
        await db.refresh(opa)
        opa_id = opa.id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OwnerPayoutAccount).where(OwnerPayoutAccount.id == opa_id)
        )
        loaded = result.scalar_one()

    assert loaded.owner_name == f"Test Owner {uid}"
    assert Decimal(str(loaded.commission_rate)) == Decimal("0.3000")
    assert loaded.streamline_owner_id == 42
    assert loaded.account_status == "pending_kyc"
    # No stripe_account_id on this test row, so is_enrolled should be False
    assert loaded.is_enrolled is False


def test_commission_rate_rejects_out_of_range():
    """The DB check constraint must reject commission_rate > 0.5 and < 0."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    uid = uuid.uuid4().hex[:8]

    with pytest.raises(Exception, match="chk_opa_commission_rate"):
        cur.execute("""
            INSERT INTO owner_payout_accounts
                (property_id, owner_name, commission_rate, account_status)
            VALUES (%s, %s, %s, %s)
        """, (f"bad-{uid}", "Bad Owner", Decimal("0.9000"), "onboarding"))
        conn.commit()
    conn.rollback()
    conn.close()


# ── 3. OwnerStatementSend ORM insert / read ───────────────────────────────────

@pytest.mark.asyncio
async def test_owner_statement_send_insert_reads_back():
    """
    Insert a complete OwnerStatementSend row and verify every field is
    stored and retrieved correctly.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.owner_payout import OwnerPayoutAccount, OwnerStatementSend
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:8]

    # Need a real property UUID for the FK
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        # Create parent account row.
        # Use a unique string for property_id (owner_payout_accounts.property_id is
        # VARCHAR with no FK, so any unique string is valid) to avoid colliding with
        # other tests that also use the first-active-property UUID.
        opa = OwnerPayoutAccount(
            property_id=f"phase1-test-{uid}",
            owner_name=f"Statement Test Owner {uid}",
            owner_email=f"stmt-{uid}@example.com",
            commission_rate=Decimal("0.3500"),
            streamline_owner_id=None,
            account_status="active",
            stripe_account_id=f"acct_phase1test_{uid}",
        )
        db.add(opa)
        await db.flush()

        oss = OwnerStatementSend(
            owner_payout_account_id=opa.id,
            property_id=property_id,
            statement_period_start=date(2026, 3, 1),
            statement_period_end=date(2026, 3, 31),
            sent_at=None,
            sent_to_email=f"stmt-{uid}@example.com",
            crog_total_amount=Decimal("1200.00"),
            streamline_total_amount=Decimal("1200.00"),
            source_used="crog",
            comparison_status="match",
            comparison_diff_cents=0,
            email_message_id=None,
            error_message=None,
            is_test=True,
        )
        db.add(oss)
        await db.commit()
        oss_id = oss.id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OwnerStatementSend).where(OwnerStatementSend.id == oss_id)
        )
        loaded = result.scalar_one()

    assert loaded.statement_period_start == date(2026, 3, 1)
    assert loaded.statement_period_end == date(2026, 3, 31)
    assert Decimal(str(loaded.crog_total_amount)) == Decimal("1200.00")
    assert Decimal(str(loaded.streamline_total_amount)) == Decimal("1200.00")
    assert loaded.source_used == "crog"
    assert loaded.comparison_status == "match"
    assert loaded.comparison_diff_cents == 0
    assert loaded.is_test is True
    assert loaded.sent_at is None   # not sent yet


@pytest.mark.asyncio
async def test_owner_statement_send_error_row():
    """
    A failed send should store an error_message with sent_at still null.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.owner_payout import OwnerPayoutAccount, OwnerStatementSend
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:8]

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        opa = OwnerPayoutAccount(
            property_id=f"phase1-err-{uid}",
            owner_name=f"Error Test Owner {uid}",
            owner_email=f"err-{uid}@example.com",
            commission_rate=Decimal("0.3000"),
            account_status="pending_kyc",
            stripe_account_id=f"acct_errtest_{uid}",
        )
        db.add(opa)
        await db.flush()

        oss = OwnerStatementSend(
            owner_payout_account_id=opa.id,
            property_id=property_id,
            statement_period_start=date(2026, 3, 1),
            statement_period_end=date(2026, 3, 31),
            source_used="failed",
            comparison_status="not_compared",
            error_message="SMTP connection refused: [Errno 111]",
            is_test=False,
        )
        db.add(oss)
        await db.commit()
        oss_id = oss.id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OwnerStatementSend).where(OwnerStatementSend.id == oss_id)
        )
        loaded = result.scalar_one()

    assert loaded.sent_at is None
    assert loaded.source_used == "failed"
    assert "SMTP" in loaded.error_message
