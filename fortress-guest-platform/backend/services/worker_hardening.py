"""Worker guardrails for the post-Drupal sovereign boundary."""

from __future__ import annotations

import logging
import os

from sqlalchemy import func, select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.functional_node import FunctionalNode

logger = logging.getLogger("Worker.Hardening")

WORKER_NICE_LEVEL = 10


def require_legacy_host_active(operation: str) -> None:
    """Block legacy-host operations once the Drupal estate is decommissioned."""
    if settings.legacy_host_active:
        return
    raise RuntimeError(
        f"{operation} is blocked because LEGACY_HOST_ACTIVE is false and the legacy host is offline."
    )


def apply_low_priority() -> None:
    """Lower CPU scheduling priority for background workers so they never
    contend with the guest-facing FastAPI request handlers."""
    try:
        current = os.nice(0)
        if current < WORKER_NICE_LEVEL:
            os.nice(WORKER_NICE_LEVEL - current)
            logger.info(
                "CPU priority lowered for background worker",
                extra={"nice": os.nice(0)},
            )
    except (OSError, AttributeError):
        logger.warning("Failed to lower CPU priority (non-POSIX or insufficient perms)")


async def enforce_sovereign_boundary() -> None:
    """
    STRIKE 15 GUARDRAIL:
    Harden worker startup so the retired legacy host cannot be used again.
    Also enforces low CPU priority for all background tasks.
    """
    apply_low_priority()

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
