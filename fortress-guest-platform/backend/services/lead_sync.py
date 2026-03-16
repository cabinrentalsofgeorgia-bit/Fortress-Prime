"""
Lead Sync Service — Streamline xLead ingestion with Rule 6 sanitization.

Sanitization (Rule 6 — Data Boundary Sanitization):
  - phone:   Strip non-digits, prepend +1 for 10-digit US numbers (E.164)
  - email:   Strip whitespace, lowercase
  - message: Strip HTML tags

The Streamline GetLeads/GetXLeads endpoint is not yet mapped in our client.
sync_streamline_leads() currently uses a mock payload so the full pipeline
(sanitize -> upsert -> persist) can be validated end-to-end.
"""
import re
from typing import Dict, Any, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.lead import Lead, LeadStatus

logger = structlog.get_logger()


# ── Rule 6 Sanitizers ──────────────────────────────────────────────────────


def sanitize_phone(raw: Optional[str]) -> Optional[str]:
    """Strip non-digits; prepend +1 if exactly 10 digits (E.164 US)."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return digits or None


def sanitize_email(raw: Optional[str]) -> Optional[str]:
    """Strip whitespace, lowercase."""
    if not raw:
        return None
    return raw.strip().lower()


def sanitize_message(raw: Optional[str]) -> Optional[str]:
    """Strip HTML tags from freeform guest messages."""
    if not raw:
        return None
    return re.sub(r"<[^>]+>", "", raw).strip()


# ── Sync Pipeline ──────────────────────────────────────────────────────────


async def sync_streamline_leads(db: AsyncSession) -> Dict[str, Any]:
    """
    Ingest leads from Streamline (mocked until GetLeads is mapped).

    For each lead:
      1. Sanitize phone, email, message per Rule 6
      2. Upsert into leads table (match on streamline_lead_id)

    Returns a summary dict with created/updated counts.
    """

    # Mock payload — replace with real Streamline API call when available
    mock_leads: List[Dict[str, Any]] = [
        {
            "streamline_lead_id": "SL-10001",
            "guest_name": "Jane Doe",
            "email": "  Jane.Doe@GMAIL.COM  ",
            "phone": "(770) 555-9876",
            "guest_message": "<p>We'd love to <b>book</b> a cabin for October!</p>",
            "source": "streamline",
        },
        {
            "streamline_lead_id": "SL-10002",
            "guest_name": "Bob Smith",
            "email": "BOB@yahoo.com ",
            "phone": "4045551234",
            "guest_message": "Interested in a <a href='#'>weekend getaway</a>.",
            "source": "streamline",
        },
    ]

    created = 0
    updated = 0

    for raw_lead in mock_leads:
        sl_id = raw_lead["streamline_lead_id"]

        phone = sanitize_phone(raw_lead.get("phone"))
        email = sanitize_email(raw_lead.get("email"))
        message = sanitize_message(raw_lead.get("guest_message"))

        result = await db.execute(
            select(Lead).where(Lead.streamline_lead_id == sl_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.guest_name = raw_lead.get("guest_name") or existing.guest_name
            existing.email = email or existing.email
            existing.phone = phone or existing.phone
            existing.guest_message = message or existing.guest_message
            existing.source = raw_lead.get("source") or existing.source
            updated += 1
            logger.info("lead_updated", streamline_id=sl_id, email=email)
        else:
            lead = Lead(
                streamline_lead_id=sl_id,
                guest_name=raw_lead.get("guest_name"),
                email=email,
                phone=phone,
                guest_message=message,
                source=raw_lead.get("source"),
                status=LeadStatus.NEW.value,
            )
            db.add(lead)
            created += 1
            logger.info("lead_created", streamline_id=sl_id, email=email)

    await db.flush()

    summary = {"created": created, "updated": updated, "total": created + updated}
    logger.info("lead_sync_complete", **summary)
    return summary
