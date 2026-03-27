from __future__ import annotations

from html import escape
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from backend.core.config import settings
from backend.services.notifications import notifications_configured, send_system_email

router = APIRouter()
logger = structlog.get_logger(service="dispatch_api")

CONTACT_NOTIFICATION_RECIPIENTS = (
    "lissa@cabin-rentals-of-georgia.com",
    "gary@cabin-rentals-of-georgia.com",
)
CONTACT_RATE_LIMIT = 4
CONTACT_RATE_WINDOW_SECONDS = 3600


class ContactFormRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    email_address: EmailStr
    phone: str = Field(..., min_length=7, max_length=40)
    property_street_address: str | None = Field(default=None, max_length=1000)
    message: str | None = Field(default=None, max_length=5000)
    session_id: UUID | None = Field(
        default=None,
        description="Optional first-party storefront session UUID for anonymous lead attribution.",
    )

    @field_validator("first_name", "last_name", "phone", "property_street_address", "message", mode="before")
    @classmethod
    def _normalize_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ContactFormResponse(BaseModel):
    status: str
    queued_notifications: int
    session_id: UUID | None = None


async def get_redis_client(request: Request):
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        yield pool
        return

    redis_client = aioredis.from_url(
        settings.arq_redis_url,
        decode_responses=True,
    )
    try:
        yield redis_client
    finally:
        await redis_client.aclose()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _enforce_contact_rate_limit(redis_client: Any, request: Request, payload: ContactFormRequest) -> None:
    client_ip = _client_ip(request)
    email_key = str(payload.email_address).strip().lower()
    limit_key = f"dispatch:contact_form:{client_ip}:{email_key}"
    current_count = int(await redis_client.incr(limit_key))
    if current_count == 1:
        await redis_client.expire(limit_key, CONTACT_RATE_WINDOW_SECONDS)

    ttl = int(await redis_client.ttl(limit_key))
    if ttl < 0:
        ttl = CONTACT_RATE_WINDOW_SECONDS
        await redis_client.expire(limit_key, ttl)

    if current_count > CONTACT_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many contact form submissions. Try again later.",
            headers={"Retry-After": str(ttl)},
        )


def _build_contact_bodies(payload: ContactFormRequest, request: Request) -> tuple[str, str, str]:
    submitted_email = str(payload.email_address)
    subject = "Request for more info about property management"
    client_ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "").strip()
    message = payload.message or ""
    property_address = payload.property_street_address or ""
    session_line = str(payload.session_id) if payload.session_id else "<none>"

    text_body = (
        "Property management contact request\n\n"
        f"First Name: {payload.first_name}\n"
        f"Last Name: {payload.last_name}\n"
        f"Email Address: {submitted_email}\n"
        f"Phone: {payload.phone}\n"
        f"Property Street Address: {property_address}\n"
        f"Message: {message}\n"
        f"Session ID: {session_line}\n"
        f"Client IP: {client_ip}\n"
        f"User Agent: {user_agent}\n"
    )
    html_body = f"""
<html>
  <body style="font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;">
    <h2 style="color:#bfdbfe;">Property management contact request</h2>
    <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;background:#111827;">
      <tr><td><strong>First Name</strong></td><td>{escape(payload.first_name)}</td></tr>
      <tr><td><strong>Last Name</strong></td><td>{escape(payload.last_name)}</td></tr>
      <tr><td><strong>Email Address</strong></td><td>{escape(submitted_email)}</td></tr>
      <tr><td><strong>Phone</strong></td><td>{escape(payload.phone)}</td></tr>
      <tr><td><strong>Property Street Address</strong></td><td>{escape(property_address) or '&lt;none&gt;'}</td></tr>
      <tr><td><strong>Message</strong></td><td>{escape(message) or '&lt;none&gt;'}</td></tr>
      <tr><td><strong>Session ID</strong></td><td>{escape(session_line)}</td></tr>
      <tr><td><strong>Client IP</strong></td><td>{escape(client_ip)}</td></tr>
      <tr><td><strong>User Agent</strong></td><td>{escape(user_agent) or '&lt;none&gt;'}</td></tr>
    </table>
  </body>
</html>
""".strip()
    return subject, text_body, html_body


@router.get("/health")
async def dispatch_health():
    return {"status": "ok", "service": "dispatch"}


@router.post("/contact-form", response_model=ContactFormResponse)
async def submit_contact_form(
    payload: ContactFormRequest,
    request: Request,
    redis_client: Any = Depends(get_redis_client),
) -> ContactFormResponse:
    await _enforce_contact_rate_limit(redis_client, request, payload)

    if not notifications_configured():
        logger.error("dispatch_notifications_not_configured")
        raise HTTPException(
            status_code=503,
            detail="Dispatch notifications are not configured.",
        )

    subject, text_body, html_body = _build_contact_bodies(payload, request)
    delivered = await send_system_email(
        recipients=CONTACT_NOTIFICATION_RECIPIENTS,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
    if not delivered:
        raise HTTPException(
            status_code=502,
            detail="Dispatch notification delivery failed.",
        )

    logger.info(
        "dispatch_contact_form_submitted",
        email=str(payload.email_address),
        session_id=str(payload.session_id) if payload.session_id else None,
        recipient_count=len(CONTACT_NOTIFICATION_RECIPIENTS),
    )
    return ContactFormResponse(
        status="accepted",
        queued_notifications=len(CONTACT_NOTIFICATION_RECIPIENTS),
        session_id=payload.session_id,
    )

