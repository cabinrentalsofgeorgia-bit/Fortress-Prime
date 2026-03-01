"""
SMTP Dispatcher — Async-safe email delivery for the Agentic Sales Engine.

Wraps the existing synchronous email_service.send_email() in
asyncio.to_thread so it never blocks the FastAPI event loop (Rule 5).
Combines TemplateEngine (branded HTML letterhead + Magic Link CTA)
with SMTP delivery in a single call.

Supports:
  - send_quote()        — Branded quote email with optional CTA
  - send_confirmation() — Booking confirmation with PDF attachments
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from backend.services.email_service import is_email_configured, send_email
from backend.services.template_engine import TemplateEngine

logger = structlog.get_logger(service="smtp_dispatcher")


class SMTPDispatcher:
    """Async-safe SMTP dispatcher with branded HTML wrapping."""

    def __init__(self):
        self._engine = TemplateEngine()

    async def send_quote(
        self,
        to_email: str,
        subject: str,
        text_content: str,
        checkout_url: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """
        Render a branded HTML email and dispatch via SMTP.

        1. Wraps text_content in the Jinja2 letterhead (with optional CTA)
        2. Sends via asyncio.to_thread(send_email, ...) — non-blocking
        3. Returns a result dict; never raises to the caller
        """
        result: Dict[str, Any] = {
            "success": False,
            "recipient": to_email,
            "error": None,
        }

        if not to_email:
            result["error"] = "no_recipient_email"
            logger.error("smtp_dispatch_no_recipient")
            return result

        if not is_email_configured():
            result["error"] = "smtp_not_configured"
            logger.warning(
                "smtp_dispatch_not_configured",
                to=to_email,
                subject=subject,
            )
            return result

        try:
            html_body = self._engine.wrap_email(
                text_content,
                checkout_url=checkout_url,
            )

            sent = await asyncio.to_thread(
                send_email,
                to_email,
                subject,
                html_body,
                text_content,
                attachments,
            )

            result["success"] = sent
            if not sent:
                result["error"] = "smtp_send_returned_false"

            logger.info(
                "smtp_dispatch_complete",
                to=to_email,
                subject=subject,
                success=sent,
                has_cta=bool(checkout_url),
                attachments=len(attachments) if attachments else 0,
            )

        except Exception as exc:
            result["error"] = str(exc)
            logger.error(
                "smtp_dispatch_exception",
                to=to_email,
                error=str(exc),
            )

        return result

    async def send_confirmation(
        self,
        to_email: str,
        quote_data: dict,
        attachments: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """
        Send a booking confirmation email with PDF receipt and agreement attached.

        Uses the booking_confirmation.html template instead of the quote letterhead.
        """
        result: Dict[str, Any] = {
            "success": False,
            "recipient": to_email,
            "error": None,
        }

        if not to_email:
            result["error"] = "no_recipient_email"
            logger.error("smtp_confirmation_no_recipient")
            return result

        if not is_email_configured():
            result["error"] = "smtp_not_configured"
            logger.warning("smtp_confirmation_not_configured", to=to_email)
            return result

        try:
            html_body = self._engine.wrap_confirmation(quote_data)
            subject = f"Booking Confirmed — {quote_data.get('property_name', 'Your Cabin')}"
            text_body = (
                f"Thank you for securing your dates at {quote_data.get('property_name', 'our cabin')}! "
                f"Attached are your official payment receipt and rental agreement. "
                f"We will send your door codes 48 hours prior to check-in."
            )

            sent = await asyncio.to_thread(
                send_email,
                to_email,
                subject,
                html_body,
                text_body,
                attachments,
            )

            result["success"] = sent
            if not sent:
                result["error"] = "smtp_send_returned_false"

            logger.info(
                "smtp_confirmation_sent",
                to=to_email,
                property=quote_data.get("property_name"),
                success=sent,
                attachments=len(attachments) if attachments else 0,
            )

        except Exception as exc:
            result["error"] = str(exc)
            logger.error(
                "smtp_confirmation_exception",
                to=to_email,
                error=str(exc),
            )

        return result
