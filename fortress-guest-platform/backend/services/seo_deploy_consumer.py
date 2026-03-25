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
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.services.openshell_audit import record_audit_event
from backend.services.redirect_vanguard_kv import cabin_slug_from_patch_targets, upsert_deployed_cabin_slug
from backend.vrs.infrastructure.seo_event_bus import (
    SEOEventBus,
    SEO_QUEUE_DEPLOY_EVENTS,
    parse_swarm_event,
)

logger = logging.getLogger(__name__)


class SEOPatchTargets:
    def __init__(self, *, slug: str | None, page_path: str) -> None:
        self.slug = slug
        self.page_path = page_path


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
    def revalidate_origin(self) -> str:
        return (
            settings.storefront_revalidate_origin.strip()
            or settings.storefront_base_url.strip()
        ).rstrip("/")

    @property
    def webhook_url(self) -> str:
        return f"{self.revalidate_origin}/api/revalidate-seo"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.running = True
        logger.info(
            "SEO Deploy Event Consumer: ONLINE. Listening for cache invalidation events… origin=%s webhook_url=%s",
            self.revalidate_origin,
            self.webhook_url,
        )

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
            targets = await self._resolve_patch_targets(db, patch_id)

        if not targets:
            logger.error("Could not resolve deploy targets for patch %s → DLQ.", patch_id)
            await self._mark_patch_failed(
                patch_id,
                envelope=envelope,
                error="deploy targets not found for deploy event",
                final_trace={},
            )
            return

        if not await self._mark_patch_processing(patch_id, envelope):
            return

        await self._trigger_revalidation(patch_id, targets, envelope, http_client)

    async def _resolve_patch_targets(self, db: AsyncSession, patch_id: UUID) -> SEOPatchTargets | None:
        stmt = (
            select(SEOPatch.page_path, Property.slug)
            .select_from(SEOPatch)
            .outerjoin(Property, SEOPatch.property_id == Property.id)
            .where(SEOPatch.id == patch_id)
        )
        result = await db.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None

        page_path, slug = row
        normalized_page_path = str(page_path or "").strip()
        if not normalized_page_path:
            return None

        normalized_slug = str(slug).strip() if slug else None
        return SEOPatchTargets(slug=normalized_slug or None, page_path=normalized_page_path)

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
        webhook_url: str,
        response_payload: dict[str, Any],
    ) -> None:
        async with AsyncSessionLocal() as db:
            patch = await db.get(SEOPatch, patch_id)
            if patch is None:
                logger.error("Deploy worker could not find patch %s while marking success.", patch_id)
                return

            acknowledged_at = datetime.now(timezone.utc)
            patch.deploy_task_id = envelope.task_id
            patch.deploy_status = "succeeded"
            patch.deploy_acknowledged_at = acknowledged_at
            patch.deploy_last_error = None
            patch.deploy_last_http_status = http_status
            patch.status = "deployed"
            patch.deployed_at = func.now()
            if patch.property_id is not None:
                await db.execute(
                    update(SEOPatch)
                    .where(
                        SEOPatch.property_id == patch.property_id,
                        SEOPatch.status == "deployed",
                        SEOPatch.id != patch.id,
                    )
                    .values(status="archived")
                )
            await db.commit()
            await db.refresh(patch)

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
                    "webhook_url": webhook_url,
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
        webhook_url: str | None = None,
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
                        "webhook_url": webhook_url,
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
                    "webhook_url": webhook_url,
                    "http_status": http_status,
                    "error": error[:500],
                },
            )

    async def _trigger_revalidation(
        self,
        patch_id: UUID,
        targets: SEOPatchTargets,
        envelope: Any,
        http_client: httpx.AsyncClient,
    ) -> None:
        revalidation_secret = settings.edge_revalidation_secret.strip()
        webhook_url = self.webhook_url
        if not revalidation_secret:
            logger.error(
                "EDGE_REVALIDATION_SECRET is not configured. Aborting webhook for page_path=%s webhook_url=%s.",
                targets.page_path,
                webhook_url,
            )
            await self._mark_patch_failed(
                patch_id,
                envelope=envelope,
                error="EDGE_REVALIDATION_SECRET is not configured",
                webhook_url=webhook_url,
                final_trace={"page_path": targets.page_path, "slug": targets.slug, "webhook_url": webhook_url},
            )
            return

        paths = [targets.page_path]
        if targets.page_path.startswith("/cabins/"):
            paths.append("/sitemap.xml")

        tag_set = {f"seo-patch-{targets.slug}"} if targets.slug else set()
        headers = {
            "Authorization": f"Bearer {revalidation_secret}",
            "Content-Type": "application/json",
        }
        revalidation_payload = {
            "paths": paths,
            "tags": sorted(tag_set),
        }

        try:
            logger.info(
                "Sending SEO revalidation webhook for page_path=%s slug=%s webhook_url=%s",
                targets.page_path,
                targets.slug,
                webhook_url,
            )
            response = await http_client.post(
                webhook_url,
                json=revalidation_payload,
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info(
                "Edge cache invalidated for page_path=%s slug=%s (HTTP %d).",
                targets.page_path,
                targets.slug,
                response.status_code,
            )
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                payload = {}
            await self._mark_patch_succeeded(
                patch_id,
                envelope=envelope,
                http_status=response.status_code,
                webhook_url=webhook_url,
                response_payload=payload,
            )
            slug_for_kv = cabin_slug_from_patch_targets(
                property_slug=targets.slug,
                page_path=targets.page_path,
            )
            if slug_for_kv:
                await upsert_deployed_cabin_slug(slug_for_kv, http_client=http_client)
        except httpx.HTTPError as exc:
            logger.error(
                "Failed to invalidate Edge cache for page_path=%s slug=%s: %s",
                targets.page_path,
                targets.slug,
                exc,
            )
            http_status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            response_text = ""
            if isinstance(exc, httpx.HTTPStatusError):
                response_text = exc.response.text[:1000]
            await self._mark_patch_failed(
                patch_id,
                envelope=envelope,
                webhook_url=webhook_url,
                http_status=http_status,
                error=f"Failed to invalidate Edge cache for page_path={targets.page_path}: {exc}",
                final_trace={
                    "page_path": targets.page_path,
                    "slug": targets.slug,
                    "webhook_url": webhook_url,
                    "response_text": response_text,
                },
            )
