"""
fire_test_event.py — Developer utility to inject a synthetic Streamline event
into the Redis queue, exercising the full VRS Rule Engine pipeline:

    Redis LPUSH → event_consumer BRPOP → RuleEngine.dispatch → action execution

Usage:
    cd fortress-guest-platform
    python fire_test_event.py
"""

import asyncio
import sys

from backend.vrs.domain.automations import StreamlineEventPayload
from backend.vrs.infrastructure.event_bus import publish_vrs_event


async def run_test() -> None:
    print("Firing synthetic Streamline event to Redis...")

    test_event = StreamlineEventPayload(
        entity_type="reservation",
        entity_id="RES-TEST-999",
        event_type="created",
        previous_state={},
        current_state={
            "id": "RES-TEST-999",
            "status": "confirmed",
            "total_amount": 1500.00,
            "guest_name": "Fortune 500 VIP",
        },
    )

    ok = await publish_vrs_event(test_event)
    if ok:
        print("Event pushed successfully. Check your backend worker logs.")
    else:
        print("Failed to push event — check Redis connectivity.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_test())
