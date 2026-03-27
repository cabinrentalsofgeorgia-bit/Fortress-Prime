"""Worker guardrails for the post-Drupal sovereign boundary."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.functional_node import FunctionalNode

logger = logging.getLogger("Worker.Hardening")


def require_legacy_host_active(operation: str) -> None:
    """Block legacy-host operations once the Drupal estate is decommissioned."""
    if settings.legacy_host_active:
        return
    raise RuntimeError(
        f"{operation} is blocked because LEGACY_HOST_ACTIVE is false and the legacy host is offline."
    )


async def enforce_sovereign_boundary() -> None:
    """
    STRIKE 15 GUARDRAIL:
    Harden worker startup so the retired legacy host cannot be used again.
    """
    if settings.legacy_host_active:
        raise RuntimeError(
            "LEGACY_HOST_ACTIVE must be false before worker startup. Legacy host boundary is not hardened."
        )

    async with AsyncSessionLocal() as db:
        legacy_count = int(
            (
                await db.execute(
                    select(func.count(FunctionalNode.id)).where(FunctionalNode.cutover_status == "legacy")
                )
            ).scalar_one()
        )

    logger.info("GUARDRAIL: Sovereign Boundary enforced. Legacy host is now OFFLINE.")
    if legacy_count:
        logger.warning(
            "Zero-Trust Check: lingering legacy FunctionalNodes remain.",
            extra={"legacy_count": legacy_count},
        )
        return
    logger.info("Zero-Trust Check: All FunctionalNodes are SOVEREIGN.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(enforce_sovereign_boundary())
