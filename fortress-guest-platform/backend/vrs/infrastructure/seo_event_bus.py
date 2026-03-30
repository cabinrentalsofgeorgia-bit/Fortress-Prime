"""
SEO Event Bus — durable Redis list queues for DGX Swarm <-> God Head <-> Edge dispatch.

Uses LPUSH/BRPOP (FIFO) instead of pub/sub to guarantee at-least-once delivery
even when consumers are temporarily offline.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from backend.core.config import settings

logger = logging.getLogger(__name__)

GRADE_REQUEST_QUEUE_KEY = "fortress:seo:grade_requests"
REWRITE_REQUEST_QUEUE_KEY = "fortress:seo:rewrite_requests"
DEPLOY_EVENTS_QUEUE_KEY = "fortress:seo:deploy_events"
DLQ_QUEUE_KEY = "fortress:seo:dlq"

SEO_QUEUE_GRADE_REQUESTS = GRADE_REQUEST_QUEUE_KEY
SEO_QUEUE_REMAP_GRADE_REQUESTS = "fortress:seo:remap_grade_requests"
SEO_QUEUE_REWRITE_REQUESTS = REWRITE_REQUEST_QUEUE_KEY
SEO_QUEUE_DEPLOY_EVENTS = DEPLOY_EVENTS_QUEUE_KEY
SEO_QUEUE_DLQ = DLQ_QUEUE_KEY
SWARM_QUEUE_DLQ = "fortress:swarm:dlq"

SwarmEventStatus = Literal["drafted", "evaluating", "failed", "complete"]


class SwarmEventEnvelope(BaseModel):
    """Canonical cross-swarm queue envelope required by the architecture doctrine."""

    model_config = ConfigDict(extra="allow")

    task_id: UUID
    source_agent: str
    target_queue: str
    context_refs: list[UUID] = Field(default_factory=list, min_length=1)
    status: SwarmEventStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def primary_context_ref(self) -> UUID:
        return self.context_refs[0]


def _serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, default=str, separators=(",", ":"))


def build_swarm_event(
    *,
    source_agent: str,
    target_queue: str,
    context_refs: list[UUID],
    status: SwarmEventStatus,
    task_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> SwarmEventEnvelope:
    return SwarmEventEnvelope(
        task_id=task_id or uuid4(),
        source_agent=source_agent,
        target_queue=target_queue,
        context_refs=context_refs,
        status=status,
        metadata=metadata or {},
    )


def parse_swarm_event(
    message: str,
    *,
    expected_queue: str,
    legacy_source_agent: str,
    legacy_status: SwarmEventStatus,
) -> SwarmEventEnvelope:
    payload = json.loads(message)
    if not isinstance(payload, dict):
        raise ValueError("Queue message must decode to a JSON object.")

    required_keys = {"task_id", "source_agent", "target_queue", "context_refs", "status"}
    if required_keys.issubset(payload):
        envelope = SwarmEventEnvelope.model_validate(payload)
        if envelope.target_queue != expected_queue:
            raise ValueError(
                f"Queue envelope target_queue mismatch: expected {expected_queue}, got {envelope.target_queue}."
            )
        return envelope

    raw_patch_id = payload.get("patch_id")
    if raw_patch_id is None:
        raise ValueError("Legacy queue payload missing patch_id.")

    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"patch_id", "task_id", "source_agent", "target_queue", "context_refs", "status"}
    }
    raw_status = payload.get("status") or legacy_status
    if raw_status not in {"drafted", "evaluating", "failed", "complete"}:
        raise ValueError(f"Unsupported legacy queue status: {raw_status}")

    return build_swarm_event(
        task_id=UUID(str(payload["task_id"])) if payload.get("task_id") else UUID(str(raw_patch_id)),
        source_agent=str(payload.get("source_agent") or legacy_source_agent),
        target_queue=expected_queue,
        context_refs=[UUID(str(raw_patch_id))],
        status=raw_status,
        metadata=metadata,
    )


async def create_seo_event_redis() -> aioredis.Redis:
    return aioredis.from_url(
        settings.arq_redis_url,
        decode_responses=True,
        socket_timeout=15,
        socket_connect_timeout=5,
        health_check_interval=30,
    )


async def publish_grade_request(
    patch_id: UUID,
    *,
    source_agent: str = "seo_patch_api",
    task_id: UUID | None = None,
) -> bool:
    """
    Lightweight producer shim for routes that only need to enqueue a grade request.
    """
    redis_client = await create_seo_event_redis()
    try:
        event_bus = SEOEventBus(redis_client)
        await event_bus.publish_grade_request(patch_id, source_agent=source_agent, task_id=task_id)
        return True
    except Exception:
        return False
    finally:
        await redis_client.aclose()


async def publish_rewrite_request(
    patch_id: UUID,
    feedback: dict[str, Any],
    *,
    source_agent: str = "seo_grading_service",
    task_id: UUID | None = None,
) -> bool:
    redis_client = await create_seo_event_redis()
    try:
        event_bus = SEOEventBus(redis_client)
        await event_bus.publish_rewrite_request(
            patch_id,
            feedback,
            source_agent=source_agent,
            task_id=task_id,
        )
        return True
    except Exception:
        return False
    finally:
        await redis_client.aclose()


async def publish_deploy_event(
    patch_id: UUID,
    *,
    source_agent: str = "seo_patch_api",
    task_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> SwarmEventEnvelope | None:
    redis_client = await create_seo_event_redis()
    try:
        event_bus = SEOEventBus(redis_client)
        return await event_bus.publish_deploy_event(
            patch_id,
            source_agent=source_agent,
            task_id=task_id,
            metadata=metadata,
        )
    except Exception:
        return None
    finally:
        await redis_client.aclose()


async def publish_swarm_dlq(
    *,
    task_id: UUID,
    source_agent: str,
    failed_queue: str,
    context_refs: list[UUID],
    error: str,
    final_trace: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    redis_client = await create_seo_event_redis()
    try:
        event_bus = SEOEventBus(redis_client)
        await event_bus.publish_swarm_dlq(
            task_id=task_id,
            source_agent=source_agent,
            failed_queue=failed_queue,
            context_refs=context_refs,
            error=error,
            final_trace=final_trace,
            metadata=metadata,
        )
        return True
    except Exception:
        return False
    finally:
        await redis_client.aclose()


class SEOEventBus:
    """
    Manages asynchronous dispatch of SEO patches between the DGX Swarm,
    the God Head graders, and the Edge cache invalidators via durable
    Redis list queues.
    """

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def _publish(self, envelope: SwarmEventEnvelope) -> None:
        await self.redis.lpush(
            envelope.target_queue,
            _serialize_payload(envelope.model_dump(mode="json")),
        )

    async def publish_grade_request(
        self,
        patch_id: UUID,
        *,
        source_agent: str = "seo_patch_api",
        task_id: UUID | None = None,
    ) -> SwarmEventEnvelope:
        """
        Triggered by the DGX Swarm after drafting a new patch.
        Pushes to the grading queue for God Head evaluation.
        """
        envelope = build_swarm_event(
            task_id=task_id,
            source_agent=source_agent,
            target_queue=SEO_QUEUE_GRADE_REQUESTS,
            context_refs=[patch_id],
            status="drafted",
        )
        try:
            await self._publish(envelope)
            logger.info("SEO Event Bus: Published grade request for patch %s", patch_id)
            return envelope
        except Exception as e:
            logger.error("SEO Event Bus: Failed to publish grade request for patch %s: %s", patch_id, e)
            raise

    async def publish_rewrite_request(
        self,
        patch_id: UUID,
        feedback: dict[str, Any],
        *,
        source_agent: str = "seo_grading_service",
        task_id: UUID | None = None,
    ) -> SwarmEventEnvelope:
        """
        Triggered by the God Head grading service when a score is below min_pass_score.
        Routes back to the Swarm for revision.
        """
        envelope = build_swarm_event(
            task_id=task_id,
            source_agent=source_agent,
            target_queue=SEO_QUEUE_REWRITE_REQUESTS,
            context_refs=[patch_id],
            status="failed",
            metadata={"feedback": feedback},
        )
        try:
            await self._publish(envelope)
            logger.info("SEO Event Bus: Published rewrite request for patch %s", patch_id)
            return envelope
        except Exception as e:
            logger.error("SEO Event Bus: Failed to publish rewrite request for patch %s: %s", patch_id, e)
            raise

    async def publish_remap_grade_request(self, payload: dict[str, Any]) -> SwarmEventEnvelope:
        """
        Legacy redirect remap queue retained for compatibility with the SEO fallback swarm.
        """
        review_id = payload.get("review_id")
        if review_id is None:
            raise ValueError("Remap grade request requires review_id")

        envelope = build_swarm_event(
            task_id=UUID(str(payload["task_id"])) if payload.get("task_id") else None,
            source_agent=str(payload.get("source_agent") or "seo_redirect_swarm"),
            target_queue=SEO_QUEUE_REMAP_GRADE_REQUESTS,
            context_refs=[UUID(str(review_id))],
            status="drafted",
        )
        try:
            await self._publish(envelope)
            logger.info(
                "SEO Event Bus: Published remap grade request for review %s",
                review_id,
            )
            return envelope
        except Exception as e:
            logger.error(
                "SEO Event Bus: Failed to publish remap grade request for review %s: %s",
                review_id,
                e,
            )
            raise

    async def publish_deploy_event(
        self,
        patch_id: UUID,
        *,
        source_agent: str = "seo_patch_api",
        task_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SwarmEventEnvelope:
        """
        Triggered upon HITL approval.
        Consumed by Edge sync workers to invalidate Cloudflare/CDN caches.
        """
        envelope = build_swarm_event(
            task_id=task_id,
            source_agent=source_agent,
            target_queue=SEO_QUEUE_DEPLOY_EVENTS,
            context_refs=[patch_id],
            status="complete",
            metadata=metadata or {},
        )
        try:
            await self._publish(envelope)
            logger.info("SEO Event Bus: Published deploy event for patch %s", patch_id)
            return envelope
        except Exception as e:
            logger.error("SEO Event Bus: Failed to publish deploy event for patch %s: %s", patch_id, e)
            raise

    async def publish_swarm_dlq(
        self,
        *,
        task_id: UUID,
        source_agent: str,
        failed_queue: str,
        context_refs: list[UUID],
        error: str,
        final_trace: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SwarmEventEnvelope:
        envelope = build_swarm_event(
            task_id=task_id,
            source_agent=source_agent,
            target_queue=SWARM_QUEUE_DLQ,
            context_refs=context_refs,
            status="failed",
            metadata={
                "failed_queue": failed_queue,
                "error": error[:500],
                "final_trace": final_trace or {},
                **(metadata or {}),
            },
        )
        try:
            serialized = _serialize_payload(envelope.model_dump(mode="json"))
            await self.redis.lpush(SWARM_QUEUE_DLQ, serialized)
            await self.redis.lpush(SEO_QUEUE_DLQ, serialized)
            logger.error(
                "SEO Event Bus: Routed task %s from %s to swarm DLQ.",
                task_id,
                failed_queue,
            )
            return envelope
        except Exception as e:
            logger.error("SEO Event Bus: Failed to publish swarm DLQ event for task %s: %s", task_id, e)
            raise
