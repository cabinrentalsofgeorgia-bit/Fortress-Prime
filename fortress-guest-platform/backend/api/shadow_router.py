"""
Shadow Router — intake endpoint for Legacy-vs-DGX parity auditing.

Accepts legacy checkout payloads and fires the Godhead Swarm pipeline
as a background task so the caller is never blocked.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from backend.agents.godhead_swarm import agent_paper_clip

logger = structlog.get_logger("shadow_router")
router = APIRouter()


class ShadowIntakePayload(BaseModel):
    property_id: UUID
    dates: dict[str, str] = Field(
        ...,
        description="Must contain 'check_in' and 'check_out' in YYYY-MM-DD format",
    )
    guests: int = Field(ge=1, default=1)
    pets: int = Field(ge=0, default=0)
    legacy_total_cents: int = Field(
        ...,
        description="Total the Legacy site charged, in cents",
    )


async def _run_swarm(payload: dict[str, Any]) -> None:
    """Fire-and-forget wrapper that catches swarm failures cleanly."""
    try:
        await agent_paper_clip(payload)
    except Exception:
        logger.exception("shadow_swarm.unhandled_failure", payload=payload)


@router.post("/intake")
async def shadow_intake(
    body: ShadowIntakePayload,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    payload = body.model_dump(mode="json")
    payload["property_id"] = str(body.property_id)

    logger.info(
        "shadow.intake_received",
        property_id=str(body.property_id),
        legacy_total_cents=body.legacy_total_cents,
    )

    background_tasks.add_task(_run_swarm, payload)

    return {"status": "received", "tracking": True}
