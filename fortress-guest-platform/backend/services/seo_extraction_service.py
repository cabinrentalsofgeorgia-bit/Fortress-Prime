"""
DGX SEO extraction service for drafted SEOPatch generation.
"""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.media import PropertyImage
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.services.jsonld_builder import build_property_jsonld
from backend.services.swarm_service import submit_chat_completion
from backend.vrs.infrastructure.seo_event_bus import publish_grade_request

logger = structlog.get_logger(service="seo_extraction_service")

MAX_LEGACY_CONTEXT_CHARS = 12000
MAX_LEGACY_MATCHES = 3
GENERATION_SYSTEM_PROMPT = (
    "You are the Fortress Prime sovereign SEO extraction swarm. "
    "Return ONLY a JSON object with keys: title, meta_description, og_title, "
    "og_description, h1_suggestion, alt_tags. "
    "Generate guest-facing SEO copy grounded in the supplied property facts and legacy Drupal context. "
    "alt_tags must be an object mapping stable image keys to concise descriptive alt text."
)


async def generate_initial_seo_draft(property_id: UUID) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as db:
        return await SEOExtractionSwarm(db).generate_initial_seo_draft(property_id)


async def extract_and_draft_seo(property_id: UUID | str) -> dict[str, Any] | None:
    normalized_property_id = property_id if isinstance(property_id, UUID) else UUID(str(property_id))
    return await generate_initial_seo_draft(normalized_property_id)


@lru_cache(maxsize=1)
def _load_legacy_blueprint() -> dict[str, Any] | None:
    configured_path = str(settings.historian_blueprint_path or "").strip()
    if configured_path:
        blueprint_path = Path(configured_path).expanduser()
    else:
        blueprint_path = Path(__file__).resolve().parents[1] / "scripts" / "drupal_granular_blueprint.json"
    if not blueprint_path.exists():
        return None
    try:
        return json.loads(blueprint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class SEOExtractionSwarm:
    SOURCE_AGENT = "seo_extraction_service"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.model_name = str(
            settings.dgx_inference_model
            or settings.swarm_model
            or settings.ollama_fast_model
        ).strip()

    async def generate_initial_seo_draft(self, property_id: UUID) -> dict[str, Any] | None:
        rubric = await self._resolve_active_rubric()
        if rubric is None:
            logger.error("seo_extraction_no_active_rubric", property_id=str(property_id))
            return None

        property_record = await self._fetch_property(property_id)
        if property_record is None:
            logger.error("seo_extraction_property_not_found", property_id=str(property_id))
            return None

        legacy_context = self._load_legacy_drupal_context(property_record)
        return await self.run_extraction(
            property_id=property_id,
            rubric_id=rubric.id,
            legacy_drupal_context=legacy_context,
        )

    async def run_extraction(
        self,
        property_id: UUID,
        rubric_id: UUID,
        legacy_drupal_context: str,
    ) -> dict[str, Any] | None:
        started_at = time.perf_counter()
        property_record = await self._fetch_property(property_id)
        if property_record is None:
            logger.error("seo_extraction_property_not_found", property_id=str(property_id))
            return None

        property_payload = await self._build_property_payload(property_record)
        seo_payload = await self._generate_seo_copy(property_payload, legacy_drupal_context)
        if seo_payload is None:
            return None

        page_path = f"/cabins/{property_record.slug}"
        canonical_url = f"{settings.storefront_base_url.rstrip('/')}{page_path}"
        patch_payload = {
            "page_path": page_path,
            "canonical_url": canonical_url,
            "meta_description": seo_payload["meta_description"],
            "og_description": seo_payload["og_description"],
            "storefront_base_url": settings.storefront_base_url,
        }

        jsonld_payload = build_property_jsonld(property_payload, patch_payload)
        generation_ms = max(1, int((time.perf_counter() - started_at) * 1000))

        patch = SEOPatch(
            property_id=property_record.id,
            rubric_id=rubric_id,
            page_path=page_path,
            title=seo_payload["title"],
            meta_description=seo_payload["meta_description"],
            og_title=seo_payload["og_title"],
            og_description=seo_payload["og_description"],
            canonical_url=canonical_url,
            h1_suggestion=seo_payload["h1_suggestion"],
            alt_tags=seo_payload["alt_tags"],
            jsonld_payload=jsonld_payload,
            swarm_model=self.model_name,
            swarm_node=settings.node_ip,
            generation_ms=generation_ms,
            status="drafted",
        )
        self.db.add(patch)
        await self.db.commit()
        await self.db.refresh(patch)

        published = await publish_grade_request(patch.id, source_agent=self.SOURCE_AGENT)
        if not published:
            logger.error("seo_extraction_grade_enqueue_failed", patch_id=str(patch.id))
            return None

        logger.info(
            "seo_extraction_completed",
            patch_id=str(patch.id),
            property_id=str(property_record.id),
            rubric_id=str(rubric_id),
            model=self.model_name,
            generation_ms=generation_ms,
        )
        return {
            "patch_id": str(patch.id),
            "status": patch.status,
            "generation_ms": generation_ms,
            "queued_for_grading": True,
        }

    async def _fetch_property(self, property_id: UUID) -> Property | None:
        return (
            await self.db.execute(select(Property).where(Property.id == property_id))
        ).scalar_one_or_none()

    async def _resolve_active_rubric(self) -> SEORubric | None:
        return (
            await self.db.execute(
                select(SEORubric)
                .where(SEORubric.status == "active")
                .order_by(SEORubric.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _build_property_payload(self, property_record: Property) -> dict[str, Any]:
        image_rows = (
            await self.db.execute(
                select(PropertyImage)
                .where(PropertyImage.property_id == property_record.id)
                .order_by(PropertyImage.is_hero.desc(), PropertyImage.display_order.asc())
            )
        ).scalars().all()
        images = [
            image.sovereign_url or image.legacy_url
            for image in image_rows
            if (image.sovereign_url or image.legacy_url)
        ]
        return {
            "id": str(property_record.id),
            "name": property_record.name,
            "slug": property_record.slug,
            "property_type": property_record.property_type,
            "bedrooms": property_record.bedrooms,
            "bathrooms": property_record.bathrooms,
            "max_guests": property_record.max_guests,
            "address": property_record.address,
            "latitude": property_record.latitude,
            "longitude": property_record.longitude,
            "amenities": property_record.amenities or [],
            "rate_card": property_record.rate_card or {},
            "parking_instructions": property_record.parking_instructions,
            "streamline_property_id": property_record.streamline_property_id,
            "is_active": property_record.is_active,
            "owner_name": property_record.owner_name,
            "images": images,
            "default_image_path": images[0] if images else None,
            "storefront_base_url": settings.storefront_base_url,
        }

    async def _generate_seo_copy(
        self,
        property_payload: dict[str, Any],
        legacy_context: str,
    ) -> dict[str, Any] | None:
        if not self.model_name:
            logger.error(
                "seo_extraction_missing_model",
                property_id=property_payload.get("id"),
            )
            return None

        prompt = json.dumps(
            {
                "task": "Generate a first-pass SEO patch for a Fortress Prime property page.",
                "property": {
                    "name": property_payload.get("name"),
                    "slug": property_payload.get("slug"),
                    "property_type": property_payload.get("property_type"),
                    "bedrooms": property_payload.get("bedrooms"),
                    "bathrooms": str(property_payload.get("bathrooms") or ""),
                    "max_guests": property_payload.get("max_guests"),
                    "address": property_payload.get("address"),
                    "amenities": self._flatten_amenities(property_payload.get("amenities")),
                },
                "legacy_drupal_context": legacy_context[:MAX_LEGACY_CONTEXT_CHARS],
                "response_contract": {
                    "title": "string <= 255 chars",
                    "meta_description": "string <= 320 chars",
                    "og_title": "string_or_null <= 255 chars",
                    "og_description": "string_or_null <= 320 chars",
                    "h1_suggestion": "string_or_null <= 255 chars",
                    "alt_tags": {"image_key": "short alt text"},
                },
            },
            ensure_ascii=True,
            default=str,
        )

        try:
            response = await submit_chat_completion(
                prompt=prompt,
                model=self.model_name,
                system_message=GENERATION_SYSTEM_PROMPT,
                timeout_s=120.0,
                extra_payload={
                    "temperature": 0.15,
                    "max_tokens": 1400,
                    "response_format": {"type": "json_object"},
                },
            )
            parsed = self._extract_json_object(self._extract_message_content(response))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "seo_extraction_generation_failed",
                property_id=property_payload.get("id"),
                model=self.model_name,
                error=str(exc)[:400],
            )
            return None

        title = str(parsed.get("title") or property_payload.get("name") or "").strip()[:255]
        meta_description = str(parsed.get("meta_description") or "").strip()[:320]
        if not title or not meta_description:
            logger.error(
                "seo_extraction_incomplete_payload",
                property_id=property_payload.get("id"),
                model=self.model_name,
            )
            return None

        og_title = str(parsed.get("og_title") or title).strip()[:255] or None
        og_description = str(parsed.get("og_description") or meta_description).strip()[:320] or None
        h1_suggestion = str(parsed.get("h1_suggestion") or property_payload.get("name") or "").strip()[:255] or None
        return {
            "title": title,
            "meta_description": meta_description,
            "og_title": og_title,
            "og_description": og_description,
            "h1_suggestion": h1_suggestion,
            "alt_tags": self._normalize_alt_tags(parsed.get("alt_tags")),
        }

    def _load_legacy_drupal_context(self, property_record: Property) -> str:
        blueprint = _load_legacy_blueprint()
        property_context = self._build_property_context(property_record)
        if blueprint is None:
            return property_context

        slug = property_record.slug.strip().lower()
        property_name = property_record.name.strip().lower()
        records = ((blueprint.get("global_alias_scan") or {}).get("records") or [])
        scored_matches: list[tuple[int, str]] = []

        for record in records:
            if not isinstance(record, dict):
                continue
            alias_path = str(record.get("alias_path") or "").strip().lower()
            source_path = str(record.get("source_path") or "").strip().lower()
            node_payload = record.get("node") if isinstance(record.get("node"), dict) else {}
            title = str(node_payload.get("title") or "").strip()
            body = str(node_payload.get("body") or "").strip()
            haystack = " ".join([alias_path, source_path, title.lower(), body.lower()])
            if not haystack:
                continue

            score = 0
            if slug and slug in haystack:
                score += 8
            if property_name and property_name in haystack:
                score += 5
            if alias_path.startswith("/cabin/") or alias_path.startswith("/cabins/"):
                score += 2
            if score <= 0:
                continue

            excerpt = re.sub(r"\s+", " ", body)[:1600]
            summary = (
                f"Legacy Alias: {alias_path or 'unknown'}\n"
                f"Legacy Source: {source_path or 'unknown'}\n"
                f"Legacy Title: {title or 'unknown'}\n"
                f"Legacy Body Excerpt: {excerpt or 'none'}"
            )
            scored_matches.append((score, summary))

        scored_matches.sort(key=lambda item: item[0], reverse=True)
        sections = [property_context]
        for _, summary in scored_matches[:MAX_LEGACY_MATCHES]:
            sections.append(summary)
        return "\n\n".join(sections)[:MAX_LEGACY_CONTEXT_CHARS]

    @staticmethod
    def _build_property_context(property_record: Property) -> str:
        return (
            f"Property: {property_record.name}\n"
            f"Slug: {property_record.slug}\n"
            f"Type: {property_record.property_type}\n"
            f"Bedrooms: {property_record.bedrooms}\n"
            f"Bathrooms: {property_record.bathrooms}\n"
            f"Max Guests: {property_record.max_guests}\n"
            f"Address: {property_record.address or 'Not provided'}\n"
        )

    @staticmethod
    def _flatten_amenities(amenities: Any) -> list[str]:
        if not isinstance(amenities, list):
            return []
        names: list[str] = []
        seen: set[str] = set()
        for item in amenities:
            raw_name = item.get("amenity_name") if isinstance(item, dict) else item
            name = str(raw_name or "").strip()
            if not name:
                continue
            normalized = name.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(name)
        return names[:18]

    @staticmethod
    def _normalize_alt_tags(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {
                str(key): str(raw_text).strip()[:160]
                for key, raw_text in value.items()
                if str(raw_text or "").strip()
            }
        if isinstance(value, list):
            return {
                f"image_{index}": str(raw_text).strip()[:160]
                for index, raw_text in enumerate(value, start=1)
                if str(raw_text or "").strip()
            }
        return {}

    @staticmethod
    def _extract_message_content(response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any]:
        cleaned_text = re.sub(r"```(?:json)?", "", raw_text, flags=re.IGNORECASE)
        cleaned_text = cleaned_text.replace("```", "").strip()

        match = re.search(r"(\{.*\})", cleaned_text, re.DOTALL)
        if match is None:
            logger.error(
                "seo_extraction_json_not_found",
                raw_response=raw_text[:4000],
            )
            raise ValueError("No JSON object found in extraction response")

        candidate_json = match.group(1).strip()
        try:
            parsed = json.loads(candidate_json)
        except json.JSONDecodeError as exc:
            logger.error(
                "seo_extraction_json_decode_failed",
                error=str(exc),
                raw_response=raw_text[:4000],
                extracted_json=candidate_json[:4000],
            )
            raise ValueError("Failed to decode extraction response JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Extraction response must decode to a JSON object")
        return parsed
