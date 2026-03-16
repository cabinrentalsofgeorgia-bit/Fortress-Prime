"""
StreamlineClient — Thin facade over the production StreamlineVRS API client.

All retry logic (tenacity 3x exponential backoff), rate-limit handling,
and token renewal are handled by the underlying StreamlineVRS class in
backend.integrations.streamline_vrs. This facade exposes the directive's
requested interface without duplicating infrastructure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(service="synapse_client")


class StreamlineClient:
    """Resilient Streamline API client with retry and backoff (via StreamlineVRS)."""

    def __init__(self):
        from backend.integrations.streamline_vrs import StreamlineVRS
        self._vrs = StreamlineVRS()
        logger.info("streamline_client_init", configured=self._vrs.is_configured)

    @property
    def is_configured(self) -> bool:
        return self._vrs.is_configured

    async def get_properties(self) -> List[Dict[str, Any]]:
        """Fetch all properties from Streamline (with tenacity retry)."""
        logger.info("fetching_properties")
        props = await self._vrs.fetch_properties()
        logger.info("properties_fetched", count=len(props))
        return props

    async def get_calendar(
        self,
        unit_id: int,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch blocked/booked days for a property (with tenacity retry)."""
        logger.info("fetching_calendar", unit_id=unit_id)
        blocked = await self._vrs.fetch_blocked_days(unit_id, start_date, end_date)
        logger.info("calendar_fetched", unit_id=unit_id, blocks=len(blocked))
        return blocked

    async def get_reservations(self) -> List[Dict[str, Any]]:
        """Fetch all reservations from Streamline (with tenacity retry)."""
        logger.info("fetching_reservations")
        reservations = await self._vrs.fetch_reservations()
        logger.info("reservations_fetched", count=len(reservations))
        return reservations
