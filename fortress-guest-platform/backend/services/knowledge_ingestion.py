"""Sovereign property knowledge ingestion for pgvector-backed concierge RAG."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.vector_db import embed_text
from backend.models.guestbook import GuestbookGuide
from backend.models.knowledge import PropertyKnowledgeChunk
from backend.models.property import Property

MAX_CHUNK_CHARS = 900
CHUNK_OVERLAP_CHARS = 120


@dataclass(slots=True)
class PropertyKnowledgeSource:
    """Named source block that contributes grounded concierge context."""

    label: str
    content: str


class KnowledgeIngestionService:
    """Chunk, embed, and persist property knowledge in sovereign Postgres."""

    async def ingest_property(self, db: AsyncSession, property_id: UUID) -> dict[str, int | str]:
        property_record = await db.get(Property, property_id)
        if property_record is None:
            raise ValueError("Property not found")

        sources = await self._build_sources(db, property_record)
        chunks = self._chunk_sources(sources)

        await self.delete_existing_chunks(db, property_id)

        stored_chunks = 0
        for chunk in chunks:
            embedding = await embed_text(chunk)
            db.add(
                PropertyKnowledgeChunk(
                    property_id=property_id,
                    content=chunk,
                    embedding=embedding,
                )
            )
            stored_chunks += 1

        await db.commit()
        return {
            "property_id": str(property_id),
            "source_count": len(sources),
            "chunk_count": stored_chunks,
        }

    async def delete_existing_chunks(self, db: AsyncSession, property_id: UUID) -> None:
        """Delete stale chunks before rebuilding the property knowledge ledger."""
        await db.execute(
            delete(PropertyKnowledgeChunk).where(PropertyKnowledgeChunk.property_id == property_id)
        )
        await db.flush()

    async def _build_sources(
        self,
        db: AsyncSession,
        property_record: Property,
    ) -> list[PropertyKnowledgeSource]:
        sources: list[PropertyKnowledgeSource] = []

        detail_lines = [
            f"Property name: {property_record.name}",
            f"Property type: {property_record.property_type}",
            f"Bedrooms: {property_record.bedrooms}",
            f"Bathrooms: {property_record.bathrooms}",
            f"Max guests: {property_record.max_guests}",
        ]
        if property_record.address:
            detail_lines.append(f"Address: {property_record.address}")
        if property_record.parking_instructions:
            detail_lines.append(f"Parking instructions: {property_record.parking_instructions}")
        if property_record.wifi_ssid:
            detail_lines.append(f"WiFi network: {property_record.wifi_ssid}")
        if property_record.wifi_password:
            detail_lines.append(f"WiFi password: {property_record.wifi_password}")
        if property_record.access_code_type:
            detail_lines.append(f"Access type: {property_record.access_code_type}")
        if property_record.access_code_location:
            detail_lines.append(f"Access instructions: {property_record.access_code_location}")
        sources.append(
            PropertyKnowledgeSource(
                label="property_overview",
                content="\n".join(detail_lines),
            )
        )

        amenities_text = self._render_amenities(property_record.amenities)
        if amenities_text:
            sources.append(
                PropertyKnowledgeSource(
                    label="amenities",
                    content=f"Amenities for {property_record.name}:\n{amenities_text}",
                )
            )

        guide_result = await db.execute(
            select(GuestbookGuide)
            .where(GuestbookGuide.property_id == property_record.id)
            .where(GuestbookGuide.is_visible.is_(True))
            .order_by(GuestbookGuide.display_order.asc(), GuestbookGuide.created_at.asc())
        )
        for guide in guide_result.scalars().all():
            guide_text = (guide.content or "").strip()
            if not guide_text:
                continue
            label = guide.category or guide.guide_type or "guide"
            sources.append(
                PropertyKnowledgeSource(
                    label=f"guide_{label}",
                    content=f"{guide.title}\nCategory: {label}\n{guide_text}",
                )
            )

        return sources

    def _chunk_sources(self, sources: list[PropertyKnowledgeSource]) -> list[str]:
        chunks: list[str] = []
        for source in sources:
            normalized = self._normalize_text(source.content)
            if not normalized:
                continue

            prefixed = f"Source: {source.label}\n{normalized}"
            if len(prefixed) <= MAX_CHUNK_CHARS:
                chunks.append(prefixed)
                continue

            start = 0
            while start < len(prefixed):
                end = min(len(prefixed), start + MAX_CHUNK_CHARS)
                chunk = prefixed[start:end].strip()
                if chunk:
                    chunks.append(chunk)
                if end >= len(prefixed):
                    break
                start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
        return chunks

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", value.strip())

    @staticmethod
    def _render_amenities(raw_amenities: object) -> str:
        if raw_amenities is None:
            return ""
        if isinstance(raw_amenities, list):
            return "\n".join(f"- {KnowledgeIngestionService._stringify_amenity(item)}" for item in raw_amenities)
        if isinstance(raw_amenities, dict):
            return json.dumps(raw_amenities, ensure_ascii=True, sort_keys=True, indent=2)
        return str(raw_amenities)

    @staticmethod
    def _stringify_amenity(item: object) -> str:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("label") or item.get("amenity") or "").strip()
            value = str(item.get("value") or item.get("description") or "").strip()
            if name and value:
                return f"{name}: {value}"
            return name or json.dumps(item, ensure_ascii=True, sort_keys=True)
        return str(item)
