"""Internal inventory / availability change notifications (Kafka)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from backend.core.event_publisher import EventPublisher

logger = structlog.get_logger(service="inventory_events")

TOPIC_INVENTORY_AVAILABILITY_CHANGED = "inventory.availability.changed"


async def publish_inventory_availability_changed(
    property_id: str,
    *,
    reason: str,
    source: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit work for the Channex egress consumer (and any future subscribers)."""
    payload: dict[str, Any] = {
        "property_id": property_id,
        "reason": reason,
        "source": source,
        "emitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if extra:
        payload.update(extra)
    await EventPublisher.publish(TOPIC_INVENTORY_AVAILABILITY_CHANGED, payload, key=property_id)
    logger.info(
        "inventory_availability_changed_emitted",
        property_id=property_id,
        reason=reason,
        source=source,
    )
