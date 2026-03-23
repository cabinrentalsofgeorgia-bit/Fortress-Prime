"""
CourtListener API client.

This module is optional-safe: if no API token is configured or the upstream
call fails, it returns None so callers can degrade gracefully.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from backend.core.config import settings

logger = structlog.get_logger()


async def courtlistener_get(
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    token = (settings.courtlistener_api_token or "").strip()
    if not token:
        logger.warning("courtlistener_token_missing")
        return None

    base = (settings.courtlistener_base_url or "").rstrip("/")
    endpoint = f"{base}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(endpoint, params=params or {}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning(
            "courtlistener_request_failed",
            endpoint=endpoint,
            error=str(exc)[:200],
        )
        return None
