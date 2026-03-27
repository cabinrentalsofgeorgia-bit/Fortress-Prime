"""
Strike 11 — Sovereign Concierge: consented session ↔ guest resolution (storefront public).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.services.concierge_identity_service import resolve_session_identity

logger = structlog.get_logger()

router = APIRouter()


class ConciergeResolveIn(BaseModel):
    session_id: UUID = Field(description="Same UUID as intent lane / fgp_storefront_session_id")
    consent_recovery_contact: bool = Field(
        ...,
        description="Must be true — guest opts in to recovery SMS/email about this trip.",
    )
    flow: Literal["save_quote", "booking_field_blur"] = "booking_field_blur"
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    guest_first_name: str | None = Field(default=None, max_length=100)
    guest_last_name: str | None = Field(default=None, max_length=100)
    property_slug: str | None = Field(default=None, max_length=255)

    @field_validator("email", "phone", "guest_first_name", "guest_last_name", mode="before")
    @classmethod
    def _strip_optional(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class ConciergeResolveOut(BaseModel):
    status: Literal["ok"] = "ok"
    linked: bool
    guest_id: UUID | None = None
    created_guest: bool = False


@router.post("/resolve", response_model=ConciergeResolveOut)
async def post_concierge_resolve(
    body: ConciergeResolveIn,
    db: AsyncSession = Depends(get_db),
) -> ConciergeResolveOut:
    if not body.consent_recovery_contact:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="consent_recovery_contact must be true to resolve identity",
        )
    try:
        outcome = await resolve_session_identity(
            db,
            session_id=body.session_id,
            consent_recovery_contact=body.consent_recovery_contact,
            flow=body.flow,
            email=body.email,
            phone=body.phone,
            guest_first_name=body.guest_first_name,
            guest_last_name=body.guest_last_name,
            property_slug=body.property_slug,
        )
    except ProgrammingError as exc:
        await db.rollback()
        logger.warning("concierge_resolve_table_missing", error=str(exc)[:200])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Concierge ledger not migrated — run alembic upgrade head",
        ) from exc

    return ConciergeResolveOut(
        linked=outcome.linked,
        guest_id=outcome.guest_id,
        created_guest=outcome.created_guest,
    )
