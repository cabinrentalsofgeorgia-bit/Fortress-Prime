"""
SEO Deploy Event Consumer — BRPOP listener for fortress:seo:deploy_events.

Resolves the approved patch's property slug via Postgres, then fires a secure
webhook to the storefront (cabin-rentals-of-georgia.com) to invalidate the
Next.js tag-based cache for that property's SEO payload.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.services.openshell_audit import record_audit_event
from backend.vrs.infrastructure.seo_event_bus import (
    SEOEventBus,
    SEO_QUEUE_DEPLOY_EVENTS,
    parse_swarm_event,
)

logger = logging.getLogger(__name__)


class SEODeployWorker:
    """
    Background consumer that listens for approved SEO patches and
    fires webhooks to the storefront edge to invalidate Next.js caches.
    """

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client
        self.event_bus = SEOEventBus(redis_client)
        self.running = False

    @property
    def webhook_url(self) -> str:
        base = settings.storefront_base_url.rstrip("/")
        return f"{base}/api/revalidate-seo"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.running = True
        logger.info("SEO Deploy Event Consumer: ONLINE. Listening for cache invalidation events…")

        async with httpx.AsyncClient() as http_client:
            while self.running:
                try:
                    result = await self.redis.brpop([SEO_QUEUE_DEPLOY_EVENTS], timeout=5)
                    if result:
                        _, message = result
                        await self._process_deploy_event(message, http_client)
                except asyncio.CancelledError:
                    logger.info("Deploy worker received cancellation signal. Shutting down.")
                    self.running = False
                except Exception as exc:
                    logger.error("Deploy Worker fatal loop error: %s", exc)
                    await asyncio.sleep(5)

    def stop(self) -> None:
        self.running = False

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _process_deploy_event(self, message: str, http_client: httpx.AsyncClient) -> None:
        try:
            envelope = parse_swarm_event(
                message,
                expected_queue=SEO_QUEUE_DEPLOY_EVENTS,
                legacy_source_agent="seo_patch_api",
                legacy_status="complete",
            )
            patch_id = envelope.primary_context_ref
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Malformed message on deploy_events → DLQ. Error: %s", exc)
            await self.event_bus.publish_swarm_dlq(
                task_id=uuid4(),
                source_agent="seo_deploy_consumer",
                failed_queue=SEO_QUEUE_DEPLOY_EVENTS,
                context_refs=[uuid4()],
                error=str(exc),
                final_trace={"raw_message": str(message)[:2000]},
            )
            return

        async with AsyncSessionLocal() as db:
            slug = await self._resolve_property_slug(db, patch_id)

        if not slug:
            logger.error("Could not resolve slug for patch %s → DLQ.", patch_id)
            await self._mark_patch_failed(
                patch_id,
                envelope=envelope,
                error="property slug not found for deploy event",
                final_trace={},
            )
            return

        if not await self._mark_patch_processing(patch_id, envelope):
            return

        await self._trigger_revalidation(patch_id, slug, envelope, http_client)

    async def _resolve_property_slug(self, db: AsyncSession, patch_id: UUID) -> str | None:
        stmt = (
            select(Property.slug)
            .join(SEOPatch, SEOPatch.property_id == Property.id)
            .where(SEOPatch.id == patch_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Edge webhook
    # ------------------------------------------------------------------

    async def _mark_patch_processing(self, patch_id: UUID, envelope: Any) -> bool:
        async with AsyncSessionLocal() as db:
            patch = await db.get(SEOPatch, patch_id)
            if patch is None:
                logger.error("Deploy worker could not find patch %s while marking processing.", patch_id)
                await self.event_bus.publish_swarm_dlq(
                    task_id=envelope.task_id,
                    source_agent="seo_deploy_consumer",
                    failed_queue=SEO_QUEUE_DEPLOY_EVENTS,
                    context_refs=[patch_id],
                    error="seo patch not found while marking deploy processing",
                    final_trace={},
                )
                return False

            patch.deploy_task_id = envelope.task_id
            patch.deploy_status = "processing"
            patch.deploy_attempts = int(patch.deploy_attempts or 0) + 1
            patch.deploy_last_error = None
            patch.deploy_last_http_status = None
            await db.commit()

            await record_audit_event(
                actor_email="seo_deploy_consumer",
                action="seo.patch.deploy_started",
                resource_type="seo_patch",
                resource_id=str(patch.id),
                purpose="seo_phase2_deploy",
                tool_name="seo_deploy_consumer",
                model_route="worker",
                db=db,
                metadata_json={
                    "task_id": str(envelope.task_id),
                    "page_path": patch.page_path,
                    "property_id": str(patch.property_id) if patch.property_id else None,
                    "deploy_attempts": patch.deploy_attempts,
                },
            )
            return True

    async def _mark_patch_succeeded(
        self,
        patch_id: UUID,
        *,
        envelope: Any,
        http_status: int,
        response_payload: dict[str, Any],
    ) -> None:
        async with AsyncSessionLocal() as db:
            patch = await db.get(SEOPatch, patch_id)
            if patch is None:
                logger.error("Deploy worker could not find patch %s while marking success.", patch_id)
                return

            acknowledged_at = datetime.now(timezone.utc)
            patch.deploy_task_id = envelope.task_id
            patch.status = "deployed"
            patch.deployed_at = acknowledged_at
            patch.deploy_status = "succeeded"
            patch.deploy_acknowledged_at = acknowledged_at
            patch.deploy_last_error = None
            patch.deploy_last_http_status = http_status
            await db.commit()

            await record_audit_event(
                actor_email="seo_deploy_consumer",
                action="seo.patch.deploy_succeeded",
                resource_type="seo_patch",
                resource_id=str(patch.id),
                purpose="seo_phase2_deploy",
                tool_name="seo_deploy_consumer",
                model_route="worker",
                db=db,
                metadata_json={
                    "task_id": str(envelope.task_id),
                    "page_path": patch.page_path,
                    "property_id": str(patch.property_id) if patch.property_id else None,
                    "http_status": http_status,
                    "response": response_payload,
                    "acknowledged_at": acknowledged_at.isoformat(),
                },
            )

    async def _mark_patch_failed(
        self,
        patch_id: UUID,
        *,
        envelope: Any,
        error: str,
        http_status: int | None = None,
        final_trace: dict[str, Any] | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            patch = await db.get(SEOPatch, patch_id)
            if patch is not None:
                acknowledged_at = datetime.now(timezone.utc)
                patch.deploy_task_id = envelope.task_id
                patch.deploy_status = "failed"
                patch.deploy_acknowledged_at = acknowledged_at
                patch.deploy_last_error = error[:2000]
                patch.deploy_last_http_status = http_status
                await db.commit()

                await record_audit_event(
                    actor_email="seo_deploy_consumer",
                    action="seo.patch.deploy_failed",
                    resource_type="seo_patch",
                    resource_id=str(patch.id),
                    purpose="seo_phase2_deploy",
                    tool_name="seo_deploy_consumer",
                    model_route="worker",
                    outcome="failure",
                    db=db,
                    metadata_json={
                        "task_id": str(envelope.task_id),
                        "page_path": patch.page_path,
                        "property_id": str(patch.property_id) if patch.property_id else None,
                        "http_status": http_status,
                        "error": error[:500],
                        "acknowledged_at": acknowledged_at.isoformat(),
                    },
                )

        dlq_published = await self.event_bus.publish_swarm_dlq(
            task_id=envelope.task_id,
            source_agent="seo_deploy_consumer",
            failed_queue=SEO_QUEUE_DEPLOY_EVENTS,
            context_refs=[patch_id],
            error=error,
            final_trace=final_trace or {},
            metadata={"http_status": http_status} if http_status is not None else None,
        )
        if dlq_published:
            await record_audit_event(
                actor_email="seo_deploy_consumer",
                action="seo.patch.deploy_dlq",
                resource_type="seo_patch",
                resource_id=str(patch_id),
                purpose="seo_phase2_deploy",
                tool_name="seo_deploy_consumer",
                model_route="worker",
                outcome="failure",
                db=None,
                metadata_json={
                    "task_id": str(envelope.task_id),
                    "http_status": http_status,
                    "error": error[:500],
                },
            )

    async def _trigger_revalidation(
        self,
        patch_id: UUID,
        slug: str,
        envelope: Any,
        http_client: httpx.AsyncClient,
    ) -> None:
        if not settings.edge_revalidation_secret:
            logger.error("EDGE_REVALIDATION_SECRET is not configured. Aborting webhook for slug=%s.", slug)
            await self._mark_patch_failed(
                patch_id,
                envelope=envelope,
                error="EDGE_REVALIDATION_SECRET is not configured",
                final_trace={"slug": slug},
            )
            return

        headers = {
            "Authorization": f"Bearer {settings.edge_revalidation_secret}",
            "Content-Type": "application/json",
        }

        try:
            response = await http_client.post(
                self.webhook_url,
                json={"slug": slug},
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Edge cache invalidated for slug=%s (HTTP %d).", slug, response.status_code)
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                payload = {}
            await self._mark_patch_succeeded(
                patch_id,
                envelope=envelope,
                http_status=response.status_code,
                response_payload=payload,
            )
        except httpx.HTTPError as exc:
            logger.error("Failed to invalidate Edge cache for slug=%s: %s", slug, exc)
            http_status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            response_text = ""
            if isinstance(exc, httpx.HTTPStatusError):
                response_text = exc.response.text[:1000]
            await self._mark_patch_failed(
                patch_id,
                envelope=envelope,
                http_status=http_status,
                error=f"Failed to invalidate Edge cache for slug={slug}: {exc}",
                final_trace={"slug": slug, "response_text": response_text},
            )
