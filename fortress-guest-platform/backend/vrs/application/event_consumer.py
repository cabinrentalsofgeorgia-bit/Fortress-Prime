"""
VRS Application — Background worker that processes the Redis event queue.

Runs as a continuous ``asyncio`` task inside the FastAPI lifespan.
BRPOP blocks until an event arrives (zero CPU waste), then dispatches
through the Rule Engine for condition evaluation and action execution.

Failed events are pushed to a dead-letter queue for later inspection.
"""
import asyncio
import time

import structlog
from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.vrs.infrastructure.event_bus import (
    redis_client,
    EVENT_QUEUE_KEY,
    send_to_dlq,
    queue_depth,
    close as close_bus,
)
from backend.vrs.domain.automations import (
    VRSRuleEngine,
    StreamlineEventPayload,
)
from backend.vrs.application.rule_engine import RuleEngine

logger = structlog.get_logger(service="vrs.event_consumer")


async def process_automation_queue() -> None:
    """Infinite loop: BRPOP → dispatch → commit → repeat.

    Uses ``timeout=5`` on BRPOP so the loop can honour ``CancelledError``
    and emit periodic heartbeat logs without blocking forever.
    """
    logger.info("event_consumer_starting")
    await asyncio.sleep(15)

    consecutive_errors = 0
    last_heartbeat = time.monotonic()

    while True:
        raw_payload: str | None = None
        try:
            result = await redis_client.brpop(EVENT_QUEUE_KEY, timeout=5)
            if not result:
                if time.monotonic() - last_heartbeat > 300:
                    depth = await queue_depth()
                    logger.info("event_consumer_heartbeat", queue_depth=depth)
                    last_heartbeat = time.monotonic()
                continue

            _, raw_payload = result
            event = StreamlineEventPayload.model_validate_json(raw_payload)

            # ── Autonomous Dispatcher: IoT checkout → AI → work order ──
            if (
                event.entity_type == "iot"
                and event.event_type in ("lock.checkout", "checkout", "checkout_detected")
            ):
                property_id = event.current_state.get("property_id") or event.entity_id
                try:
                    from backend.services.vrs_agent_dispatcher import handle_iot_checkout_event
                    async with AsyncSessionLocal() as dispatch_session:
                        result_data = await handle_iot_checkout_event(
                            db=dispatch_session,
                            property_id=property_id,
                            event_data={"event_type": event.event_type, **event.current_state},
                        )
                        logger.info(
                            "autonomous_dispatch_via_consumer",
                            property_id=property_id,
                            dispatched=result_data.get("dispatched", False),
                            ticket=result_data.get("ticket_number"),
                        )
                except Exception as dispatch_exc:
                    logger.error("autonomous_dispatch_failed", error=str(dispatch_exc)[:300])
                consecutive_errors = 0
                last_heartbeat = time.monotonic()
                continue

            # ── Standard rule engine dispatch ──
            async with AsyncSessionLocal() as session:
                query = select(VRSRuleEngine).where(
                    VRSRuleEngine.target_entity == event.entity_type,
                    VRSRuleEngine.trigger_event == event.event_type,
                    VRSRuleEngine.is_active == True,
                )
                matching_rules = (await session.execute(query)).scalars().all()

                fired = 0
                for rule in matching_rules:
                    try:
                        if RuleEngine._evaluate_conditions(rule.conditions, event):
                            await RuleEngine._execute_action(rule, event, session)
                            fired += 1
                            logger.info(
                                "rule_fired",
                                rule_id=str(rule.id),
                                rule_name=rule.name,
                                entity=event.entity_type,
                                entity_id=event.entity_id,
                            )
                    except Exception as exc:
                        logger.error(
                            "rule_execution_failed",
                            rule_id=str(rule.id),
                            error=str(exc),
                        )

                await session.commit()

                if fired > 0:
                    logger.info(
                        "event_processed",
                        entity=event.entity_type,
                        entity_id=event.entity_id,
                        event_type=event.event_type,
                        rules_fired=fired,
                    )

            consecutive_errors = 0
            last_heartbeat = time.monotonic()

        except asyncio.CancelledError:
            logger.info("event_consumer_shutting_down")
            await close_bus()
            return
        except Exception as exc:
            consecutive_errors += 1
            backoff = min(2 ** consecutive_errors, 60)
            logger.error(
                "event_consumer_error",
                error=str(exc),
                consecutive=consecutive_errors,
                backoff_s=backoff,
            )
            if raw_payload is not None:
                await send_to_dlq(raw_payload, str(exc))
            await asyncio.sleep(backoff)


# Keep the old name as an alias for backward-compat callers
run_consumer = process_automation_queue
