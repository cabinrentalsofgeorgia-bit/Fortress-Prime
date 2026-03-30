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
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.media import PropertyImage
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.services.jsonld_builder import build_property_jsonld
from backend.services.swarm_service import submit_chat_completion
from backend.vrs.infrastructure.seo_event_bus import publish_grade_request

logger = structlog.get_logger(service="seo_extraction_service")

MAX_LEGACY_CONTEXT_CHARS = 12000
MAX_LEGACY_MATCHES = 3
META_DESCRIPTION_MIN_CHARS = 130
META_DESCRIPTION_MAX_CHARS = 155
GENERATION_SYSTEM_PROMPT = (
    "You are the Fortress Prime sovereign SEO extraction swarm. "
    "Return ONLY a JSON object with keys: title, meta_description, og_title, "
    "og_description, h1_suggestion, alt_tags. "
    "Generate guest-facing SEO copy grounded in the supplied property facts and legacy Drupal context. "
    "alt_tags must be an object mapping no more than 6 stable image keys to concise descriptive alt text, "
    "with each alt text no longer than 110 characters. "
    "Constraint: meta_description MUST be strictly between 130 and 155 characters. "
    "Do not exceed 155 characters under any circumstances. "
    "You are a deterministic data transformation engine. DO NOT output conversational text. "
    "DO NOT explain your reasoning. Your absolute final output must be a single valid JSON block "
    "wrapped in ```json fences."
)


def parse_fenced_json(raw_response: str) -> dict[str, Any]:
    """Extract JSON from markdown code fences or raw text."""
    text = str(raw_response or "").strip()
    if not text:
        raise ValueError("No extraction response text to parse")

    fence_patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
    ]
    for pattern in fence_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("Extraction fenced payload must decode to a JSON object")

    raw_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if raw_match:
        parsed = json.loads(raw_match.group(1).strip())
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Extraction raw payload must decode to a JSON object")

    raise ValueError("No JSON object found in extraction response")


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
        return await self.generate_initial_seo_draft_for_context(property_id)

    async def generate_initial_seo_draft_for_context(
        self,
        property_id: UUID,
        *,
        source_intelligence_id: UUID | None = None,
        source_agent: str | None = None,
        scout_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
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
            source_intelligence_id=source_intelligence_id,
            source_agent=source_agent,
            scout_context=scout_context,
        )

    async def run_extraction(
        self,
        property_id: UUID,
        rubric_id: UUID,
        legacy_drupal_context: str,
        *,
        source_intelligence_id: UUID | None = None,
        source_agent: str | None = None,
        scout_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        started_at = time.perf_counter()
        property_record = await self._fetch_property(property_id)
        if property_record is None:
            logger.error("seo_extraction_property_not_found", property_id=str(property_id))
            return None

        property_payload = await self._build_property_payload(property_record)
        seo_payload = await self._generate_seo_copy(
            property_payload,
            legacy_drupal_context,
            scout_context=scout_context,
        )
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
            source_intelligence_id=source_intelligence_id,
            source_agent=(source_agent or self.SOURCE_AGENT).strip(),
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

        published = await publish_grade_request(patch.id, source_agent=patch.source_agent)
        if not published:
            logger.error("seo_extraction_grade_enqueue_failed", patch_id=str(patch.id))
            return None

        logger.info(
            "seo_extraction_completed",
            patch_id=str(patch.id),
            property_id=str(property_record.id),
            rubric_id=str(rubric_id),
            source_intelligence_id=str(source_intelligence_id) if source_intelligence_id else None,
            model=self.model_name,
            generation_ms=generation_ms,
        )
        return {
            "patch_id": str(patch.id),
            "status": patch.status,
            "generation_ms": generation_ms,
            "queued_for_grading": True,
            "source_intelligence_id": str(source_intelligence_id) if source_intelligence_id else None,
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
        images = await self._load_property_media_urls(property_record)
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
            "hero_image_url": images[0] if images else None,
            "images": images,
            "default_image_path": images[0] if images else None,
            "storefront_base_url": settings.storefront_base_url,
        }

    async def _load_property_media_urls(self, property_record: Property) -> list[str]:
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
        if images:
            return images

        streamline_property_id = str(property_record.streamline_property_id or "").strip()
        if not streamline_property_id:
            return []

        try:
            unit_id = int(streamline_property_id)
        except ValueError:
            return []

        client = StreamlineVRS()
        if not client.is_configured:
            return []

        fallback_images: list[str] = []

        def append_if_present(raw_url: Any) -> None:
            value = str(raw_url or "").strip()
            if value and value not in fallback_images:
                fallback_images.append(value)

        try:
            detail = await client.fetch_property_detail(unit_id)
            gallery = await client.fetch_property_gallery(unit_id)
            if isinstance(detail, dict):
                append_if_present(detail.get("default_image_path"))
            if isinstance(gallery, list):
                for item in gallery:
                    if isinstance(item, dict):
                        append_if_present(
                            item.get("image_path")
                            or item.get("original_path")
                            or item.get("thumbnail_path")
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "seo_extraction_media_fallback_failed",
                property_id=str(property_record.id),
                streamline_property_id=streamline_property_id,
                error=str(exc)[:400],
            )
        finally:
            await client.close()

        return fallback_images[:10]

    async def _generate_seo_copy(
        self,
        property_payload: dict[str, Any],
        legacy_context: str,
        *,
        scout_context: dict[str, Any] | None = None,
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
                    "hero_image_url": property_payload.get("hero_image_url"),
                    "media_gallery": self._build_media_gallery_context(property_payload.get("images")),
                },
                "legacy_drupal_context": legacy_context[:MAX_LEGACY_CONTEXT_CHARS],
                "market_intelligence_context": scout_context or {},
                "response_contract": {
                    "title": "string <= 255 chars",
                    "meta_description": "string between 130 and 155 chars inclusive",
                    "og_title": "string_or_null <= 255 chars",
                    "og_description": "string_or_null <= 155 chars",
                    "h1_suggestion": "string_or_null <= 255 chars",
                    "alt_tags": {"image_key": "short alt text <= 110 chars, max 6 entries"},
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
                    "max_tokens": 4000,
                },
            )
            parsed = parse_fenced_json(self._extract_message_content(response))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "seo_extraction_generation_failed",
                property_id=property_payload.get("id"),
                model=self.model_name,
                error=str(exc)[:400],
            )
            return None

        property_name = str(property_payload.get("name") or "").strip()
        title = self._normalize_title(
            parsed.get("title") or property_payload.get("name") or "",
            property_name=property_name,
        )
        meta_description = self._normalize_meta_description(
            parsed.get("meta_description"),
            property_name=property_name,
        )
        if not title or not meta_description:
            logger.error(
                "seo_extraction_incomplete_payload",
                property_id=property_payload.get("id"),
                model=self.model_name,
            )
            return None

        og_title = self._normalize_title(parsed.get("og_title") or title, property_name=property_name) or None
        og_description = self._normalize_meta_description(
            parsed.get("og_description") or meta_description,
            property_name=property_name,
        ) or None
        h1_suggestion = self._normalize_h1_suggestion(
            parsed.get("h1_suggestion") or property_name,
            property_name=property_name,
        )
        return {
            "title": title,
            "meta_description": meta_description,
            "og_title": og_title,
            "og_description": og_description,
            "h1_suggestion": h1_suggestion,
            "alt_tags": self._normalize_alt_tags(parsed.get("alt_tags")),
        }

    @staticmethod
    def _normalize_generated_text(value: Any, *, max_len: int) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        replacements = {
            "\u00a0": " ",
            "\u2010": "-",
            "\u2011": "-",
            "\u2012": "-",
            "\u2013": "-",
            "\u2014": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\bfrom(?=[A-Z])", "from ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_len].strip()

    @staticmethod
    def _normalize_title(value: Any, *, property_name: str = "") -> str:
        text = SEOExtractionSwarm._normalize_generated_text(value, max_len=255)
        if property_name:
            text = re.sub(
                rf"\b{re.escape(property_name)}\s+Cabin Rental\b",
                f"{property_name} Rental",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(
                rf"\b{re.escape(property_name)}\s+Cabin\b",
                property_name,
                text,
                flags=re.IGNORECASE,
            )
        return text[:255].strip()

    @staticmethod
    def _normalize_meta_description(value: Any, *, property_name: str = "") -> str:
        text = SEOExtractionSwarm._normalize_generated_text(value, max_len=META_DESCRIPTION_MAX_CHARS * 2)
        if not text:
            return ""
        text = re.sub(r"\s*&\s*more\b", " and more", text, flags=re.IGNORECASE)
        text = text.replace("&", " and ")
        if property_name:
            text = re.sub(
                rf"\bat\s+{re.escape(property_name)}\s+cabin\b",
                f"at {property_name}",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(
                rf"\b{re.escape(property_name)}\s+cabin\b",
                property_name,
                text,
                flags=re.IGNORECASE,
            )
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > META_DESCRIPTION_MAX_CHARS:
            truncated = text[: META_DESCRIPTION_MAX_CHARS + 1].rstrip()
            if " " in truncated:
                candidate = truncated.rsplit(" ", 1)[0].rstrip(" ,;:-")
                if len(candidate) >= META_DESCRIPTION_MIN_CHARS:
                    text = candidate
                else:
                    text = truncated[:META_DESCRIPTION_MAX_CHARS].rstrip(" ,;:-")
            else:
                text = truncated[:META_DESCRIPTION_MAX_CHARS].rstrip(" ,;:-")

        if len(text) < META_DESCRIPTION_MIN_CHARS:
            suffix = " Book your luxury cabin retreat today."
            if suffix.strip() not in text:
                text = f"{text.rstrip('.')}." if not text.endswith(".") else text
                text = f"{text}{suffix}"
            if len(text) > META_DESCRIPTION_MAX_CHARS:
                text = text[: META_DESCRIPTION_MAX_CHARS + 1].rstrip()
                if " " in text:
                    text = text.rsplit(" ", 1)[0].rstrip(" ,;:-")
        return text[:META_DESCRIPTION_MAX_CHARS].strip()

    @staticmethod
    def _normalize_h1_suggestion(value: Any, *, property_name: str = "") -> str | None:
        text = SEOExtractionSwarm._normalize_title(value, property_name=property_name)
        if not text:
            text = property_name
        if not text:
            return None
        if "blue ridge" not in text.lower():
            text = f"{text.rstrip(' -|,')} in Blue Ridge GA"
        return text[:255].strip() or None

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
    def _build_media_gallery_context(images: Any) -> list[dict[str, Any]]:
        if not isinstance(images, list):
            return []
        gallery: list[dict[str, Any]] = []
        for index, raw_url in enumerate(images[:6], start=1):
            url = str(raw_url or "").strip()
            if not url:
                continue
            gallery.append(
                {
                    "image_key": "hero" if index == 1 else f"image_{index}",
                    "url": url,
                    "is_hero": index == 1,
                }
            )
        return gallery

    @staticmethod
    def _normalize_alt_tags(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {
                str(key): SEOExtractionSwarm._normalize_generated_text(raw_text, max_len=110)
                for key, raw_text in list(value.items())[:6]
                if SEOExtractionSwarm._normalize_generated_text(raw_text, max_len=110)
            }
        if isinstance(value, list):
            return {
                f"image_{index}": SEOExtractionSwarm._normalize_generated_text(raw_text, max_len=110)
                for index, raw_text in enumerate(value[:6], start=1)
                if SEOExtractionSwarm._normalize_generated_text(raw_text, max_len=110)
            }
        return {}

    @staticmethod
    def _extract_message_content(response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        reasoning_content = message.get("reasoning_content")
        provider_specific_fields = message.get("provider_specific_fields") or {}
        provider_reasoning = (
            provider_specific_fields.get("reasoning_content")
            or provider_specific_fields.get("reasoning")
        )
        fragments: list[str] = []
        if isinstance(content, str):
            fragments.append(content.strip())
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    fragments.append(item["text"].strip())
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            fragments.append(reasoning_content.strip())
        if isinstance(provider_reasoning, str) and provider_reasoning.strip():
            fragments.append(provider_reasoning.strip())
        raw_text = "\n".join(fragment for fragment in fragments if fragment).strip()
        if raw_text:
            return raw_text
        logger.error("seo_extraction_empty_model_response", raw_response=json.dumps(response, default=str)[:4000])
        return ""
