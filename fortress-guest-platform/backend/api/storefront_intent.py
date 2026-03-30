"""
Consented storefront intent events + Sovereign Nudge eligibility.

Public routes — must stay free of PII in payloads (validated).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.storefront_intent import StorefrontIntentEvent

logger = structlog.get_logger()

router = APIRouter()

EVENT_WEIGHTS: dict[str, float] = {
    "page_view": 0.5,
    "property_view": 1.0,
    "quote_open": 2.0,
    "checkout_step": 3.0,
    # Observability only; does not currently affect nudge eligibility.
    "insight_impression": 0.0,
    # Server-emitted only — checkout hold created (post-email submit).
    "funnel_hold_started": 4.0,
    # Consented concierge resolve (Strike 11).
    "concierge_identity_resolved": 3.5,
}

BANNED_META_KEYS = frozenset(
    {
        "email",
        "mail",
        "e-mail",
        "phone",
        "tel",
        "telephone",
        "mobile",
        "password",
        "ssn",
        "creditcard",
        "credit_card",
        "card",
    }
)

_EMAILISH = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _session_fingerprint(session_id: UUID) -> str:
    pepper = (settings.audit_log_signing_key or "").strip().encode()
    if not pepper:
        pepper = b"fortress-dev-storefront-intent-pepper"
    return hmac.new(pepper, str(session_id).encode("utf-8"), hashlib.sha256).hexdigest()


def _sanitize_meta(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in raw.items():
        lk = str(key).lower()
        if lk in BANNED_META_KEYS:
            continue
        if isinstance(val, dict):
            nested = _sanitize_meta(val)
            if nested:
                out[key] = nested
        elif isinstance(val, (bool, int, float)):
            out[key] = val
        elif isinstance(val, str):
            if lk in BANNED_META_KEYS:
                continue
            if _EMAILISH.match(val.strip()):
                continue
            if len(val) > 500:
                continue
            out[key] = val
    return out


class IntentEventIn(BaseModel):
    session_id: UUID
    event_type: Literal[
        "page_view",
        "property_view",
        "quote_open",
        "checkout_step",
        "insight_impression",
        "consent_granted",
        "consent_revoked",
        "nudge_dismissed",
    ]
    consent_marketing: bool = False
    property_slug: str | None = Field(default=None, max_length=255)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("property_slug")
    @classmethod
    def _slug_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip().lower()
        if not s or len(s) > 255:
            return None
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", s):
            raise ValueError("property_slug must be alphanumeric with hyphens")
        return s


class IntentEventAck(BaseModel):
    status: Literal["ok"] = "ok"


class NudgeEligibilityOut(BaseModel):
    eligible: bool
    variant: str | None = None
    score_window: float = 0.0
    consent_active: bool = False


async def _marketing_consent_active(db: AsyncSession, session_fp: str) -> bool:
    stmt = (
        select(StorefrontIntentEvent)
        .where(StorefrontIntentEvent.session_fp == session_fp)
        .order_by(desc(StorefrontIntentEvent.created_at))
        .limit(200)
    )
    rows = (await db.execute(stmt)).scalars().all()
    for ev in rows:
        if ev.event_type == "consent_revoked":
            return False
        if ev.event_type == "consent_granted":
            return bool(ev.consent_marketing)
    return False


async def _nudge_dismissed_recently(db: AsyncSession, session_fp: str, *, hours: int = 168) -> bool:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(StorefrontIntentEvent.id)
        .where(
            StorefrontIntentEvent.session_fp == session_fp,
            StorefrontIntentEvent.event_type == "nudge_dismissed",
            StorefrontIntentEvent.created_at >= since,
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _score_recent(db: AsyncSession, session_fp: str, *, minutes: int = 120) -> float:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    stmt = select(StorefrontIntentEvent).where(
        StorefrontIntentEvent.session_fp == session_fp,
        StorefrontIntentEvent.created_at >= since,
    )
    rows = (await db.execute(stmt)).scalars().all()
    total = 0.0
    for ev in rows:
        total += EVENT_WEIGHTS.get(ev.event_type, 0.0)
    return total


@router.post("/event", response_model=IntentEventAck)
async def post_intent_event(body: IntentEventIn, db: AsyncSession = Depends(get_db)) -> IntentEventAck:
    fp = _session_fingerprint(body.session_id)
    meta = _sanitize_meta(body.meta)
    row = StorefrontIntentEvent(
        session_fp=fp,
        event_type=body.event_type,
        consent_marketing=body.consent_marketing,
        property_slug=body.property_slug,
        meta=meta,
    )
    try:
        db.add(row)
        await db.commit()
    except ProgrammingError as exc:
        await db.rollback()
        logger.warning("storefront_intent_table_missing", error=str(exc)[:200])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intent ledger not migrated — run alembic upgrade head",
        ) from exc

    logger.info(
        "storefront_intent_event",
        event_type=body.event_type,
        consent_marketing=body.consent_marketing,
        has_slug=bool(body.property_slug),
    )
    return IntentEventAck()


@router.get("/nudge", response_model=NudgeEligibilityOut)
async def get_nudge_eligibility(
    session_id: UUID = Query(..., description="First-party session UUID from the browser"),
    db: AsyncSession = Depends(get_db),
) -> NudgeEligibilityOut:
    fp = _session_fingerprint(session_id)
    try:
        consent = await _marketing_consent_active(db, fp)
        dismissed = await _nudge_dismissed_recently(db, fp)
        score = await _score_recent(db, fp)
    except ProgrammingError as exc:
        logger.warning("storefront_intent_nudge_table_missing", error=str(exc)[:200])
        return NudgeEligibilityOut(eligible=False, variant=None, score_window=0.0, consent_active=False)

    if not consent or dismissed:
        return NudgeEligibilityOut(
            eligible=False,
            variant=None,
            score_window=round(score, 2),
            consent_active=consent,
        )

    # Threshold tunable via settings later
    threshold = 4.0
    eligible = score >= threshold
    return NudgeEligibilityOut(
        eligible=eligible,
        variant="concierge_offer" if eligible else None,
        score_window=round(score, 2),
        consent_active=consent,
    )
