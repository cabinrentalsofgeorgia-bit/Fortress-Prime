"""
VRS Application — Background worker that processes the Redis event queue.

Runs as a continuous ``asyncio`` task inside the FastAPI lifespan.
BRPOP blocks until an event arrives (zero CPU waste), then dispatches
through the Rule Engine for condition evaluation and action execution.

Failed events are pushed to a dead-letter queue for later inspection.
"""
import asyncio
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.services.hunter_reactivation import draft_reactivation_sequence
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


def _internal_api_base_url() -> str:
    base = str(settings.internal_api_base_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("INTERNAL_API_BASE_URL is not configured")
    return base


def _internal_api_headers() -> dict[str, str]:
    token = settings.internal_api_bearer_token
    if not token:
        raise RuntimeError("INTERNAL_API_TOKEN or SWARM_API_KEY is not configured")
    return {"Authorization": f"Bearer {token}"}


async def _post_fireclaw_interrogate(document_path: str) -> dict[str, Any]:
    base = _internal_api_base_url()
    headers = _internal_api_headers()
    mime = "application/pdf" if document_path.lower().endswith(".pdf") else "application/octet-stream"
    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(document_path, "rb") as payload_stream:
            response = await client.post(
                f"{base}/api/sandbox/fireclaw/interrogate",
                headers=headers,
                files={"file": (Path(document_path).name, payload_stream, mime)},
            )
        response.raise_for_status()
        return response.json()


async def _post_legal_threat_assessor(payload: dict[str, Any]) -> dict[str, Any]:
    base = _internal_api_base_url()
    headers = _internal_api_headers()
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{base}/api/agent/tools/legal-threat-assessor",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def handle_docket_updated_event(event: StreamlineEventPayload) -> dict[str, Any]:
    current = event.current_state or {}
    case_number = str(current.get("case_number") or "").strip()
    case_slug = str(current.get("case_slug") or "").strip()
    document_path = str(current.get("document_path") or "").strip()
    filing_name = str(current.get("filing_name") or Path(document_path).name).strip()
    target_vault_path = current.get("target_vault_path")

    if not case_number:
        raise RuntimeError("docket_updated event missing case_number")
    if not document_path:
        raise RuntimeError("docket_updated event missing document_path")
    if not Path(document_path).is_file():
        raise RuntimeError(f"docket_updated document_path does not exist: {document_path}")

    logger.info(
        "docket_updated_decontamination_started",
        case_number=case_number,
        case_slug=case_slug or None,
        document_path=document_path,
    )
    sandbox_data = await _post_fireclaw_interrogate(document_path)
    guest_output = sandbox_data.get("guest") or {}
    if guest_output.get("status") != "success":
        raise RuntimeError(
            f"Fireclaw guest failed: {guest_output.get('message') or sandbox_data.get('stderr') or 'unknown error'}"
        )

    safe_text = str(guest_output.get("sanitized_content") or "").strip()
    if not safe_text:
        raise RuntimeError("Fireclaw decontamination returned empty sanitized_content")

    tool_payload = {
        "case_number": case_number,
        "case_slug": case_slug or None,
        "filing_name": filing_name or None,
        "document_text": safe_text,
        "metadata": guest_output.get("metadata") or {},
        "target_vault_path": target_vault_path,
        "persist_to_vault": bool(current.get("persist_to_vault", True)),
    }
    tool_result = await _post_legal_threat_assessor(tool_payload)
    if tool_result.get("status") != "success":
        raise RuntimeError(
            tool_result.get("error_message") or "Legal threat assessor returned a non-success status"
        )

    artifact = tool_result.get("data") or {}
    logger.info(
        "docket_updated_threat_assessment_completed",
        case_number=case_number,
        case_slug=case_slug or None,
        sha256_hash=(guest_output.get("metadata") or {}).get("sha256_hash"),
        artifact_path=artifact.get("vault_path") or artifact.get("download_url"),
        artifact_filename=artifact.get("artifact_filename"),
    )
    return {
        "fireclaw": sandbox_data,
        "paperclip": tool_result,
    }


async def handle_reactivation_dispatched_event(
    db: Any,
    event: StreamlineEventPayload,
) -> dict[str, Any]:
    current = event.current_state or {}
    raw_guest_id = str(current.get("guest_id") or event.entity_id or "").strip()
    if not raw_guest_id:
        raise RuntimeError("reactivation_dispatched event missing guest_id")

    try:
        guest_id = UUID(raw_guest_id)
    except ValueError as exc:
        raise RuntimeError(f"reactivation_dispatched guest_id is not a UUID: {raw_guest_id}") from exc

    target_score = int(current.get("target_score") or 0)
    return await draft_reactivation_sequence(
        db,
        guest_id=guest_id,
        target_score=target_score,
        trigger_type="EVENT_CONSUMER_REACTIVATION_DISPATCHED",
    )


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
            logger.info(
                "event_dequeued",
                entity=event.entity_type,
                entity_id=event.entity_id,
                event_type=event.event_type,
            )

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
                logger.info(
                    "event_rule_scan",
                    entity=event.entity_type,
                    entity_id=event.entity_id,
                    event_type=event.event_type,
                    matching_rules=len(matching_rules),
                )

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
                elif event.event_type == "docket_updated":
                    fallback = await handle_docket_updated_event(event)
                    logger.info(
                        "event_processed_via_fallback",
                        entity=event.entity_type,
                        entity_id=event.entity_id,
                        event_type=event.event_type,
                        fallback="docket_updated_decontamination",
                        artifact_path=((fallback.get("paperclip") or {}).get("data") or {}).get("vault_path"),
                    )
                elif (
                    event.entity_type == "guest"
                    and event.event_type == "reactivation_dispatched"
                ):
                    fallback = await handle_reactivation_dispatched_event(session, event)
                    await session.commit()
                    logger.info(
                        "event_processed_via_fallback",
                        entity=event.entity_type,
                        entity_id=event.entity_id,
                        event_type=event.event_type,
                        fallback="draft_reactivation_sequence",
                        queue_entry_id=((fallback.get("queue_entry") or {}).get("id")),
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
