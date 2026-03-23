"""
Deep entity swarm for quarantined SEO redirects with confidence < 0.50.

Targets rows that the initial swarm + God Head grading cycle rejected at
sub-0.50 confidence.  Runs a more aggressive entity extraction prompt via
NemoClaw.  If a hard entity is found, the row is recycled back to
``proposed`` and published to the grade bus for God Head re-evaluation.
If no entity surfaces, the row is classified as dead content and
superseded so it 404s naturally.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.seo_redirect_remap import SeoRedirectRemapQueue
from backend.services.seo_fallback_swarm import (
    _load_candidate_routes,
    _normalize_path,
    _parse_proposal,
    _shortlist_candidates,
)
from backend.services.swarm_service import submit_chat_completion
from backend.vrs.infrastructure.seo_event_bus import SEOEventBus, create_seo_event_redis

logger = structlog.get_logger(service="deep_entity_swarm")

QUARANTINE_CONFIDENCE_CEILING = 0.50
DEAD_CONTENT_GROUNDING_MODE = "dead_content_404"


def _build_deep_entity_prompt(
    row: SeoRedirectRemapQueue,
    shortlist: list[str],
    rubric_version: str,
) -> str:
    snapshot = row.source_snapshot or {}
    return json.dumps(
        {
            "task": (
                "Deep entity extraction for a quarantined legacy redirect. "
                "This path was previously rejected at low confidence.  Your job "
                "is to find the single strongest named entity (cabin name, "
                "activity, review subject, blog topic) and map it to an exact "
                "modern route.  If no hard entity exists, return null."
            ),
            "source_path": row.source_path,
            "previous_proposed_destination": row.proposed_destination_path,
            "previous_grade_score": row.grade_score,
            "previous_rationale": row.rationale,
            "legacy_snapshot": snapshot,
            "candidate_routes": shortlist,
            "instructions": [
                "Return strict JSON only.",
                "If you identify a hard named entity, set destination_path to the best exact match.",
                "If there is no recoverable entity, set destination_path to null.",
                "Do NOT use generic fallbacks like /cabins or /activities unless the entity genuinely maps there.",
                "entities array must contain at least one concrete named entity or be empty.",
                f"Ground your decision to rubric {rubric_version}.",
            ],
            "response_schema": {
                "destination_path": "string_or_null",
                "entities": ["string"],
                "rationale": "string",
                "route_candidates": ["string"],
            },
        },
        ensure_ascii=True,
    )


def _is_null_result(proposal_destination: str | None) -> bool:
    if not proposal_destination:
        return True
    normalized = _normalize_path(proposal_destination)
    return normalized in ("", "/", "null", "/null")


async def run_deep_entity_swarm(
    db: AsyncSession,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_payload = payload or {}
    confidence_ceiling = float(
        job_payload.get("confidence_ceiling") or QUARANTINE_CONFIDENCE_CEILING,
    )
    campaign = str(job_payload.get("campaign") or "deep_entity_swarm").strip() or "deep_entity_swarm"
    source_campaign = str(job_payload.get("source_campaign") or "").strip() or None
    rubric_version = str(
        job_payload.get("rubric_version") or "seo_deep_entity_v1",
    ).strip() or "seo_deep_entity_v1"
    proposal_run_id = str(
        job_payload.get("proposal_run_id") or f"deep-entity-{campaign}",
    ).strip()
    model = str(
        job_payload.get("model")
        or settings.seo_redirect_swarm_model
        or "nemotron-3-super-120b",
    ).strip()
    limit_value = job_payload.get("limit")
    limit = max(1, int(limit_value)) if limit_value is not None else None
    offset = max(0, int(job_payload.get("offset") or 0))

    query = (
        select(SeoRedirectRemapQueue)
        .where(
            SeoRedirectRemapQueue.status == "rejected",
            SeoRedirectRemapQueue.grade_score.isnot(None),
            SeoRedirectRemapQueue.grade_score < confidence_ceiling,
        )
        .order_by(SeoRedirectRemapQueue.grade_score.asc())
        .offset(offset)
    )
    if source_campaign:
        query = query.where(SeoRedirectRemapQueue.campaign == source_campaign)
    if limit is not None:
        query = query.limit(limit)

    rows = list((await db.execute(query)).scalars().all())
    logger.info(
        "deep_entity_swarm_start",
        quarantined_rows=len(rows),
        confidence_ceiling=confidence_ceiling,
        campaign=campaign,
        model=model,
    )

    candidate_routes = _load_candidate_routes()
    redis = await create_seo_event_redis()
    event_bus = SEOEventBus(redis)

    recycled = 0
    dead_classified = 0
    published_messages = 0
    queue_ids: list[str] = []
    dead_ids: list[str] = []

    try:
        for row in rows:
            shortlist = _shortlist_candidates(str(row.source_path or ""), candidate_routes)
            prompt = _build_deep_entity_prompt(row, shortlist, rubric_version)

            try:
                response = await submit_chat_completion(
                    prompt=prompt,
                    model=model,
                    system_message=(
                        "You are the Fortress Prime deep entity extractor. "
                        "Return strict JSON. If no hard entity exists, "
                        "set destination_path to null."
                    ),
                    timeout_s=120.0,
                    extra_payload={"temperature": 0.05, "max_tokens": 800},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "deep_entity_swarm_inference_error",
                    source_path=row.source_path,
                    error=str(exc)[:300],
                )
                response = {"error": str(exc)[:500], "choices": []}

            raw_text = ""
            choices = response.get("choices") or []
            if choices:
                msg = (choices[0] or {}).get("message") or {}
                raw_content = msg.get("content")
                if isinstance(raw_content, str):
                    raw_text = raw_content.strip()

            null_markers = ('"destination_path":null', '"destination_path": null', '"destination_path":"null"')
            is_null = (not raw_text) or any(marker in raw_text.replace(" ", "") for marker in null_markers)

            if is_null or _is_null_result(raw_text):
                row.status = "superseded"
                row.grounding_mode = DEAD_CONTENT_GROUNDING_MODE
                row.review_note = (
                    f"Deep entity swarm returned NULL. "
                    f"Legacy path classified as dead content — natural 404. "
                    f"Run: {proposal_run_id}"
                )
                row.reviewed_by = "deep_entity_swarm"
                row.updated_at = datetime.now(timezone.utc)
                dead_classified += 1
                dead_ids.append(str(row.id))
                await db.flush()
                logger.info("deep_entity_dead_content", source_path=row.source_path, row_id=str(row.id))
                continue

            proposal = _parse_proposal(str(row.source_path or ""), shortlist, response)

            if _is_null_result(proposal.destination_path) or not proposal.extracted_entities:
                row.status = "superseded"
                row.grounding_mode = DEAD_CONTENT_GROUNDING_MODE
                row.review_note = (
                    f"Deep entity swarm found no concrete entities. "
                    f"Classified as dead content — natural 404. "
                    f"Run: {proposal_run_id}"
                )
                row.reviewed_by = "deep_entity_swarm"
                row.updated_at = datetime.now(timezone.utc)
                dead_classified += 1
                dead_ids.append(str(row.id))
                await db.flush()
                logger.info("deep_entity_no_entities", source_path=row.source_path, row_id=str(row.id))
                continue

            row.proposed_destination_path = proposal.destination_path
            row.grounding_mode = "deep_entity_match"
            row.status = "proposed"
            row.campaign = campaign
            row.proposal_run_id = proposal_run_id
            row.rubric_version = rubric_version
            row.proposed_by = "deep_entity_swarm"
            row.extracted_entities = proposal.extracted_entities
            row.route_candidates = proposal.route_candidates
            row.rationale = proposal.rationale
            row.grade_score = None
            row.grade_payload = {}
            row.reviewed_by = None
            row.review_note = None
            row.approved_at = None
            row.updated_at = datetime.now(timezone.utc)
            await db.flush()

            grade_request = {
                "review_id": str(row.id),
                "source_path": row.source_path,
                "current_destination_path": row.current_destination_path,
                "proposed_destination_path": row.proposed_destination_path,
                "campaign": campaign,
                "rubric_version": rubric_version,
                "threshold": float(settings.seo_redirect_grade_threshold),
                "entities": row.extracted_entities,
                "rationale": row.rationale,
                "route_candidates": row.route_candidates,
                "source_snapshot": row.source_snapshot,
            }
            await event_bus.publish_remap_grade_request(grade_request)
            published_messages += 1
            recycled += 1
            queue_ids.append(str(row.id))
            logger.info(
                "deep_entity_recycled",
                source_path=row.source_path,
                destination=proposal.destination_path,
                entities=proposal.extracted_entities,
                row_id=str(row.id),
            )

        await db.commit()
    finally:
        await redis.aclose()

    summary = {
        "campaign": campaign,
        "proposal_run_id": proposal_run_id,
        "rubric_version": rubric_version,
        "model": model,
        "confidence_ceiling": confidence_ceiling,
        "scanned_count": len(rows),
        "recycled_count": recycled,
        "dead_classified_count": dead_classified,
        "published_messages": published_messages,
        "recycled_ids": queue_ids[:50],
        "dead_ids": dead_ids[:50],
    }
    logger.info("deep_entity_swarm_complete", **summary)
    return summary
