"""
Staff Invitation API — enterprise invite-to-join flow.

Admin creates invite → email sent with token link → user sets password → account active.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_admin, hash_password
from backend.models.staff import StaffUser
from backend.models.staff_invite import StaffInvite
from backend.services.email_service import send_invite_email

logger = structlog.get_logger()
router = APIRouter()

VALID_ROLES = ("admin", "manager", "staff", "maintenance")


def _build_invite_url(token: str) -> str:
    base = settings.frontend_url.rstrip("/")
    return f"{base}/invite?token={token}"


def _invite_dict(inv: StaffInvite) -> dict:
    return {
        "id": str(inv.id),
        "email": inv.email,
        "first_name": inv.first_name,
        "last_name": inv.last_name,
        "role": inv.role,
        "status": "expired" if inv.is_expired else inv.status,
        "invited_by": str(inv.invited_by),
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class InviteRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    role: str = "staff"


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8)


class InviteResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    role: str
    status: str
    expires_at: Optional[str] = None
    email_sent: Optional[bool] = None


# ---------------------------------------------------------------------------
# Admin endpoints (require auth)
# ---------------------------------------------------------------------------
@router.post("/", response_model=InviteResponse, status_code=201)
async def create_invite(
    body: InviteRequest,
    db: AsyncSession = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
):
    """Create an invitation and send the signup email."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")

    # Check if email is already registered
    existing_user = await db.execute(
        select(StaffUser).where(StaffUser.email == body.email.lower())
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    # Check for an existing pending invite for this email
    existing_invite = await db.execute(
        select(StaffInvite)
        .where(StaffInvite.email == body.email.lower())
        .where(StaffInvite.status == "pending")
    )
    old_invite = existing_invite.scalar_one_or_none()
    if old_invite and not old_invite.is_expired:
        raise HTTPException(
            status_code=409,
            detail="A pending invitation already exists for this email. Resend or revoke it first.",
        )
    # If expired, mark it
    if old_invite and old_invite.is_expired:
        old_invite.status = "expired"

    token = secrets.token_urlsafe(48)
    expiry = datetime.utcnow() + timedelta(hours=settings.invite_expiry_hours)

    invite = StaffInvite(
        email=body.email.lower(),
        first_name=body.first_name,
        last_name=body.last_name,
        role=body.role,
        token=token,
        invited_by=admin.id,
        expires_at=expiry,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    invite_url = _build_invite_url(token)
    email_sent = send_invite_email(
        to=invite.email,
        first_name=invite.first_name,
        invite_url=invite_url,
        invited_by_name=admin.full_name,
        role=invite.role,
        expires_hours=settings.invite_expiry_hours,
    )

    logger.info(
        "invite_created",
        invite_id=str(invite.id),
        email=invite.email,
        role=invite.role,
        by=str(admin.id),
        email_sent=email_sent,
    )

    return InviteResponse(
        id=str(invite.id),
        email=invite.email,
        first_name=invite.first_name,
        last_name=invite.last_name,
        role=invite.role,
        status=invite.status,
        expires_at=invite.expires_at.isoformat(),
        email_sent=email_sent,
    )


@router.get("/")
async def list_invites(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _admin: StaffUser = Depends(require_admin),
):
    q = select(StaffInvite).order_by(StaffInvite.created_at.desc())
    if status_filter:
        q = q.where(StaffInvite.status == status_filter)
    result = await db.execute(q)
    return [_invite_dict(inv) for inv in result.scalars()]


@router.post("/{invite_id}/resend")
async def resend_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
):
    """Resend the invite email. Generates a new token and resets expiry."""
    invite = await db.get(StaffInvite, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot resend — invite is {invite.status}")

    invite.token = secrets.token_urlsafe(48)
    invite.expires_at = datetime.utcnow() + timedelta(hours=settings.invite_expiry_hours)
    await db.commit()

    invite_url = _build_invite_url(invite.token)
    email_sent = send_invite_email(
        to=invite.email,
        first_name=invite.first_name,
        invite_url=invite_url,
        invited_by_name=admin.full_name,
        role=invite.role,
        expires_hours=settings.invite_expiry_hours,
    )

    logger.info("invite_resent", invite_id=str(invite_id), email=invite.email, email_sent=email_sent)
    return {"status": "resent", "email_sent": email_sent}


@router.post("/{invite_id}/revoke")
async def revoke_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
):
    invite = await db.get(StaffInvite, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot revoke — invite is {invite.status}")

    invite.status = "revoked"
    await db.commit()
    logger.info("invite_revoked", invite_id=str(invite_id), by=str(admin.id))
    return {"status": "revoked"}


# ---------------------------------------------------------------------------
# Public endpoint (no auth) — accept an invitation
# ---------------------------------------------------------------------------
@router.get("/validate/{token}")
async def validate_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Public — check if a token is valid and return invite details."""
    result = await db.execute(select(StaffInvite).where(StaffInvite.token == token))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invitation link")
    if invite.status != "pending":
        raise HTTPException(status_code=410, detail=f"This invitation has been {invite.status}")
    if invite.is_expired:
        invite.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="This invitation has expired")

    return {
        "email": invite.email,
        "first_name": invite.first_name,
        "last_name": invite.last_name,
        "role": invite.role,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.post("/accept")
async def accept_invite(body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    """Public — accept an invitation and create the user account."""
    result = await db.execute(select(StaffInvite).where(StaffInvite.token == body.token))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invitation link")
    if invite.status != "pending":
        raise HTTPException(status_code=410, detail=f"This invitation has been {invite.status}")
    if invite.is_expired:
        invite.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="This invitation has expired. Ask your admin to resend.")

    # Check if email already taken (edge case: registered between invite and accept)
    existing = await db.execute(
        select(StaffUser).where(StaffUser.email == invite.email)
    )
    if existing.scalar_one_or_none():
        invite.status = "accepted"
        await db.commit()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try logging in.")

    user = StaffUser(
        email=invite.email,
        password_hash=hash_password(body.password),
        first_name=invite.first_name,
        last_name=invite.last_name,
        role=invite.role,
        is_active=True,
    )
    db.add(user)

    invite.status = "accepted"
    invite.accepted_at = datetime.utcnow()

    await db.commit()
    await db.refresh(user)

    logger.info(
        "invite_accepted",
        invite_id=str(invite.id),
        user_id=str(user.id),
        email=invite.email,
    )

    return {
        "status": "account_created",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
        },
    }
