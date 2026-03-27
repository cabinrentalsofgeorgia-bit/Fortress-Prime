"""
Research Scout service for grounded market intelligence discovery.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.intelligence_ledger import IntelligenceLedgerEntry

logger = structlog.get_logger(service="research_scout")
_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_SCOUT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=20.0, pool=10.0)


class ScoutFinding(BaseModel):
    category: str
    title: str
    summary: str
    locality: str | None = None
    confidence_score: float | None = None
    source_urls: list[str] = Field(default_factory=list)
    observed_at: datetime | None = None
    finding_payload: dict[str, Any] = Field(default_factory=dict)


class ScoutTopicResult(BaseModel):
    topic: str
    query: str
    inserted_count: int
    duplicate_count: int
    items: list[dict[str, Any]] = Field(default_factory=list)


def _normalize_text(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip().lower()
    return re.sub(r"[^a-z0-9:/._ -]+", "", collapsed)


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def compute_intelligence_dedupe_hash(
    *,
    category: str,
    title: str,
    summary: str,
    market: str,
    locality: str | None,
    source_urls: list[str],
) -> str:
    normalized_urls = sorted({_canonicalize_url(url) for url in source_urls if url.strip()})
    fingerprint = "||".join(
        [
            _normalize_text(category),
            _normalize_text(title),
            _normalize_text(summary),
            _normalize_text(market),
            _normalize_text(locality or ""),
            "|".join(normalized_urls),
        ]
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    trimmed = raw_text.strip()
    if trimmed.startswith("```"):
        trimmed = re.sub(r"^```(?:json)?\s*", "", trimmed)
        trimmed = re.sub(r"\s*```$", "", trimmed)
    return json.loads(trimmed)


def _extract_response_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini Scout response did not include candidates")
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    text_parts = [
        str(part.get("text")).strip()
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str) and part.get("text").strip()
    ]
    if not text_parts:
        raise RuntimeError("Gemini Scout response did not include textual JSON output")
    return "\n".join(text_parts)


def _extract_grounding_urls(payload: dict[str, Any]) -> list[str]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    urls: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        grounding = candidate.get("groundingMetadata")
        if not isinstance(grounding, dict):
            continue
        chunks = grounding.get("groundingChunks")
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            web = chunk.get("web")
            if not isinstance(web, dict):
                continue
            uri = web.get("uri")
            if isinstance(uri, str) and uri.strip():
                urls.append(_canonicalize_url(uri))
    return sorted(dict.fromkeys(urls))


def _extract_grounding_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        grounding = candidate.get("groundingMetadata")
        if isinstance(grounding, dict):
            return grounding
    return {}


def _coerce_observed_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class ResearchScoutService:
    """Discovers grounded market findings and persists only unique ledger entries."""

    def __init__(self) -> None:
        self.market = str(settings.research_scout_market or "Blue Ridge, Georgia").strip()
        self.locality = self.market
        self.model = str(settings.gemini_model or "gemini-2.5-pro").strip()

    def _build_topics(self) -> list[tuple[str, str]]:
        market = self.market
        return [
            (
                "content_gap",
                f"Find underserved content gaps, missing traveler questions, and booking-intent topics in {market} cabin rentals.",
            ),
            (
                "competitor_trend",
                f"Find competitor launches, promotions, pricing posture changes, amenity positioning, and campaign trends in {market} cabin rentals.",
            ),
            (
                "market_shift",
                f"Find local market shifts, event demand signals, seasonal behavior changes, and traveler trend movements affecting {market} cabin rentals.",
            ),
        ]

    async def run_cycle(
        self,
        db: AsyncSession,
        *,
        scout_run_key: str,
        topics: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not settings.gemini_api_key.strip():
            raise RuntimeError("GEMINI_API_KEY is not configured for the Research Scout")

        selected_topics = topics or self._build_topics()
        results: list[ScoutTopicResult] = []
        total_inserted = 0
        total_duplicates = 0
        inserted_entry_ids: list[str] = []
        inserted_items: list[dict[str, Any]] = []

        for topic, query in selected_topics:
            findings, raw_payload = await self._fetch_grounded_findings(topic=topic, query=query)
            inserted_count = 0
            duplicate_count = 0
            persisted_items: list[dict[str, Any]] = []
            for finding in findings:
                persisted = await self._persist_finding(
                    db,
                    finding=finding,
                    topic=topic,
                    query=query,
                    scout_run_key=scout_run_key,
                    raw_payload=raw_payload,
                )
                if persisted["status"] == "inserted":
                    inserted_count += 1
                    entry_id = str(persisted.get("entry_id") or "").strip()
                    if entry_id:
                        inserted_entry_ids.append(entry_id)
                    inserted_items.append(persisted)
                else:
                    duplicate_count += 1
                persisted_items.append(persisted)

            total_inserted += inserted_count
            total_duplicates += duplicate_count
            results.append(
                ScoutTopicResult(
                    topic=topic,
                    query=query,
                    inserted_count=inserted_count,
                    duplicate_count=duplicate_count,
                    items=persisted_items,
                )
            )

        return {
            "market": self.market,
            "scout_run_key": scout_run_key,
            "inserted_count": total_inserted,
            "duplicate_count": total_duplicates,
            "inserted_entry_ids": inserted_entry_ids,
            "inserted_items": inserted_items,
            "topics": [result.model_dump() for result in results],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _fetch_grounded_findings(
        self,
        *,
        topic: str,
        query: str,
    ) -> tuple[list[ScoutFinding], dict[str, Any]]:
        prompt = (
            f"You are the Fortress Prime Research Scout focused on {self.market}. "
            "Use Google Search grounding to surface only factual, externally grounded findings. "
            "Return strict JSON with shape "
            '{"findings":[{"category":"content_gap|competitor_trend|market_shift","title":"...","summary":"...","locality":"...","confidence_score":0.0,"source_urls":["https://..."],"observed_at":"ISO8601"}]}. '
            "Each item must be actionable for Cabin Rentals of Georgia, unique, concise, and tied to Blue Ridge market conditions. "
            f"Topic category: {topic}. Query focus: {query}"
        )
        endpoint = f"{_GEMINI_API_BASE}/models/{self.model}:generateContent?key={settings.gemini_api_key}"
        payload = {
            "system_instruction": {
                "parts": [
                    {
                        "text": "Return only valid JSON. Do not emit markdown or commentary outside the JSON object."
                    }
                ]
            },
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=_SCOUT_TIMEOUT) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            raw_payload = response.json()

        response_text = _extract_response_text(raw_payload)
        parsed_json = _extract_json_payload(response_text)
        raw_findings = parsed_json.get("findings")
        if not isinstance(raw_findings, list):
            raise RuntimeError("Gemini Scout response did not include a findings array")

        grounding_urls = _extract_grounding_urls(raw_payload)
        findings: list[ScoutFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            merged_payload = dict(item)
            candidate_urls = item.get("source_urls") if isinstance(item.get("source_urls"), list) else []
            merged_urls = [
                _canonicalize_url(url)
                for url in [*candidate_urls, *grounding_urls]
                if isinstance(url, str) and url.strip()
            ]
            confidence = float(item["confidence_score"]) if item.get("confidence_score") is not None else None
            if confidence is not None and confidence > 1.0:
                confidence = confidence / 100.0
            merged_payload["source_urls"] = sorted(dict.fromkeys(merged_urls))
            try:
                findings.append(
                    ScoutFinding(
                        category=str(item.get("category") or topic).strip() or topic,
                        title=str(item.get("title") or "").strip(),
                        summary=str(item.get("summary") or "").strip(),
                        locality=str(item.get("locality")).strip() if item.get("locality") else self.locality,
                        confidence_score=confidence,
                        source_urls=merged_payload["source_urls"],
                        observed_at=_coerce_observed_at(item.get("observed_at")),
                        finding_payload=merged_payload,
                    )
                )
            except (TypeError, ValueError, ValidationError) as exc:
                logger.warning("research_scout_invalid_finding", topic=topic, error=str(exc)[:300], finding=item)

        filtered = [finding for finding in findings if finding.title and finding.summary]
        return filtered, raw_payload

    async def _persist_finding(
        self,
        db: AsyncSession,
        *,
        finding: ScoutFinding,
        topic: str,
        query: str,
        scout_run_key: str,
        raw_payload: dict[str, Any],
    ) -> dict[str, Any]:
        dedupe_hash = compute_intelligence_dedupe_hash(
            category=finding.category,
            title=finding.title,
            summary=finding.summary,
            market=self.market,
            locality=finding.locality,
            source_urls=finding.source_urls,
        )

        existing = (
            await db.execute(
                select(IntelligenceLedgerEntry).where(
                    IntelligenceLedgerEntry.dedupe_hash == dedupe_hash
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "status": "duplicate",
                "entry_id": str(existing.id),
                "dedupe_hash": dedupe_hash,
                "title": existing.title,
                "category": existing.category,
            }

        entry = IntelligenceLedgerEntry(
            category=finding.category,
            title=finding.title,
            summary=finding.summary,
            market=self.market,
            locality=finding.locality,
            dedupe_hash=dedupe_hash,
            confidence_score=finding.confidence_score,
            query_topic=topic,
            scout_query=query,
            scout_run_key=scout_run_key,
            source_urls=finding.source_urls,
            grounding_payload={
                "grounding_urls": _extract_grounding_urls(raw_payload),
                "grounding_metadata": _extract_grounding_metadata(raw_payload),
            },
            finding_payload=finding.finding_payload,
            discovered_at=finding.observed_at or datetime.now(timezone.utc),
        )
        db.add(entry)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing_after_race = (
                await db.execute(
                    select(IntelligenceLedgerEntry).where(
                        IntelligenceLedgerEntry.dedupe_hash == dedupe_hash
                    )
                )
            ).scalar_one_or_none()
            return {
                "status": "duplicate",
                "entry_id": str(existing_after_race.id) if existing_after_race is not None else None,
                "dedupe_hash": dedupe_hash,
                "title": finding.title,
                "category": finding.category,
            }

        await db.refresh(entry)
        return {
            "status": "inserted",
            "entry_id": str(entry.id),
            "dedupe_hash": dedupe_hash,
            "title": entry.title,
            "category": entry.category,
        }
