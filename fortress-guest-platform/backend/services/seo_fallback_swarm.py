"""
Sovereign swarm proposal generation for quarantined SEO redirect fallbacks.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.seo_redirect_remap import SeoRedirectRemapQueue
from backend.services.archive_restoration import (
    ArchiveBlueprintUnavailable,
    ArchiveRecordNotFound,
    ArchiveRestorationService,
)
from backend.services.swarm_service import submit_chat_completion
from backend.scripts.generate_seo_migration_map import _discover_next_routes
from backend.vrs.infrastructure.seo_event_bus import SEOEventBus, create_seo_event_redis

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_APP_DIR = REPO_ROOT / "apps" / "storefront" / "src" / "app"
LEGACY_REDIRECTS_PATH = REPO_ROOT / "apps" / "storefront" / "src" / "data" / "legacy-redirects.ts"
DEFAULT_PREVIEW_PATH = (
    REPO_ROOT / "backend" / "data" / "async_jobs" / "emergency-brake-20260320T152318Z" / "safety_first_remap_preview.json"
)
LEGACY_REDIRECT_RE = re.compile(r'\{\s*source:\s*"([^"]+)",\s*destination:\s*"([^"]+)"')
JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
PUBLIC_ROUTE_BLOCKLIST = (
    "/admin",
    "/agreements",
    "/ai-engine",
    "/analytics",
    "/automations",
    "/damage-claims",
    "/email-intake",
    "/guestbooks",
    "/guests",
    "/housekeeping",
    "/intelligence",
    "/invite",
    "/iot",
    "/legal",
    "/login",
    "/messages",
    "/owner",
    "/owner-login",
    "/payments",
    "/prime",
    "/reservations",
    "/settings",
    "/sign",
    "/sso",
    "/system-health",
    "/vault",
    "/vrs",
    "/work-orders",
)


@dataclass(slots=True)
class SwarmProposal:
    destination_path: str
    extracted_entities: list[str]
    rationale: str
    route_candidates: list[str]
    grounding_mode: str
    raw_response: dict[str, Any]


def _normalize_path(path: str) -> str:
    value = (path or "").strip()
    if not value:
        return "/"
    if not value.startswith("/"):
        value = f"/{value}"
    return re.sub(r"/{2,}", "/", value.rstrip("/") or "/")


def _tokenize(value: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return {token for token in cleaned.split() if len(token) >= 2}


def _shortlist_candidates(source_path: str, candidate_routes: list[str], *, limit: int = 16) -> list[str]:
    source_tokens = _tokenize(source_path)
    scored: list[tuple[float, str]] = []
    for route in candidate_routes:
        route_tokens = _tokenize(route)
        overlap = len(source_tokens & route_tokens) / float(max(len(route_tokens), 1))
        sequence = SequenceMatcher(a=source_path.lower(), b=route.lower()).ratio()
        score = 0.65 * overlap + 0.35 * sequence
        if any(route.startswith(prefix) for prefix in ("/activity", "/activities", "/cabins", "/reviews", "/blog")):
            score += 0.05
        scored.append((score, route))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [route for _, route in scored[:limit]]


def _load_candidate_routes() -> list[str]:
    routes = set(_discover_next_routes(FRONTEND_APP_DIR))
    if LEGACY_REDIRECTS_PATH.exists():
        text = LEGACY_REDIRECTS_PATH.read_text(encoding="utf-8")
        for _source, destination in LEGACY_REDIRECT_RE.findall(text):
            normalized = _normalize_path(destination)
            if any(normalized.startswith(prefix) for prefix in PUBLIC_ROUTE_BLOCKLIST):
                continue
            routes.add(normalized)
    filtered = [
        route
        for route in routes
        if route != "/" and not any(route.startswith(prefix) for prefix in PUBLIC_ROUTE_BLOCKLIST)
    ]
    return sorted(filtered)


def _extract_model_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
        return "\n".join(text_parts).strip()
    return ""


def _fallback_destination(source_path: str, candidate_routes: list[str]) -> str:
    lowered = source_path.lower()
    if lowered.startswith(("/activity/", "/activity-type/", "/event/")):
        return "/activities"
    if lowered.startswith("/blog/"):
        return "/blog" if "/blog" in candidate_routes else "/cabins"
    if lowered.startswith("/testimonial/"):
        slug = lowered.split("/")[-1]
        return f"/reviews/{slug}"
    return "/cabins"


def _build_fallback_proposal(source_path: str, candidate_routes: list[str], raw_response: dict[str, Any]) -> SwarmProposal:
    destination = _fallback_destination(source_path, candidate_routes)
    return SwarmProposal(
        destination_path=destination,
        extracted_entities=[],
        rationale="Model response was unavailable or invalid; retained a deterministic sovereign fallback.",
        route_candidates=candidate_routes,
        grounding_mode="swarm_semantic_fallback",
        raw_response=raw_response,
    )


def _parse_proposal(source_path: str, candidate_routes: list[str], response: dict[str, Any]) -> SwarmProposal:
    raw_text = _extract_model_text(response)
    match = JSON_OBJECT_RE.search(raw_text)
    if not match:
        return _build_fallback_proposal(source_path, candidate_routes, response)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _build_fallback_proposal(source_path, candidate_routes, response)

    destination = _normalize_path(str(payload.get("destination_path") or ""))
    if destination not in candidate_routes and destination not in {"/activities", "/cabins", "/blog"}:
        return _build_fallback_proposal(source_path, candidate_routes, response)

    entities = [
        str(item).strip()
        for item in (payload.get("entities") or [])
        if str(item).strip()
    ][:12]
    rationale = str(payload.get("rationale") or "").strip() or "No rationale provided by swarm."
    shortlist = [
        _normalize_path(str(item))
        for item in (payload.get("route_candidates") or [])
        if str(item).strip()
    ]
    shortlist = [item for item in shortlist if item in candidate_routes][:12] or candidate_routes[:12]
    return SwarmProposal(
        destination_path=destination,
        extracted_entities=entities,
        rationale=rationale,
        route_candidates=shortlist,
        grounding_mode="swarm_semantic_match",
        raw_response=response,
    )


def _build_snapshot(row: dict[str, Any], restored: dict[str, Any] | None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "source_path": row.get("source_path"),
        "current_destination_path": row.get("current_destination_path"),
        "current_confidence": row.get("current_confidence"),
        "source_ref": row.get("source_ref"),
        "source_type": row.get("source_type"),
    }
    if restored:
        for key in (
            "title",
            "original_slug",
            "archive_path",
            "node_type",
            "legacy_type",
            "related_property_slug",
            "related_property_path",
            "related_property_title",
            "category_tags",
            "content_body",
        ):
            value = restored.get(key)
            if value not in (None, "", [], {}):
                snapshot[key] = value
    return snapshot


async def _generate_swarm_proposal(
    *,
    row: dict[str, Any],
    candidate_routes: list[str],
    model: str,
    rubric_version: str,
) -> SwarmProposal:
    restoration_service = ArchiveRestorationService()
    restored_record: dict[str, Any] | None = None
    try:
        restored = await restoration_service.restore_archive(str(row.get("source_path") or ""))
        restored_record = restored.record
    except (ArchiveRecordNotFound, ArchiveBlueprintUnavailable):
        restored_record = None

    snapshot = _build_snapshot(row, restored_record)
    shortlist = _shortlist_candidates(str(row.get("source_path") or ""), candidate_routes)
    prompt = json.dumps(
        {
            "task": "Choose the best modern destination for a quarantined legacy SEO redirect.",
            "source_path": row.get("source_path"),
            "legacy_snapshot": snapshot,
            "candidate_routes": shortlist,
            "instructions": [
                "Return strict JSON only.",
                "Prefer the most exact public destination on the new site.",
                "Use /activities or /cabins only when no stronger exact path exists.",
                "Do not pick dashboard, legal, admin, or staff-only routes.",
                f"Ground your decision to rubric {rubric_version}.",
            ],
            "response_schema": {
                "destination_path": "string",
                "entities": ["string"],
                "rationale": "string",
                "route_candidates": ["string"],
            },
        },
        ensure_ascii=True,
    )
    try:
        response = await submit_chat_completion(
            prompt=prompt,
            model=model,
            system_message=(
                "You are the Fortress Prime SEO remap swarm. "
                "Produce only valid JSON. Prefer exact public routes over generic fallbacks."
            ),
            timeout_s=90.0,
            extra_payload={"temperature": 0.1, "max_tokens": 700},
        )
        proposal = _parse_proposal(str(row.get("source_path") or ""), shortlist, response)
    except Exception as exc:  # noqa: BLE001
        response = {"error": str(exc)[:500], "choices": []}
        proposal = _build_fallback_proposal(str(row.get("source_path") or ""), shortlist, response)
        proposal.rationale = (
            "NemoClaw endpoint was unavailable, so the runner retained a deterministic sovereign fallback. "
            f"Error: {str(exc)[:200]}"
        )
    proposal.raw_response.setdefault("legacy_snapshot", snapshot)
    return proposal


async def run_seo_fallback_swarm(
    db: AsyncSession,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_payload = payload or {}
    preview_path = Path(str(job_payload.get("preview_path") or DEFAULT_PREVIEW_PATH))
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    rows = [
        row
        for row in (preview.get("rows") or [])
        if row.get("grounding_mode") != "curated_legacy_redirect_exact"
    ]
    offset = max(0, int(job_payload.get("offset") or 0))
    limit_value = job_payload.get("limit")
    limit = max(1, int(limit_value)) if limit_value is not None else None
    selected_rows = rows[offset : offset + limit] if limit is not None else rows[offset:]

    campaign = str(job_payload.get("campaign") or "seo_fallback_swarm").strip() or "seo_fallback_swarm"
    rubric_version = str(job_payload.get("rubric_version") or "seo_redirect_remap_v1").strip() or "seo_redirect_remap_v1"
    proposal_run_id = str(job_payload.get("proposal_run_id") or f"seo-fallback-swarm-{campaign}").strip()
    model = str(job_payload.get("model") or settings.seo_redirect_swarm_model or "nemotron-3-super-120b").strip()

    candidate_routes = _load_candidate_routes()
    redis = await create_seo_event_redis()
    event_bus = SEOEventBus(redis)
    published_messages = 0
    persisted = 0
    promoted_candidates = 0
    queued_ids: list[str] = []
    try:
        for row in selected_rows:
            source_path = _normalize_path(str(row.get("source_path") or ""))
            existing = (
                await db.execute(
                    select(SeoRedirectRemapQueue).where(
                        SeoRedirectRemapQueue.source_path == source_path,
                        SeoRedirectRemapQueue.campaign == campaign,
                        SeoRedirectRemapQueue.proposal_run_id == proposal_run_id,
                    )
                )
            ).scalar_one_or_none()
            proposal = await _generate_swarm_proposal(
                row=row,
                candidate_routes=candidate_routes,
                model=model,
                rubric_version=rubric_version,
            )
            snapshot = proposal.raw_response.get("legacy_snapshot") or _build_snapshot(row, None)

            queue_row = existing or SeoRedirectRemapQueue(
                source_path=source_path,
                campaign=campaign,
                proposal_run_id=proposal_run_id,
            )
            if existing is None:
                db.add(queue_row)

            queue_row.current_destination_path = str(row.get("current_destination_path") or "")
            queue_row.proposed_destination_path = proposal.destination_path
            queue_row.applied_destination_path = None
            queue_row.grounding_mode = proposal.grounding_mode
            queue_row.status = "proposed"
            queue_row.rubric_version = rubric_version
            queue_row.proposed_by = "nemoclaw_swarm"
            queue_row.extracted_entities = proposal.extracted_entities
            queue_row.source_snapshot = snapshot
            queue_row.route_candidates = proposal.route_candidates
            queue_row.rationale = proposal.rationale
            queue_row.grade_score = None
            queue_row.grade_payload = {}
            queue_row.reviewed_by = None
            queue_row.review_note = None
            queue_row.approved_at = None
            await db.flush()

            grade_request = {
                "review_id": str(queue_row.id),
                "source_path": queue_row.source_path,
                "current_destination_path": queue_row.current_destination_path,
                "proposed_destination_path": queue_row.proposed_destination_path,
                "campaign": campaign,
                "rubric_version": rubric_version,
                "threshold": float(settings.seo_redirect_grade_threshold),
                "entities": queue_row.extracted_entities,
                "rationale": queue_row.rationale,
                "route_candidates": queue_row.route_candidates,
                "source_snapshot": queue_row.source_snapshot,
            }
            queued_ids.append(str(queue_row.id))
            persisted += 1
            await event_bus.publish_remap_grade_request(grade_request)
            published_messages += 1

        await db.commit()
    finally:
        await redis.aclose()

    return {
        "preview_path": str(preview_path),
        "campaign": campaign,
        "proposal_run_id": proposal_run_id,
        "rubric_version": rubric_version,
        "model": model,
        "processed_count": len(selected_rows),
        "persisted_count": persisted,
        "published_messages": published_messages,
        "promoted_count": promoted_candidates,
        "queue_ids": queued_ids[:50],
    }
