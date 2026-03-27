"""
Projection helpers for Scout feed, routing traceability, and alpha metrics.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.intelligence_distillation import DistillationQueue, DistillationStatus
from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.models.storefront_intent import StorefrontIntentEvent


def _parse_uuid_list(raw_values: list[str] | None) -> list[UUID]:
    parsed: list[UUID] = []
    for raw_value in raw_values or []:
        try:
            parsed.append(UUID(str(raw_value)))
        except (TypeError, ValueError):
            continue
    return parsed


def _status_value(value: str | DistillationStatus | None) -> str:
    if isinstance(value, DistillationStatus):
        return value.value
    return str(value or "")


async def build_intelligence_feed_snapshot(
    db: AsyncSession,
    *,
    limit: int,
    category: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(IntelligenceLedgerEntry).order_by(
        desc(IntelligenceLedgerEntry.discovered_at),
        desc(IntelligenceLedgerEntry.created_at),
    )
    if category:
        stmt = stmt.where(IntelligenceLedgerEntry.category == category.strip())
    entries = (await db.execute(stmt.limit(limit))).scalars().all()
    if not entries:
        return []

    entry_ids = [entry.id for entry in entries]
    property_ids = {
        property_id
        for entry in entries
        for property_id in _parse_uuid_list(list(entry.target_property_ids or []))
    }

    properties = (
        await db.execute(select(Property).where(Property.id.in_(property_ids)))
    ).scalars().all() if property_ids else []
    property_map = {prop.id: prop for prop in properties}

    seo_rows = (
        await db.execute(
            select(SEOPatch).where(
                SEOPatch.source_intelligence_id.in_(entry_ids),
            )
        )
    ).scalars().all()
    seo_by_entry: dict[UUID, list[SEOPatch]] = defaultdict(list)
    for row in seo_rows:
        if isinstance(row.source_intelligence_id, UUID):
            seo_by_entry[row.source_intelligence_id].append(row)

    distillation_rows = (
        await db.execute(
            select(DistillationQueue).where(
                DistillationQueue.source_intelligence_id.in_(entry_ids),
            )
        )
    ).scalars().all()
    distillation_by_entry: dict[UUID, list[DistillationQueue]] = defaultdict(list)
    for row in distillation_rows:
        if isinstance(row.source_intelligence_id, UUID):
            distillation_by_entry[row.source_intelligence_id].append(row)

    feed: list[dict[str, Any]] = []
    for entry in entries:
        targeted_properties = []
        for property_id in _parse_uuid_list(list(entry.target_property_ids or [])):
            prop = property_map.get(property_id)
            if prop is None:
                continue
            targeted_properties.append(
                {"id": str(prop.id), "slug": prop.slug, "name": prop.name}
            )

        seo_patches = seo_by_entry.get(entry.id, [])
        pricing_rows = distillation_by_entry.get(entry.id, [])
        feed.append(
            {
                "id": str(entry.id),
                "category": entry.category,
                "title": entry.title,
                "summary": entry.summary,
                "market": entry.market,
                "locality": entry.locality,
                "confidence_score": entry.confidence_score,
                "dedupe_hash": entry.dedupe_hash,
                "query_topic": entry.query_topic,
                "source_urls": list(entry.source_urls or []),
                "target_tags": list(entry.target_tags or []),
                "targeted_properties": targeted_properties,
                "seo_patch_ids": [str(patch.id) for patch in seo_patches],
                "seo_patch_statuses": [patch.status for patch in seo_patches],
                "pricing_signal_ids": [str(row.id) for row in pricing_rows],
                "pricing_signal_statuses": [_status_value(row.status) for row in pricing_rows],
                "discovered_at": entry.discovered_at,
                "created_at": entry.created_at,
            }
        )
    return feed


async def build_property_context_projection(
    db: AsyncSession,
    *,
    property_slug: str,
    limit: int,
) -> dict[str, Any] | None:
    property_row = (
        await db.execute(
            select(Property)
            .where(Property.slug == property_slug.strip().lower())
            .where(Property.is_active.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if property_row is None:
        return None

    entry_rows = (
        await db.execute(
            select(IntelligenceLedgerEntry)
            .where(IntelligenceLedgerEntry.target_property_ids.contains([str(property_row.id)]))
            .order_by(
                desc(IntelligenceLedgerEntry.discovered_at),
                desc(IntelligenceLedgerEntry.created_at),
            )
            .limit(limit)
        )
    ).scalars().all()

    return {
        "property_id": str(property_row.id),
        "property_slug": property_row.slug,
        "property_name": property_row.name,
        "items": [
            {
                "id": str(entry.id),
                "category": entry.category,
                "title": entry.title,
                "summary": entry.summary,
                "market": entry.market,
                "locality": entry.locality,
                "confidence_score": entry.confidence_score,
                "query_topic": entry.query_topic,
                "source_urls": list(entry.source_urls or []),
                "target_tags": list(entry.target_tags or []),
                "discovered_at": entry.discovered_at,
            }
            for entry in entry_rows
        ],
    }


async def load_scout_alpha_metrics(
    db: AsyncSession,
    *,
    window_days: int = 30,
) -> dict[str, Any]:
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)
    patches = (
        await db.execute(
            select(SEOPatch).where(SEOPatch.created_at >= window_start)
        )
    ).scalars().all()

    scout_patches = [patch for patch in patches if patch.source_intelligence_id is not None]
    manual_patches = [patch for patch in patches if patch.source_intelligence_id is None]

    property_ids = {
        patch.property_id for patch in patches if isinstance(patch.property_id, UUID)
    }
    recent_intelligence_entries = (
        await db.execute(
            select(IntelligenceLedgerEntry).where(IntelligenceLedgerEntry.discovered_at >= window_start)
        )
    ).scalars().all()
    property_ids.update(
        property_id
        for entry in recent_intelligence_entries
        for property_id in _parse_uuid_list(list(entry.target_property_ids or []))
    )
    properties = (
        await db.execute(select(Property).where(Property.id.in_(property_ids)))
    ).scalars().all() if property_ids else []
    slug_by_property_id = {prop.id: prop.slug for prop in properties}

    scout_slugs = {
        slug_by_property_id[patch.property_id]
        for patch in scout_patches
        if patch.property_id in slug_by_property_id
    }
    manual_slugs = {
        slug_by_property_id[patch.property_id]
        for patch in manual_patches
        if patch.property_id in slug_by_property_id
    }
    scout_projection_slugs = {
        slug_by_property_id[property_id]
        for entry in recent_intelligence_entries
        for property_id in _parse_uuid_list(list(entry.target_property_ids or []))
        if property_id in slug_by_property_id
    }

    event_rows = (
        await db.execute(
            select(StorefrontIntentEvent).where(StorefrontIntentEvent.created_at >= window_start)
        )
    ).scalars().all()

    def _event_count(property_slugs: set[str], *, event_type: str | None = None) -> int:
        return sum(
            1
            for row in event_rows
            if row.property_slug in property_slugs and (event_type is None or row.event_type == event_type)
        )

    scout_categories: dict[str, list[SEOPatch]] = defaultdict(list)
    scout_entry_ids = {patch.source_intelligence_id for patch in scout_patches if patch.source_intelligence_id}
    scout_entries = (
        await db.execute(
            select(IntelligenceLedgerEntry).where(IntelligenceLedgerEntry.id.in_(scout_entry_ids))
        )
    ).scalars().all() if scout_entry_ids else []
    category_by_entry_id = {entry.id: entry.category for entry in scout_entries}
    for patch in scout_patches:
        if patch.source_intelligence_id in category_by_entry_id:
            scout_categories[category_by_entry_id[patch.source_intelligence_id]].append(patch)

    def _avg_score(rows: list[SEOPatch]) -> float:
        scores = [float(row.godhead_score) for row in rows if row.godhead_score is not None]
        return float(mean(scores)) if scores else 0.0

    return {
        "window_days": window_days,
        "scout_patch_count": len(scout_patches),
        "manual_patch_count": len(manual_patches),
        "scout_deployed_count": sum(1 for patch in scout_patches if patch.deploy_status == "succeeded"),
        "manual_deployed_count": sum(1 for patch in manual_patches if patch.deploy_status == "succeeded"),
        "scout_pending_human_count": sum(1 for patch in scout_patches if patch.status == "pending_human"),
        "manual_pending_human_count": sum(1 for patch in manual_patches if patch.status == "pending_human"),
        "scout_avg_godhead_score": _avg_score(scout_patches),
        "manual_avg_godhead_score": _avg_score(manual_patches),
        "scout_intent_event_count": _event_count(scout_slugs),
        "manual_intent_event_count": _event_count(manual_slugs),
        "scout_hold_started_count": _event_count(scout_slugs, event_type="funnel_hold_started"),
        "manual_hold_started_count": _event_count(manual_slugs, event_type="funnel_hold_started"),
        "scout_insight_impression_count": _event_count(
            scout_projection_slugs,
            event_type="insight_impression",
        ),
        "category_breakdown": [
            {
                "category": category,
                "patch_count": len(rows),
                "deployed_count": sum(1 for patch in rows if patch.deploy_status == "succeeded"),
                "avg_godhead_score": _avg_score(rows),
            }
            for category, rows in sorted(
                scout_categories.items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )
        ],
    }
