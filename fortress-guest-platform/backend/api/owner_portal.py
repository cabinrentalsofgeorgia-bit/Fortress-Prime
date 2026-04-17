"""
Owner Portal API — public endpoints for the invite acceptance flow.

These endpoints require NO JWT auth. The raw invite token is the credential.
Called from the storefront /owner/accept-invite page.

  GET  /api/owner/invite/validate?token=...  — validate token, return owner info
  POST /api/owner/invite/accept              — accept invite, return Stripe onboarding URL
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.services.owner_onboarding import validate_token, accept_invite

logger = structlog.get_logger(service="owner_portal_api")

# No auth dependency — this router is intentionally public.
# The raw token in the request body / query param IS the credential.
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class InviteAcceptBody(BaseModel):
    token: str
    property_id: str
    owner_name: str
    return_url: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/invite/validate")
async def validate_invite_token(
    token: str = Query(..., description="Raw invite token from the email link"),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate an owner invite token before the owner clicks Accept.

    Returns 404 if the token is invalid, expired, or already used.
    """
    token_row = await validate_token(db, token)
    if not token_row:
        raise HTTPException(
            status_code=404,
            detail={"valid": False, "message": "This invite link is invalid or has expired."},
        )

    owner_email = token_row.get("owner_email", "")

    # Optionally surface property name if a pending payout account already exists.
    property_name: Optional[str] = None
    try:
        result = await db.execute(
            text("""
                SELECT p.name
                FROM owner_payout_accounts opa
                JOIN properties p ON p.id::text = opa.property_id
                WHERE opa.owner_email = :email
                LIMIT 1
            """),
            {"email": owner_email},
        )
        row = result.fetchone()
        if row:
            property_name = row[0]
    except Exception:
        pass  # Non-critical enrichment — continue without it

    from datetime import timezone
    expires_at = token_row.get("expires_at")
    expires_iso = (
        expires_at.replace(tzinfo=timezone.utc).isoformat()
        if expires_at and not getattr(expires_at, "tzinfo", None)
        else expires_at.isoformat() if expires_at else None
    )

    return {
        "valid": True,
        "owner_email": owner_email,
        "property_name": property_name,
        "expires_at": expires_iso,
    }


@router.post("/invite/accept")
async def accept_owner_invite(
    body: InviteAcceptBody,
    db: AsyncSession = Depends(get_db),
):
    """
    Accept an owner invite and begin Stripe Connect Express onboarding.

    Creates a Stripe Express account, generates an AccountLink URL (Stripe-hosted
    KYC), writes the owner_payout_accounts row, and marks the token used.

    The caller should immediately redirect the owner to `onboarding_url`.
    """
    result = await accept_invite(
        db,
        raw_token=body.token,
        property_id=body.property_id,
        owner_name=body.owner_name,
        return_url=body.return_url,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=422,
            detail=result.get("message", "Invite acceptance failed"),
        )

    logger.info(
        "owner_invite_accepted_via_portal",
        property_id=body.property_id,
        stripe_account_id=result.get("stripe_account_id"),
    )
    return result
