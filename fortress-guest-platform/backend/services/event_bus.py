"""
Backward-compat shim — canonical location is backend.vrs.infrastructure.event_bus.

All consumers should migrate to:
  from backend.vrs.infrastructure.event_bus import redis_client, publish_vrs_event, ...
"""
from backend.vrs.infrastructure.event_bus import (  # noqa: F401
    redis_client,
    publish_vrs_event,
    consume_one,
    queue_depth,
    dlq_depth,
    send_to_dlq,
    close,
    EVENT_QUEUE_KEY,
    DLQ_KEY,
)

publish_event = publish_vrs_event
