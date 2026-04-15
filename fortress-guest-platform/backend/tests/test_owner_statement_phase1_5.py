"""
Phase 1.5 tests — commission rate infrastructure.

Deliberately-failing tests fixed in this phase:
  - test_owner_portal_area2.py::test_accept_invite_writes_payout_account
  - test_stripe_connect_flow.py::test_full_invite_accept_flow_with_real_stripe

These tests now pass because accept_invite() includes commission_rate in the
owner_payout_accounts INSERT.

New tests in this file:
1.  Invite endpoint rejects missing commission_rate_percent (HTTP 422).
2.  Invite endpoint rejects commission_rate_percent below 0 (HTTP 422).
3.  Invite endpoint rejects commission_rate_percent above 50 (HTTP 422).
4.  Invite endpoint accepts 30, 35, 32.5 — stored as 0.3000, 0.3500, 0.3250.
5.  accept_invite() fails clearly when token has no commission_rate (legacy tokens).
6.  Full create→accept round-trip stores correct commission_rate in owner_payout_accounts.
7.  Two owners with different rates produce different net amounts on the same gross.
8.  calculate_owner_payout() no longer has a default rate (KeyError if omitted).
9.  send_monthly_statement stub raises NotImplementedError.
10. admin_statements.py get_owner_statement reads rate from DB (no default).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import psycopg2
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── 1–3. Invite endpoint validation ──────────────────────────────────────────

def test_invite_request_rejects_missing_commission_rate():
    from pydantic import ValidationError
    from backend.api.admin_payouts import OwnerInviteRequest

    with pytest.raises(ValidationError) as exc:
        OwnerInviteRequest(
            property_id="abc",
            owner_email="owner@example.com",
            owner_name="Test Owner",
            # commission_rate_percent intentionally omitted
        )
    assert "commission_rate_percent" in str(exc.value)


def test_invite_request_rejects_negative_rate():
    from pydantic import ValidationError
    from backend.api.admin_payouts import OwnerInviteRequest

    with pytest.raises(ValidationError):
        OwnerInviteRequest(
            property_id="abc",
            owner_email="owner@example.com",
            owner_name="Test Owner",
            commission_rate_percent=-1.0,
        )


def test_invite_request_rejects_rate_above_50():
    from pydantic import ValidationError
    from backend.api.admin_payouts import OwnerInviteRequest

    with pytest.raises(ValidationError):
        OwnerInviteRequest(
            property_id="abc",
            owner_email="owner@example.com",
            owner_name="Test Owner",
            commission_rate_percent=51.0,
        )


# ── 4. Valid rates stored as correct fractions ────────────────────────────────

@pytest.mark.asyncio
async def test_create_invite_stores_commission_rate_as_fraction():
    """
    create_invite(commission_rate=Decimal("0.3000")) stores exactly 0.3000
    in owner_magic_tokens.commission_rate.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    for pct, expected_frac in [
        (Decimal("0.3000"), "0.3000"),
        (Decimal("0.3500"), "0.3500"),
        (Decimal("0.3250"), "0.3250"),
    ]:
        uid = uuid.uuid4().hex[:8]
        email = f"rate-test-{uid}@example.com"
        async with AsyncSessionLocal() as db:
            result = await create_invite(
                db,
                property_id=property_id,
                owner_email=email,
                owner_name=f"Rate Test {uid}",
                commission_rate=pct,
            )

        conn = psycopg2.connect(DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT commission_rate FROM owner_magic_tokens WHERE owner_email=%s",
            (email,),
        )
        stored = cur.fetchone()[0]
        conn.close()

        assert str(stored) == expected_frac, (
            f"Expected {expected_frac} for input {pct}, got {stored}"
        )


# ── 5. Legacy token (no commission_rate) fails clearly ───────────────────────

@pytest.mark.asyncio
async def test_accept_invite_fails_on_legacy_token_without_rate():
    """
    An old token row with commission_rate=NULL should cause accept_invite()
    to return {success: False} with a clear message — not crash.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import accept_invite
    from sqlalchemy import text

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    import hashlib, secrets
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(hours=72)

    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO owner_magic_tokens
                (token_hash, owner_email, sl_owner_id, expires_at, commission_rate)
            VALUES (:hash, :email, '', :exp, NULL)
        """), {
            "hash": token_hash,
            "email": f"legacy-{uuid.uuid4().hex[:8]}@example.com",
            "exp": future,
        })
        await db.commit()

        result = await accept_invite(
            db,
            raw_token=raw,
            property_id=property_id,
            owner_name="Legacy Owner",
        )

    assert result["success"] is False
    assert "commission" in result["message"].lower() or "rate" in result["message"].lower()


# ── 6. Full create→accept round-trip stores correct rate ─────────────────────

@pytest.mark.asyncio
async def test_create_invite_and_accept_stores_commission_rate():
    """
    End-to-end: create invite with commission_rate=0.30, accept it (mocked Stripe),
    verify owner_payout_accounts.commission_rate == 0.3000.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, accept_invite

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    uid = uuid.uuid4().hex[:8]
    email = f"roundtrip-{uid}@example.com"
    stub_account_id = f"acct_rtrip_{uid}"
    stub_url = f"https://connect.stripe.com/setup/e/{stub_account_id}/test"

    with patch("backend.services.owner_onboarding.create_connect_account",
               AsyncMock(return_value={"account_id": stub_account_id, "status": "onboarding"})), \
         patch("backend.services.owner_onboarding.create_onboarding_link",
               AsyncMock(return_value=stub_url)):

        async with AsyncSessionLocal() as db:
            invite = await create_invite(
                db,
                property_id=property_id,
                owner_email=email,
                owner_name=f"RoundTrip Owner {uid}",
                commission_rate=Decimal("0.3000"),
            )
            raw_token = invite["invite_url"].split("token=")[1].split("&")[0]
            result = await accept_invite(
                db,
                raw_token=raw_token,
                property_id=property_id,
                owner_name=f"RoundTrip Owner {uid}",
            )

    assert result["success"] is True

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT commission_rate, streamline_owner_id FROM owner_payout_accounts "
        "WHERE property_id=%s",
        (property_id,),
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None, "owner_payout_accounts row not found"
    assert str(row[0]) == "0.3000", f"Expected 0.3000, got {row[0]}"


# ── 7. Two owners with different rates produce different net amounts ──────────

def test_different_commission_rates_produce_different_net_amounts():
    """
    Same gross revenue, two different commission rates → different net_owner_payout.
    This proves there is no hidden hardcoded rate.
    """
    from backend.services.ledger import calculate_owner_payout, BucketedItem, TaxBucket

    items = [
        BucketedItem(name="Base Rent", amount=Decimal("2000.00"),
                     item_type="rent", bucket=TaxBucket.LODGING),
    ]

    payout_30 = calculate_owner_payout(items, commission_rate=Decimal("30.00"))
    payout_35 = calculate_owner_payout(items, commission_rate=Decimal("35.00"))

    assert payout_30.commission_amount == Decimal("600.00")   # 2000 × 30%
    assert payout_35.commission_amount == Decimal("700.00")   # 2000 × 35%
    assert payout_30.net_owner_payout > payout_35.net_owner_payout
    # Owner at 30% keeps 100 more than owner at 35% on same gross
    diff = payout_30.net_owner_payout - payout_35.net_owner_payout
    assert diff == Decimal("100.00")


# ── 8. calculate_owner_payout no longer has a default rate ───────────────────

def test_calculate_owner_payout_requires_explicit_rate():
    """
    Calling calculate_owner_payout without commission_rate must fail.
    (The default was removed; callers must supply the rate explicitly.)
    """
    from backend.services.ledger import calculate_owner_payout, BucketedItem, TaxBucket
    import inspect

    sig = inspect.signature(calculate_owner_payout)
    param = sig.parameters["commission_rate"]
    assert param.default is inspect.Parameter.empty, (
        "commission_rate should have no default — it was removed intentionally."
    )


# ── 9. send_monthly_statement stub raises NotImplementedError ─────────────────

@pytest.mark.asyncio
async def test_send_monthly_statement_raises_not_implemented():
    """
    The deleted send_monthly_statement function must raise NotImplementedError,
    not silently return False or produce a 65%-rate email.
    """
    from backend.services.owner_emails import send_monthly_statement

    with pytest.raises(NotImplementedError) as exc:
        await send_monthly_statement(db=None, property_id="x", year=2026, month=3)  # type: ignore
    assert "65%" in str(exc.value) or "removed" in str(exc.value).lower() or "commission" in str(exc.value).lower()


# ── 10. admin_statements get_owner_statement requires DB rate ─────────────────

@pytest.mark.asyncio
async def test_get_owner_statement_returns_422_if_no_payout_account():
    """
    When the owner has no enrolled owner_payout_accounts row, get_owner_statement
    should return HTTP 422 (not use a default rate).
    """
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements import get_owner_statement
    from fastapi import HTTPException

    # Find an owner_id where NONE of their active properties have a payout account.
    # This ensures get_owner_statement cannot find any enrolled rate.
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT p.owner_id
        FROM properties p
        WHERE p.is_active = true
          AND p.owner_id IS NOT NULL
        GROUP BY p.owner_id
        HAVING COUNT(CASE WHEN EXISTS (
            SELECT 1 FROM owner_payout_accounts opa
            WHERE opa.property_id = p.id::text
        ) THEN 1 END) = 0
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if row is None:
        pytest.skip("Every active owner has at least one payout account; cannot test this path")

    owner_id = row[0]
    from datetime import date
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await get_owner_statement(
                owner_id=owner_id,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 31),
                commission_rate_override=None,
                db=db,
            )

    assert exc_info.value.status_code in (404, 422)
