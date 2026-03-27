"""
Channex (or structurally identical aggregator) webhook ingress.

POST /api/webhooks/channex — HMAC-SHA256 body verification, normalized envelope → Kafka OTA topics.

Implemented as ``webhooks_channex.py`` (sibling to ``webhooks.py``) to avoid a ``webhooks/`` package
shadowing the existing Twilio webhook module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.config import settings
from backend.core.event_publisher import publish_event

logger = structlog.get_logger()
router = APIRouter()


class ChannexWebhookPayload(BaseModel):
    """Expected normalized shape from the aggregator; extra keys are preserved in ``raw`` when publishing."""

    model_config = ConfigDict(extra="allow")

    event: str = Field(default="", description="e.g. booking_new, booking_modification, booking_cancellation")
    payload: dict[str, Any] = Field(default_factory=dict)
    property_id: str = ""
    booking_id: str = ""


def _normalize_signature_header(value: str | None) -> str:
    if not value:
        return ""
    sig = value.strip()
    lower = sig.lower()
    if lower.startswith("sha256="):
        return sig.split("=", 1)[1].strip()
    return sig


def verify_channex_signature(payload_body: bytes, signature_header: str | None) -> bool:
    secret = (settings.channex_webhook_secret or "").strip()
    if not secret:
        return False
    sig = _normalize_signature_header(signature_header)
    if not sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    if len(sig) != len(expected):
        return False
    return hmac.compare_digest(expected, sig)


def _ota_topic_for_event(event_type: str | None) -> str:
    et = (event_type or "").strip().lower().replace("-", "_")
    if et in ("booking_modification", "booking_modified", "booking_updated", "modification"):
        return "ota.booking.modified"
    if et in (
        "booking_cancellation",
        "booking_cancelled",
        "booking_canceled",
        "cancellation",
        "cancelled",
        "canceled",
    ):
        return "ota.booking.cancelled"
    return "ota.booking.created"


def _resolve_booking_key(data: dict[str, Any], parsed: ChannexWebhookPayload) -> str | None:
    for candidate in (parsed.booking_id, data.get("booking_id")):
        s = str(candidate or "").strip()
        if s:
            return s
    inner = parsed.payload or data.get("payload")
    if isinstance(inner, dict):
        for key in ("booking_id", "id", "reservation_id", "confirmation_code"):
            s = str(inner.get(key) or "").strip()
            if s:
                return s
    return None


@router.post("", summary="Channex / headless channel-manager booking webhook")
async def receive_channex_webhook(
    request: Request,
    x_channex_signature: str | None = Header(None, alias="x-channex-signature"),
) -> dict[str, str]:
    if x_channex_signature is None or not str(x_channex_signature).strip():
        raise HTTPException(status_code=401, detail="Missing signature header")

    raw_body = await request.body()
    if not verify_channex_signature(raw_body, x_channex_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    try:
        parsed = ChannexWebhookPayload.model_validate(data)
    except ValidationError:
        inner = data.get("payload")
        parsed = ChannexWebhookPayload(
            event=str(data.get("event") or ""),
            payload=inner if isinstance(inner, dict) else {},
            property_id=str(data.get("property_id") or ""),
            booking_id=str(data.get("booking_id") or ""),
        )

    event_type = parsed.event or str(data.get("event") or "")
    topic = _ota_topic_for_event(event_type)
    booking_key = _resolve_booking_key(data, parsed)

    envelope: dict[str, Any] = {
        "source": "channex",
        "ingested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": event_type,
        "property_id": str(parsed.property_id or data.get("property_id") or ""),
        "booking_id": str(parsed.booking_id or data.get("booking_id") or ""),
        "payload": parsed.payload if parsed.payload else (data.get("payload") if isinstance(data.get("payload"), dict) else {}),
        "raw": data,
    }

    await publish_event(topic=topic, payload=envelope, key=booking_key)

    logger.info(
        "channex_webhook_accepted",
        topic=topic,
        channex_event=event_type,
        booking_key=booking_key,
    )
    return {"status": "accepted"}
