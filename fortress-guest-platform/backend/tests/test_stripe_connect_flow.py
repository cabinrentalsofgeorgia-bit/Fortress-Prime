"""
End-to-end Stripe Connect sandbox tests.

These tests call the REAL Stripe test API — no mocks for Stripe calls.
They require STRIPE_SECRET_KEY=sk_test_... to be set in .env.

All created Stripe accounts are deleted in teardown so the test suite
remains idempotent and doesn't pollute the Stripe test dashboard.

Tests:
1. test_stripe_secret_key_is_test_mode        — guard against live keys
2. test_stripe_connect_client_id_in_settings  — config field present
3. test_stripe_express_account_creation       — Account.create() works
4. test_stripe_account_link_generation        — AccountLink.create() works
5. test_full_invite_accept_flow_with_real_stripe — complete round-trip
6. test_validate_token_valid                  — validate_token() returns row
7. test_validate_token_expired                — validate_token() returns None
8. test_validate_token_used                   — consumed token returns None
9. test_accept_invalid_token_returns_failure  — garbage token → success: False
10. test_public_validate_endpoint             — GET /api/owner/invite/validate
11. test_public_accept_endpoint_bad_token     — POST /api/owner/invite/accept 422
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# ── 1. Guard: test mode only ──────────────────────────────────────────────────

def test_stripe_secret_key_is_test_mode():
    from backend.core.config import settings
    assert settings.stripe_secret_key.startswith("sk_test_"), (
        "STRIPE_SECRET_KEY must be a test-mode key (sk_test_...). "
        "Never run Connect tests with live keys."
    )

# ── 2. Config field ───────────────────────────────────────────────────────────

def test_stripe_connect_client_id_in_settings():
    from backend.core.config import settings
    assert hasattr(settings, "stripe_connect_client_id"), (
        "stripe_connect_client_id field missing from Settings"
    )
    # Default is "" — that's fine; Express accounts don't need it
    assert isinstance(settings.stripe_connect_client_id, str)

# ── 3. Account creation (real Stripe) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_stripe_express_account_creation():
    """
    create_connect_account() creates a real Stripe Express account in test mode.
    Cleans up by deleting the account after assertion.
    """
    from backend.services.payout_service import create_connect_account

    result = await create_connect_account(
        owner_name="Test Owner",
        owner_email=f"test-connect-{uuid.uuid4().hex[:8]}@example.com",
    )

    assert result is not None, "create_connect_account returned None — check STRIPE_SECRET_KEY"
    assert "account_id" in result
    assert result["account_id"].startswith("acct_"), (
        f"Expected Stripe account ID starting with acct_, got: {result['account_id']}"
    )
    assert result["status"] == "onboarding"

    # Cleanup
    import stripe
    from backend.core.config import settings
    stripe.api_key = settings.stripe_secret_key
    try:
        stripe.Account.delete(result["account_id"])
    except Exception:
        pass  # Best-effort cleanup

# ── 4. Account link generation (real Stripe) ─────────────────────────────────

@pytest.mark.asyncio
async def test_stripe_account_link_generation():
    """
    create_onboarding_link() returns a real connect.stripe.com URL.
    Cleans up by deleting the account after assertion.
    """
    from backend.services.payout_service import create_connect_account, create_onboarding_link

    result = await create_connect_account(
        owner_name="Link Test Owner",
        owner_email=f"test-link-{uuid.uuid4().hex[:8]}@example.com",
    )
    assert result is not None

    account_id = result["account_id"]
    try:
        url = await create_onboarding_link(
            account_id=account_id,
            return_url="https://cabin-rentals-of-georgia.com/owner/onboarding-complete",
        )

        assert url is not None, (
            "create_onboarding_link returned None — check STRIPE_SECRET_KEY"
        )
        assert url.startswith("https://connect.stripe.com/"), (
            f"Expected Stripe-hosted onboarding URL, got: {url[:80]}"
        )
    finally:
        import stripe
        from backend.core.config import settings
        stripe.api_key = settings.stripe_secret_key
        try:
            stripe.Account.delete(account_id)
        except Exception:
            pass

# ── 5. Full invite → accept → real Stripe round-trip ─────────────────────────

@pytest.mark.asyncio
async def test_full_invite_accept_flow_with_real_stripe():
    """
    End-to-end sandbox test:
      1. Create invite token in DB
      2. Call accept_invite() — real Stripe calls, no mocks
      3. Assert onboarding_url is a real connect.stripe.com URL
      4. Assert owner_payout_accounts row created with real stripe_account_id
      5. Assert account_status == 'pending_kyc'
      6. Clean up Stripe account
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, accept_invite

    # Get a real property_id
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    uid = uuid.uuid4().hex[:8]
    test_email = f"test-e2e-{uid}@example.com"

    stripe_account_id: str | None = None
    try:
        async with AsyncSessionLocal() as db:
            # Step 1: create invite
            invite = await create_invite(
                db,
                property_id=property_id,
                owner_email=test_email,
                owner_name=f"E2E Owner {uid}",
                commission_rate=Decimal("0.3000"),
                sl_owner_id=f"TEST-{uid}",
            )

        raw_token = invite["invite_url"].split("token=")[1].split("&")[0]

        # Step 2: accept with real Stripe (no mocks)
        async with AsyncSessionLocal() as db:
            result = await accept_invite(
                db,
                raw_token=raw_token,
                property_id=property_id,
                owner_name=f"E2E Owner {uid}",
                return_url="https://cabin-rentals-of-georgia.com/owner/onboarding-complete",
            )

        # Step 3: assertions
        assert result["success"] is True, (
            f"accept_invite failed: {result.get('message')}"
        )
        assert result["onboarding_url"] is not None
        assert result["onboarding_url"].startswith("https://connect.stripe.com/"), (
            f"Expected connect.stripe.com URL, got: {result['onboarding_url'][:120]}"
        )

        stripe_account_id = result["stripe_account_id"]
        assert stripe_account_id is not None
        assert stripe_account_id.startswith("acct_")

        # Step 4: DB row exists
        conn = psycopg2.connect(DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT stripe_account_id, account_status FROM owner_payout_accounts "
            "WHERE property_id=%s",
            (property_id,),
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None, "No owner_payout_accounts row created"
        assert row[0] == stripe_account_id, (
            f"DB has {row[0]!r}, expected {stripe_account_id!r}"
        )
        assert row[1] == "pending_kyc", f"Expected 'pending_kyc', got {row[1]!r}"

        # Step 5: token marked used
        conn = psycopg2.connect(DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT used_at FROM owner_magic_tokens WHERE owner_email=%s",
            (test_email,),
        )
        token_row = cur.fetchone()
        conn.close()
        assert token_row is not None
        assert token_row[0] is not None, "Token used_at was not set after accept"

    finally:
        # Clean up Stripe account
        if stripe_account_id:
            import stripe as _stripe
            from backend.core.config import settings
            _stripe.api_key = settings.stripe_secret_key
            try:
                _stripe.Account.delete(stripe_account_id)
            except Exception:
                pass

# ── 6–8. validate_token unit tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_token_valid():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, validate_token

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    property_id = str(cur.fetchone()[0])
    conn.close()

    test_email = f"test-vt-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSessionLocal() as db:
        invite = await create_invite(
            db, property_id=property_id, owner_email=test_email, owner_name="VT Test",
            commission_rate=Decimal("0.3000"),
        )
        raw_token = invite["invite_url"].split("token=")[1].split("&")[0]
        token_row = await validate_token(db, raw_token)

    assert token_row is not None
    assert token_row["owner_email"] == test_email

@pytest.mark.asyncio
async def test_validate_token_expired():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import validate_token
    from sqlalchemy import text

    test_email = f"test-exp-{uuid.uuid4().hex[:8]}@example.com"

    # Insert an already-expired token directly
    import hashlib, secrets
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    past = datetime.now(timezone.utc) - timedelta(hours=1)

    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO owner_magic_tokens (token_hash, owner_email, sl_owner_id, expires_at)
            VALUES (:hash, :email, '', :exp)
        """), {"hash": token_hash, "email": test_email, "exp": past})
        await db.commit()
        result = await validate_token(db, raw)

    assert result is None, "Expected None for expired token"

@pytest.mark.asyncio
async def test_validate_token_already_used():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import validate_token
    from sqlalchemy import text

    test_email = f"test-used-{uuid.uuid4().hex[:8]}@example.com"

    import hashlib, secrets
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    future = datetime.now(timezone.utc) + timedelta(hours=72)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO owner_magic_tokens (token_hash, owner_email, sl_owner_id, expires_at, used_at)
            VALUES (:hash, :email, '', :exp, :used)
        """), {"hash": token_hash, "email": test_email, "exp": future, "used": now})
        await db.commit()
        result = await validate_token(db, raw)

    assert result is None, "Expected None for already-used token"

# ── 9. Garbage token → failure ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_accept_invalid_token_returns_failure():
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import accept_invite

    async with AsyncSessionLocal() as db:
        result = await accept_invite(
            db,
            raw_token="this-is-not-a-valid-token-at-all-xyz",
            property_id=str(uuid.uuid4()),
            owner_name="Nobody",
        )

    assert result["success"] is False

# ── 10–11. Public API endpoints ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_validate_endpoint_invalid_token():
    """GET /api/owner/invite/validate with bad token → 404."""
    from backend.core.database import AsyncSessionLocal
    from backend.api.owner_portal import validate_invite_token
    from fastapi import HTTPException

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await validate_invite_token(
                token="garbage-token-that-does-not-exist",
                db=db,
            )
    assert exc_info.value.status_code == 404

@pytest.mark.asyncio
async def test_public_accept_endpoint_invalid_token():
    """POST /api/owner/invite/accept with bad token → 422."""
    from backend.core.database import AsyncSessionLocal
    from backend.api.owner_portal import accept_owner_invite, InviteAcceptBody
    from fastapi import HTTPException

    body = InviteAcceptBody(
        token="garbage-token",
        property_id=str(uuid.uuid4()),
        owner_name="Nobody",
        return_url="",
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await accept_owner_invite(body=body, db=db)
    assert exc_info.value.status_code == 422
