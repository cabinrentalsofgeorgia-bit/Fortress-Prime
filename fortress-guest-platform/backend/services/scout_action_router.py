"""
Route grounded Scout findings into SEO drafts and Treasurer staging.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import async_session_maker
from backend.models.intelligence_distillation import DistillationQueue, DistillationStatus
from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.models.property import Property
from backend.models.property_knowledge import PropertyKnowledge
from backend.models.seo_patch import SEOPatch
from backend.services.seo_extraction_service import SEOExtractionSwarm

logger = structlog.get_logger(service="scout_action_router")

MIN_SEO_CONFIDENCE = 0.75
MIN_PRICING_CONFIDENCE = 0.70
MAX_ROUTED_PROPERTIES = 6
LOCAL_EVENT_TERMS = {
    "event",
    "festival",
    "concert",
    "tournament",
    "weekend",
    "fair",
    "rodeo",
    "market",
    "fly fishing",
    "fishing",
}
TAG_KEYWORDS: dict[str, set[str]] = {
    "river-access": {"river", "riverside", "riverfront", "waterfront", "water access"},
    "fishing-nearby": {"fishing", "fly fishing", "trout", "angler", "fishing lodge"},
    "lake-nearby": {"lake", "lakeside", "dock"},
    "hiking-nearby": {"hiking", "trail", "mountain trail", "waterfall"},
    "pet-friendly": {"pet friendly", "dog friendly", "pets allowed"},
    "family-friendly": {"family", "kid friendly", "group trip", "multi-family"},
    "romantic-retreat": {"romantic", "couples", "honeymoon", "anniversary"},
    "vineyard-nearby": {"vineyard", "winery", "wine tasting"},
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return [normalized] if normalized else []
    if isinstance(value, Decimal):
        return [str(value)]
    if isinstance(value, dict):
        flattened: list[str] = []
        for item in value.values():
            flattened.extend(_flatten_strings(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_strings(item))
        return flattened
    return _flatten_strings(str(value))


def _coerce_uuid_list(raw_values: list[str] | None) -> list[UUID]:
    parsed: list[UUID] = []
    for raw_value in raw_values or []:
        try:
            parsed.append(UUID(str(raw_value)))
        except (TypeError, ValueError):
            continue
    return parsed


def _extract_target_tags(entry: IntelligenceLedgerEntry) -> list[str]:
    haystack = " ".join(
        filter(
            None,
            [
                entry.category,
                entry.title,
                entry.summary,
                entry.locality or "",
                entry.query_topic or "",
                " ".join(_flatten_strings(entry.finding_payload)),
            ],
        )
    )
    normalized = _normalize_text(haystack)
    matches = {
        tag
        for tag, keywords in TAG_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    }
    return sorted(matches)


def _is_local_event(entry: IntelligenceLedgerEntry) -> bool:
    normalized = _normalize_text(f"{entry.title} {entry.summary} {entry.query_topic or ''}")
    return any(term in normalized for term in LOCAL_EVENT_TERMS)


def _should_create_seo(entry: IntelligenceLedgerEntry) -> bool:
    confidence = float(entry.confidence_score or 0.0)
    return confidence >= MIN_SEO_CONFIDENCE and (
        entry.category in {"content_gap", "market_shift"} or _is_local_event(entry)
    )


def _should_stage_pricing(entry: IntelligenceLedgerEntry) -> bool:
    confidence = float(entry.confidence_score or 0.0)
    return confidence >= MIN_PRICING_CONFIDENCE and entry.category in {
        "competitor_trend",
        "market_shift",
    }


class ResearchScoutActionRouter:
    SOURCE_AGENT = "agentic_scout"

    async def route_inserted_findings(
        self,
        db: AsyncSession,
        *,
        inserted_entry_ids: list[str] | None,
    ) -> dict[str, Any]:
        entry_ids = _coerce_uuid_list(inserted_entry_ids)
        if not entry_ids:
            return {
                "routed_count": 0,
                "seo_draft_count": 0,
                "pricing_signal_count": 0,
                "items": [],
            }

        entries = (
            await db.execute(
                select(IntelligenceLedgerEntry)
                .where(IntelligenceLedgerEntry.id.in_(entry_ids))
                .order_by(IntelligenceLedgerEntry.discovered_at.desc())
            )
        ).scalars().all()
        if not entries:
            return {
                "routed_count": 0,
                "seo_draft_count": 0,
                "pricing_signal_count": 0,
                "items": [],
            }

        property_context = await self._load_property_context(db)
        items: list[dict[str, Any]] = []
        seo_draft_count = 0
        pricing_signal_count = 0

        for entry in entries:
            try:
                async with db.begin_nested():
                    target_tags = _extract_target_tags(entry)
                    targeted_property_ids = self._resolve_target_property_ids(
                        entry,
                        property_context,
                        target_tags,
                    )
                    entry.target_tags = target_tags
                    entry.target_property_ids = [str(property_id) for property_id in targeted_property_ids]
                    await db.flush()

                    seo_results: list[dict[str, Any]] = []
                    pricing_signal: dict[str, Any] | None = None

                    if targeted_property_ids and _should_create_seo(entry):
                        seo_results = await self._ensure_seo_drafts(
                            db,
                            entry=entry,
                            property_ids=targeted_property_ids,
                            target_tags=target_tags,
                        )
                        seo_draft_count += len(seo_results)

                    if targeted_property_ids and _should_stage_pricing(entry):
                        pricing_signal = await self._ensure_pricing_signal(
                            db,
                            entry=entry,
                            property_ids=targeted_property_ids,
                            target_tags=target_tags,
                        )
                        if pricing_signal is not None:
                            pricing_signal_count += 1

                    if seo_results or pricing_signal is not None:
                        payload = dict(entry.finding_payload or {})
                        payload["action_routed"] = True
                        payload["routed_at"] = datetime.now(timezone.utc).isoformat()
                        entry.finding_payload = payload
                        await db.flush()

                    items.append(
                        {
                            "entry_id": str(entry.id),
                            "category": entry.category,
                            "target_property_ids": [str(property_id) for property_id in targeted_property_ids],
                            "target_tags": target_tags,
                            "seo_drafts": seo_results,
                            "pricing_signal": pricing_signal,
                        }
                    )
            except Exception:
                logger.exception(
                    "research_scout_route_entry_failed",
                    entry_id=str(entry.id),
                    category=entry.category,
                )
                continue

        await db.commit()
        return {
            "routed_count": len(items),
            "seo_draft_count": seo_draft_count,
            "pricing_signal_count": pricing_signal_count,
            "items": items,
        }

    async def _load_property_context(self, db: AsyncSession) -> list[dict[str, Any]]:
        properties = (
            await db.execute(select(Property).where(Property.is_active.is_(True)).order_by(Property.name.asc()))
        ).scalars().all()
        knowledge_rows = (await db.execute(select(PropertyKnowledge))).scalars().all()
        knowledge_by_property: dict[UUID, list[PropertyKnowledge]] = defaultdict(list)
        for row in knowledge_rows:
            property_id = getattr(row, "property_id", None)
            if isinstance(property_id, UUID):
                knowledge_by_property[property_id].append(row)

        contexts: list[dict[str, Any]] = []
        for prop in properties:
            searchable = {
                _normalize_text(prop.name),
                _normalize_text(prop.slug),
                _normalize_text(prop.address or ""),
            }
            searchable.update(_flatten_strings(prop.amenities))
            for row in knowledge_by_property.get(prop.id, []):
                searchable.update(_flatten_strings(row.tags))
                searchable.add(_normalize_text(row.category))
                searchable.update(_flatten_strings(row.content))
            expanded_terms = {term for term in searchable if term}
            expanded_terms.update(term.replace(" ", "-") for term in list(expanded_terms))
            for tag, keywords in TAG_KEYWORDS.items():
                if tag in expanded_terms or any(
                    keyword in term for term in expanded_terms for keyword in keywords
                ):
                    expanded_terms.add(tag)
            contexts.append(
                {
                    "id": prop.id,
                    "name": prop.name,
                    "slug": prop.slug,
                    "address": prop.address or "",
                    "max_guests": int(prop.max_guests or 0),
                    "searchable_terms": expanded_terms,
                }
            )
        return contexts

    def _match_properties(
        self,
        entry: IntelligenceLedgerEntry,
        property_context: list[dict[str, Any]],
        target_tags: list[str],
    ) -> list[UUID]:
        locality = _normalize_text(entry.locality or entry.market)
        locality_slug = locality.replace(" ", "-")
        ranked: list[tuple[int, int, UUID]] = []
        for ctx in property_context:
            searchable_terms: set[str] = ctx["searchable_terms"]
            matched_tags = sum(1 for tag in target_tags if tag in searchable_terms)
            locality_overlap = (
                1
                if locality
                and any(locality in term or locality_slug in term for term in searchable_terms)
                else 0
            )
            if matched_tags == 0 and locality_overlap == 0:
                continue
            score = (matched_tags * 10) + (locality_overlap * 3)
            ranked.append((score, int(ctx["max_guests"]), ctx["id"]))

        if not ranked and locality:
            for ctx in property_context:
                searchable_terms = ctx["searchable_terms"]
                if any(locality in term or locality_slug in term for term in searchable_terms):
                    ranked.append((1, int(ctx["max_guests"]), ctx["id"]))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [property_id for _score, _guest_count, property_id in ranked[:MAX_ROUTED_PROPERTIES]]

    def _resolve_target_property_ids(
        self,
        entry: IntelligenceLedgerEntry,
        property_context: list[dict[str, Any]],
        target_tags: list[str],
    ) -> list[UUID]:
        seeded_property_ids = _coerce_uuid_list(entry.target_property_ids)
        if seeded_property_ids:
            return seeded_property_ids[:MAX_ROUTED_PROPERTIES]
        return self._match_properties(entry, property_context, target_tags)

    async def _ensure_seo_drafts(
        self,
        db: AsyncSession,
        *,
        entry: IntelligenceLedgerEntry,
        property_ids: list[UUID],
        target_tags: list[str],
    ) -> list[dict[str, Any]]:
        existing_rows = (
            await db.execute(
                select(SEOPatch).where(
                    SEOPatch.source_intelligence_id == entry.id,
                    SEOPatch.property_id.in_(property_ids),
                )
            )
        ).scalars().all()
        existing_property_ids = {
            patch.property_id for patch in existing_rows if isinstance(patch.property_id, UUID)
        }
        swarm = SEOExtractionSwarm(db)
        results: list[dict[str, Any]] = []
        for property_id in property_ids:
            if property_id in existing_property_ids:
                continue
            generated = await swarm.generate_initial_seo_draft_for_context(
                property_id,
                source_intelligence_id=entry.id,
                source_agent=self.SOURCE_AGENT,
                scout_context=self._build_scout_context(entry, target_tags),
            )
            if generated is not None:
                results.append(
                    {
                        "property_id": str(property_id),
                        "patch_id": generated["patch_id"],
                        "status": generated["status"],
                    }
                )
        return results

    async def _ensure_pricing_signal(
        self,
        db: AsyncSession,
        *,
        entry: IntelligenceLedgerEntry,
        property_ids: list[UUID],
        target_tags: list[str],
    ) -> dict[str, Any] | None:
        existing = (
            await db.execute(
                select(DistillationQueue).where(
                    DistillationQueue.source_module == "research_scout",
                    DistillationQueue.source_ref == str(entry.id),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "id": str(existing.id),
                "status": existing.status.value if isinstance(existing.status, DistillationStatus) else str(existing.status),
            }

        queue_row = DistillationQueue(
            source_module="research_scout",
            source_ref=str(entry.id),
            source_intelligence_id=entry.id,
            input_payload={
                "title": entry.title,
                "summary": entry.summary,
                "category": entry.category,
                "market": entry.market,
                "locality": entry.locality,
                "confidence_score": entry.confidence_score,
                "target_property_ids": [str(property_id) for property_id in property_ids],
                "target_tags": target_tags,
                "source_urls": list(entry.source_urls or []),
            },
            output_payload={},
            status=DistillationStatus.QUEUED,
        )
        db.add(queue_row)
        await db.flush()
        return {"id": str(queue_row.id), "status": queue_row.status.value}

    def _build_scout_context(
        self,
        entry: IntelligenceLedgerEntry,
        target_tags: list[str],
    ) -> dict[str, Any]:
        return {
            "source_intelligence_id": str(entry.id),
            "category": entry.category,
            "title": entry.title,
            "summary": entry.summary,
            "market": entry.market,
            "locality": entry.locality,
            "confidence_score": entry.confidence_score,
            "target_tags": target_tags,
            "source_urls": list(entry.source_urls or []),
        }


research_scout_action_router = ResearchScoutActionRouter()


class ScoutActionRouter:
    """Backward-compatible facade for the legacy classmethod router API."""

    @classmethod
    async def route_findings(cls, finding_ids: list[UUID]) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await research_scout_action_router.route_inserted_findings(
                db,
                inserted_entry_ids=[str(finding_id) for finding_id in finding_ids],
            )
