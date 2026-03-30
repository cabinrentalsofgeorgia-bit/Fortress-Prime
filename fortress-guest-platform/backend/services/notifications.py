"""
System notification helpers for storefront dispatch flows.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable

import structlog

from backend.core.config import settings
from backend.services.email_service import is_email_configured, send_email

logger = structlog.get_logger(service="notifications")

SYSTEM_EMAIL_DOMAIN = "@cabin-rentals-of-georgia.com"


def notifications_configured() -> bool:
    from_address = (settings.email_from_address or settings.smtp_user or "").strip().lower()
    return (
        is_email_configured()
        and bool(from_address)
        and from_address.endswith(SYSTEM_EMAIL_DOMAIN)
    )


async def send_system_email(
    *,
    recipients: Iterable[str],
    subject: str,
    html_body: str,
    text_body: str = "",
) -> bool:
    recipient_list = [recipient.strip() for recipient in recipients if recipient and recipient.strip()]
    if not recipient_list:
        logger.warning("system_email_missing_recipients", subject=subject)
        return False

    if not notifications_configured():
        logger.warning(
            "system_email_not_configured",
            subject=subject,
            from_address=(settings.email_from_address or settings.smtp_user or "").strip(),
        )
        return False

    results = await asyncio.gather(
        *[
            asyncio.to_thread(
                send_email,
                recipient,
                subject,
                html_body,
                text_body,
            )
            for recipient in recipient_list
        ]
    )
    success = all(results)
    logger.info(
        "system_email_dispatch_complete",
        subject=subject,
        recipient_count=len(recipient_list),
        success=success,
    )
    return success
