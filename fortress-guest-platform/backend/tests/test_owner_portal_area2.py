"""
Integration tests for Area 2 — Owner Portal Onboarding & Communications.

Tests:
1. create_invite writes to owner_magic_tokens with correct expiry
2. validate_token succeeds with valid raw token
3. validate_token fails with expired / used / wrong token
4. accept_invite writes to owner_payout_accounts (Stripe Connect stubbed)
5. send_booking_alert: skips gracefully if no owner_payout_accounts row
6. send_monthly_statement: returns False if no enrolled owners
7. admin_payouts: OwnerInviteRequest validation
8. Token is consumed (used_at set) after accept
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import psycopg2
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# ── 1–4. Invite + Accept flow ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_invite_writes_token():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, _hash_token

    # Use a real property_id
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    test_email = f"test-invite-{uuid.uuid4().hex[:8]}@example.com"

    async with AsyncSessionLocal() as db:
        result = await create_invite(
            db,
            property_id=property_id,
            owner_email=test_email,
            owner_name="Test Owner",
            commission_rate=Decimal("0.3000"),
            sl_owner_id="TEST123",
        )

    assert result["token_id"] is not None
    assert result["owner_email"] == test_email
    assert "invite_url" in result
    assert "token=" in result["invite_url"]

    # Verify DB row
    raw_token = result["invite_url"].split("token=")[1].split("&")[0]
    expected_hash = _hash_token(raw_token)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT token_hash, owner_email FROM owner_magic_tokens WHERE owner_email=%s", (test_email,))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == expected_hash

@pytest.mark.asyncio
async def test_validate_token_valid():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, validate_token

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    test_email = f"test-validate-{uuid.uuid4().hex[:8]}@example.com"

    async with AsyncSessionLocal() as db:
        result = await create_invite(db, property_id=property_id,
                                     owner_email=test_email, owner_name="Test",
                                     commission_rate=Decimal("0.3000"))
        raw_token = result["invite_url"].split("token=")[1].split("&")[0]
        token_row = await validate_token(db, raw_token)

    assert token_row is not None
    assert token_row["owner_email"] == test_email

@pytest.mark.asyncio
async def test_validate_token_wrong_token():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import validate_token

    async with AsyncSessionLocal() as db:
        result = await validate_token(db, "totally-wrong-token-xyz-123")
    assert result is None

@pytest.mark.asyncio
async def test_accept_invite_writes_payout_account():
    """
    Accept creates an owner_payout_accounts row.
    Stripe calls are mocked: account creation returns a stub ID, and
    create_onboarding_link returns a fake connect.stripe.com URL so the
    full accept flow runs without hitting the real Stripe API.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, accept_invite
    from unittest.mock import AsyncMock, patch

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    test_email = f"test-accept-{uuid.uuid4().hex[:8]}@example.com"
    # Unique stub IDs per run to avoid unique-constraint collisions across runs.
    stub_account_id = f"acct_test_{uuid.uuid4().hex[:8]}"
    stub_onboarding_url = f"https://connect.stripe.com/setup/e/{stub_account_id}/test"

    # Mock both Stripe calls to avoid real API calls in this unit test.
    # The real Stripe integration is covered by test_stripe_connect_flow.py.
    with patch("backend.services.owner_onboarding.create_connect_account",
               AsyncMock(return_value={"account_id": stub_account_id, "status": "onboarding"})), \
         patch("backend.services.owner_onboarding.create_onboarding_link",
               AsyncMock(return_value=stub_onboarding_url)):

        async with AsyncSessionLocal() as db:
            invite = await create_invite(db, property_id=property_id,
                                         owner_email=test_email, owner_name="Invite Owner",
                                         commission_rate=Decimal("0.3000"))
            raw_token = invite["invite_url"].split("token=")[1].split("&")[0]
            result = await accept_invite(db, raw_token=raw_token,
                                         property_id=property_id, owner_name="Invite Owner")

    assert result["success"] is True
    assert result["stripe_account_id"] == stub_account_id
    assert result["onboarding_url"] == stub_onboarding_url

    # Verify DB row
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT owner_email, stripe_account_id, account_status "
        "FROM owner_payout_accounts WHERE property_id=%s",
        (property_id,),
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[1] == stub_account_id
    assert row[2] == "pending_kyc"

    # Token should be marked used
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT used_at FROM owner_magic_tokens WHERE owner_email=%s", (test_email,))
    token_row = cur.fetchone()
    conn.close()
    assert token_row[0] is not None  # used_at is set

# ── 5–6. Email functions skip gracefully ─────────────────────────────────────

@pytest.mark.asyncio
async def test_booking_alert_skips_for_unenrolled_property():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_emails import send_booking_alert
    from datetime import date

    fake_property_id = str(uuid.uuid4())  # not in owner_payout_accounts

    async with AsyncSessionLocal() as db:
        sent = await send_booking_alert(
            db,
            reservation_id=str(uuid.uuid4()),
            property_id=fake_property_id,
            confirmation_code="TEST-SKIP",
            guest_name="Jane Doe",
            check_in_date=date(2026, 8, 1),
            check_out_date=date(2026, 8, 5),
            total_amount=Decimal("1500.00"),
            nights=4,
        )
    assert sent is False  # no owner row → skip, not error

@pytest.mark.asyncio
async def test_monthly_statement_raises_not_implemented():
    """
    send_monthly_statement was deleted in Phase 1.5 (hardcoded 65% rate).
    It now raises NotImplementedError to prevent accidental use.
    """
    from backend.services.owner_emails import send_monthly_statement

    with pytest.raises(NotImplementedError):
        await send_monthly_statement(
            db=None, property_id=str(uuid.uuid4()), year=2026, month=3  # type: ignore
        )

# ── 7. Request model validation ───────────────────────────────────────────────

def test_owner_invite_request_validates_email():
    from pydantic import ValidationError
    from backend.api.admin_payouts import OwnerInviteRequest

    with pytest.raises(ValidationError):
        OwnerInviteRequest(
            property_id="abc",
            owner_email="not-an-email",
            owner_name="Bad Email",
        )

    valid = OwnerInviteRequest(
        property_id="abc",
        owner_email="owner@example.com",
        owner_name="Good Owner",
        commission_rate_percent=30.0,
        mailing_address_line1="123 Main St",
        mailing_address_city="Blue Ridge",
        mailing_address_state="GA",
        mailing_address_postal_code="30513",
    )
    assert valid.owner_email == "owner@example.com"
