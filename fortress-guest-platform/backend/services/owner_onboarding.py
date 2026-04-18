"""
Owner Onboarding Service
========================
Manages the invite-token → Stripe Connect Express onboarding flow.

Flow:
  1. Admin calls POST /api/admin/payouts/invites  (create_invite)
     → generates a random token, hashes it, stores in owner_magic_tokens
     → sends invite email with a link containing the raw token
  2. Owner clicks the link → GET /owner/accept-invite?token=<raw>&email=<email>
     → storefront page validates token via GET /api/owner/invite/validate
     → shows invitation card with Accept button
  3. Owner submits form → POST /api/owner/invite/accept  (accept_invite)
     → Stripe Connect Express account created via stripe.Account.create(type="express")
     → AccountLink generated via stripe.AccountLink.create() — Stripe-hosted KYC
     → row inserted into owner_payout_accounts with stripe_account_id='pending_kyc'
     → token marked used
     → response includes onboarding_url (real connect.stripe.com URL)
  4. Owner completes Stripe onboarding
     → Stripe fires account.updated webhook
     → stripe_connect_webhooks._handle_account_updated sets account_status='active'

Note: STRIPE_CONNECT_CLIENT_ID is for Standard OAuth Connect and is NOT required
for Express accounts. create_connect_account() and create_onboarding_link() both
work with STRIPE_SECRET_KEY alone (sk_test_... in sandbox).
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.services.email_service import send_email, is_email_configured
from backend.services.payout_service import create_connect_account, create_onboarding_link

logger = structlog.get_logger(service="owner_onboarding")

TOKEN_BYTES = 32           # 256-bit token
TOKEN_TTL_HOURS = 72       # 3-day window to accept invite
PORTAL_BASE_URL = os.getenv("OWNER_PORTAL_BASE_URL", "https://cabin-rentals-of-georgia.com")


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_invite(
    db: AsyncSession,
    *,
    property_id: str,
    owner_email: str,
    owner_name: str,
    commission_rate: "Decimal",
    sl_owner_id: str = "",
    invited_by: str = "admin",
    mailing_address_line1: str = "",
    mailing_address_line2: Optional[str] = None,
    mailing_address_city: str = "",
    mailing_address_state: str = "",
    mailing_address_postal_code: str = "",
    mailing_address_country: str = "USA",
) -> dict:
    """
    Create an owner invite token and send an email invitation.

    commission_rate must be the fractional form (e.g. Decimal("0.3000") for 30%).
    It is stored on the token so it is available when the owner accepts.

    Returns:
        {token_id, owner_email, expires_at, email_sent, invite_url}
    """
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)

    # Upsert: revoke any existing unused token for this email
    await db.execute(text("""
        UPDATE owner_magic_tokens
        SET used_at = now()
        WHERE owner_email = :email AND used_at IS NULL
    """), {"email": owner_email})

    result = await db.execute(text("""
        INSERT INTO owner_magic_tokens
            (token_hash, owner_email, sl_owner_id, expires_at, commission_rate,
             mailing_address_line1, mailing_address_line2,
             mailing_address_city, mailing_address_state,
             mailing_address_postal_code, mailing_address_country,
             created_at)
        VALUES
            (:hash, :email, :sl_id, :expires, :commission_rate,
             :addr1, :addr2, :city, :state, :postal, :country,
             now())
        RETURNING id
    """), {
        "hash": token_hash,
        "email": owner_email,
        "sl_id": sl_owner_id or "",
        "expires": expires_at,
        "commission_rate": commission_rate,
        "addr1": mailing_address_line1 or None,
        "addr2": mailing_address_line2 or None,
        "city": mailing_address_city or None,
        "state": mailing_address_state or None,
        "postal": mailing_address_postal_code or None,
        "country": mailing_address_country or "USA",
    })
    row = result.fetchone()
    token_id = row[0]
    await db.commit()

    invite_url = f"{PORTAL_BASE_URL}/owner/accept-invite?token={raw_token}&email={owner_email}"

    email_sent = False
    if is_email_configured():
        subject = "You're invited to the Cabin Rentals of Georgia Owner Portal"
        html_body = f"""
        <p>Hello {owner_name},</p>
        <p>You've been invited to manage your property on the Cabin Rentals of Georgia
        owner portal. Click the button below to accept the invitation and set up
        your payout account.</p>
        <p style="text-align:center;margin:32px 0;">
          <a href="{invite_url}"
             style="background:#1e293b;color:#fff;padding:14px 28px;border-radius:6px;
                    text-decoration:none;font-weight:600;font-size:15px;">
            Accept Invitation
          </a>
        </p>
        <p>This invitation expires in {TOKEN_TTL_HOURS} hours.</p>
        <p>If you didn't expect this email, you can safely ignore it.</p>
        """
        text_body = (
            f"Hello {owner_name},\n\n"
            f"Accept your owner portal invitation here:\n{invite_url}\n\n"
            f"This link expires in {TOKEN_TTL_HOURS} hours."
        )
        email_sent = send_email(owner_email, subject, html_body, text_body)

    logger.info(
        "owner_invite_created",
        token_id=token_id,
        owner_email=owner_email,
        property_id=property_id,
        email_sent=email_sent,
        invited_by=invited_by,
    )
    return {
        "token_id": token_id,
        "owner_email": owner_email,
        "expires_at": expires_at.isoformat(),
        "email_sent": email_sent,
        "invite_url": invite_url,  # for admin copy/paste if email fails
    }


async def validate_token(db: AsyncSession, raw_token: str) -> Optional[dict]:
    """Validate an invite token. Returns token row dict (including commission_rate and address) or None."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(text("""
        SELECT id, owner_email, sl_owner_id, expires_at, used_at, commission_rate,
               mailing_address_line1, mailing_address_line2,
               mailing_address_city, mailing_address_state,
               mailing_address_postal_code, mailing_address_country
        FROM owner_magic_tokens
        WHERE token_hash = :hash
    """), {"hash": token_hash})
    row = result.fetchone()
    if not row:
        return None
    if row.used_at is not None:
        return None
    if datetime.now(timezone.utc) > row.expires_at.replace(tzinfo=timezone.utc):
        return None
    return dict(row._mapping)


async def accept_invite(
    db: AsyncSession,
    *,
    raw_token: str,
    property_id: str,
    owner_name: str,
    return_url: str = "",
) -> dict:
    """
    Accept an owner invite: create Stripe Connect account, write payout row.

    Returns:
        {success, onboarding_url, stripe_account_id, message}
    """
    token_row = await validate_token(db, raw_token)
    if not token_row:
        return {"success": False, "message": "Invalid or expired invite token"}

    owner_email = token_row["owner_email"]

    # commission_rate MUST be present on the token — it was set at invite-creation time.
    raw_commission_rate = token_row.get("commission_rate")
    if raw_commission_rate is None:
        return {
            "success": False,
            "message": (
                "This invite token does not have a commission rate set. "
                "Ask the admin to create a new invite with a commission_rate_percent."
            ),
        }
    commission_rate = Decimal(str(raw_commission_rate))

    # streamline_owner_id stored in sl_owner_id as a string; convert to int if valid.
    sl_id_str = token_row.get("sl_owner_id") or ""
    streamline_owner_id: Optional[int] = None
    if sl_id_str.strip().lstrip("-").isdigit():
        streamline_owner_id = int(sl_id_str.strip())

    # Mailing address from token (may be None for legacy tokens without address)
    addr1 = token_row.get("mailing_address_line1")
    addr2 = token_row.get("mailing_address_line2")
    addr_city = token_row.get("mailing_address_city")
    addr_state = token_row.get("mailing_address_state")
    addr_postal = token_row.get("mailing_address_postal_code")
    addr_country = token_row.get("mailing_address_country") or "USA"

    # Create Stripe Connect Express account
    connect_result = await create_connect_account(owner_name, owner_email)
    stripe_account_id = connect_result["account_id"] if connect_result else None

    # Build onboarding URL — stub if Connect client_id not configured
    onboarding_url: Optional[str] = None
    if stripe_account_id:
        if not return_url:
            return_url = f"{PORTAL_BASE_URL}/owner/onboarding-complete"
        onboarding_url = await create_onboarding_link(stripe_account_id, return_url)
    if not onboarding_url:
        # Account was created but AccountLink failed — mark it in the DB and
        # surface the error so the caller can retry rather than silently stub.
        logger.error(
            "onboarding_link_generation_failed",
            stripe_account_id=stripe_account_id,
            property_id=property_id,
        )
        return {
            "success": False,
            "onboarding_url": None,
            "stripe_account_id": stripe_account_id,
            "message": (
                "Stripe Express account was created but the onboarding link could "
                "not be generated. Verify STRIPE_SECRET_KEY is valid and check "
                "server logs for the stripe_onboarding_link_failed event."
            ),
        }

    # Write to owner_payout_accounts (upsert on property_id)
    await db.execute(text("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, streamline_owner_id,
             mailing_address_line1, mailing_address_line2,
             mailing_address_city, mailing_address_state,
             mailing_address_postal_code, mailing_address_country,
             account_status, instant_payout, payout_schedule,
             minimum_payout_threshold, created_at, updated_at)
        VALUES
            (:pid, :name, :email, :stripe_id,
             :commission_rate, :streamline_owner_id,
             :addr1, :addr2, :addr_city, :addr_state, :addr_postal, :addr_country,
             'pending_kyc', false, 'monthly',
             100.00, now(), now())
        ON CONFLICT (property_id) DO UPDATE
            SET owner_name                 = EXCLUDED.owner_name,
                owner_email                = EXCLUDED.owner_email,
                stripe_account_id          = EXCLUDED.stripe_account_id,
                commission_rate            = EXCLUDED.commission_rate,
                streamline_owner_id        = EXCLUDED.streamline_owner_id,
                mailing_address_line1      = EXCLUDED.mailing_address_line1,
                mailing_address_line2      = EXCLUDED.mailing_address_line2,
                mailing_address_city       = EXCLUDED.mailing_address_city,
                mailing_address_state      = EXCLUDED.mailing_address_state,
                mailing_address_postal_code= EXCLUDED.mailing_address_postal_code,
                mailing_address_country    = EXCLUDED.mailing_address_country,
                account_status             = 'pending_kyc',
                updated_at                 = now()
    """), {
        "pid": property_id,
        "name": owner_name,
        "email": owner_email,
        "stripe_id": stripe_account_id,
        "commission_rate": commission_rate,
        "streamline_owner_id": streamline_owner_id,
        "addr1": addr1,
        "addr2": addr2,
        "addr_city": addr_city,
        "addr_state": addr_state,
        "addr_postal": addr_postal,
        "addr_country": addr_country,
    })

    # Mark token used
    await db.execute(text("""
        UPDATE owner_magic_tokens SET used_at = now()
        WHERE token_hash = :hash
    """), {"hash": _hash_token(raw_token)})

    await db.commit()

    logger.info(
        "owner_invite_accepted",
        owner_email=owner_email,
        property_id=property_id,
        stripe_account_id=stripe_account_id,
    )
    return {
        "success": True,
        "onboarding_url": onboarding_url,
        "stripe_account_id": stripe_account_id,
        "message": "Owner account created. Complete Stripe onboarding to enable payouts.",
    }
